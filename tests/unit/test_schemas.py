"""FF-01 — 입력 스키마 검증 시험 (조성 합계, 목표 자동 결정, 과잉 지정 모순)."""

import pytest

from dry_process_ai.rules import physics
from dry_process_ai.services.schemas import (
    CompositionInput,
    ForwardRequest,
    OverdeterminedSpec,
)


def _comp():
    return CompositionInput(active_material_content=96, binder_content=2, conductive_content=2)


def test_composition_sum_enforced():
    with pytest.raises(ValueError):
        CompositionInput(active_material_content=96, binder_content=2, conductive_content=3)


def test_two_targets_resolve_third():
    req = ForwardRequest(composition=_comp(), target_areal_capacity_mah_cm2=5.0, target_density_gcc=3.2)
    # 두께 자동 결정: 24.8 / 3.2 / 0.1 ≈ 77.5 μm
    assert req.target_thickness_um == pytest.approx(77.5, abs=0.01)


def test_density_thickness_resolve_capacity():
    req = ForwardRequest(composition=_comp(), target_density_gcc=3.2, target_thickness_um=77.5)
    loading = physics.loading_mg_cm2(77.5, 3.2)
    assert req.target_areal_capacity_mah_cm2 == pytest.approx(
        physics.areal_capacity_mah_cm2(loading, 0.96))


def test_single_target_rejected():
    with pytest.raises(ValueError):
        ForwardRequest(composition=_comp(), target_areal_capacity_mah_cm2=5.0)


def test_overdetermined_contradiction_raises_with_options():
    # 셋 모두 지정 + 모순 → 즉시 알림, 완화 대상 선택지 제공
    with pytest.raises((OverdeterminedSpec, ValueError)) as exc_info:
        ForwardRequest(
            composition=_comp(), target_areal_capacity_mah_cm2=5.0,
            target_density_gcc=3.2, target_thickness_um=120.0,
        )
    assert "모순" in str(exc_info.value)


def test_consistent_three_targets_ok():
    req = ForwardRequest(
        composition=_comp(), target_areal_capacity_mah_cm2=5.0,
        target_density_gcc=3.2, target_thickness_um=77.5,
    )
    assert req.target_thickness_um == 77.5
