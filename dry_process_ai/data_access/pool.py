"""FD-07 — unlabeled pool 생성.

실험 가능한 조성 범위와 설비 사양 범위 안에서만 미탐색 조합을 생성한다.
범위 밖 조합은 후보에서 제외하여 실현 불가능한 추천을 원천 차단한다.
"""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd

from dry_process_ai.config import COMPOSITION_TOTAL_WT, DATA_POOL_DIR, DEFAULT_SEED, STAGES
from dry_process_ai.data_access.repository import GAP_FEATURES, INPUT_FEATURES


def generate_pool(
    train_df: pd.DataFrame,
    n_candidates: int = 500,
    composition_bounds: dict[str, tuple[float, float]] | None = None,
    seed: int = DEFAULT_SEED,
) -> pd.DataFrame:
    """학습 분포와 설비 이력 범위 안에서 미탐색 조성-공정 조합을 샘플링한다.

    composition_bounds 예: {"active_material_content": (94, 98),
                            "binder_content": (1, 3), "conductive_content": (1, 3)}
    미지정 시 학습 데이터의 실측 범위를 사용한다.
    """
    rng = np.random.default_rng(seed)
    bounds: dict[str, tuple[float, float]] = {}
    for col in INPUT_FEATURES:
        series = train_df[col].dropna() if col in train_df.columns else pd.Series(dtype=float)
        if composition_bounds and col in composition_bounds:
            bounds[col] = composition_bounds[col]
        elif not series.empty:
            bounds[col] = (float(series.min()), float(series.max()))
        else:
            bounds[col] = (0.0, 0.0)

    rows = []
    attempts = 0
    while len(rows) < n_candidates and attempts < n_candidates * 50:
        attempts += 1
        # 조성: 도전재·바인더를 범위 내 샘플링, 활물질은 합계 100 으로 종속 (심플렉스 2자유도)
        b_lo, b_hi = bounds["binder_content"]
        c_lo, c_hi = bounds["conductive_content"]
        binder = rng.uniform(b_lo, b_hi)
        conductive = rng.uniform(c_lo, c_hi)
        active = COMPOSITION_TOTAL_WT - binder - conductive
        a_lo, a_hi = bounds["active_material_content"]
        if not (a_lo <= active <= a_hi):
            continue

        row = {
            "active_material_content": active,
            "binder_content": binder,
            "conductive_content": conductive,
        }
        for col in INPUT_FEATURES:
            if col in row:
                continue
            lo, hi = bounds[col]
            row[col] = rng.uniform(lo, hi) if hi > lo else lo

        # 갭 스케줄은 단조 감소로 정렬해 설비 운용 형태를 유지한다
        gaps = sorted([row[g] for g in GAP_FEATURES], reverse=True)
        for g, v in zip(GAP_FEATURES, gaps):
            row[g] = v
        rows.append(row)

    return pd.DataFrame(rows, columns=list(INPUT_FEATURES))


def save_pool(pool_df: pd.DataFrame, directory=DATA_POOL_DIR, today: datetime.date | None = None) -> str:
    """pool_{YYYYMMDD}.csv 규약으로 저장 (12.2)."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = (today or datetime.date.today()).strftime("%Y%m%d")
    path = directory / f"pool_{stamp}.csv"
    pool_df.to_csv(path, index=False)
    return str(path)
