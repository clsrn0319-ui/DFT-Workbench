"""FT-06 — 마스킹 손실함수.

B등급(간헐 측정)·C등급(지연 측정) 변수는 측정된 Lot 에서만 손실을 계산하고
미측정 Lot(NaN 라벨)은 역전파에서 제외한다. 결측을 0/평균으로 채우지 않는
FP-02 원칙이 손실 수준에서 완성된다.
"""

from __future__ import annotations

import tensorflow as tf


def masked_mse(y_true: tf.Tensor, y_pred: tf.Tensor) -> tf.Tensor:
    """NaN 라벨을 마스킹하는 MSE — 샘플별 손실 벡터를 반환한다.

    샘플별로 반환해야 Keras 의 sample_weight(실측 1순위 가중 — 실측 1.0,
    생성 GENERATED_SAMPLE_WEIGHT)가 손실에 곱해진다. 전 라벨 결측 샘플은 0.
    """
    mask = tf.cast(tf.logical_not(tf.math.is_nan(y_true)), y_pred.dtype)
    y_true_filled = tf.where(tf.math.is_nan(y_true), tf.zeros_like(y_true), y_true)
    squared_error = tf.square(y_pred - y_true_filled) * mask
    denom = tf.maximum(tf.reduce_sum(mask, axis=-1), 1.0)
    return tf.reduce_sum(squared_error, axis=-1) / denom
