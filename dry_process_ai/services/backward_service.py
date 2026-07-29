"""FB — 역방향 설계 서비스 (F2). 목표 성능 → Pareto front + 추천 레시피 5건."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy.orm import Session

from dry_process_ai.core.infer.predictor import Predictor
from dry_process_ai.core.optimize.backward import (
    BackwardDesigner,
    BackwardResult,
    ObjectiveSpec,
    usable_strength_constraints,
)
from dry_process_ai.data_access.capability import build_capability
from dry_process_ai.services.schemas import BackwardRequest


@dataclass
class BackwardResponse:
    result: BackwardResult
    strength_constraint_info: dict
    model_version: str
    train_lot_count: int


def run_backward(
    session: Session,
    predictor: Predictor,
    train_df: pd.DataFrame,
    request: BackwardRequest,
    train_lot_count: int,
) -> BackwardResponse:
    capability = build_capability(session)
    designer = BackwardDesigner(predictor, capability, train_df)
    objectives = [
        ObjectiveSpec(column=o.column, direction=o.direction, weight=o.weight, target=o.target)
        for o in request.objectives
    ]
    result = designer.design(
        objectives,
        target_areal_capacity=request.target_areal_capacity_mah_cm2,
        n_samples=request.n_samples,
        n_bo_calls=request.n_bo_calls,
        top_k=request.top_k,
    )
    return BackwardResponse(
        result=result,
        strength_constraint_info=usable_strength_constraints(train_df),
        model_version=predictor.model_version,
        train_lot_count=train_lot_count,
    )
