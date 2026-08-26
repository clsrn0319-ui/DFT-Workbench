"""5대 DFT Score — 「DFT 기반 바인더 후보군 Screening 프로그램 기획서 v0.1」 7·8장 구현.

다섯 축(접착·전기화학 안정성·전해액 친화도·이온 상호작용·화학적 안정성)의
기술자를 0~100 점수로 정규화하고, 적용 소재별 가중치로 총점을 만든다.

기획서의 원칙을 그대로 따른다:
  - 점수는 «동일 프로토콜에서의 상대 비교» 도구이지 최종 성능값이 아니다.
  - Hard Filter(작동 전위 위반)와 Soft Ranking(점수)을 분리한다 — 치명적 약점이
    높은 평균에 가려지지 않도록 탈락은 점수와 별개로 표시한다.
  - 친화도·이온 결합은 «높을수록 좋은 선형»이 아니라 목표 범위(target window)
    로 채점한다 — 과한 친화는 swelling, 과한 결합은 Li⁺ 이동성 저하 위험.
  - 감점(Penalty)에는 반드시 사유를 남긴다.
  - 축 데이터가 없으면 그 축을 빼고 가중치를 재정규화하며, 무엇이 빠졌는지
    표시한다 — 결측을 0점으로 오판하지 않는다.
"""

import json
import os

# 프로토콜 버전 — 계산 조건 표준의 이름표. 조건 표준(프리셋·범함수·기저·용매
# 파라미터)이 바뀌어 후보 간 비교 가능성이 깨질 때만 올린다.
PROTOCOL_VERSION = "DFT-BINDER-v1.0"

AXES = [
    ("adhesion", "접착"),
    ("electrochem", "전기화학 안정성"),
    ("affinity", "전해액 친화도"),
    ("ion", "이온 상호작용"),
    ("chemstab", "화학적 안정성"),
]
AXIS_LABEL = dict(AXES)

# 점수 앵커 — 기획서 7.1의 «사전 정의 정규화 함수» 기준점.
#   선형형: zero(0점) ↔ full(100점)   ·   window형: [lo, hi] 100점, span 만큼
#   벗어나면 0점까지 선형 감점.
# 절대값은 대용 클러스터·SMD 근사 위에서의 실용 기준이며,
# RHOBENCH_SCORE_ANCHORS 환경변수(JSON)로 통째로 덮어쓸 수 있다.
ANCHORS = {
    "adhesion": {"zero": 0.0, "full": -120.0},        # 표면 흡착 E (kJ/mol)
    "electrochem": {"zero": -0.5, "full": 1.5},       # ESW 최소 여유 (V)
    "affinity": {"lo": -12.0, "hi": -3.0, "span": 10.0},    # 용매화 E (kcal/mol)
    "ion": {"lo": -250.0, "hi": -120.0, "span": 120.0},     # Li⁺ 결합 (kJ/mol)
    "chemstab": {"zero": 250.0, "full": 350.0},       # 최약 BDE 298K (kJ/mol)
}
_env_anchors = os.environ.get("RHOBENCH_SCORE_ANCHORS")
if _env_anchors:
    try:
        ANCHORS.update(json.loads(_env_anchors))
    except (json.JSONDecodeError, TypeError):
        pass

# BDE 가 이 값보다 낮으면 분해 취약 감점 (기획서 7.2 Penalty)
BDE_PENALTY_KJ = ANCHORS["chemstab"]["zero"]
BDE_PENALTY_POINTS = 15.0

# 적용 소재별 가중치 preset (기획서 7.3) — 사용자가 복사·조정할 수 있다
WEIGHT_PRESETS = {
    "균등": {"adhesion": 0.20, "electrochem": 0.20, "affinity": 0.20,
             "ion": 0.20, "chemstab": 0.20},
    "Si 음극": {"adhesion": 0.30, "ion": 0.25, "affinity": 0.20,
                "electrochem": 0.15, "chemstab": 0.10},
    "흑연 음극": {"electrochem": 0.30, "affinity": 0.25, "adhesion": 0.15,
                  "ion": 0.15, "chemstab": 0.15},
    "하이니켈 양극": {"electrochem": 0.35, "chemstab": 0.25, "adhesion": 0.20,
                      "affinity": 0.10, "ion": 0.10},
}


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def _linear(x, zero, full):
    """zero→0점, full→100점 선형 (증가·감소 방향 자동)."""
    if full == zero:
        return None
    return _clamp(100.0 * (x - zero) / (full - zero))


