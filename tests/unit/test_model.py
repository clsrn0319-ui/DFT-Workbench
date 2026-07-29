"""FT-01/06/07 — 모델 구조·마스킹 손실·출력 제약층 시험."""

import numpy as np
import pandas as pd
import pytest

tf = pytest.importorskip("tensorflow")

from dry_process_ai.config import STAGES  # noqa: E402


def test_masked_mse_ignores_nan():
    from dry_process_ai.core.model.losses import masked_mse

    y_true = tf.constant([[1.0, np.nan], [np.nan, 2.0]])
    y_pred = tf.constant([[1.5, 100.0], [100.0, 2.5]])
    # NaN 위치의 큰 오차(100)는 손실에 기여하지 않아야 한다
    loss = float(masked_mse(y_true, y_pred))
    assert loss == pytest.approx((0.5 ** 2 + 0.5 ** 2) / 2)


def test_masked_mse_all_nan_returns_zero():
    from dry_process_ai.core.model.losses import masked_mse

    y_true = tf.constant([[np.nan, np.nan]])
    y_pred = tf.constant([[1.0, 2.0]])
    assert float(masked_mse(y_true, y_pred)) == 0.0


def _tiny_spec():
    from dry_process_ai.core.model.builder import (
        AUX_OUTPUT_COLUMNS, FINAL_OUTPUT_COLUMNS, ModelSpec, PERF_OUTPUT_COLUMNS,
        STAGE_OUTPUT_COLUMNS,
    )

    scale_params = {}
    for c in STAGE_OUTPUT_COLUMNS:
        if "thickness" in c:
            scale_params[c] = (50.0, 300.0)
        elif "density" in c:
            scale_params[c] = (2.0, 3.5)
        else:
            scale_params[c] = (2.0, 20.0)
    for c in FINAL_OUTPUT_COLUMNS:
        scale_params[c] = (50.0, 300.0) if "thickness" in c else ((2.0, 3.5) if "density" in c else (1.0, 20.0))
    for c in AUX_OUTPUT_COLUMNS:
        scale_params[c] = (0.0, 10.0)
    scale_params["initial_discharge_capacity_mah_g"] = (120.0, 215.0)
    scale_params["initial_coulombic_efficiency_pct"] = (80.0, 100.0)
    scale_params["interface_resistance_ohm"] = (1.0, 20.0)
    scale_params["cell_discharge_retention_pct"] = (50.0, 100.0)
    return ModelSpec(feature_columns=[f"f{i}" for i in range(5)], scale_params=scale_params, seed=1)


def test_output_constraint_layer_enforces_monotonicity():
    """무작위 가중치 모델도 두께 단조 감소·밀도 단조 증가를 만족해야 한다 (NFR-04)."""
    from dry_process_ai.core.model.builder import STAGE_OUTPUT_COLUMNS, build_model

    spec = _tiny_spec()
    model = build_model(spec)
    x = np.random.default_rng(0).random((16, 5)).astype(np.float32)
    pred = model.predict(x, verbose=0)

    stage = pred["stage"]  # (16, 24) scaled
    cols = list(STAGE_OUTPUT_COLUMNS)
    for row in stage:
        phys = {}
        for j, c in enumerate(cols):
            lo, hi = spec.scale_params[c]
            phys[c] = row[j] * (hi - lo) + lo
        thicknesses = [phys[f"{s}_composite_thickness_um"] for s in STAGES]
        densities = [phys[f"{s}_composite_density_gcc"] for s in STAGES]
        capacities = [phys[f"{s}_areal_capacity_mah_cm2"] for s in STAGES]
        assert all(a >= b - 1e-4 for a, b in zip(thicknesses, thicknesses[1:])), "두께 단조 감소 위반"
        assert all(a <= b + 1e-4 for a, b in zip(densities, densities[1:])), "밀도 단조 증가 위반"
        assert all(a >= b - 1e-4 for a, b in zip(capacities, capacities[1:])), "용량 단조 감소 위반"


def test_perf_outputs_within_physical_ranges():
    from dry_process_ai.core.model.builder import PERF_OUTPUT_COLUMNS, build_model

    spec = _tiny_spec()
    model = build_model(spec)
    x = np.random.default_rng(1).random((8, 5)).astype(np.float32)
    pred = model.predict(x, verbose=0)
    cols = list(PERF_OUTPUT_COLUMNS)
    for row in pred["perf"]:
        phys = {c: row[j] * (spec.scale_params[c][1] - spec.scale_params[c][0]) + spec.scale_params[c][0]
                for j, c in enumerate(cols)}
        assert 80.0 <= phys["initial_coulombic_efficiency_pct"] <= 100.0
        assert 0.0 <= phys["cell_discharge_retention_pct"] <= 100.0
        assert phys["interface_resistance_ohm"] > 0
        assert phys["initial_discharge_capacity_mah_g"] > 0


def test_performance_branch_depends_on_property_branch():
    """물성→성능 인과 연결 확인 — perf_concat 이 stage/final 출력을 입력으로 받는다."""
    from dry_process_ai.core.model.builder import build_model

    model = build_model(_tiny_spec())
    concat_layer = model.get_layer("perf_concat")
    input_names = [t.node.layer.name for t in concat_layer.input]
    assert "stage" in input_names and "final" in input_names
