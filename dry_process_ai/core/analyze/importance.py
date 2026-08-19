"""FA — 변수 중요도 분석 (STEP 5).

Permutation importance: 변수별 값을 무작위 치환한 뒤 예측 오차 증가량으로
기여도를 정량화한다 (FA-01). 목표 변수별 분리 산출(FA-02), 단계별 산출(FA-03),
공정군별 집계(FA-04), 조성-공정 상호작용(FA-05)을 제공한다.

생성 데이터는 해석 근거로 사용하지 않는다 — 함수가 source_flag == 'measured'
레코드만 남기고 자동 제외한다 (규칙 R3). 모든 결과에 학습 Lot 수를 병기한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from dry_process_ai.config import DEFAULT_SEED, STAGES
from dry_process_ai.core.infer.predictor import Predictor
from dry_process_ai.data_access.repository import (
    COMPOSITION_FEATURES,
    GAP_FEATURES,
    INPUT_FEATURES,
)

# 공정군 매핑 (FA-04)
_GROUP_OF = {}
for f in INPUT_FEATURES:
    if f in COMPOSITION_FEATURES:
        _GROUP_OF[f] = "formulation"
    elif f.startswith("mixing_"):
        _GROUP_OF[f] = "mixing"
    elif f.startswith("kneader_"):
        _GROUP_OF[f] = "kneading"
    elif f.startswith("cutting_"):
        _GROUP_OF[f] = "cutting"
    elif f.startswith("gap_M"):
        _GROUP_OF[f] = "milling"
    elif f.startswith("gap_R") or f.startswith("rolling_"):
        _GROUP_OF[f] = "rolling"
    elif f.startswith("gap_L") or f.startswith("laminating_") or f in ("foil_thickness_um", "coating_side_flag"):
        _GROUP_OF[f] = "laminating"
    else:
        _GROUP_OF[f] = "other"


@dataclass
class ImportanceResult:
    per_feature: pd.DataFrame     # index=feature, columns=target, 값=오차 증가량
    per_group: pd.DataFrame       # 공정군 집계
    measured_lot_count: int
    model_version: str
    confidence_note: str


def _select_measured(df: pd.DataFrame) -> pd.DataFrame:
    """생성 데이터 자동 제외 (규칙 R3)."""
    if "source_flag" not in df.columns:
        raise ValueError("source_flag 컬럼이 필요하다 — 출처 미상 데이터로는 중요도를 해석하지 않는다")
    return df[df["source_flag"] == "measured"].copy()


def _baseline_errors(predictor: Predictor, df: pd.DataFrame, target_columns: list[str]) -> tuple[pd.DataFrame, pd.Series]:
    pred = predictor.predict_frame(df)
    errors = {}
    for col in target_columns:
        actual = df[col] if col in df.columns else pd.Series(np.nan, index=df.index)
        mask = actual.notna()
        errors[col] = float(((pred.loc[mask, col] - actual[mask]) ** 2).mean()) if mask.any() else np.nan
    return pred, pd.Series(errors)


def permutation_importance(
    predictor: Predictor,
    df: pd.DataFrame,
    target_columns: list[str],
    n_repeats: int = 5,
    seed: int = DEFAULT_SEED,
    features: list[str] | None = None,
) -> ImportanceResult:
    """FA-01/02/04 — 목표 변수별 permutation importance."""
    measured = _select_measured(df)
    if measured.empty:
        raise ValueError("실측 Lot 이 없어 중요도를 산출할 수 없다")
    rng = np.random.default_rng(seed)
    feats = features or [f for f in predictor.spec.feature_columns]
    _, baseline = _baseline_errors(predictor, measured, target_columns)

    rows = {}
    for feat in feats:
        deltas = np.zeros(len(target_columns))
        for _ in range(n_repeats):
            shuffled = measured.copy()
            shuffled[feat] = rng.permutation(shuffled[feat].to_numpy())
            _, permuted = _baseline_errors(predictor, shuffled, target_columns)
            deltas += (permuted - baseline).to_numpy()
        rows[feat] = deltas / n_repeats
    per_feature = pd.DataFrame.from_dict(rows, orient="index", columns=target_columns)

    per_group = per_feature.copy()
    per_group["process_group"] = [_GROUP_OF.get(f, "other") for f in per_feature.index]
    per_group = per_group.groupby("process_group").sum()

    n = len(measured)
    note = (
        f"학습 Lot 수 {n}건 기준. "
        + ("Lot 수가 적어 특정 변수에 중요도가 과도 집중될 수 있음 — 시계열 관리 필요 (리스크 R-01)"
           if n < 30 else "정확도 지표 적용 구간 (30건 이상)")
    )
    return ImportanceResult(
        per_feature=per_feature,
        per_group=per_group,
        measured_lot_count=n,
        model_version=predictor.model_version,
        confidence_note=note,
    )


def stage_importance(
    predictor: Predictor,
    df: pd.DataFrame,
    n_repeats: int = 3,
    seed: int = DEFAULT_SEED,
) -> pd.DataFrame:
    """FA-03 — M1~L2 각 단계 두께·밀도 예측의 지배 변수.

    조성·피브릴화 지배 구간 → 갭·압력 지배 구간의 전환점 확인용.
    """
    targets = [f"{s}_{t}" for s in STAGES for t in ("composite_thickness_um", "composite_density_gcc")]
    result = permutation_importance(predictor, df, targets, n_repeats=n_repeats, seed=seed)
    return result.per_feature


def composition_process_interaction(
    predictor: Predictor,
    df: pd.DataFrame,
    process_features: list[str] | None = None,
    target_column: str = "sheet_resistance_ohm_sq",
    n_repeats: int = 3,
    seed: int = DEFAULT_SEED,
) -> pd.DataFrame:
    """FA-05 — 조성-공정 상호작용 히트맵 데이터.

    동시 치환 오차 증가량 − 개별 치환 합 = 상호작용 크기.
    「조성이 바뀌면 어떤 공정을 다시 잡아야 하는가」에 직접 답한다.
    """
    measured = _select_measured(df)
    rng = np.random.default_rng(seed)
    proc_feats = process_features or ["kneader_time", "mixing_rpm", "gap_L2", "laminating_pressure"]
    proc_feats = [f for f in proc_feats if f in predictor.spec.feature_columns]
    comp_feats = [f for f in COMPOSITION_FEATURES if f in predictor.spec.feature_columns]

    _, baseline = _baseline_errors(predictor, measured, [target_column])
    base = baseline[target_column]

    def _delta(features_to_permute: list[str]) -> float:
        total = 0.0
        for _ in range(n_repeats):
            shuffled = measured.copy()
            for f in features_to_permute:
                shuffled[f] = rng.permutation(shuffled[f].to_numpy())
            _, permuted = _baseline_errors(predictor, shuffled, [target_column])
            total += permuted[target_column] - base
        return total / n_repeats

    singles = {f: _delta([f]) for f in comp_feats + proc_feats}
    matrix = pd.DataFrame(index=comp_feats, columns=proc_feats, dtype=float)
    for cf in comp_feats:
        for pf in proc_feats:
            matrix.loc[cf, pf] = _delta([cf, pf]) - (singles[cf] + singles[pf])
    return matrix
