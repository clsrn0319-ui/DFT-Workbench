"""도메인 물리 계산식 — 단일 정의 지점 (CLAUDE.md 3장).

모든 두께·밀도·로딩은 합제층(composite layer) 기준이다 (규칙 R1).
이 모듈 외부에서 아래 수식을 재구현하지 않는다. pytest 오차 0 검증 대상.

    로딩 L/L (mg/cm²)     = 합제층 두께(μm) × 합제밀도(g/cc) × 0.1
    면적당 용량 (mAh/cm²)  = 로딩 × 활물질 함량(wt 분율) × 비용량 ÷ 1000
    합제층 두께 (μm)       = 측정 전체 두께 − 집전체 두께      # Laminating 구간
    필요 로딩 (mg/cm²)     = 목표 면적당 용량 ÷ (활물질 함량 × 비용량) × 1000
    최종 합제층 두께 (μm)   = 필요 로딩 ÷ 목표 합제밀도 ÷ 0.1
    총 합제 질량 (g)       = 로딩 × 전극 면적(cm²) ÷ 1000     # 양면 도포는 × 도포 면수
    총 용량 (mAh)          = 면적당 용량 × 전극 면적(cm²)
"""

from __future__ import annotations

from dry_process_ai.config import NCM811_SPECIFIC_CAPACITY_MAH_G


def loading_mg_cm2(composite_thickness_um: float, composite_density_gcc: float) -> float:
    """로딩 L/L (mg/cm²) = 합제층 두께(μm) × 합제밀도(g/cc) × 0.1"""
    return composite_thickness_um * composite_density_gcc * 0.1


def areal_capacity_mah_cm2(
    loading: float,
    active_material_fraction: float,
    specific_capacity_mah_g: float = NCM811_SPECIFIC_CAPACITY_MAH_G,
) -> float:
    """면적당 용량 (mAh/cm²) = 로딩 × 활물질 함량(wt 분율) × 비용량 ÷ 1000

    active_material_fraction 은 0~1 분율 (96 wt% → 0.96).
    """
    return loading * active_material_fraction * specific_capacity_mah_g / 1000.0


def composite_thickness_from_total(total_thickness_um: float, foil_thickness_um: float) -> float:
    """합제층 두께 (μm) = 측정 전체 두께 − 집전체 두께.

    Laminating 구간의 측정값을 합제층 기준으로 환산할 때 사용한다.
    적재 시점(FD-05)에 호출되어야 하며, 예측 시점 차감은 금지 (규칙 R1).
    """
    return total_thickness_um - foil_thickness_um


def required_loading_mg_cm2(
    target_areal_capacity_mah_cm2: float,
    active_material_fraction: float,
    specific_capacity_mah_g: float = NCM811_SPECIFIC_CAPACITY_MAH_G,
) -> float:
    """필요 로딩 (mg/cm²) = 목표 면적당 용량 ÷ (활물질 함량 × 비용량) × 1000"""
    return target_areal_capacity_mah_cm2 / (active_material_fraction * specific_capacity_mah_g) * 1000.0


def final_composite_thickness_um(required_loading: float, target_density_gcc: float) -> float:
    """최종 합제층 두께 (μm) = 필요 로딩 ÷ 목표 합제밀도 ÷ 0.1"""
    return required_loading / target_density_gcc / 0.1


def composite_density_gcc(loading: float, composite_thickness_um: float) -> float:
    """합제밀도 (g/cc) = 로딩(mg/cm²) ÷ (합제층 두께(μm) × 0.1)"""
    return loading / (composite_thickness_um * 0.1)


def total_composite_mass_g(loading: float, electrode_area_cm2: float, coated_face_count: int = 1) -> float:
    """총 합제 질량 (g) = 로딩 × 전극 면적(cm²) ÷ 1000. 양면 도포는 × 도포 면수.

    전극 면적은 모델 입력이 아닌 Lot 속성이며 절대량 환산에만 쓰인다 (규칙 R4).
    """
    return loading * electrode_area_cm2 / 1000.0 * coated_face_count


def total_capacity_mah(areal_capacity: float, electrode_area_cm2: float, coated_face_count: int = 1) -> float:
    """총 용량 (mAh) = 면적당 용량 × 전극 면적(cm²). 양면 도포는 × 도포 면수."""
    return areal_capacity * electrode_area_cm2 * coated_face_count
