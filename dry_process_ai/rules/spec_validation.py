"""FV — 목표 스펙 타당성 검증 (F3).

순방향(FF-01)과 역방향(FB-01) 양쪽에서 동일하게 호출된다.
요청을 거부하거나 입력값을 임의로 바꾸지 않는다 — 요청 조건의 공정 조건은
그대로 제시하되 알람과 대안을 병기한다 (기획서 3.4.5 동작 원칙).

판정 기준은 고정 상수가 아니라 실측 이력에서 도출한 ProcessCapability 로
전달된다. 실측 Lot 축적 시 판정선이 자동 갱신된다 (FV-04, 규칙 R6).

검증 6항목 (FV-01):
    density_history      밀도 달성 이력 — 유사 조성 실측 최대 밀도 초과
    density_composition  조성-밀도 양립성 — 도전재 증량 + 고밀도 동시 지정
    binder_floor         바인더 하한 — 목표 밀도 대비 바인더가 이력 하단
    reduction_limit      압하율 한계 — 필요 단계별 압하율이 이력 임계 초과
    springback_margin    스프링백 여유 — 요구 두께 < 최소 갭에서의 예상 두께
    training_range       학습 범위 — 목표 조합이 실험 데이터 분포 밖

알람 등급 (FV-02):
    정보(info)    전 항목 통과, 학습 범위 내 → 조건표만 출력
    주의(caution) 학습 범위 경계 또는 단일 항목 경미 위반 → 노란색 + 검증 실험 권장
    경고(warning) 밀도 달성 이력·스프링백 여유 위반 또는 복수 항목 위반
                  → 빨간색 + 대안 스펙 제안 패널 자동 전개
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dry_process_ai.config import (
    DEFAULT_MAX_REDUCTION_RATIO,
    DEFAULT_SPRINGBACK_RATIO,
    DENSITY_HEADROOM_GCC,
)
from dry_process_ai.rules import physics

INFO, CAUTION, WARNING = "info", "caution", "warning"

# 경고 등급으로 직행하는 항목 (FV-02 판정 규칙)
_CRITICAL_ITEMS = {"density_history", "springback_margin"}


@dataclass
class ProcessCapability:
    """실측 이력에서 동적으로 산출된 공정 능력 판정선 (FV-04 갱신 대상).

    모든 필드는 이력이 없으면 None 이며, 해당 검사는 판정 불가로 건너뛴다.
    data_access.capability 가 measured Lot 만으로 산출한다.
    """

    # 유사 조성(도전재·바인더 함량 근방)에서 실측된 최대/최소 합제밀도 (g/cc)
    max_density_gcc: float | None = None
    min_density_gcc: float | None = None
    # 실측 이력상 단계별 최대 압하율 (0~1)
    max_reduction_ratio: float = DEFAULT_MAX_REDUCTION_RATIO
    # 실측 이력상 스프링백 비율 (두께/갭 − 1)의 중앙값
    springback_ratio: float = DEFAULT_SPRINGBACK_RATIO
    # 설비 최소 롤 갭 (μm)
    min_gap_um: float | None = None
    # 실측 이력상 바인더 함량 분포 (wt%)
    binder_range_wt: tuple[float, float] | None = None
    # 학습 데이터 조성 분포 (wt%): {"active_material_content": (lo, hi), ...}
    composition_ranges: dict[str, tuple[float, float]] = field(default_factory=dict)
    # 학습 데이터 목표 스펙 분포: {"areal_capacity_mah_cm2": (lo, hi), ...}
    target_ranges: dict[str, tuple[float, float]] = field(default_factory=dict)
    # 기준(최빈) 조성의 도전재 함량 — 조성-밀도 양립성 판정 기준점
    reference_conductive_wt: float | None = None
    # 단계 프로파일 (FV-04 동적 산출): 실측 이력의 단계별 중앙값
    #   {stage: {"loading_ratio": 로딩_k/로딩_L2, "density_ratio": 밀도_k/밀도_L2,
    #            "springback": 두께_k/갭_k − 1 (이력 없으면 None)}}
    # 갭 스케줄 탐색(FF-03)이 실제 공정 경로에 앵커되도록 한다.
    stage_profile: dict[str, dict] = field(default_factory=dict)
    # 산출 근거 Lot 수 — 화면 표기용
    lot_count: int = 0


@dataclass
class ItemVerdict:
    item: str
    passed: bool
    severity: str  # "ok" | "minor" | "critical"
    basis: str      # 어느 이력 범위를 얼마나 벗어났는지


@dataclass
class SpecValidationResult:
    grade: str                      # info | caution | warning
    verdicts: list[ItemVerdict]
    messages: list[str]
    alternatives: list[dict] = field(default_factory=list)

    @property
    def violated(self) -> list[ItemVerdict]:
        return [v for v in self.verdicts if not v.passed]


def validate_spec(
    active_material_wt: float,
    binder_wt: float,
    conductive_wt: float,
    target_areal_capacity: float,
    target_density_gcc: float,
    capability: ProcessCapability,
    target_thickness_um: float | None = None,
) -> SpecValidationResult:
    """FV-01 검증 6항목 판정 + FV-02 알람 등급 판정."""
    am_frac = active_material_wt / 100.0
    required_loading = physics.required_loading_mg_cm2(target_areal_capacity, am_frac)
    final_thickness = target_thickness_um or physics.final_composite_thickness_um(
        required_loading, target_density_gcc
    )

    verdicts: list[ItemVerdict] = []

    # ① 밀도 달성 이력
    if capability.max_density_gcc is not None:
        ceiling = capability.max_density_gcc + DENSITY_HEADROOM_GCC
        ok = target_density_gcc <= capability.max_density_gcc
        minor = target_density_gcc <= ceiling
        verdicts.append(ItemVerdict(
            "density_history", ok, "ok" if ok else ("minor" if minor else "critical"),
            f"목표 {target_density_gcc:.2f} g/cc vs 유사 조성 실측 최대 {capability.max_density_gcc:.2f} g/cc"
            f" (여유폭 +{DENSITY_HEADROOM_GCC})",
        ))

    # ② 조성-밀도 양립성 — 도전재 증량 + 이력 상단 밀도 동시 지정
    if capability.reference_conductive_wt is not None and capability.max_density_gcc is not None:
        conductive_up = conductive_wt > capability.reference_conductive_wt
        density_high = target_density_gcc > capability.max_density_gcc * 0.97
        ok = not (conductive_up and density_high)
        verdicts.append(ItemVerdict(
            "density_composition", ok, "ok" if ok else "minor",
            f"도전재 {conductive_wt:.1f} wt% (기준 {capability.reference_conductive_wt:.1f}) 에서"
            f" 목표 밀도 {target_density_gcc:.2f} g/cc — 도전재는 저밀도·고탄성이라 치밀화가 더 어려움",
        ))

    # ③ 바인더 하한
    if capability.binder_range_wt is not None:
        b_lo, _ = capability.binder_range_wt
        ok = binder_wt >= b_lo
        verdicts.append(ItemVerdict(
            "binder_floor", ok, "ok" if ok else "minor",
            f"바인더 {binder_wt:.1f} wt% vs 실측 이력 하한 {b_lo:.1f} wt% (미만은 시트 균열·박리 위험)",
        ))

    # ④ 압하율 한계 — 초기 시트 두께에서 최종 두께까지 8단으로 도달 가능한지
    if capability.min_density_gcc is not None:
        initial_thickness = required_loading / max(capability.min_density_gcc, 1e-6) / 0.1
        n_stages = 8
        needed_ratio = 1.0 - (final_thickness / initial_thickness) ** (1.0 / n_stages) \
            if initial_thickness > final_thickness else 0.0
        ok = needed_ratio <= capability.max_reduction_ratio
        verdicts.append(ItemVerdict(
            "reduction_limit", ok, "ok" if ok else "minor",
            f"필요 평균 압하율 {needed_ratio:.1%} vs 이력 한계 {capability.max_reduction_ratio:.1%}"
            " (초과 시 시트 균열 위험 — 압연 단수 추가 필요)",
        ))

    # ⑤ 스프링백 여유 — 설비 최소 갭에서의 예상 두께보다 얇은 요구는 도달 불가
    if capability.min_gap_um is not None:
        min_achievable = capability.min_gap_um * (1.0 + capability.springback_ratio)
        ok = final_thickness >= min_achievable
        verdicts.append(ItemVerdict(
            "springback_margin", ok, "ok" if ok else "critical",
            f"요구 최종 두께 {final_thickness:.1f} μm vs 최소 갭 {capability.min_gap_um:.0f} μm"
            f" 에서의 예상 두께 {min_achievable:.1f} μm",
        ))

    # ⑥ 학습 범위
    out_of_range: list[str] = []
    comp = {
        "active_material_content": active_material_wt,
        "binder_content": binder_wt,
        "conductive_content": conductive_wt,
    }
    for name, value in comp.items():
        rng = capability.composition_ranges.get(name)
        if rng and not (rng[0] <= value <= rng[1]):
            out_of_range.append(f"{name}={value:.1f} ∉ [{rng[0]:.1f}, {rng[1]:.1f}]")
    for name, value in (
        ("areal_capacity_mah_cm2", target_areal_capacity),
        ("composite_density_gcc", target_density_gcc),
    ):
        rng = capability.target_ranges.get(name)
        if rng and not (rng[0] <= value <= rng[1]):
            out_of_range.append(f"{name}={value:.2f} ∉ [{rng[0]:.2f}, {rng[1]:.2f}]")
    if capability.composition_ranges or capability.target_ranges:
        ok = not out_of_range
        verdicts.append(ItemVerdict(
            "training_range", ok, "ok" if ok else "minor",
            "; ".join(out_of_range) if out_of_range else "학습 분포 내",
        ))

    return SpecValidationResult(
        grade=_grade(verdicts),
        verdicts=verdicts,
        messages=[v.basis for v in verdicts if not v.passed],
    )


def _grade(verdicts: list[ItemVerdict]) -> str:
    """FV-02 알람 등급 판정 규칙."""
    violated = [v for v in verdicts if not v.passed]
    if not violated:
        return INFO
    critical = any(v.item in _CRITICAL_ITEMS and v.severity == "critical" for v in violated)
    if critical or len(violated) >= 2:
        return WARNING
    return CAUTION


def propose_alternatives(
    result: SpecValidationResult,
    active_material_wt: float,
    binder_wt: float,
    conductive_wt: float,
    target_areal_capacity: float,
    target_density_gcc: float,
    capability: ProcessCapability,
    primary_goal: str = "areal_capacity",
) -> list[dict]:
    """FV-03 대안 스펙 제안 — 1차 목표를 고정한 채 나머지를 실현 가능 영역으로 이동.

    각 대안에는 예측 성능 변화량 병기가 원칙이므로, 서비스 계층이 모델 예측을
    붙일 수 있도록 스펙 변경 내용만 구조화하여 돌려준다.
    """
    alternatives: list[dict] = []
    am_frac = active_material_wt / 100.0
    violated_items = {v.item for v in result.violated}

    if "density_history" in violated_items and capability.max_density_gcc is not None:
        alt_density = capability.max_density_gcc
        loading = physics.required_loading_mg_cm2(target_areal_capacity, am_frac)
        alternatives.append({
            "kind": "relax_density",
            "description": (
                f"조성 고정, 합제밀도를 달성 이력 최대 {alt_density:.2f} g/cc 로 완화"
                f" (합제층 두께 {physics.final_composite_thickness_um(loading, alt_density):.1f} μm)"
            ),
            "spec": {
                "active_material_wt": active_material_wt,
                "binder_wt": binder_wt,
                "conductive_wt": conductive_wt,
                "target_areal_capacity": target_areal_capacity,
                "target_density_gcc": round(alt_density, 3),
            },
        })

    if ("density_composition" in violated_items or "density_history" in violated_items) \
            and capability.reference_conductive_wt is not None \
            and conductive_wt > capability.reference_conductive_wt:
        delta = min(conductive_wt - capability.reference_conductive_wt, 1.0)
        alternatives.append({
            "kind": "reduce_conductive",
            "description": (
                f"목표 밀도 고정, 도전재 {delta:.1f} wt% 감량·활물질 증량으로 치밀화 난이도 완화"
            ),
            "spec": {
                "active_material_wt": active_material_wt + delta,
                "binder_wt": binder_wt,
                "conductive_wt": conductive_wt - delta,
                "target_areal_capacity": target_areal_capacity,
                "target_density_gcc": target_density_gcc,
            },
        })

    if "springback_margin" in violated_items and capability.min_gap_um is not None:
        min_thickness = capability.min_gap_um * (1.0 + capability.springback_ratio)
        alt_density = physics.required_loading_mg_cm2(target_areal_capacity, am_frac) / min_thickness / 0.1
        if capability.max_density_gcc is None or alt_density <= capability.max_density_gcc + DENSITY_HEADROOM_GCC:
            alternatives.append({
                "kind": "relax_thickness",
                "description": (
                    f"면적당 용량 고정, 최종 두께를 설비 도달 가능 {min_thickness:.1f} μm 로 완화"
                    f" (필요 밀도 {alt_density:.2f} g/cc)"
                ),
                "spec": {
                    "active_material_wt": active_material_wt,
                    "binder_wt": binder_wt,
                    "conductive_wt": conductive_wt,
                    "target_areal_capacity": target_areal_capacity,
                    "target_density_gcc": round(alt_density, 3),
                },
            })

    result.alternatives = alternatives
    return alternatives
