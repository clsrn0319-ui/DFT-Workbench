"""물리 계산식 단위 시험 — 기준값 대비 오차 0 (시험 전략 16장).

기준값은 기획서 3.4.4 의 예시 계산을 사용한다:
    조성 96:2:2, 목표 5 mAh/cm², 3.2 g/cc
    → 필요 로딩 = 5 ÷ (0.96 × 210) × 1000 ≈ 24.8 mg/cm²
    → 최종 합제층 두께 = 24.8 ÷ 3.2 ÷ 0.1 ≈ 77.5 μm
"""

import pytest

from dry_process_ai.config import NCM811_SPECIFIC_CAPACITY_MAH_G
from dry_process_ai.rules import physics


def test_specific_capacity_constant():
    assert NCM811_SPECIFIC_CAPACITY_MAH_G == 210.0


def test_loading_formula():
    # 로딩 = 두께 × 밀도 × 0.1 — 오차 0
    assert physics.loading_mg_cm2(77.5, 3.2) == 77.5 * 3.2 * 0.1
    assert physics.loading_mg_cm2(100.0, 3.0) == 30.0


def test_areal_capacity_formula():
    loading = 24.8
    expected = 24.8 * 0.96 * 210.0 / 1000.0
    assert physics.areal_capacity_mah_cm2(loading, 0.96) == expected


def test_required_loading_planning_example():
    # 기획서 예시: 5 ÷ (0.96 × 210) × 1000 = 24.801587...
    loading = physics.required_loading_mg_cm2(5.0, 0.96)
    assert loading == 5.0 / (0.96 * 210.0) * 1000.0
    assert loading == pytest.approx(24.8, abs=0.01)


def test_final_thickness_planning_example():
    loading = physics.required_loading_mg_cm2(5.0, 0.96)
    thickness = physics.final_composite_thickness_um(loading, 3.2)
    assert thickness == loading / 3.2 / 0.1
    assert thickness == pytest.approx(77.5, abs=0.01)


def test_composite_thickness_from_total():
    # Laminating: 측정 전체 두께 − 집전체 두께 (규칙 R1)
    assert physics.composite_thickness_from_total(92.5, 15.0) == 77.5


def test_density_from_loading_and_thickness():
    assert physics.composite_density_gcc(24.8, 77.5) == 24.8 / 7.75


def test_roundtrip_consistency():
    """질량 보존 왕복: 두께·밀도 → 로딩 → 밀도 복원 오차 0."""
    t, d = 88.0, 2.9
    loading = physics.loading_mg_cm2(t, d)
    assert physics.composite_density_gcc(loading, t) == pytest.approx(d, rel=1e-12)


def test_absolute_quantities():
    # 총 합제 질량 = 로딩 × 면적 ÷ 1000, 총 용량 = 면적당 용량 × 면적
    assert physics.total_composite_mass_g(24.8, 25.0) == 24.8 * 25.0 / 1000.0
    assert physics.total_capacity_mah(5.0, 25.0) == 125.0
    # 양면 도포 × 도포 면수
    assert physics.total_composite_mass_g(24.8, 25.0, coated_face_count=2) == 2 * 24.8 * 25.0 / 1000.0
    assert physics.total_capacity_mah(5.0, 25.0, coated_face_count=2) == 250.0
