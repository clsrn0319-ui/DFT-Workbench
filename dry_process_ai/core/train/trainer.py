"""FT-02~05, FT-08 — Teacher/Student 준지도 학습 파이프라인.

절차 (기획서 3.3.3):
    ① Teacher 학습 — 성능(C등급) 라벨이 온전한 행만 인덱싱
    ② 의사 라벨 생성 — 성능 라벨 결측 행에 Teacher 적용
    ③ 물리 정합성 필터 — 통과분만 채택, 통과율 로그 (임계 미달 시 중단)
    ④ Student 통합 학습 — 실측 + 고신뢰 의사 라벨 병합

A·B등급 라벨은 마스킹 손실이 결측을 자동 제외하므로 전 행을 사용한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd
import tensorflow as tf

from dry_process_ai.config import (
    DEFAULT_SEED,
    GENERATED_SAMPLE_WEIGHT,
    MEASURED_SAMPLE_WEIGHT,
    PSEUDO_LABEL_MIN_PASS_RATE,
)
from dry_process_ai.core.model.builder import (
    AUX_OUTPUT_COLUMNS,
    FINAL_OUTPUT_COLUMNS,
    ModelSpec,
    PERF_OUTPUT_COLUMNS,
    STAGE_OUTPUT_COLUMNS,
    build_model,
)
from dry_process_ai.core.train.physics_filter import FilterResult, filter_pseudo_labels
from dry_process_ai.data_access.preprocess import ScalingRegistry


class TeacherRejected(RuntimeError):
    """의사 라벨 통과율이 임계 미만 — Student 학습 중단, Teacher 재검토 요청."""


@dataclass
class TrainingResult:
    model: tf.keras.Model
    spec: ModelSpec
    registry: ScalingRegistry
    train_lot_count: int
    measured_ratio: float
    pseudo_label_result: FilterResult | None
    history: dict

    def hyperparameters_json(self) -> str:
        return json.dumps({
            "shared_units": list(self.spec.shared_units),
            "branch_units": self.spec.branch_units,
            "dropout_rate": self.spec.dropout_rate,
            "seed": self.spec.seed,
            "loss_weights": self.spec.loss_weights,
        })


def _target_frames(scaled: pd.DataFrame) -> dict[str, np.ndarray]:
    return {
        "stage": scaled[list(STAGE_OUTPUT_COLUMNS)].to_numpy(dtype=np.float32),
        "final": scaled[list(FINAL_OUTPUT_COLUMNS)].to_numpy(dtype=np.float32),
        "aux": scaled[list(AUX_OUTPUT_COLUMNS)].to_numpy(dtype=np.float32),
        "perf": scaled[list(PERF_OUTPUT_COLUMNS)].to_numpy(dtype=np.float32),
    }


def train_teacher_student(
    df: pd.DataFrame,
    registry: ScalingRegistry,
    seed: int = DEFAULT_SEED,
    epochs: int = 300,
    batch_size: int = 16,
    density_ceiling_gcc: float | None = None,
    min_pass_rate: float = PSEUDO_LABEL_MIN_PASS_RATE,
    verbose: int = 0,
) -> TrainingResult:
    """wide 학습 데이터셋(df)으로 Teacher → Student 학습을 수행한다.

    df 는 fetch_dataset() 산출 형식이어야 하며 source_flag 컬럼을 포함한다.
    """
    tf.keras.utils.set_random_seed(seed)  # 규칙 R8

    feature_cols = registry.feature_columns
    target_cols = registry.target_columns
    scaled = registry.transform(df, feature_cols + target_cols)
    x_all = scaled[feature_cols].fillna(0.5).to_numpy(dtype=np.float32)  # 입력 결측은 중앙 보완(FF-06 대응은 서비스에서 명시)
    y_all = _target_frames(scaled)

    # 실측 1순위 가중 — 생성(합성) Lot 은 낮은 샘플 가중치로 보조 학습에만 기여
    if "source_flag" in df.columns:
        weights = np.where(
            df["source_flag"].to_numpy() == "measured",
            MEASURED_SAMPLE_WEIGHT, GENERATED_SAMPLE_WEIGHT,
        ).astype(np.float32)
    else:
        weights = np.full(len(df), MEASURED_SAMPLE_WEIGHT, dtype=np.float32)

    def _sw(mask: np.ndarray | None = None) -> dict[str, np.ndarray]:
        w = weights if mask is None else weights[mask]
        return {k: w for k in ("stage", "final", "aux", "perf")}

    spec = ModelSpec(
        feature_columns=feature_cols,
        scale_params={c: registry.params[c] for c in target_cols},
        seed=seed,
    )

    # ---- ① Teacher: C등급 라벨 완전 보유 행 ----
    perf_complete = df[list(PERF_OUTPUT_COLUMNS)].notna().all(axis=1).to_numpy()
    teacher_history = {}
    pseudo_result: FilterResult | None = None
    y_student = {k: v.copy() for k, v in y_all.items()}

    if perf_complete.sum() >= 4:
        teacher = build_model(spec)
        h = teacher.fit(
            x_all[perf_complete],
            {k: v[perf_complete] for k, v in y_all.items()},
            sample_weight=_sw(perf_complete),
            epochs=epochs, batch_size=batch_size, verbose=verbose,
        )
        teacher_history = {k: [float(x) for x in v] for k, v in h.history.items()}

        # ---- ② 의사 라벨 생성 ----
        missing = ~perf_complete
        if missing.any():
            pred = teacher.predict(x_all[missing], verbose=0)
            missing_idx = df.index[missing]
            stage_phys = registry.inverse_transform(
                pd.DataFrame(pred["stage"], index=missing_idx, columns=list(STAGE_OUTPUT_COLUMNS))
            )
            perf_phys = registry.inverse_transform(
                pd.DataFrame(pred["perf"], index=missing_idx, columns=list(PERF_OUTPUT_COLUMNS))
            )

            # ---- ③ 물리 정합성 필터 ----
            am_frac = df.loc[missing_idx, "active_material_content"] / 100.0
            pseudo_result = filter_pseudo_labels(
                stage_phys, perf_phys, am_frac, density_ceiling_gcc=density_ceiling_gcc,
            )
            if pseudo_result.pass_rate < min_pass_rate:
                raise TeacherRejected(
                    f"의사 라벨 통과율 {pseudo_result.pass_rate:.1%} < 임계 {min_pass_rate:.0%} — "
                    f"탈락 사유: {pseudo_result.rejected}"
                )

            # ---- 채택분만 Student 라벨에 주입 (scaled 공간) ----
            perf_scaled = registry.transform(perf_phys, list(PERF_OUTPUT_COLUMNS))
            pos = {idx: i for i, idx in enumerate(df.index)}
            for idx in pseudo_result.accepted_index:
                row_scaled = perf_scaled.loc[idx].to_numpy(dtype=np.float32)
                existing = y_student["perf"][pos[idx]]
                y_student["perf"][pos[idx]] = np.where(np.isnan(existing), row_scaled, existing)

    # ---- ④ Student 통합 학습 (실측 1순위 가중) ----
    student = build_model(spec)
    h = student.fit(x_all, y_student, sample_weight=_sw(),
                    epochs=epochs, batch_size=batch_size, verbose=verbose)

    measured = (df["source_flag"] == "measured").sum() if "source_flag" in df.columns else len(df)
    return TrainingResult(
        model=student,
        spec=spec,
        registry=registry,
        train_lot_count=len(df),
        measured_ratio=measured / len(df) if len(df) else 0.0,
        pseudo_label_result=pseudo_result,
        history={"teacher": teacher_history,
                 "student": {k: [float(x) for x in v] for k, v in h.history.items()}},
    )
