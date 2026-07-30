"""FF-02/03/09 — 목표 역산·갭 스케줄 탐색·공정 중 재계산 시험."""

import pytest

from dry_process_ai.config import ACTIVE_STAGES, STAGES
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
    # 운용 단계만 계획 대상 — Rolling 1회 운용 (R2 제외)
    assert set(schedule.gaps_um) == set(ACTIVE_STAGES)
    # 최종 두께 = 필요 로딩 ÷ 목표 밀도 ÷ 0.1
    assert schedule.planned_thickness_um["L2"] == pytest.approx(schedule.final_thickness_um, abs=0.01)
    # 두께 단조 감소, 밀도 단조 증가
    thicknesses = [schedule.planned_thickness_um[s] for s in ACTIVE_STAGES]
    densities = [schedule.planned_density_gcc[s] for s in ACTIVE_STAGES]
    assert all(a >= b for a, b in zip(thicknesses, thicknesses[1:]))
    assert all(a <= b + 1e-9 for a, b in zip(densities, densities[1:]))
    # 스프링백: 계획 두께 > 갭
    for s in ACTIVE_STAGES:
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
    assert set(schedule.gaps_um) == set(ACTIVE_STAGES[2:])  # M3 이후 운용 단계만
    assert schedule.planned_thickness_um["L2"] == pytest.approx(schedule.final_thickness_um, abs=0.01)


def test_profile_anchored_schedule():
    """실측 단계 프로파일이 있으면 갭 계획이 실제 공정 경로에 앵커된다.

    회귀 배경: 초기 로딩을 최종의 1.08배로 가정한 기하 계획이 실측 갭
    (M1 180 μm 급)과 전혀 다른 88 μm 급 갭을 낸 결함 수정.
    """
    cap = _capability()
    # 실측 이력 형태의 프로파일: M1 로딩 ~2.75×, 단계별 상이한 스프링백
    cap.stage_profile = {
        "M1": {"loading_ratio": 2.75, "density_ratio": 0.851, "springback": 0.51},
        "M2": {"loading_ratio": 1.66, "density_ratio": 0.835, "springback": 0.21},
        "M3": {"loading_ratio": 1.14, "density_ratio": 0.836, "springback": 0.12},
        "M4": {"loading_ratio": 1.11, "density_ratio": 0.867, "springback": 0.11},
        "R1": {"loading_ratio": 1.03, "density_ratio": 0.891, "springback": 0.13},
        "R2": {"loading_ratio": 1.03, "density_ratio": 0.889, "springback": 0.12},
        "L1": {"loading_ratio": 1.01, "density_ratio": 0.926, "springback": 0.05},
        "L2": {"loading_ratio": 1.00, "density_ratio": 1.000, "springback": 0.25},
    }
    schedule = search_gap_schedule(0.96, 5.0, 3.2, cap)
    assert "프로파일" in schedule.notes[0]
    # 초기 갭이 실측 레짐(150 μm 이상)이어야 한다 — 기하 계획의 88 μm 급이 아님
    assert schedule.gaps_um["M1"] > 150.0
    # 단계별 스프링백 반영: 갭 = 두께 / (1 + sb_k)
    assert schedule.gaps_um["M1"] == pytest.approx(
        schedule.planned_thickness_um["M1"] / 1.51, abs=0.5)
    # 최종 단계는 목표 두께·로딩을 정확히 달성
    assert schedule.planned_thickness_um["L2"] == pytest.approx(schedule.final_thickness_um, abs=0.01)
    assert schedule.planned_loading_mg_cm2["L2"] == pytest.approx(schedule.required_loading_mg_cm2, abs=0.01)
    # 단조성 유지 (운용 단계열)
    thicknesses = [schedule.planned_thickness_um[s] for s in ACTIVE_STAGES]
    densities = [schedule.planned_density_gcc[s] for s in ACTIVE_STAGES]
    assert all(a >= b for a, b in zip(thicknesses, thicknesses[1:]))
    assert all(a <= b + 1e-9 for a, b in zip(densities, densities[1:]))


def test_fallback_without_profile_noted():
    schedule = search_gap_schedule(0.96, 5.0, 3.2, _capability())
    assert any("기하 보간" in n for n in schedule.notes)


def test_kneading_compensation_for_low_binder():
    # 저바인더 → 피브릴화 보상으로 Kneading 시간 연장
    assert adjust_kneading_time(30.0, binder_wt=1.0, reference_binder_wt=2.0) > 30.0
    assert adjust_kneading_time(30.0, binder_wt=2.5, reference_binder_wt=2.0) == 30.0
