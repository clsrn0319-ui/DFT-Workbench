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


@dataclass
class SpecAdvice:
    """AI 스펙 조정 제언 — 사용자 지정 스펙과 무제약 최적점의 괴리를 정량 보고.

    사용자 입력을 임의로 바꾸지 않는다(FV 동작 원칙) — 지정 스펙 결과는 그대로
    제시하고, 주 목표를 더 개선하는 스펙 방향이 있으면 득실과 함께 제언만 한다.
    """

    parameter: str            # 예: "합제밀도"
    user_target: float
    recommended: float
    direction: str            # "증가" | "감소" | "유지"
    primary_column: str | None
    value_at_target: float | None      # 지정 스펙 최선 후보의 주 목표 예측값
    value_at_recommended: float | None  # 무제약 최선 후보의 주 목표 예측값
    message: str


def advise_density_adjustment(
    result: BackwardResult,
    objectives: list[ObjectiveSpec],
    user_target_density: float | None,
    threshold_gcc: float = 0.05,
) -> SpecAdvice | None:
    """주 목표만으로 재순위화한 무제약 최적 밀도와 사용자 지정 밀도를 대조한다.

    탐색은 밀도를 변수로 다루므로, 지정 밀도 equal 목표를 제외한 주 목표
    점수만으로 최선 후보를 찾으면 「목표 개선에 유리한 밀도 방향」이 드러난다.
    """
    if not result.candidates or user_target_density is None:
        return None
    primary_idx = [
        i for i, o in enumerate(objectives)
        if o.column not in ("electrode_density_gcc",)
    ]
    if not primary_idx:
        return None

    def primary_score(cand: Candidate) -> float:
        return sum(objectives[i].weight * cand.objectives[i] for i in primary_idx)

    best = min(result.candidates, key=primary_score)
    primary_col = objectives[primary_idx[0]].column
    near_target = [
        c for c in result.candidates
        if abs(c.target_density_gcc - user_target_density) <= threshold_gcc
    ]
    at_target = min(near_target, key=primary_score) if near_target else None

    diff = best.target_density_gcc - user_target_density
    v_best = best.predictions.get(primary_col)
    v_target = at_target.predictions.get(primary_col) if at_target else None

    if abs(diff) <= threshold_gcc:
        return SpecAdvice(
            parameter="합제밀도", user_target=user_target_density,
            recommended=user_target_density, direction="유지",
            primary_column=primary_col, value_at_target=v_target, value_at_recommended=v_best,
            message=(f"지정 합제밀도 {user_target_density:.2f} g/cc 가 주 목표 기준으로도 "
                     f"최적 근방입니다 — 조정 불필요"),
        )

    direction = "증가" if diff > 0 else "감소"
    gain = ""
    if v_best is not None and v_target is not None and abs(v_target) > 1e-12:
        pct = (v_best - v_target) / abs(v_target) * 100.0
        gain = f" ({primary_col} {v_target:.4g} → {v_best:.4g}, {pct:+.1f}%)"
    caution = (
        " 밀도 상향은 달성 이력·스프링백 여유의 스펙 타당성 검증(FV) 대상입니다."
        if diff > 0 else
        " 밀도 하향 시 합제층 두께가 증가합니다 (동일 로딩 기준)."
    )
    return SpecAdvice(
        parameter="합제밀도", user_target=user_target_density,
        recommended=best.target_density_gcc, direction=direction,
        primary_column=primary_col, value_at_target=v_target, value_at_recommended=v_best,
        message=(f"AI 추천: 주 목표 개선을 위해 합제밀도 {direction}를 추천합니다 — "
                 f"{user_target_density:.2f} → {best.target_density_gcc:.2f} g/cc{gain}.{caution}"),
    )


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
        for stage, gap in schedule.gaps_um.items():
            features[f"gap_{stage}"] = gap
        for stage, front in schedule.gaps_front_um.items():
            features[f"gap_front_{stage}"] = front

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
