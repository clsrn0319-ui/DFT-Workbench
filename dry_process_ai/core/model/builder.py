"""FT-01 — 계층적 다중 출력 모델 구성.

Input (조성 + 6공정 조건 + collector 플래그)
  └─ 공유 기저층 (Dense + Dropout ← MC Dropout 에 재사용)
       ├─ 단계별 물성 분기 → 8단계 × 3항목 = 24 출력  [A등급, 단조성 제약]
       │      └─ concat ─→ 최종 물성 분기 → 두께·밀도·시트 저항  [A등급, 표준 손실]
       │                       └─→ 보조 물성 분기 → 인장강도·접착력 [B등급, 마스킹 손실]
       └─ 공유층 + 물성 분기 출력 concat → 성능 분기
              → 초기 방전 용량, ICE, 계면 저항, 유지율  [C등급, 준지도 + 마스킹 손실]
  └─ 출력 제약층 (clipping + 단조성 강제)

성능 분기가 물성 분기 출력을 입력으로 받는 것은 의도된 설계다 —
"전극의 물리적 구조가 결정되어야 전기화학 특성이 발현된다"는 도메인 인과를
신경망 연결에 직접 주입한 것이므로 병렬 분기로 평탄화하지 말 것 (CLAUDE.md 6장).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import tensorflow as tf

from dry_process_ai.config import DEFAULT_SEED, STAGES
from dry_process_ai.core.model.constraint_layer import RangeConstraintLayer, StageConstraintLayer
from dry_process_ai.core.model.losses import masked_mse

# 출력 헤드 정의 (컬럼 순서 고정 — Predictor / Trainer 와 공유)
STAGE_OUTPUT_COLUMNS = tuple(
    f"{s}_{t}" for s in STAGES
    for t in ("areal_capacity_mah_cm2", "composite_thickness_um", "composite_density_gcc")
)
FINAL_OUTPUT_COLUMNS = ("electrode_thickness_um", "electrode_density_gcc", "sheet_resistance_ohm_sq")
AUX_OUTPUT_COLUMNS = ("tensile_strength_mpa", "electrode_adhesion_n_cm")
PERF_OUTPUT_COLUMNS = (
    "initial_discharge_capacity_mah_g", "initial_coulombic_efficiency_pct",
    "interface_resistance_ohm", "cell_discharge_retention_pct",
)

# 고정 물리 범위 (기획서 3.3.4 출력 범위 제약표). 이력 기반 동적 상·하한은
# 규칙 엔진(FF-08)이 이중 방어로 담당한다.
_FIXED_PHYS_RANGES = {
    "areal_capacity_mah_cm2": (0.0, 1e6),
    "composite_thickness_um": (0.0, 1e6),
    "composite_density_gcc": (0.0, 1e6),
    "electrode_thickness_um": (0.0, 1e6),
    "electrode_density_gcc": (0.0, 1e6),
    "sheet_resistance_ohm_sq": (1e-6, 1e9),
    "tensile_strength_mpa": (0.0, 1e6),
    "electrode_adhesion_n_cm": (0.0, 1e6),
    "initial_discharge_capacity_mah_g": (1e-6, 1e9),
    "initial_coulombic_efficiency_pct": (80.0, 100.0),
    "interface_resistance_ohm": (1e-6, 1e9),
    "cell_discharge_retention_pct": (0.0, 100.0),
}


@dataclass
class ModelSpec:
    """모델 구조·재현 정보. registry 와 함께 저장되어 로드 시 재구성에 쓰인다."""

    feature_columns: list[str]
    scale_params: dict[str, tuple[float, float]]  # 출력 컬럼별 registry (min, max)
    shared_units: tuple = (64, 64)
    branch_units: int = 32
    dropout_rate: float = 0.15
    seed: int = DEFAULT_SEED
    loss_weights: dict = field(default_factory=lambda: {
        "stage": 1.0, "final": 1.0, "aux": 0.5, "perf": 0.5,
    })


def _range_arrays(columns: tuple, scale_params: dict) -> tuple[list, list, list, list]:
    scale_lo = [scale_params[c][0] for c in columns]
    scale_hi = [scale_params[c][1] for c in columns]
    base = [c.split("_", 1)[1] if c.split("_", 1)[0] in STAGES else c for c in columns]
    phys_lo = [_FIXED_PHYS_RANGES[b][0] for b in base]
    phys_hi = [_FIXED_PHYS_RANGES[b][1] for b in base]
    return scale_lo, scale_hi, phys_lo, phys_hi


def build_model(spec: ModelSpec) -> tf.keras.Model:
    tf.keras.utils.set_random_seed(spec.seed)  # 재현성 (규칙 R8)

    inputs = tf.keras.Input(shape=(len(spec.feature_columns),), name="features")

    x = inputs
    for i, units in enumerate(spec.shared_units):
        x = tf.keras.layers.Dense(units, activation="relu", name=f"shared_{i}")(x)
        # MC Dropout 재사용을 위해 공유층에 Dropout 을 둔다 (FF-07, FR-01)
        x = tf.keras.layers.Dropout(spec.dropout_rate, name=f"shared_dropout_{i}")(x)
    shared = x

    # --- 단계별 물성 분기 (A등급, 24출력) ---
    sb = tf.keras.layers.Dense(spec.branch_units, activation="relu", name="stage_dense")(shared)
    sb = tf.keras.layers.Dropout(spec.dropout_rate, name="stage_dropout")(sb)
    stage_raw = tf.keras.layers.Dense(len(STAGE_OUTPUT_COLUMNS), activation="sigmoid", name="stage_raw")(sb)
    stage_out = StageConstraintLayer(
        *_range_arrays(STAGE_OUTPUT_COLUMNS, spec.scale_params), n_stages=len(STAGES), name="stage",
    )(stage_raw)

    # --- 최종 물성 분기 (A등급) — 단계별 분기 출력을 concat 하여 입력받는다 ---
    fb = tf.keras.layers.Concatenate(name="final_concat")([shared, stage_out])
    fb = tf.keras.layers.Dense(spec.branch_units, activation="relu", name="final_dense")(fb)
    final_raw = tf.keras.layers.Dense(len(FINAL_OUTPUT_COLUMNS), activation="sigmoid", name="final_raw")(fb)
    final_out = RangeConstraintLayer(
        *_range_arrays(FINAL_OUTPUT_COLUMNS, spec.scale_params), name="final",
    )(final_raw)

    # --- 보조 물성 분기 (B등급, 마스킹 손실) — 최종 물성 분기 출력을 입력받는다 ---
    ab = tf.keras.layers.Concatenate(name="aux_concat")([fb, final_out])
    ab = tf.keras.layers.Dense(spec.branch_units // 2, activation="relu", name="aux_dense")(ab)
    aux_raw = tf.keras.layers.Dense(len(AUX_OUTPUT_COLUMNS), activation="sigmoid", name="aux_raw")(ab)
    aux_out = RangeConstraintLayer(
        *_range_arrays(AUX_OUTPUT_COLUMNS, spec.scale_params), name="aux",
    )(aux_raw)

    # --- 성능 분기 (C등급) — 공유층 + 물성 분기 출력 concat (물성→성능 인과 주입) ---
    pb = tf.keras.layers.Concatenate(name="perf_concat")([shared, stage_out, final_out])
    pb = tf.keras.layers.Dense(spec.branch_units, activation="relu", name="perf_dense")(pb)
    pb = tf.keras.layers.Dropout(spec.dropout_rate, name="perf_dropout")(pb)
    perf_raw = tf.keras.layers.Dense(len(PERF_OUTPUT_COLUMNS), activation="sigmoid", name="perf_raw")(pb)
    perf_out = RangeConstraintLayer(
        *_range_arrays(PERF_OUTPUT_COLUMNS, spec.scale_params), name="perf",
    )(perf_raw)

    model = tf.keras.Model(
        inputs=inputs,
        outputs={"stage": stage_out, "final": final_out, "aux": aux_out, "perf": perf_out},
        name="dry_process_master_model",
    )
    model.compile(
        optimizer=tf.keras.optimizers.Adam(1e-3),
        loss={"stage": masked_mse, "final": masked_mse, "aux": masked_mse, "perf": masked_mse},
        loss_weights=spec.loss_weights,
    )
    return model
