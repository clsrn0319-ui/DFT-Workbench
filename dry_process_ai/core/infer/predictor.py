"""FF-04/05/07/08 — 추론기.

registry 스케일링 → 모델 추론 → 역스케일링 → 정합성 검사 → MC Dropout 신뢰 구간.
모든 예측값은 신뢰 구간과 확보 등급(A/B/C) 배지를 동반한다 (NFR-05).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import tensorflow as tf

from dry_process_ai.config import ACTIVE_STAGES, MC_DROPOUT_SAMPLES, STAGES
from dry_process_ai.core.model.builder import (
    AUX_OUTPUT_COLUMNS,
    FINAL_OUTPUT_COLUMNS,
    ModelSpec,
    PERF_OUTPUT_COLUMNS,
    STAGE_OUTPUT_COLUMNS,
)
from dry_process_ai.data_access.preprocess import ScalingRegistry
from dry_process_ai.rules import constraints, physics

ALL_OUTPUT_COLUMNS = STAGE_OUTPUT_COLUMNS + FINAL_OUTPUT_COLUMNS + AUX_OUTPUT_COLUMNS + PERF_OUTPUT_COLUMNS

GRADE_BY_COLUMN: dict[str, str] = {
    **{c: "A" for c in STAGE_OUTPUT_COLUMNS},
    **{c: "A" for c in FINAL_OUTPUT_COLUMNS},
    **{c: "B" for c in AUX_OUTPUT_COLUMNS},
    **{c: "C" for c in PERF_OUTPUT_COLUMNS},
}


@dataclass
class PredictionInterval:
    mean: float
    lower: float
    upper: float
    std: float
    grade: str


@dataclass
class PredictionResult:
    """단일 레시피 예측 결과 (물리 단위)."""

    values: dict[str, PredictionInterval]
    stage_table: pd.DataFrame               # 단계별 예측표 (로딩 병기 — FF-04)
    consistency: constraints.ConsistencyReport
    model_version: str
    mc_samples: int
    warnings: list[str] = field(default_factory=list)


class Predictor:
    def __init__(self, model: tf.keras.Model, spec: ModelSpec, registry: ScalingRegistry, model_version: str):
        self.model = model
        self.spec = spec
        self.registry = registry
        self.model_version = model_version

    # ------------------------------------------------------------ helpers
    def _features_matrix(self, features: pd.DataFrame) -> np.ndarray:
        scaled = self.registry.transform(features, self.spec.feature_columns)
        return scaled.fillna(0.5).to_numpy(dtype=np.float32)

    def _flat_outputs(self, pred: dict) -> np.ndarray:
        return np.concatenate(
            [pred["stage"], pred["final"], pred["aux"], pred["perf"]], axis=1
        )

    def predict_frame(self, features: pd.DataFrame) -> pd.DataFrame:
        """배치 추론 (결정적, Dropout 비활성) → 물리 단위 DataFrame."""
        x = self._features_matrix(features)
        pred = self.model.predict(x, verbose=0)
        flat = self._flat_outputs(pred)
        scaled = pd.DataFrame(flat, index=features.index, columns=list(ALL_OUTPUT_COLUMNS))
        return self.registry.inverse_transform(scaled)

    def mc_predict_frame(
        self, features: pd.DataFrame, n_samples: int = MC_DROPOUT_SAMPLES, seed: int | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """MC Dropout 반복 추론 → (평균, 표준편차) 물리 단위 (FF-07, FR-01)."""
        if seed is not None:
            tf.keras.utils.set_random_seed(seed)
        x = tf.convert_to_tensor(self._features_matrix(features))
        samples = []
        for _ in range(n_samples):
            pred = self.model(x, training=True)  # 추론 시에도 Dropout 활성화
            samples.append(self._flat_outputs({k: v.numpy() for k, v in pred.items()}))
        stack = np.stack(samples)  # (n, batch, outputs)
        cols = list(ALL_OUTPUT_COLUMNS)
        mean = self.registry.inverse_transform(
            pd.DataFrame(stack.mean(axis=0), index=features.index, columns=cols)
        )
        # 표준편차는 span 배율만 적용 (오프셋 무관)
        std_scaled = pd.DataFrame(stack.std(axis=0), index=features.index, columns=cols)
        spans = {c: max(self.registry.params[c][1] - self.registry.params[c][0], 1e-12) for c in cols}
        std = std_scaled * pd.Series(spans)
        return mean, std

    # ------------------------------------------------------------- single
    def predict_one(
        self,
        features: pd.Series,
        active_material_fraction: float,
        gaps_um: dict[str, float] | None = None,
        density_ceiling_gcc: float | None = None,
        n_samples: int = MC_DROPOUT_SAMPLES,
        seed: int | None = None,
        stages: tuple = ACTIVE_STAGES,
    ) -> PredictionResult:
        """단일 레시피에 대한 전체 예측 + 정합성 검사 + 신뢰 구간 (FF-04/05/07/08)."""
        frame = features.to_frame().T
        mean, std = self.mc_predict_frame(frame, n_samples=n_samples, seed=seed)
        mean_row, std_row = mean.iloc[0], std.iloc[0]

        values = {
            col: PredictionInterval(
                mean=float(mean_row[col]),
                lower=float(mean_row[col] - 1.96 * std_row[col]),
                upper=float(mean_row[col] + 1.96 * std_row[col]),
                std=float(std_row[col]),
                grade=GRADE_BY_COLUMN[col],
            )
            for col in ALL_OUTPUT_COLUMNS
        }

        # 단계별 예측표 — 로딩은 두께×밀도로부터 계산해 병기한다 (FF-04).
        # 면적당 용량은 정합성 제약상 로딩·조성에 종속이므로 (세 값 중 둘이
        # 정해지면 나머지는 종속) 물리식으로 정합화하여 표기한다 — 규칙 R5:
        # 물리적으로 불가능한(자기모순인) 값은 화면에 나오지 않는다.
        # 단계별 표·정합성 검사는 운용 단계(ACTIVE_STAGES)만 대상 — 모델 출력
        # 스키마(8단계)는 유지되어 R2 이력 학습·다단 복귀에 무변경 대응한다.
        rows = []
        stage_values = {}
        for stage in stages:
            t = float(mean_row[f"{stage}_composite_thickness_um"])
            d = float(mean_row[f"{stage}_composite_density_gcc"])
            loading = physics.loading_mg_cm2(t, d)
            q = physics.areal_capacity_mah_cm2(loading, active_material_fraction)
            rows.append({
                "stage_index": stage,
                "areal_capacity_mah_cm2": q,
                "composite_thickness_um": t,
                "composite_density_gcc": d,
                "loading_mg_cm2": loading,
                "gap_um": gaps_um.get(stage) if gaps_um else None,
            })
            stage_values[stage] = {
                "areal_capacity_mah_cm2": q,
                "composite_thickness_um": t,
                "composite_density_gcc": d,
                "loading_mg_cm2": loading,
            }
        stage_table = pd.DataFrame(rows)

        # FF-08 독립 정합성 검사 (출력 제약층과 이중 방어 — 규칙 R5)
        report = constraints.check_stage_sequence(
            stage_values,
            gaps_um=gaps_um,
            density_ceiling_gcc=density_ceiling_gcc,
            active_material_fraction=active_material_fraction,
        )
        return PredictionResult(
            values=values,
            stage_table=stage_table,
            consistency=report,
            model_version=self.model_version,
            mc_samples=n_samples,
        )
