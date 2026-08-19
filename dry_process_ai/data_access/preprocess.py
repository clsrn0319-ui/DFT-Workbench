"""FP — 전처리 엔진 (STEP 2).

- Min-Max 스케일링 파라미터를 registry 로 저장한다 (FP-04).
  registry 는 모델 버전과 1:1 짝으로 보관하며, 로드 시 버전 일치를 검증한다 (규칙 R8).
- 결측(NaN)은 스케일링 후에도 결측 상태를 유지한다 (FP-02) — 0/평균 대체 금지.
- 저변동 변수는 스케일 발산을 막기 위해 자동 제외한다 (FP-05, 리스크 R-04).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import joblib
import numpy as np
import pandas as pd

from dry_process_ai.config import LOW_VARIANCE_THRESHOLD, REGISTRY_DIR


class RegistryVersionMismatch(RuntimeError):
    """모델-registry 버전 불일치. 역스케일링이 조용히 틀리는 것을 막는다 (리스크 R-03)."""


@dataclass
class ScalingRegistry:
    """변수별 Min-Max 스케일 파라미터 저장소.

    version 은 모델 버전과 1:1 대응한다. 물리 단위 복원(inverse_transform)은
    반드시 학습에 사용된 registry 로만 수행한다.
    """

    version: str
    params: dict[str, tuple[float, float]] = field(default_factory=dict)  # {col: (min, max)}
    excluded_low_variance: list[str] = field(default_factory=list)         # FP-05 제외 목록
    feature_columns: list[str] = field(default_factory=list)
    target_columns: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ fit
    @classmethod
    def fit(
        cls,
        df: pd.DataFrame,
        feature_columns: list[str],
        target_columns: list[str],
        version: str,
        low_variance_threshold: float = LOW_VARIANCE_THRESHOLD,
    ) -> "ScalingRegistry":
        registry = cls(version=version)
        registry.target_columns = list(target_columns)

        kept_features: list[str] = []
        for col in feature_columns:
            series = df[col].dropna() if col in df.columns else pd.Series(dtype=float)
            if series.empty:
                registry.excluded_low_variance.append(col)
                continue
            lo, hi = float(series.min()), float(series.max())
            scale_ref = max(abs(float(series.median())), 1.0)
            if (hi - lo) / scale_ref < low_variance_threshold:
                # 저변동 변수 — Min-Max 발산 위험 (FP-05). 학습 제외, 상수 취급.
                registry.excluded_low_variance.append(col)
                continue
            registry.params[col] = (lo, hi)
            kept_features.append(col)
        registry.feature_columns = kept_features

        for col in target_columns:
            series = df[col].dropna() if col in df.columns else pd.Series(dtype=float)
            if series.empty:
                # 라벨이 전무한 목표(예: C등급 초기)는 [0,1] 항등 스케일로 자리 유지
                registry.params[col] = (0.0, 1.0)
                continue
            lo, hi = float(series.min()), float(series.max())
            if hi - lo <= 0:
                hi = lo + max(abs(lo), 1.0)  # 단일값 라벨 보호
            registry.params[col] = (lo, hi)
        return registry

    # ------------------------------------------------------------ transform
    def transform(self, df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
        """0~1 스케일 변환. NaN 은 NaN 으로 유지된다 (FP-02)."""
        cols = columns or (self.feature_columns + self.target_columns)
        out = pd.DataFrame(index=df.index)
        for col in cols:
            lo, hi = self.params[col]
            span = hi - lo if hi > lo else 1.0
            src = df[col] if col in df.columns else pd.Series(np.nan, index=df.index)
            out[col] = (src - lo) / span
        return out

    def inverse_transform(self, df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
        cols = columns or list(df.columns)
        out = pd.DataFrame(index=df.index)
        for col in cols:
            lo, hi = self.params[col]
            span = hi - lo if hi > lo else 1.0
            out[col] = df[col] * span + lo
        return out

    def inverse_value(self, column: str, value: float) -> float:
        lo, hi = self.params[column]
        span = hi - lo if hi > lo else 1.0
        return value * span + lo

    def transform_value(self, column: str, value: float) -> float:
        lo, hi = self.params[column]
        span = hi - lo if hi > lo else 1.0
        return (value - lo) / span

    def missing_mask(self, df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
        """학습용 결측 마스크 (FP-02): 1=측정, 0=결측."""
        mask = pd.DataFrame(index=df.index)
        for col in columns:
            src = df[col] if col in df.columns else pd.Series(np.nan, index=df.index)
            mask[col] = (~src.isna()).astype(float)
        return mask

    # ------------------------------------------------------------- persist
    def save(self, directory=REGISTRY_DIR) -> str:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"scaling_registry_{self.version}.pkl"
        joblib.dump(self, path)
        return str(path)

    @classmethod
    def load(cls, version: str, directory=REGISTRY_DIR, expected_model_version: str | None = None) -> "ScalingRegistry":
        path = directory / f"scaling_registry_{version}.pkl"
        registry: ScalingRegistry = joblib.load(path)
        check_version = expected_model_version or version
        if registry.version != check_version:
            raise RegistryVersionMismatch(
                f"registry 버전 {registry.version} ≠ 모델 버전 {check_version} — "
                "모델과 scaling registry 는 항상 1:1 짝으로 보관해야 한다 (규칙 R8)"
            )
        return registry
