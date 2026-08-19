"""AI 스펙 조정 제언 (advise_density_adjustment) 시험."""

import pandas as pd
import pytest

from dry_process_ai.core.optimize.backward import (
    BackwardResult,
    Candidate,
    ObjectiveSpec,
    advise_density_adjustment,
)


def _cand(density, sr, objectives_vals):
    return Candidate(
        binder_wt=2.0, conductive_wt=2.0, active_material_wt=96.0,
        target_density_gcc=density, features=pd.Series(dtype=float), gaps_um={},
        predictions={"sheet_resistance_ohm_sq": sr, "electrode_density_gcc": density},
        objectives=objectives_vals, weighted_score=sum(objectives_vals),
        alarm_grade="info", rationale="",
    )


# 목표: [시트 저항 min (주), 밀도 equal 3.2 (설계 사양)]
OBJS = [
    ObjectiveSpec("sheet_resistance_ohm_sq", "min", 3.0),
    ObjectiveSpec("electrode_density_gcc", "equal", 2.0, target=3.2),
]


def test_recommends_density_increase_when_it_helps():
    """고밀도 후보의 주 목표(저항)가 더 좋으면 「증가 추천」과 정량 득실을 제시."""
    cands = [
        _cand(3.20, 15000.0, [15000.0, 0.00]),  # 지정 밀도 근방
        _cand(3.30, 12000.0, [12000.0, 0.10]),  # 밀도↑ → 저항↓ (무제약 최적)
        _cand(3.10, 17000.0, [17000.0, 0.10]),
    ]
    result = BackwardResult(cands, cands, cands[:1])
    advice = advise_density_adjustment(result, OBJS, user_target_density=3.2)
    assert advice is not None
    assert advice.direction == "증가"
    assert advice.recommended == pytest.approx(3.30)
    assert advice.value_at_target == pytest.approx(15000.0)
    assert advice.value_at_recommended == pytest.approx(12000.0)
    assert "합제밀도 증가" in advice.message and "3.20 → 3.30" in advice.message
    assert "FV" in advice.message  # 밀도 상향은 타당성 검증 대상 경고 병기


def test_keeps_density_when_target_is_optimal():
    cands = [
        _cand(3.20, 12000.0, [12000.0, 0.00]),  # 지정 밀도가 최적
        _cand(3.35, 15000.0, [15000.0, 0.15]),
        _cand(3.05, 16000.0, [16000.0, 0.15]),
    ]
    result = BackwardResult(cands, cands, cands[:1])
    advice = advise_density_adjustment(result, OBJS, user_target_density=3.2)
    assert advice.direction == "유지"
    assert "조정 불필요" in advice.message


def test_recommends_decrease():
    cands = [
        _cand(3.20, 15000.0, [15000.0, 0.00]),
        _cand(3.05, 11000.0, [11000.0, 0.15]),  # 밀도↓ 가 유리한 가상 상황
    ]
    result = BackwardResult(cands, cands, cands[:1])
    advice = advise_density_adjustment(result, OBJS, user_target_density=3.2)
    assert advice.direction == "감소"
    assert "두께가 증가" in advice.message  # 하향 시 두께 증가 주의 병기


def test_no_advice_without_target_or_candidates():
    assert advise_density_adjustment(BackwardResult([], [], []), OBJS, 3.2) is None
    cands = [_cand(3.2, 1.0, [1.0, 0.0])]
    assert advise_density_adjustment(BackwardResult(cands, cands, cands), OBJS, None) is None
