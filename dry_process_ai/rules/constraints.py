"""정합성 제약 검사기 — 모든 단계 출력에 적용 (CLAUDE.md 3장).

FF-08 독립 정합성 검사기와 FT-04 의사 라벨 물리 필터가 공유하는 규칙 집합.
출력 제약층(FT-07)과 이중 방어를 구성한다 (규칙 R5, NFR-04).

검사 항목:
    - 질량 보존: 로딩 ≈ 두께 × 밀도 × 0.1 (허용 오차 3%)
    - 용량-로딩 연동: 면적당 용량 = 로딩 × 활물질 함량 × 비용량 ÷ 1000
    - 단계 간 단조성: 두께 단조 감소 / 합제밀도 단조 증가
    - 두께 하한: 각 단계 두께 > 해당 단계 롤 갭 (스프링백)
    - 밀도 상한: 해당 조성 실측 최대 밀도 + 여유폭 (동적 산출 — 고정 상수 금지)
    - 성능 물리 범위: ICE 80~100 %, 유지율 0~100 %, 저항 > 0
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from dry_process_ai.config import (
    DENSITY_HEADROOM_GCC,
    MASS_BALANCE_TOLERANCE,
    STAGES,
)
from dry_process_ai.rules import physics


@dataclass
class Violation:
    """단일 제약 위반 항목."""

    rule: str
    stage: str | None
    message: str
    severity: str = "error"  # "error" | "warning"


@dataclass
class ConsistencyReport:
    """정합성 검사 결과. violations 가 비어 있으면 전 항목 통과."""

    violations: list[Violation] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(v.severity == "error" for v in self.violations)

    def add(self, rule: str, stage: str | None, message: str, severity: str = "error") -> None:
        self.violations.append(Violation(rule=rule, stage=stage, message=message, severity=severity))


def check_mass_balance(
    loading: float,
    thickness_um: float,
    density_gcc: float,
    tolerance: float = MASS_BALANCE_TOLERANCE,
) -> bool:
    """질량 보존: |로딩 − 두께×밀도×0.1| / 로딩 ≤ tolerance."""
    if loading <= 0 or thickness_um <= 0 or density_gcc <= 0:
        return False
    expected = physics.loading_mg_cm2(thickness_um, density_gcc)
    return abs(loading - expected) / loading <= tolerance


def check_capacity_loading(
    areal_capacity: float,
    loading: float,
    active_material_fraction: float,
    tolerance: float = MASS_BALANCE_TOLERANCE,
) -> bool:
    """용량-로딩 연동: 조성 확정 시 면적당 용량은 로딩에 비례."""
    if areal_capacity <= 0 or loading <= 0:
        return False
    expected = physics.areal_capacity_mah_cm2(loading, active_material_fraction)
    return abs(areal_capacity - expected) / expected <= tolerance


def check_stage_sequence(
    stage_values: dict[str, dict[str, float]],
    gaps_um: dict[str, float] | None = None,
    density_ceiling_gcc: float | None = None,
    active_material_fraction: float | None = None,
    tolerance: float = MASS_BALANCE_TOLERANCE,
) -> ConsistencyReport:
    """단계열(M1~L2) 예측/계측값 전체에 대한 정합성 검사.

    Parameters
    ----------
    stage_values:
        {stage_index: {"composite_thickness_um": t, "composite_density_gcc": d,
                       "areal_capacity_mah_cm2": q, ["loading_mg_cm2": l]}}
        일부 단계가 빠져 있어도 존재하는 단계 순서대로 검사한다.
    gaps_um:
        단계별 롤 갭. 주어지면 두께 > 갭 (스프링백) 검사.
    density_ceiling_gcc:
        해당 조성의 실측 최대 밀도 + 여유폭. history 기반 동적 산출값을 전달한다.
    active_material_fraction:
        주어지면 용량-로딩 연동 검사 수행.
    """
    report = ConsistencyReport()
    ordered = [s for s in STAGES if s in stage_values]

    prev_thickness = math.inf
    prev_density = -math.inf
    prev_capacity = math.inf
    for stage in ordered:
        row = stage_values[stage]
        t = row.get("composite_thickness_um", float("nan"))
        d = row.get("composite_density_gcc", float("nan"))
        q = row.get("areal_capacity_mah_cm2", float("nan"))
        loading = row.get("loading_mg_cm2", physics.loading_mg_cm2(t, d))

        if not (t > 0 and d > 0 and q > 0):
            report.add("positive", stage, f"{stage}: 두께/밀도/용량은 양수여야 함 (t={t}, d={d}, q={q})")
            continue

        if not check_mass_balance(loading, t, d, tolerance=tolerance):
            report.add("mass_balance", stage, f"{stage}: 질량 보존 위반 (로딩 {loading:.2f} ≠ {t:.1f}×{d:.2f}×0.1)")

        if active_material_fraction is not None and not check_capacity_loading(
                q, loading, active_material_fraction, tolerance=tolerance):
            report.add("capacity_loading", stage, f"{stage}: 용량-로딩 연동 위반 (용량 {q:.2f})")

        # 동률 허용 오차는 모델 출력(float32) 정밀도(상대 ~1e-7)를 상회해야 한다
        if t > prev_thickness * (1.0 + 1e-6):
            report.add("monotonic_thickness", stage, f"{stage}: 두께 단조 감소 위반 ({prev_thickness:.1f} → {t:.1f} μm)")
        if d < prev_density * (1.0 - 1e-6):
            report.add("monotonic_density", stage, f"{stage}: 합제밀도 단조 증가 위반 ({prev_density:.2f} → {d:.2f} g/cc)")
        if q > prev_capacity * (1.0 + 1e-6):
            report.add("monotonic_capacity", stage, f"{stage}: 면적당 용량 단조 감소 위반", severity="warning")

        if gaps_um is not None and stage in gaps_um and gaps_um[stage] is not None:
            if t <= gaps_um[stage]:
                report.add("springback", stage, f"{stage}: 두께 {t:.1f} μm ≤ 롤 갭 {gaps_um[stage]:.1f} μm (스프링백 위반)")

        if density_ceiling_gcc is not None and d > density_ceiling_gcc:
            report.add("density_ceiling", stage, f"{stage}: 밀도 {d:.2f} > 이력 상한 {density_ceiling_gcc:.2f} g/cc")

        prev_thickness, prev_density, prev_capacity = t, d, q

    return report


def check_performance_ranges(values: dict[str, float]) -> ConsistencyReport:
    """C등급 성능 변수의 물리 범위 검사 (FT-04 ④, 출력 범위 제약표 기준)."""
    report = ConsistencyReport()
    rules: dict[str, tuple[float, float]] = {
        "initial_coulombic_efficiency": (80.0, 100.0),
        "cell_discharge_retention": (0.0, 100.0),
    }
    for name, (lo, hi) in rules.items():
        v = values.get(name)
        if v is not None and not (lo <= v <= hi):
            report.add("range", None, f"{name}={v:.2f} 는 물리 범위 [{lo}, {hi}] 밖")
    for name in ("sheet_resistance", "interface_resistance", "initial_discharge_capacity"):
        v = values.get(name)
        if v is not None and v <= 0:
            report.add("positive", None, f"{name}={v:.4g} 는 양수여야 함")
    return report


def density_ceiling_from_history(max_measured_density_gcc: float | None,
                                 headroom_gcc: float = DENSITY_HEADROOM_GCC) -> float | None:
    """조성별 실측 최대 밀도 + 여유폭. 이력이 없으면 None (상한 미적용).

    고정 상수 하드코딩 금지 — 호출측이 실측 이력에서 최대값을 조회해 전달한다 (FV-04).
    """
    if max_measured_density_gcc is None:
        return None
    return max_measured_density_gcc + headroom_gcc
