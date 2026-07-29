"""FT-07 — 출력 제약층.

변수별 물리 상·하한 clipping 과 단계 간 단조성 제약을 모델 출력단에 적용하여
물리적으로 불가능한 예측값의 출력을 구조적으로 차단한다 (규칙 R5, NFR-04).

모델은 0~1 스케일 공간에서 동작하지만, 서로 다른 컬럼의 Min-Max 파라미터가
다르므로 단조성은 물리 단위 공간에서 강제해야 한다. 이 계층은 registry 의
스케일 파라미터를 상수 텐서로 내장해 (모델과 registry 는 1:1 짝 — 규칙 R8)
물리 단위로 복원 → 제약 적용 → 스케일 공간 복귀를 수행한다.

단조성 (기획서 3.3.2):
    두께      단계 진행에 따라 단조 감소  → 누적 최소값
    합제밀도  단조 증가                → 누적 최대값
    면적당 용량 단조 감소 (트리밍·압착) → 누적 최소값
"""

from __future__ import annotations

import numpy as np
import tensorflow as tf

# 단계별 3항목 출력 순서: (capacity, thickness, density) — builder 와 공유
CAPACITY_IDX, THICKNESS_IDX, DENSITY_IDX = 0, 1, 2


class StageConstraintLayer(tf.keras.layers.Layer):
    """단계별 24출력 (8단계 × [용량, 두께, 밀도]) 제약층."""

    def __init__(self, scale_lo, scale_hi, phys_lo, phys_hi, n_stages: int = 8, **kwargs):
        super().__init__(**kwargs)
        self.n_stages = n_stages
        # (24,) 벡터 — 컬럼 순서는 builder 의 stage 출력 순서와 동일
        self.scale_lo = tf.constant(np.asarray(scale_lo, dtype=np.float32))
        self.scale_hi = tf.constant(np.asarray(scale_hi, dtype=np.float32))
        self.phys_lo = tf.constant(np.asarray(phys_lo, dtype=np.float32))
        self.phys_hi = tf.constant(np.asarray(phys_hi, dtype=np.float32))
        self._config = {
            "scale_lo": list(map(float, scale_lo)), "scale_hi": list(map(float, scale_hi)),
            "phys_lo": list(map(float, phys_lo)), "phys_hi": list(map(float, phys_hi)),
            "n_stages": n_stages,
        }

    def call(self, inputs):
        span = tf.maximum(self.scale_hi - self.scale_lo, 1e-12)
        phys = inputs * span + self.scale_lo                      # 물리 단위 복원
        phys = tf.clip_by_value(phys, self.phys_lo, self.phys_hi)  # 변수별 상·하한

        shaped = tf.reshape(phys, (-1, self.n_stages, 3))          # (batch, stage, 항목)
        capacity = tf.scan(tf.minimum, tf.transpose(shaped[:, :, CAPACITY_IDX]))
        thickness = tf.scan(tf.minimum, tf.transpose(shaped[:, :, THICKNESS_IDX]))
        density = tf.scan(tf.maximum, tf.transpose(shaped[:, :, DENSITY_IDX]))
        shaped = tf.stack(
            [tf.transpose(capacity), tf.transpose(thickness), tf.transpose(density)], axis=2
        )
        phys = tf.reshape(shaped, (-1, self.n_stages * 3))
        return (phys - self.scale_lo) / span                       # 스케일 공간 복귀

    def get_config(self):
        return {**super().get_config(), **self._config}


class RangeConstraintLayer(tf.keras.layers.Layer):
    """단일 벡터 출력(최종 물성·성능)의 물리 범위 clipping 층.

    ICE 80~100 %, 유지율 0~100 %, 저항 > 0 등 고정 물리 범위를 스케일 공간으로
    환산해 clipping 한다. 이력 기반 동적 상한(밀도 등)은 규칙 엔진이 담당한다 (R6).
    """

    def __init__(self, scale_lo, scale_hi, phys_lo, phys_hi, **kwargs):
        super().__init__(**kwargs)
        self.scale_lo = tf.constant(np.asarray(scale_lo, dtype=np.float32))
        self.scale_hi = tf.constant(np.asarray(scale_hi, dtype=np.float32))
        self.phys_lo = tf.constant(np.asarray(phys_lo, dtype=np.float32))
        self.phys_hi = tf.constant(np.asarray(phys_hi, dtype=np.float32))
        self._config = {
            "scale_lo": list(map(float, scale_lo)), "scale_hi": list(map(float, scale_hi)),
            "phys_lo": list(map(float, phys_lo)), "phys_hi": list(map(float, phys_hi)),
        }

    def call(self, inputs):
        span = tf.maximum(self.scale_hi - self.scale_lo, 1e-12)
        phys = inputs * span + self.scale_lo
        phys = tf.clip_by_value(phys, self.phys_lo, self.phys_hi)
        return (phys - self.scale_lo) / span

    def get_config(self):
        return {**super().get_config(), **self._config}
