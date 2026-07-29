"""FB — 역방향 설계 (F2).

목표 성능(목표값·가중치·방향)을 입력받아 조성비와 공정 조건을 역추천한다.

    FB-01 목표 설정        ObjectiveSpec 목록 (max / min / equal)
    FB-02 목적함수 변환     방향별 최소화 목적으로 변환
    FB-03 획득함수 탐색     scikit-optimize EI (스칼라화 목적) — 선택 실행
    FB-04 제약 필터링       조성 합계·설비 사양·물리 제약 위반 해 제거
    FB-05 Pareto front     pymoo NSGA-II 비지배 정렬
    FB-06 상위 후보 순위화   가중 점수 상위 5건 + 근거
    FB-07 간헐 측정 제약 제한  실측 건수 임계 미달 시 제약 대신 참고 지표
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from dry_process_ai.config import (
    COMPOSITION_TOTAL_WT,
    DEFAULT_SEED,
    INTERMITTENT_CONSTRAINT_MIN_COUNT,
    STAGES,
)
from dry_process_ai.core.infer.gap_schedule import ScheduleInfeasible, search_gap_schedule
from dry_process_ai.core.infer.predictor import Predictor
from dry_process_ai.data_access.repository import AUX_PROPERTY_COLUMNS, INPUT_FEATURES
from dry_process_ai.rules.spec_validation import ProcessCapability, validate_spec


@dataclass
class ObjectiveSpec:
    """FB-01 — 목표 변수별 목표값·가중치·방향."""

    column: str
    direction: str            # "min" | "max" | "equal"
    weight: float = 1.0
    target: float | None = None  # equal 방향 필수


@dataclass
class Candidate:
    binder_wt: float
    conductive_wt: float
    active_material_wt: float
    target_density_gcc: float
    features: pd.Series
    gaps_um: dict[str, float]
    predictions: dict[str, float]
    objectives: list[float]
    weighted_score: float
    alarm_grade: str
    rationale: str
    is_pareto: bool = False


@dataclass
class BackwardResult:
    candidates: list[Candidate]
    pareto_front: list[Candidate]
    top: list[Candidate]
    excluded_constraints: list[str] = field(default_factory=list)  # FB-07 사유


def _objective_values(predictions: dict[str, float], objectives: list[ObjectiveSpec]) -> list[float]:
    """FB-02 — 모든 방향을 '작을수록 좋음' 목적으로 변환."""
    vals = []
    for spec in objectives:
        v = predictions.get(spec.column, float("nan"))
        if spec.direction == "min":
            vals.append(v)
        elif spec.direction == "max":
            vals.append(-v)
        else:  # equal
            vals.append(abs(v - (spec.target if spec.target is not None else 0.0)))
    return vals


def usable_strength_constraints(train_df: pd.DataFrame,
                                threshold: int = INTERMITTENT_CONSTRAINT_MIN_COUNT) -> dict[str, dict]:
    """FB-07 — B등급 변수의 제약 사용 가능 여부 판정.

    실측 건수가 임계 미만이면 제약이 아닌 참고 지표로만 쓴다.
    측정 빈도가 더 높은 쪽을 주 강도 지표로 자동 선택한다.
    """
    counts = {
        col: int(train_df[col].notna().sum()) if col in train_df.columns else 0
        for col in AUX_PROPERTY_COLUMNS
    }
    primary = max(counts, key=counts.get)
    return {
        col: {
            "measured_count": counts[col],
            "usable_as_constraint": counts[col] >= threshold,
            "is_primary_strength_indicator": col == primary,
        }
        for col in AUX_PROPERTY_COLUMNS
    }


class BackwardDesigner:
    """조성(심플렉스 2자유도) + 목표 밀도 + 주요 공정 조건 공간의 역방향 탐색기."""

    def __init__(
        self,
        predictor: Predictor,
        capability: ProcessCapability,
        train_df: pd.DataFrame,
        seed: int = DEFAULT_SEED,
    ):
        self.predictor = predictor
        self.capability = capability
        self.train_df = train_df
        self.seed = seed
        # FF-06 원칙 재사용 — 탐색하지 않는 조건은 학습 데이터 중앙값으로 보완
        self.baseline = {
            col: float(train_df[col].median()) if col in train_df.columns and train_df[col].notna().any() else 0.0
            for col in INPUT_FEATURES
        }

    # ------------------------------------------------------------------
    def _bounds(self, target_areal_capacity: float) -> list[tuple[str, float, float]]:
        cr = self.capability.composition_ranges
        b = cr.get("binder_content", (1.0, 3.5))
        c = cr.get("conductive_content", (1.0, 3.5))
        d = self.capability.target_ranges.get("composite_density_gcc", (2.7, 3.3))
        return [
            ("binder_content", b[0], b[1]),
            ("conductive_content", c[0], c[1]),
            ("target_density_gcc", d[0], d[1]),
            ("kneader_time", max(self.baseline.get("kneader_time", 30.0) * 0.5, 1.0),
             self.baseline.get("kneader_time", 30.0) * 1.5 or 60.0),
        ]

    def _evaluate_point(
        self,
        x: np.ndarray,
        target_areal_capacity: float,
        objectives: list[ObjectiveSpec],
    ) -> Candidate | None:
        binder, conductive, density, kneader_time = (float(v) for v in x)
        active = COMPOSITION_TOTAL_WT - binder - conductive
        am_range = self.capability.composition_ranges.get("active_material_content")
        if am_range and not (am_range[0] <= active <= am_range[1]):
            return None  # FB-04: 조성 제약

        try:
            schedule = search_gap_schedule(
                active_material_fraction=active / 100.0,
                target_areal_capacity=target_areal_capacity,
                target_density_gcc=density,
                capability=self.capability,
            )
        except ScheduleInfeasible:
            return None  # FB-04: 설비·물리 제약

        features = pd.Series(self.baseline).copy()
        features["active_material_content"] = active
        features["binder_content"] = binder
        features["conductive_content"] = conductive
        features["kneader_time"] = kneader_time
        for stage in STAGES:
            features[f"gap_{stage}"] = schedule.gaps_um[stage]

        pred_row = self.predictor.predict_frame(features.to_frame().T).iloc[0]
        predictions = {c: float(v) for c, v in pred_row.items()}

        validation = validate_spec(
            active_material_wt=active, binder_wt=binder, conductive_wt=conductive,
            target_areal_capacity=target_areal_capacity, target_density_gcc=density,
            capability=self.capability,
        )

        obj_vals = _objective_values(predictions, objectives)
        weighted = float(sum(w * v for w, v in zip((o.weight for o in objectives), obj_vals)))
        return Candidate(
            binder_wt=binder, conductive_wt=conductive, active_material_wt=active,
            target_density_gcc=density, features=features, gaps_um=schedule.gaps_um,
            predictions=predictions, objectives=obj_vals, weighted_score=weighted,
            alarm_grade=validation.grade, rationale="",
        )

    # ------------------------------------------------------------------
    def design(
        self,
        objectives: list[ObjectiveSpec],
        target_areal_capacity: float,
        n_samples: int = 120,
        n_bo_calls: int = 0,
        top_k: int = 5,
    ) -> BackwardResult:
        """FB-03~06 — 탐색 → 제약 필터 → Pareto front → 상위 후보."""
        rng = np.random.default_rng(self.seed)
        bounds = self._bounds(target_areal_capacity)
        lows = np.array([b[1] for b in bounds])
        highs = np.array([b[2] for b in bounds])

        strength_info = usable_strength_constraints(self.train_df)
        excluded = [
            f"{col}: 실측 {info['measured_count']}건 < {INTERMITTENT_CONSTRAINT_MIN_COUNT}건 — 참고 지표로만 제시 (FB-07)"
            for col, info in strength_info.items() if not info["usable_as_constraint"]
        ]
        active_objectives = [
            o for o in objectives
            if o.column not in strength_info or strength_info[o.column]["usable_as_constraint"]
        ]
        if not active_objectives:
            active_objectives = objectives

        # 준난수(라틴 하이퍼큐브형) 샘플링 탐색 — 소차원 공간에 충분하며 결정적이다
        samples = lows + (highs - lows) * rng.random((n_samples, len(bounds)))

        # FB-03: 선택적 BO 정밀화 — 가중 스칼라 목적에 대한 EI 탐색
        if n_bo_calls > 0:
            from skopt import gp_minimize

            def scalar_objective(x):
                cand = self._evaluate_point(np.array(x), target_areal_capacity, active_objectives)
                return cand.weighted_score if cand else 1e6

            bo = gp_minimize(
                scalar_objective,
                dimensions=[(float(lo), float(hi)) for _, lo, hi in bounds],
                n_calls=max(n_bo_calls, 10),
                random_state=self.seed,
                acq_func="EI",
            )
            samples = np.vstack([samples, np.array(bo.x_iters)])

        candidates = []
        for x in samples:
            cand = self._evaluate_point(x, target_areal_capacity, active_objectives)
            if cand is not None:
                candidates.append(cand)

        if not candidates:
            return BackwardResult([], [], [], excluded)

        # FB-05: 비지배 정렬 (pymoo NDS)
        from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting

        obj_matrix = np.array([c.objectives for c in candidates])
        fronts = NonDominatedSorting().do(obj_matrix)
        for i in fronts[0]:
            candidates[i].is_pareto = True
        pareto = [candidates[i] for i in fronts[0]]

        # FB-06: 가중 점수 순위화 + 추천 근거
        ranked = sorted(candidates, key=lambda c: c.weighted_score)
        top = ranked[:top_k]
        for cand in top:
            cand.rationale = self._rationale(cand, active_objectives)
        return BackwardResult(candidates, pareto, top, excluded)

    def _rationale(self, cand: Candidate, objectives: list[ObjectiveSpec]) -> str:
        """무엇이 기여했고 무엇을 대가로 지불했는지 (FB-06)."""
        ref_conductive = self.capability.reference_conductive_wt
        parts = []
        if ref_conductive is not None:
            delta = cand.conductive_wt - ref_conductive
            if abs(delta) > 0.1:
                direction = "증량" if delta > 0 else "감량"
                parts.append(f"도전재 {abs(delta):.1f} wt% {direction}")
        for o in objectives:
            v = cand.predictions.get(o.column)
            if v is not None and not np.isnan(v):
                parts.append(f"{o.column} 예측 {v:.3g} ({o.direction})")
        if cand.binder_wt < 2.0:
            parts.append(f"바인더 {cand.binder_wt:.1f} wt% — 시트 강도 저하 대가에 유의")
        return "; ".join(parts) if parts else "기준 조성 근방의 안전 후보"
