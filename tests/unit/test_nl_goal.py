"""자연어 목표 해석기 (nl_goal) 시험 — 기획서 3.7.2 시나리오 기준."""

import pytest

from dry_process_ai.services.nl_goal import parse_natural_goal


def test_planning_doc_scenario():
    """기획서 대표 시나리오: 「전기전도도가 개선된 전극. 면적당 용량 5 mAh/cm², 합제밀도 3.2 g/cc」."""
    g = parse_natural_goal("전기전도도가 개선된 전극. 면적당 용량 5 mAh/cm², 합제밀도 3.2 g/cc")
    cols = {o.column: o for o in g.objectives}
    # 주 목표: 시트 저항 최소화
    assert cols["sheet_resistance_ohm_sq"].direction == "min"
    assert cols["sheet_resistance_ohm_sq"].weight == 3.0
    # 설계 사양: 밀도 equal 3.2, 용량 5
    assert cols["electrode_density_gcc"].direction == "equal"
    assert cols["electrode_density_gcc"].target == 3.2
    assert g.target_areal_capacity_mah_cm2 == 5.0
    assert g.target_density_gcc == 3.2
    # 용량 손실 허용 한계 자동 추가
    assert cols["initial_discharge_capacity_mah_g"].direction == "max"
    assert not g.unrecognized
    assert g.interpretation  # 해석 근거 표시 필수


def test_longevity_goal():
    g = parse_natural_goal("장수명 전극을 만들고 싶어. 용량 4.5 이상")
    cols = {o.column for o in g.objectives}
    assert "cell_discharge_retention_pct" in cols
    assert g.target_areal_capacity_mah_cm2 == 4.5


def test_capacity_goal_no_auto_duplicate():
    g = parse_natural_goal("고용량 전극")
    caps = [o for o in g.objectives if o.column == "initial_discharge_capacity_mah_g"]
    assert len(caps) == 1  # 주 목표가 용량이면 하한 유지 자동 추가는 중복 금지
    assert caps[0].weight == 3.0


def test_strength_goal_flagged_for_fb07():
    g = parse_natural_goal("접착력이 좋은 전극")
    cols = {o.column for o in g.objectives}
    assert "electrode_adhesion_n_cm" in cols
    assert any("FB-07" in n for n in g.interpretation)


def test_unrecognized_input():
    g = parse_natural_goal("아무거나 잘 되는 전극")
    assert g.unrecognized
    assert not g.objectives


def test_density_only_number_korean():
    g = parse_natural_goal("전도도 개선, 밀도 3.1로")
    assert g.target_density_gcc == 3.1
    cols = {o.column: o for o in g.objectives}
    assert cols["electrode_density_gcc"].target == 3.1
