"""FF-02/03/09 — 목표 역산 및 갭 스케줄 탐색.

절차 (기획서 3.4.2):
    ① 조성비로부터 목표 로딩 산출 (물리식 — rules.physics 단일 정의 사용)
    ② 목표 두께·밀도를 만족하는 최종 Laminating 조건 역산 (합제층 기준)
    ③ 단계별 압하율 제약 하에서 M1~L2 갭 스케줄 탐색
    ④ (호출측) 각 단계 물성을 모델로 예측하여 스케줄 검증
    ⑤ Kneading 시간 등 피브릴화 조건을 조성에 맞춰 조정
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from dry_process_ai.config import STAGES
from dry_process_ai.rules import physics
from dry_process_ai.rules.spec_validation import ProcessCapability


class ScheduleInfeasible(ValueError):
    """압하율 제약을 만족하는 스케줄이 없음 — FV-01 압하율 한계 위반으로 처리."""


@dataclass
class GapSchedule:
    gaps_um: dict[str, float]
    planned_thickness_um: dict[str, float]
    planned_density_gcc: dict[str, float]
    planned_loading_mg_cm2: dict[str, float]
    required_loading_mg_cm2: float
    final_thickness_um: float
    springback_ratio: float
    notes: list[str] = field(default_factory=list)


def search_gap_schedule(
    active_material_fraction: float,
    target_areal_capacity: float,
    target_density_gcc: float,
    capability: ProcessCapability,
    target_thickness_um: float | None = None,
    initial_density_gcc: float | None = None,
    trimming_loss_ratio: float = 0.08,
    stages: tuple = STAGES,
) -> GapSchedule:
    """압하율 제약 하의 M1~L2 갭 스케줄 계획.

    initial_density_gcc: M1 시트 밀도. 미지정 시 실측 이력 최소 밀도(capability)
    를 사용한다 — 판정선 동적 산출 원칙 (FV-04).
    """
    required_loading = physics.required_loading_mg_cm2(target_areal_capacity, active_material_fraction)
    final_thickness = target_thickness_um or physics.final_composite_thickness_um(
        required_loading, target_density_gcc
    )

    # ---- 실측 단계 프로파일 앵커 경로 (우선) ----
    # 실제 공정은 M1 로딩이 최종의 수 배(트리밍·전개)이고 스프링백이 단계별로
    # 크게 다르다. 이력 프로파일이 있으면 그것으로 계획한다 (FV-04 동적 산출).
    profile = capability.stage_profile
    if profile and all(s in profile for s in stages):
        return _profile_schedule(
            required_loading, final_thickness, target_density_gcc, capability, stages,
        )

    d0 = initial_density_gcc or capability.min_density_gcc
    notes = ["단계 이력 프로파일 부재 — 기하 보간 계획으로 대체 (실측 축적 시 자동 전환)"]
    if d0 is None:
        d0 = target_density_gcc * 0.8
        notes.append("초기 시트 밀도 이력이 없어 목표 밀도의 80% 로 가정")
    d0 = min(d0, target_density_gcc)

    # 트리밍 손실을 반영한 초기 로딩 → 초기 두께
    loading0 = required_loading * (1.0 + trimming_loss_ratio)
    thickness0 = physics.final_composite_thickness_um(loading0, d0)
    n = len(stages)

    if final_thickness >= thickness0:
        raise ScheduleInfeasible(
            f"최종 두께 {final_thickness:.1f} μm ≥ 초기 시트 두께 {thickness0:.1f} μm — 압연 불필요 스펙"
        )

    # 단계당 균일 압하율 (기하 보간). 이력 한계 초과 시 실현 불가.
    per_stage_ratio = (final_thickness / thickness0) ** (1.0 / n)
    needed_reduction = 1.0 - per_stage_ratio
    if needed_reduction > capability.max_reduction_ratio:
        raise ScheduleInfeasible(
            f"필요 단계별 압하율 {needed_reduction:.1%} > 이력 한계 {capability.max_reduction_ratio:.1%}"
            " — 압연 단수 추가 필요"
        )

    loading_path = np.linspace(loading0, required_loading, n)
    gaps, t_plan, d_plan, l_plan = {}, {}, {}, {}
    for k, stage in enumerate(stages):
        tk = thickness0 * (per_stage_ratio ** (k + 1))
        if k == n - 1:
            tk = final_thickness
        lk = float(loading_path[k])
        dk = physics.composite_density_gcc(lk, tk)
        gap = tk / (1.0 + capability.springback_ratio)
        if capability.min_gap_um is not None and gap < capability.min_gap_um:
            raise ScheduleInfeasible(
                f"{stage} 필요 갭 {gap:.1f} μm < 설비 최소 갭 {capability.min_gap_um:.1f} μm (스프링백 여유 위반)"
            )
        gaps[stage] = round(gap, 1)
        t_plan[stage] = round(tk, 2)
        d_plan[stage] = round(dk, 4)
        l_plan[stage] = round(lk, 3)

    return GapSchedule(
        gaps_um=gaps,
        planned_thickness_um=t_plan,
        planned_density_gcc=d_plan,
        planned_loading_mg_cm2=l_plan,
        required_loading_mg_cm2=required_loading,
        final_thickness_um=final_thickness,
        springback_ratio=capability.springback_ratio,
        notes=notes,
    )


def _profile_schedule(
    required_loading: float,
    final_thickness: float,
    target_density_gcc: float,
    capability: ProcessCapability,
    stages: tuple,
) -> GapSchedule:
    """실측 단계 프로파일 기반 계획.

    로딩_k = 필요 로딩 × 이력 로딩 배율_k,
    밀도_k = 목표 밀도 × 이력 밀도 배율_k (단조 증가 보정),
    두께_k = 로딩 ÷ 밀도 ÷ 0.1 (질량 보존 종속),
    갭_k  = 두께_k ÷ (1 + 단계별 스프링백).
    """
    profile = capability.stage_profile
    gaps, t_plan, d_plan, l_plan = {}, {}, {}, {}
    prev_t, prev_d = float("inf"), -float("inf")
    for k, stage in enumerate(stages):
        p = profile[stage]
        if k == len(stages) - 1:
            lk, dk = required_loading, target_density_gcc
        else:
            lk = required_loading * p["loading_ratio"]
            dk = target_density_gcc * p["density_ratio"]
        dk = max(dk, prev_d)                       # 밀도 단조 증가
        tk = physics.final_composite_thickness_um(lk, dk)
        if tk > prev_t:                             # 두께 단조 감소
            tk = prev_t * 0.999
            dk = physics.composite_density_gcc(lk, tk)
        if k == len(stages) - 1:
            tk = final_thickness
            dk = physics.composite_density_gcc(lk, tk)
        prev_t, prev_d = tk, dk

        springback = p.get("springback")
        if springback is None:
            springback = capability.springback_ratio
        gap = tk / (1.0 + max(springback, 0.0))
        if capability.min_gap_um is not None and gap < capability.min_gap_um * (1.0 - 1e-9):
            raise ScheduleInfeasible(
                f"{stage} 필요 갭 {gap:.1f} μm < 설비 최소 갭 {capability.min_gap_um:.1f} μm (스프링백 여유 위반)"
            )
        gaps[stage] = round(gap, 1)
        t_plan[stage] = round(tk, 2)
        d_plan[stage] = round(dk, 4)
        l_plan[stage] = round(lk, 3)

    thicknesses = [t_plan[s] for s in stages]
    worst_reduction = max(
        (1.0 - b / a for a, b in zip(thicknesses, thicknesses[1:]) if a > 0), default=0.0,
    )
    if worst_reduction > capability.max_reduction_ratio * 1.5:
        raise ScheduleInfeasible(
            f"프로파일 계획의 최대 단계 압하율 {worst_reduction:.1%} 가 이력 한계"
            f" {capability.max_reduction_ratio:.1%} 를 크게 초과 — 압연 단수 추가 필요"
        )

    return GapSchedule(
        gaps_um=gaps,
        planned_thickness_um=t_plan,
        planned_density_gcc=d_plan,
        planned_loading_mg_cm2=l_plan,
        required_loading_mg_cm2=required_loading,
        final_thickness_um=final_thickness,
        springback_ratio=capability.springback_ratio,
        notes=[f"실측 단계 프로파일 앵커 계획 (근거 {capability.lot_count} Lot — FV-04 동적 산출)"],
    )


def recompute_gap_schedule(
    current_stage: str,
    measured_thickness_um: float,
    measured_loading_mg_cm2: float,
    target_areal_capacity: float,
    target_density_gcc: float,
    active_material_fraction: float,
    capability: ProcessCapability,
    stages: tuple = STAGES,
) -> GapSchedule:
    """FF-09 — 공정 중 갭 재계산.

    특정 단계 실측값이 예측 구간을 벗어났을 때, 그 시점 이후 단계의 갭 스케줄을
    재계산하여 목표 두께로 복귀하는 경로를 다시 제시한다.
    """
    if current_stage not in stages:
        raise ValueError(f"알 수 없는 단계: {current_stage}")
    idx = stages.index(current_stage)
    remaining = stages[idx + 1:]
    if not remaining:
        raise ScheduleInfeasible("마지막 단계 이후에는 재계산할 후속 단계가 없다")

    required_loading = physics.required_loading_mg_cm2(target_areal_capacity, active_material_fraction)
    final_thickness = physics.final_composite_thickness_um(required_loading, target_density_gcc)

    if final_thickness >= measured_thickness_um:
        raise ScheduleInfeasible(
            f"현재 두께 {measured_thickness_um:.1f} μm 가 이미 목표 {final_thickness:.1f} μm 이하 — 복귀 불가"
        )

    n = len(remaining)
    per_stage_ratio = (final_thickness / measured_thickness_um) ** (1.0 / n)
    needed_reduction = 1.0 - per_stage_ratio
    if needed_reduction > capability.max_reduction_ratio:
        raise ScheduleInfeasible(
            f"남은 {n}단으로 필요 압하율 {needed_reduction:.1%} > 한계 {capability.max_reduction_ratio:.1%}"
        )

    loading_path = np.linspace(measured_loading_mg_cm2, required_loading, n)
    gaps, t_plan, d_plan, l_plan = {}, {}, {}, {}
    for k, stage in enumerate(remaining):
        tk = measured_thickness_um * (per_stage_ratio ** (k + 1))
        if k == n - 1:
            tk = final_thickness
        lk = float(loading_path[k])
        gaps[stage] = round(tk / (1.0 + capability.springback_ratio), 1)
        t_plan[stage] = round(tk, 2)
        d_plan[stage] = round(physics.composite_density_gcc(lk, tk), 4)
        l_plan[stage] = round(lk, 3)

    return GapSchedule(
        gaps_um=gaps,
        planned_thickness_um=t_plan,
        planned_density_gcc=d_plan,
        planned_loading_mg_cm2=l_plan,
        required_loading_mg_cm2=required_loading,
        final_thickness_um=final_thickness,
        springback_ratio=capability.springback_ratio,
        notes=[f"{current_stage} 실측 이탈에 따른 후속 단계 재계산 (FF-09)"],
    )


def adjust_kneading_time(base_time_min: float, binder_wt: float, reference_binder_wt: float) -> float:
    """⑤ 피브릴화 보상 — 바인더 함량이 낮을수록 Kneading 시간을 연장한다.

    보정 계수는 실측 이력 기반 재학습 대상이며, 초기값은 바인더 1 wt% 감소당
    +15% 연장이라는 보수적 경험칙을 사용한다.
    """
    delta = reference_binder_wt - binder_wt
    factor = 1.0 + max(delta, 0.0) * 0.15
    return base_time_min * factor