def _window(x, lo, hi, span):
    """[lo, hi] 안 100점 — 벗어난 거리가 span 이면 0점 (target window 채점)."""
    if x < lo:
        return _clamp(100.0 * (1.0 - (lo - x) / span))
    if x > hi:
        return _clamp(100.0 * (1.0 - (x - hi) / span))
    return 100.0


def axis_scores(desc: dict, worst_margin_v, electrodes: list[str]) -> dict:
    """다섯 축 각각의 원값과 0~100 점수. 데이터가 없는 축은 score=None."""
    out = {}

    # ① 접착 — 캠페인 대상 활물질과 겹치는 표면 모델의 흡착 에너지 평균
    ads = desc.get("surface_adsorption") or {}
    targets = [ads[e]["energy_kj"] for e in electrodes if e in ads]
    if not targets and ads:      # 사용자 정의 활물질뿐이면 전 표면 평균으로 참고 채점
        targets = [v["energy_kj"] for v in ads.values()]
    a = ANCHORS["adhesion"]
    out["adhesion"] = {
        "value": round(sum(targets) / len(targets), 1) if targets else None,
        "unit": "kJ/mol",
        "score": _linear(sum(targets) / len(targets), a["zero"], a["full"])
        if targets else None,
        "note": None if targets else "표면 흡착 데이터 없음 (물성 지문 계산 필요)",
    }

    # ② 전기화학 안정성 — ESW 최소 여유 (judge 의 worst margin)
    a = ANCHORS["electrochem"]
    out["electrochem"] = {
        "value": worst_margin_v, "unit": "V",
        "score": _linear(worst_margin_v, a["zero"], a["full"])
        if worst_margin_v is not None else None,
        "note": None if worst_margin_v is not None else "전위 데이터 없음",
    }

    # ③ 전해액 친화도 — 용매화 에너지, target window
    solv = desc.get("solvation_energy_kcal")
    a = ANCHORS["affinity"]
    out["affinity"] = {
        "value": solv, "unit": "kcal/mol",
        "score": _window(solv, a["lo"], a["hi"], a["span"]) if solv is not None else None,
        "note": None if solv is not None else "용매화 에너지 없음 (용매 설정 필요)",
    }

    # ④ 이온 상호작용 — Li⁺ 결합 에너지, target window (과한 결합은 이동성 저하)
    li = desc.get("li_binding_kj")
    a = ANCHORS["ion"]
    out["ion"] = {
        "value": li, "unit": "kJ/mol",
        "score": _window(li, a["lo"], a["hi"], a["span"]) if li is not None else None,
        "note": None if li is not None else "Li⁺ 결합 데이터 없음 (물성 지문 계산 필요)",
    }

    # ⑤ 화학적 안정성 — 최약 결합 BDE (298 K 우선)
    bde = desc.get("bde_min_298_kj", desc.get("bde_min_kj"))
    a = ANCHORS["chemstab"]
    out["chemstab"] = {
        "value": bde, "unit": "kJ/mol",
        "score": _linear(bde, a["zero"], a["full"]) if bde is not None else None,
        "note": None if bde is not None else "BDE 데이터 없음 (물성 지문 계산 필요)",
    }
    return out


def normalize_weights(weights: dict | None, preset: str = "균등") -> dict:
    """가중치 정리 — 없으면 preset, 있으면 음수 제거 후 합=1 로 재정규화."""
    base = dict(WEIGHT_PRESETS.get(preset, WEIGHT_PRESETS["균등"]))
    if weights:
        for k, v in weights.items():
            if k in base and isinstance(v, (int, float)) and v >= 0:
                base[k] = float(v)
    total = sum(base.values())
    if total <= 0:
        base = dict(WEIGHT_PRESETS["균등"])
        total = 1.0
    return {k: v / total for k, v in base.items()}


