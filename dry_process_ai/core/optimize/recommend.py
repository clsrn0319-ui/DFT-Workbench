"""FR — 능동학습 실험 추천 (STEP 6).

MC Dropout 불확실성(FR-01)과 목표 근접도를 결합해 unlabeled pool 에서
Top-K 실험 조건을 추천한다. 추천 모드 (FR-02):
    탐색(exploration)   불확실성 최대 우선 — 초기 데이터 축적 구간
    활용(exploitation)  목표 달성 확률 최대 우선 — 최적화 구간
    균형(balanced)      두 기준의 가중 합 (기본값)
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from dry_process_ai.config import DEFAULT_SEED, RECOMMENDATIONS_DIR
from dry_process_ai.core.infer.predictor import ALL_OUTPUT_COLUMNS, Predictor
from dry_process_ai.rules.spec_validation import ProcessCapability

MODES = ("exploration", "exploitation", "balanced")


@dataclass
class Recommendation:
    rank: int
    features: dict[str, float]
    uncertainty: float
    goal_proximity: float
    combined_score: float
    predictions: dict[str, float]
    reason: str


def recommend_experiments(
    predictor: Predictor,
    pool_df: pd.DataFrame,
    mode: str = "balanced",
    k: int = 5,
    target_columns: list[str] | None = None,
    targets: dict[str, float] | None = None,
    capability: ProcessCapability | None = None,
    mc_samples: int = 20,
    seed: int = DEFAULT_SEED,
    balance_weight: float = 0.5,
) -> list[Recommendation]:
    """pool 전체를 배치 추론으로 1회 처리 후 정렬한다 (성능 설계 15장)."""
    if mode not in MODES:
        raise ValueError(f"mode 는 {MODES} 중 하나여야 함: {mode}")

    pool = pool_df.reset_index(drop=True)

    # FR-04: 설비 가능 범위 필터 — 이력 최소 갭 미만 후보 제외
    if capability is not None and capability.min_gap_um is not None:
        gap_cols = [c for c in pool.columns if c.startswith("gap_")]
        if gap_cols:
            ok = (pool[gap_cols] >= capability.min_gap_um).all(axis=1)
            pool = pool.loc[ok].reset_index(drop=True)
    if pool.empty:
        return []

    mean, std = predictor.mc_predict_frame(pool, n_samples=mc_samples, seed=seed)

    focus = target_columns or list(ALL_OUTPUT_COLUMNS)
    # 목표 변수별 불확실성 가중 합산 (FR-01 ③) — 스케일 차 제거를 위해 상대 표준편차 사용
    rel_std = (std[focus] / mean[focus].abs().clip(lower=1e-9)).mean(axis=1)
    uncertainty = (rel_std - rel_std.min()) / max(rel_std.max() - rel_std.min(), 1e-12)

    if targets:
        distances = pd.Series(0.0, index=pool.index)
        for col, target in targets.items():
            if col in mean.columns:
                distances += ((mean[col] - target).abs() / max(abs(target), 1e-9))
        proximity_raw = -distances
        goal_proximity = (proximity_raw - proximity_raw.min()) / max(proximity_raw.max() - proximity_raw.min(), 1e-12)
    else:
        goal_proximity = pd.Series(0.0, index=pool.index)

    if mode == "exploration":
        score = uncertainty
    elif mode == "exploitation":
        score = goal_proximity
    else:
        score = balance_weight * uncertainty + (1.0 - balance_weight) * goal_proximity

    top_idx = score.sort_values(ascending=False).head(k).index
    recs = []
    for rank, idx in enumerate(top_idx, start=1):
        # FR-05: 이 실험이 모델의 어떤 불확실성을 해소하는가
        col_std = (std.loc[idx, focus] / mean.loc[idx, focus].abs().clip(lower=1e-9))
        worst = col_std.sort_values(ascending=False).head(2)
        reason = (
            f"불확실성 상위 항목: " + ", ".join(f"{c} (±{std.loc[idx, c]:.3g})" for c in worst.index)
            + (f"; 목표 근접도 {goal_proximity[idx]:.2f}" if targets else "")
            + f" — {mode} 모드"
        )
        recs.append(Recommendation(
            rank=rank,
            features={c: float(pool.loc[idx, c]) for c in pool.columns},
            uncertainty=float(uncertainty[idx]),
            goal_proximity=float(goal_proximity[idx]),
            combined_score=float(score[idx]),
            predictions={c: float(mean.loc[idx, c]) for c in focus},
            reason=reason,
        ))
    return recs


def save_recommendations(
    recs: list[Recommendation],
    mode: str,
    model_version: str,
    train_lot_count: int,
    directory=RECOMMENDATIONS_DIR,
    today: datetime.date | None = None,
) -> str:
    """recommend_{YYYYMMDD}_{mode}.json 규약으로 저장 (12.2).

    모델 버전과 학습 Lot 수를 반드시 기록한다 (NFR-08).
    """
    directory.mkdir(parents=True, exist_ok=True)
    stamp = (today or datetime.date.today()).strftime("%Y%m%d")
    path = directory / f"recommend_{stamp}_{mode}.json"
    payload = {
        "model_version": model_version,
        "train_lot_count": train_lot_count,
        "mode": mode,
        "recommendations": [
            {
                "rank": r.rank, "features": r.features, "uncertainty": r.uncertainty,
                "goal_proximity": r.goal_proximity, "combined_score": r.combined_score,
                "predictions": r.predictions, "reason": r.reason,
            }
            for r in recs
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
