"""FB-01 확장 — 자연어 목표 해석기 (역방향 설계 진입점).

「전기전도도가 개선된 전극. 면적당 용량 5 mAh/cm², 합제밀도 3.2 g/cc」류의
한국어 목표 문장을 목표 변수·방향·가중치 집합으로 변환한다 (기획서 3.7.2
역방향 동작 시나리오의 입력 형식).

오프라인 원칙(규칙 R7)에 따라 외부 LLM 없이 결정적 키워드·수치 규칙으로
해석하며, 해석 결과를 사용자에게 그대로 표시해 확인 후 탐색하게 한다 —
해석기가 임의로 값을 바꾸지 않는다 (FV 동작 원칙과 동일).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from dry_process_ai.services.schemas import BackwardObjective

# 의도 키워드 → 목표 정의. 먼저 매칭된 의도가 주 목표(가중 3.0)가 된다.
# (키워드 목록, 컬럼, 방향, 설명)
_INTENTS: list[tuple[list[str], str, str, str]] = [
    (["전기전도도", "전도도", "도전성", "시트 저항", "시트저항", "저저항"],
     "sheet_resistance_ohm_sq", "min", "전기전도도 향상 → 시트 저항 최소화"),
    (["계면 저항", "계면저항"],
     "interface_resistance_ohm", "min", "계면 저항 최소화"),
    (["고용량", "용량 극대", "용량 최대", "용량 향상", "용량 개선", "방전 용량"],
     "initial_discharge_capacity_mah_g", "max", "초기 방전 용량 극대화"),
    (["수명", "장수명", "유지율", "사이클", "싸이클", "retention"],
     "cell_discharge_retention_pct", "max", "용량 유지율(수명) 극대화"),
    (["쿨롱 효율", "초기 효율", "ice", "ICE"],
     "initial_coulombic_efficiency_pct", "max", "초기 쿨롱 효율 극대화"),
    (["강도", "인장"],
     "tensile_strength_mpa", "max", "인장강도 확보 (간헐 측정 — FB-07 제약 제한 대상)"),
    (["접착", "밀착", "박리"],
     "electrode_adhesion_n_cm", "max", "접착력 확보 (간헐 측정 — FB-07 제약 제한 대상)"),
    (["고밀도", "치밀", "밀도 향상", "밀도 개선"],
     "electrode_density_gcc", "max", "합제밀도 극대화"),
]

# 수치 추출 패턴
_RE_CAPACITY = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*mAh\s*/?\s*cm", re.IGNORECASE)
_RE_CAPACITY_KO = re.compile(r"(?:면적당\s*)?용량\s*([0-9]+(?:\.[0-9]+)?)")
_RE_DENSITY = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*g\s*/?\s*cc", re.IGNORECASE)
_RE_DENSITY_KO = re.compile(r"(?:합제\s*)?밀도\s*([0-9]+(?:\.[0-9]+)?)")


@dataclass
class ParsedGoal:
    """해석 결과 — 화면에 그대로 표시해 사용자 확인을 받는다."""

    objectives: list[BackwardObjective]
    target_areal_capacity_mah_cm2: float | None
    target_density_gcc: float | None
    interpretation: list[str] = field(default_factory=list)  # 해석 근거 문장
    unrecognized: bool = False


def parse_natural_goal(text: str) -> ParsedGoal:
    """자연어 목표 문장 → 목표 집합.

    규칙:
    - 첫 매칭 의도 = 주 목표 (가중 3.0), 이후 매칭 = 부 목표 (가중 2.0)
    - 「N mAh/cm²」·「용량 N」 → 목표 면적당 용량 (설계 사양)
    - 「N g/cc」·「밀도 N」   → 합제밀도 equal 목표 (설계 사양 — FV 검증 대상)
    - 주 목표가 용량 계열이 아니면 초기 방전 용량 하한 유지(max, 가중 2.0)를
      자동 추가한다 — 기획서 시나리오의 「용량 손실 허용 한계」 관행
    """
    objectives: list[BackwardObjective] = []
    notes: list[str] = []
    seen: set[str] = set()

    lowered = text.lower()
    for keywords, column, direction, description in _INTENTS:
        if column in seen:
            continue
        if any(k.lower() in lowered for k in keywords):
            weight = 3.0 if not objectives else 2.0
            objectives.append(BackwardObjective(column=column, direction=direction, weight=weight))
            seen.add(column)
            notes.append(f"{'주' if weight == 3.0 else '부'} 목표: {description} (가중 {weight:g})")

    # 수치 추출
    capacity = None
    m = _RE_CAPACITY.search(text) or _RE_CAPACITY_KO.search(text)
    if m:
        capacity = float(m.group(1))
        notes.append(f"목표 면적당 용량 {capacity:g} mAh/cm² (설계 사양)")

    density = None
    m = _RE_DENSITY.search(text) or _RE_DENSITY_KO.search(text)
    if m:
        density = float(m.group(1))
        if "electrode_density_gcc" not in seen:
            objectives.append(BackwardObjective(
                column="electrode_density_gcc", direction="equal", weight=2.0, target=density))
            seen.add("electrode_density_gcc")
        notes.append(f"목표 합제밀도 {density:g} g/cc (설계 사양 — 스펙 타당성 검증 대상)")

    if not objectives:
        return ParsedGoal([], capacity, density,
                          ["해석 가능한 목표 키워드가 없습니다 — 목표를 직접 지정하세요"],
                          unrecognized=True)

    # 용량 하한 유지 (기획서 시나리오: 용량 손실 허용 한계)
    if "initial_discharge_capacity_mah_g" not in seen:
        objectives.append(BackwardObjective(
            column="initial_discharge_capacity_mah_g", direction="max", weight=2.0))
        notes.append("부 목표: 초기 방전 용량 하한 유지 (가중 2 — 용량 손실 허용 한계, 자동 추가)")

    return ParsedGoal(objectives, capacity, density, notes)
