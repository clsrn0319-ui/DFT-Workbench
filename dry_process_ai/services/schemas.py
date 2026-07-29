"""FF-01 — 입력 스키마 및 도메인 제약 검증 (Pydantic).

조성 합계 100 wt%, 3항목(용량·밀도·두께) 과잉 지정 모순 검출을
스키마 수준에서 강제한다.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator

from dry_process_ai.config import COMPOSITION_TOTAL_WT, MASS_BALANCE_TOLERANCE
from dry_process_ai.rules import physics


class CompositionInput(BaseModel):
    """조성비 (wt%). 합계 100 자동 검증 — 심플렉스 2자유도."""

    active_material_content: float = Field(gt=0, lt=100, description="NCM811 wt%")
    binder_content: float = Field(gt=0, lt=100, description="PTFE wt%")
    conductive_content: float = Field(gt=0, lt=100, description="Super C wt%")

    @model_validator(mode="after")
    def _sum_100(self):
        total = self.active_material_content + self.binder_content + self.conductive_content
        if abs(total - COMPOSITION_TOTAL_WT) > 0.01:
            raise ValueError(f"조성 합계 {total:.2f} wt% ≠ {COMPOSITION_TOTAL_WT} wt%")
        return self

    @property
    def active_material_fraction(self) -> float:
        return self.active_material_content / 100.0


class CollectorInput(BaseModel):
    foil_thickness_um: float = Field(ge=0, default=15.0, description="Al foil 두께")
    coating_side: str = Field(default="single", pattern="^(single|double)$")

    @property
    def coated_face_count(self) -> int:
        return 2 if self.coating_side == "double" else 1


class OverdeterminedSpec(ValueError):
    """용량·밀도·두께 3값 동시 지정 모순 — 완화 대상 선택 필요 (FF-01)."""

    def __init__(self, message: str, options: list[str]):
        super().__init__(message)
        self.options = options


class ForwardRequest(BaseModel):
    """순방향 예측 요청 (F1). 목표값은 사용자 구성 가능 — 고정 사양 아님."""

    composition: CompositionInput
    target_areal_capacity_mah_cm2: Optional[float] = Field(default=None, gt=0)
    target_density_gcc: Optional[float] = Field(default=None, gt=0)
    target_thickness_um: Optional[float] = Field(default=None, gt=0)
    collector: CollectorInput = Field(default_factory=CollectorInput)
    electrode_area_cm2: Optional[float] = Field(default=None, gt=0, description="절대량 환산 전용 (규칙 R4)")
    fixed_process_conditions: dict[str, float] = Field(default_factory=dict, description="사용자 고정 조건 (FF-06)")
    mc_samples: int = Field(default=30, ge=5, le=200)

    @model_validator(mode="after")
    def _resolve_targets(self):
        """세 값 중 둘 지정 → 나머지 자동 결정. 셋 모두 지정 + 모순 → 즉시 알림."""
        cap, den, thk = self.target_areal_capacity_mah_cm2, self.target_density_gcc, self.target_thickness_um
        given = sum(v is not None for v in (cap, den, thk))
        if given < 2:
            raise ValueError("면적당 용량·합제밀도·합제층 두께 중 최소 둘을 지정해야 한다")
        am_frac = self.composition.active_material_fraction

        if given == 3:
            loading = physics.required_loading_mg_cm2(cap, am_frac)
            implied_thickness = physics.final_composite_thickness_um(loading, den)
            if abs(implied_thickness - thk) / thk > MASS_BALANCE_TOLERANCE:
                raise OverdeterminedSpec(
                    f"세 값이 모순: 용량 {cap}·밀도 {den} 이면 두께는 {implied_thickness:.1f} μm 이어야 하나 "
                    f"{thk:.1f} μm 지정됨. 완화할 값을 선택하라.",
                    options=["target_areal_capacity_mah_cm2", "target_density_gcc", "target_thickness_um"],
                )
            return self

        # 둘 지정 → 나머지 자동 결정 (FF-02 목표 역산)
        if cap is not None and den is not None:
            loading = physics.required_loading_mg_cm2(cap, am_frac)
            self.target_thickness_um = physics.final_composite_thickness_um(loading, den)
        elif cap is not None and thk is not None:
            loading = physics.required_loading_mg_cm2(cap, am_frac)
            self.target_density_gcc = physics.composite_density_gcc(loading, thk)
        else:  # den + thk
            loading = physics.loading_mg_cm2(thk, den)
            self.target_areal_capacity_mah_cm2 = physics.areal_capacity_mah_cm2(loading, am_frac)
        return self


class BackwardObjective(BaseModel):
    """FB-01 — 목표 변수별 목표값·가중치·방향."""

    column: str
    direction: str = Field(pattern="^(min|max|equal)$")
    weight: float = Field(default=1.0, gt=0)
    target: Optional[float] = None

    @model_validator(mode="after")
    def _equal_needs_target(self):
        if self.direction == "equal" and self.target is None:
            raise ValueError("direction=equal 인 목표에는 target 값이 필요하다")
        return self


class BackwardRequest(BaseModel):
    objectives: list[BackwardObjective] = Field(min_length=1)
    target_areal_capacity_mah_cm2: float = Field(gt=0)
    n_samples: int = Field(default=120, ge=10, le=2000)
    n_bo_calls: int = Field(default=0, ge=0, le=100)
    top_k: int = Field(default=5, ge=1, le=20)


class RecommendRequest(BaseModel):
    mode: str = Field(default="balanced", pattern="^(exploration|exploitation|balanced)$")
    k: int = Field(default=5, ge=1, le=50)
    targets: dict[str, float] = Field(default_factory=dict)
    mc_samples: int = Field(default=20, ge=5, le=100)
