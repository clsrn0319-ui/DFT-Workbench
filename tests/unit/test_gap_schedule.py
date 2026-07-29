"""FF-02/03/09 — 목표 역산·갭 스케줄 탐색·공정 중 재계산 시험."""

import pytest

from dry_process_ai.config import STAGES
from dry_process_ai.core.infer.gap_schedule import (
    ScheduleInfeasible,
    adjust_kneading_time,
    recompute_gap_schedule,
    search_gap_schedule,
)
from dry_process_ai.rules.spec_validation import ProcessCapability


def _capability():
    return ProcessCapability(
        max_density_gcc=3.3, min_density_gcc=2.3,
        max_reduction_ratio=0.5, springback_ratio=0.05, min_gap_um=15.0,
    )


def test_schedule_reaches_target():
    schedule = search_gap_schedule(0.96, 5.0, 3.2, _capability())
    assert set(schedule.gaps_um) == set(STAGES)
    # 최종 두께 = 필요 로딩 ÷ 목표 밀도 ÷ 0.1
    assert schedule.planned_thickness_um["L2"] == pytest.approx(schedule.final_thickness_um, abs=0.01)
    # 두께 단조 감소, 밀도 단조 증가
    thicknesses = [schedule.planned_thickness_um[s] for s in STAGES]
    densities = [schedule.planned_density_gcc[s] for s in STAGES]
    assert all(a >= b for a, b in zip(thicknesses, thicknesses[1:]))
    assert all(a <= b + 1e-9 for a, b in zip(densities, densities[1:]))
    # 스프링백: 계획 두께 > 갭
    for s in STAGES:
        assert schedule.planned_thickness_um[s] > schedule.gaps_um[s]


def test_infeasible_below_min_gap():
    cap = _capability()
    cap.min_gap_um = 200.0  # 설비 갭 하한을 크게 → 도달 불가
    with pytest.raises(ScheduleInfeasible):
        search_gap_schedule(0.96, 5.0, 3.2, cap)


def test_recompute_after_deviation():
    # M2 실측 이탈 → 후속 단계 재계산 (FF-09)
    schedule = recompute_gap_schedule(
        current_stage="M2", measured_thickness_um=200.0, measured_loading_mg_cm2=27.0,
        target_areal_capacity=5.0, target_density_gcc=3.2,
        active_material_fraction=0.96, capability=_capability(),
    )
    assert set(schedule.gaps_um) == set(STAGES[2:])  # M3 이후만
    assert schedule.planned_thickness_um["L2"] == pytest.approx(schedule.final_thickness_um, abs=0.01)


def test_kneading_compensation_for_low_binder():
    # 저바인더 → 피브릴화 보상으로 Kneading 시간 연장
    assert adjust_kneading_time(30.0, binder_wt=1.0, reference_binder_wt=2.0) > 30.0
    assert adjust_kneading_time(30.0, binder_wt=2.5, reference_binder_wt=2.0) == 30.0
