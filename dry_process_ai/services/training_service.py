"""FD/FP/FT 파이프라인 조립 — 적재 → 정제 → 스케일링 → 학습 → 버전 저장.

Phase 1~2 완료 판정 경로: 데이터 오류 없이 적재 + scaling registry 생성 →
준지도 학습 완료 + 물리 제약 위반 0건.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import pandas as pd
from sqlalchemy.orm import Session

from dry_process_ai.config import DATA_PROCESSED_DIR, DEFAULT_SEED
from dry_process_ai.core.infer.predictor import Predictor
from dry_process_ai.core.train.trainer import TrainingResult, train_teacher_student
from dry_process_ai.core.train.versioning import load_model_version, next_version, save_model_version
from dry_process_ai.data_access.capability import build_capability
from dry_process_ai.data_access.db import ModelVersion
from dry_process_ai.data_access.preprocess import ScalingRegistry
from dry_process_ai.data_access.repository import ALL_TARGET_COLUMNS, INPUT_FEATURES, fetch_dataset, fetch_stage_long
from dry_process_ai.rules.constraints import density_ceiling_from_history
from dry_process_ai.rules.outliers import detect_stage_outliers, replace_with_median


@dataclass
class PipelineResult:
    version_id: str
    dataset_tag: str
    train_lot_count: int
    outlier_flags: int
    pseudo_label_pass_rate: float | None
    model_dir: str


def run_training_pipeline(
    session: Session,
    seed: int = DEFAULT_SEED,
    epochs: int = 300,
    structural_change: bool = False,
    verbose: int = 0,
) -> PipelineResult:
    """전처리 → registry → Teacher/Student → 버전 저장의 전체 파이프라인."""
    df = fetch_dataset(session)
    if df.empty:
        raise RuntimeError("적재된 Lot 이 없다 — FD-01/FD-02 로 데이터를 먼저 등록하라")

    # ---- FP-01: 물리 기반 이상치 판정·대체 (실측 이력 범위는 동적 산출) ----
    stage_long = fetch_stage_long(session)
    density_range = None
    d = stage_long["composite_density_gcc"].dropna() if not stage_long.empty else pd.Series(dtype=float)
    if len(d) >= 5:
        density_range = (float(d.min()), float(d.max()))
    outlier_report = detect_stage_outliers(stage_long, density_history_range=density_range)
    if outlier_report.flags:
        replace_with_median(stage_long, outlier_report)

    # ---- FP-04: scaling registry (버전은 저장 시 모델 버전과 짝 맞춤) ----
    version_id = next_version(session, structural_change=structural_change)
    registry = ScalingRegistry.fit(
        df,
        feature_columns=list(INPUT_FEATURES),
        target_columns=list(ALL_TARGET_COLUMNS),
        version=version_id,
    )

    # ---- 산출물 규약: train_{YYYYMMDD}_{lotcount}.csv ----
    stamp = datetime.date.today().strftime("%Y%m%d")
    dataset_tag = f"train_{stamp}_{len(df)}"
    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(DATA_PROCESSED_DIR / f"{dataset_tag}.csv", index=False)

    # ---- FT-02~05: Teacher/Student — 밀도 상한은 이력 기반 동적 산출 ----
    capability = build_capability(session)
    result: TrainingResult = train_teacher_student(
        df, registry, seed=seed, epochs=epochs,
        density_ceiling_gcc=density_ceiling_from_history(capability.max_density_gcc),
        verbose=verbose,
    )

    model_dir = save_model_version(session, result, version_id, dataset_tag=dataset_tag)
    return PipelineResult(
        version_id=version_id,
        dataset_tag=dataset_tag,
        train_lot_count=result.train_lot_count,
        outlier_flags=len(outlier_report.flags),
        pseudo_label_pass_rate=(
            result.pseudo_label_result.pass_rate if result.pseudo_label_result else None
        ),
        model_dir=model_dir,
    )


def load_latest_predictor(session: Session) -> tuple[Predictor, int] | None:
    """최신 모델 버전 로드 → (Predictor, 학습 Lot 수). 없으면 None."""
    row = (
        session.query(ModelVersion)
        .order_by(ModelVersion.trained_at.desc())
        .first()
    )
    if row is None:
        return None
    model, spec, registry = load_model_version(row.version_id)
    return Predictor(model, spec, registry, row.version_id), row.train_lot_count
