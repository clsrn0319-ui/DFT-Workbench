"""FV-01~03 — 스펙 타당성 검증·알람 등급·대안 제안 시험."""

from dry_process_ai.rules.spec_validation import (
    ProcessCapability,
    propose_alternatives,
    validate_spec,
)


def _capability():
    return ProcessCapability(
        max_density_gcc=3.2, min_density_gcc=2.3,
        max_reduction_ratio=0.5, springback_ratio=0.05, min_gap_um=20.0,
        binder_range_wt=(1.0, 3.5), reference_conductive_wt=2.0,
        composition_ranges={
            "active_material_content": (93.0, 98.0),
            "binder_content": (1.0, 3.5),
            "conductive_content": (1.0, 3.5),
        },
        target_ranges={"areal_capacity_mah_cm2": (3.0, 6.5),
                       "composite_density_gcc": (2.3, 3.2)},
        lot_count=40,
    )


def test_feasible_spec_info_grade():
    # 입력 A 시나리오: 이력 내 스펙 → 전 항목 통과, 알람 없음
    result = validate_spec(96.0, 2.0, 2.0, 5.0, 3.0, _capability())
    assert result.grade == "info"
    assert not result.violated


def test_density_beyond_history_warns():
    # 이력 최대 3.2 + 여유폭 초과 → 경고 직행
    result = validate_spec(96.0, 2.0, 2.0, 5.0, 3.5, _capability())
    assert result.grade == "warning"
    assert any(v.item == "density_history" for v in result.violated)


def test_conductive_up_with_high_density_caution():
    # 입력 B 시나리오: 도전재 증량 + 이력 상단 밀도 → 조성-밀도 양립성 저촉
    result = validate_spec(94.8, 2.0, 3.2, 5.0, 3.15, _capability())
    assert result.grade in ("caution", "warning")
    assert any(v.item == "density_composition" for v in result.violated)


def test_low_binder_flagged():
    cap = _capability()
    result = validate_spec(97.5, 0.8, 1.7, 5.0, 3.0, cap)
    assert any(v.item == "binder_floor" for v in result.violated)


def test_alternatives_keep_primary_goal():
    cap = _capability()
    result = validate_spec(96.0, 2.0, 2.0, 5.0, 3.5, cap)
    alts = propose_alternatives(result, 96.0, 2.0, 2.0, 5.0, 3.5, cap)
    assert alts
    for alt in alts:
        # 1차 목표(면적당 용량)는 고정된 채 나머지 스펙만 이동
        assert alt["spec"]["target_areal_capacity"] == 5.0
    assert any(alt["kind"] == "relax_density" and alt["spec"]["target_density_gcc"] == 3.2
               for alt in alts)


def test_no_history_skips_checks():
    # 이력이 전무하면 판정 불가 항목은 건너뛴다 (동적 판정선 원칙)
    result = validate_spec(96.0, 2.0, 2.0, 5.0, 3.2, ProcessCapability())
    assert result.grade == "info"
