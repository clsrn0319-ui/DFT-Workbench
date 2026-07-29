"""정합성 제약 검사기 (rules.constraints) 단위 시험."""

from dry_process_ai.rules import constraints, physics


def _stage(t, d, am_frac=0.96):
    loading = physics.loading_mg_cm2(t, d)
    return {
        "composite_thickness_um": t,
        "composite_density_gcc": d,
        "areal_capacity_mah_cm2": physics.areal_capacity_mah_cm2(loading, am_frac),
        "loading_mg_cm2": loading,
    }


def test_consistent_sequence_passes():
    values = {
        "M1": _stage(289, 2.60), "M2": _stage(182, 2.65), "M3": _stage(120, 2.71),
        "M4": _stage(101, 2.81), "R1": _stage(90, 2.88), "R2": _stage(88, 2.90),
        "L1": _stage(84, 3.00), "L2": _stage(77.5, 3.20),
    }
    report = constraints.check_stage_sequence(values, active_material_fraction=0.96)
    assert report.passed, [v.message for v in report.violations]


def test_thickness_monotonicity_violation():
    values = {"M1": _stage(100, 2.6), "M2": _stage(120, 2.7)}  # 두께 증가 → 위반
    report = constraints.check_stage_sequence(values)
    assert not report.passed
    assert any(v.rule == "monotonic_thickness" for v in report.violations)


def test_density_monotonicity_violation():
    values = {"M1": _stage(100, 3.0), "M2": _stage(90, 2.5)}  # 밀도 감소 → 위반
    report = constraints.check_stage_sequence(values)
    assert any(v.rule == "monotonic_density" for v in report.violations)


def test_springback_violation():
    values = {"M1": _stage(100, 2.6)}
    report = constraints.check_stage_sequence(values, gaps_um={"M1": 100.0})  # 두께 ≤ 갭
    assert any(v.rule == "springback" for v in report.violations)


def test_density_ceiling_dynamic():
    # 상한은 실측 최대 + 여유폭에서 동적 산출 — 고정 상수 아님
    ceiling = constraints.density_ceiling_from_history(3.2)
    assert ceiling > 3.2
    assert constraints.density_ceiling_from_history(None) is None

    values = {"M1": _stage(100, ceiling + 0.1)}
    report = constraints.check_stage_sequence(values, density_ceiling_gcc=ceiling)
    assert any(v.rule == "density_ceiling" for v in report.violations)


def test_mass_balance_check():
    assert constraints.check_mass_balance(24.8, 77.5, 3.2)
    assert not constraints.check_mass_balance(30.0, 77.5, 3.2)  # 3% 초과 불일치


def test_performance_ranges():
    ok = constraints.check_performance_ranges({
        "initial_coulombic_efficiency": 92.0, "cell_discharge_retention": 95.0,
        "sheet_resistance": 5.0, "interface_resistance": 8.0,
    })
    assert ok.passed
    bad = constraints.check_performance_ranges({
        "initial_coulombic_efficiency": 120.0,  # > 100 %
        "sheet_resistance": -1.0,               # 음수 저항
    })
    assert not bad.passed
    assert len(bad.violations) == 2