def confidence_of(verdict: dict | None, desc: dict) -> tuple[str, str]:
    """결과 신뢰 수준 (기획서 8장) — 전위 계산 수준과 진동수 검증으로 판정."""
    basis = (verdict or {}).get("basis")
    if basis == "ΔG 기반":
        level, why = "High", "ΔG 기반 전위 + 열보정 포함"
    elif basis == "단열":
        level, why = "Medium", "단열 전위 (열보정 없음)"
    else:
        level, why = "Low", "수직 전위 기반 — 구조 완화 미반영"
    n_imag = desc.get("n_imaginary_freqs")
    if isinstance(n_imag, int) and n_imag > 0:
        level, why = "Low", f"허수 진동수 {n_imag}개 — 안장점 가능성"
    return level, why


def evaluate(desc: dict, verdict: dict | None, electrodes: list[str],
             weights: dict | None = None, preset: str = "균등") -> dict:
    """후보 하나의 5대 Score 종합 — 총점·Hard Filter·Penalty·사유·Confidence."""
    w = normalize_weights(weights, preset)
    worst = (verdict or {}).get("worst_margin_v")
    axes = axis_scores(desc, worst, electrodes)

    available = {k: v for k, v in axes.items() if v["score"] is not None}
    missing = [AXIS_LABEL[k] for k in axes if axes[k]["score"] is None]
    reasons = []

    if available:
        # 결측 축은 빼고 가중치 재정규화 — 결측을 0점으로 오판하지 않는다
        w_sum = sum(w[k] for k in available)
        w_used = {k: (w[k] / w_sum if w_sum > 0 else 1.0 / len(available))
                  for k in available}
        total = sum(w_used[k] * available[k]["score"] for k in available)
    else:
        w_used, total = {}, None

    if missing:
        reasons.append("미산출 축 제외 후 재정규화: " + ", ".join(missing))

    # Hard Filter — 작동 전위 창 위반 (기획서 7.2: 점수와 분리, 사유 명시)
    grade = (verdict or {}).get("grade")
    hard_fail = grade == "부적합"
    if hard_fail:
        bad = [p["label"] for p in (verdict or {}).get("per_electrode", [])
               if p.get("grade") == "부적합"]
        reasons.append("Hard Filter 탈락 — 작동 전위 창 위반"
                       + (f" ({', '.join(bad)})" if bad else ""))
    elif grade == "조건부":
        reasons.append("전위 여유가 안정성 마진 이내 — 상위 단계 재확인 권장")

    # Penalty — 분해 취약 결합 (총점 감점 + 사유)
    penalty = 0.0
    bde = axes["chemstab"]["value"]
    if bde is not None and bde < BDE_PENALTY_KJ:
        penalty += BDE_PENALTY_POINTS
        reasons.append(f"최약 결합 BDE {bde:.0f} kJ/mol < {BDE_PENALTY_KJ:.0f} — "
                       f"분해 취약 감점 −{BDE_PENALTY_POINTS:.0f}")

    lc = (verdict or {}).get("lumo_check")
    if lc:
        reasons.append(f"LUMO 불일치 — LUMO 추정 {lc['naive_red_v']:+.2f} V 가 "
                       f"{', '.join(lc['mismatch'])} 침범, 수직 EA 판정과 상반 "
                       "(표준 재계산 필요)")

    level, why = confidence_of(verdict, desc)

    return {
        "protocol": PROTOCOL_VERSION,
        "axes": axes,
        "weights_used": {k: round(v, 3) for k, v in w_used.items()},
        "total": round(max(0.0, total - penalty), 1) if total is not None else None,
        "total_raw": round(total, 1) if total is not None else None,
        "penalty": round(penalty, 1),
        "hard_fail": hard_fail,
        "reasons": reasons,
        "confidence": level,
        "confidence_note": why,
    }
