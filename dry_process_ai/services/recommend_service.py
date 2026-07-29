"""FR — 실험 추천 서비스. 실험 결과 등록 → pool 이동 → 재학습 트리거 (FR-06)."""

from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from dry_process_ai.core.infer.predictor import Predictor
from dry_process_ai.core.optimize.recommend import (
    Recommendation,
    recommend_experiments,
    save_recommendations,
)
from dry_process_ai.data_access.capability import build_capability
from dry_process_ai.data_access.pool import generate_pool
from dry_process_ai.data_access.repository import fetch_dataset, register_lot
from dry_process_ai.services.schemas import RecommendRequest


def build_unlabeled_pool(session: Session, n_candidates: int = 500,
                         composition_bounds: dict | None = None) -> pd.DataFrame:
    """FD-07 — 실험 가능 범위 내 미탐색 조합 생성."""
    train_df = fetch_dataset(session)
    return generate_pool(train_df, n_candidates=n_candidates, composition_bounds=composition_bounds)


def run_recommend(
    session: Session,
    predictor: Predictor,
    pool_df: pd.DataFrame,
    request: RecommendRequest,
    train_lot_count: int,
    save: bool = True,
) -> list[Recommendation]:
    capability = build_capability(session)
    recs = recommend_experiments(
        predictor, pool_df,
        mode=request.mode, k=request.k,
        targets=request.targets or None,
        capability=capability,
        mc_samples=request.mc_samples,
    )
    if save and recs:
        save_recommendations(recs, request.mode, predictor.model_version, train_lot_count)
    return recs


def register_experiment_result(session: Session, payload: dict) -> tuple[str, bool]:
    """FR-06 — 실험 완료 결과 입력 → train set 이동 + 재학습 트리거 여부 반환.

    payload 는 register_lot 형식. source_flag 는 measured 로 강제한다.
    """
    payload = {**payload, "source_flag": "measured"}
    lot_id = register_lot(session, payload)
    session.commit()
    return lot_id, True  # 신규 실측 Lot 등록 → 재학습 트리거 (FT-08)
