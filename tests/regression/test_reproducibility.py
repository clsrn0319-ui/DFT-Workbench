"""회귀 시험 — 동일 seed 결과 동일성 (NFR-07, 규칙 R8).

생성 데이터 기반 고정 입력 세트를 반복 실행하여 결정성을 검증한다.
"""

import numpy as np
import pytest

pytest.importorskip("tensorflow")

from dry_process_ai.core.infer.predictor import Predictor  # noqa: E402
from dry_process_ai.core.train.trainer import train_teacher_student  # noqa: E402
from dry_process_ai.data_access.preprocess import ScalingRegistry  # noqa: E402
from dry_process_ai.data_access.repository import ALL_TARGET_COLUMNS, INPUT_FEATURES  # noqa: E402
from dry_process_ai.data_access.sample_data import generate_lot_payloads  # noqa: E402


def test_sample_data_deterministic():
    a = generate_lot_payloads(n_lots=5, seed=99)
    b = generate_lot_payloads(n_lots=5, seed=99)
    assert a == b


def _train_once(df, seed):
    registry = ScalingRegistry.fit(df, list(INPUT_FEATURES), list(ALL_TARGET_COLUMNS), version="v1.0")
    result = train_teacher_student(df, registry, seed=seed, epochs=15, verbose=0, min_pass_rate=0.0)
    return Predictor(result.model, result.spec, registry, "v1.0")


def test_same_seed_same_predictions(session):
    """동일 입력·동일 seed → 동일 학습·동일 예측 (허용 오차 0)."""
    from dry_process_ai.data_access.repository import fetch_dataset, register_lot

    for payload in generate_lot_payloads(n_lots=15, seed=21):
        register_lot(session, payload)
    session.commit()
    df = fetch_dataset(session)

    p1 = _train_once(df, seed=42)
    pred1 = p1.predict_frame(df.head(5))
    p2 = _train_once(df, seed=42)
    pred2 = p2.predict_frame(df.head(5))
    np.testing.assert_array_equal(pred1.to_numpy(), pred2.to_numpy())


def test_pool_generation_deterministic(train_df):
    from dry_process_ai.data_access.pool import generate_pool

    a = generate_pool(train_df, n_candidates=20, seed=3)
    b = generate_pool(train_df, n_candidates=20, seed=3)
    assert a.equals(b)
