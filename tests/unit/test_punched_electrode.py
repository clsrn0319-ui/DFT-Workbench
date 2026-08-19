"""타발 전극(코인셀) 스펙 계산 시험 — 12φ · 집전체 16 μm / 4.4 mg 기준."""

import pytest

from dry_process_ai.rules import physics

# 사용자 제공 집전체 사양
FOIL_THICKNESS_UM = 16.0
FOIL_MASS_MG = 4.4
PUNCH_DIAMETER_MM = 12.0


def test_punch_area_12phi():
    # 12φ = 직경 12 mm → π × 0.6² ≈ 1.1310 cm² (사용자 제시 1.13 cm² 일치)
    area = physics.punch_area_cm2(PUNCH_DIAMETER_MM)
    assert area == pytest.approx(1.13097, abs=1e-4)


def test_punched_spec_from_measured_totals():
    """실측 총 무게·총 두께 → 집전체 차감 → 합제층 스펙 (오차 0 검증)."""
    area = physics.punch_area_cm2(PUNCH_DIAMETER_MM)
    # 예: 실험 1 L2 스펙(로딩 24.93 mg/cm², 두께 77 μm)의 타발 전극이라면
    total_mass = 24.93 * area + FOIL_MASS_MG
    total_thickness = 77.0 + FOIL_THICKNESS_UM

    spec = physics.punched_electrode_spec(
        total_mass_mg=total_mass, total_thickness_um=total_thickness,
        active_material_fraction=0.96,
        foil_mass_mg=FOIL_MASS_MG, foil_thickness_um=FOIL_THICKNESS_UM, area_cm2=area,
    )
    assert spec["composite_mass_mg"] == pytest.approx(24.93 * area)
    assert spec["composite_thickness_um"] == pytest.approx(77.0)
    assert spec["loading_mg_cm2"] == pytest.approx(24.93)
    assert spec["composite_density_gcc"] == pytest.approx(24.93 / 7.7)
    assert spec["areal_capacity_mah_cm2"] == pytest.approx(24.93 * 0.96 * 210 / 1000)
    assert spec["total_capacity_mah"] == pytest.approx(spec["areal_capacity_mah_cm2"] * area)


def test_roundtrip_with_expected():
    """기대값(역산) → 실측 입력 재계산 왕복 일치."""
    area = physics.punch_area_cm2(PUNCH_DIAMETER_MM)
    expected = physics.expected_punched_electrode(
        loading_mg_cm2_value=24.8, composite_density_gcc_value=3.2,
        active_material_fraction=0.96,
        foil_mass_mg=FOIL_MASS_MG, foil_thickness_um=FOIL_THICKNESS_UM, area_cm2=area,
    )
    spec = physics.punched_electrode_spec(
        total_mass_mg=expected["total_mass_mg"],
        total_thickness_um=expected["total_thickness_um"],
        active_material_fraction=0.96,
        foil_mass_mg=FOIL_MASS_MG, foil_thickness_um=FOIL_THICKNESS_UM, area_cm2=area,
    )
    assert spec["loading_mg_cm2"] == pytest.approx(24.8)
    assert spec["composite_density_gcc"] == pytest.approx(3.2)
    assert spec["composite_thickness_um"] == pytest.approx(77.5)


def test_invalid_when_foil_exceeds_total():
    area = physics.punch_area_cm2(PUNCH_DIAMETER_MM)
    with pytest.raises(ValueError):
        physics.punched_electrode_spec(
            total_mass_mg=4.0, total_thickness_um=90.0,  # 총 질량 < 집전체 질량
            active_material_fraction=0.96,
            foil_mass_mg=FOIL_MASS_MG, foil_thickness_um=FOIL_THICKNESS_UM, area_cm2=area,
        )
