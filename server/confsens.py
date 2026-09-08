"""Conformer 민감도 — v2.0 개정 기획서 P0-5 · 3.6.

표준 정확도는 지금까지 «지배 conformer 하나»로 전위를 냈다. 유연한 사슬은
저에너지 conformer 가 여럿이고, 어느 것을 골랐느냐에 따라 EA·전위가
0.1~0.3 V 움직인다. 한 값만 보고 판정하면 그 편차는 보이지 않는다.

그래서 상위 N개 conformer 각각에서 같은 경로(수직 → 단열)로 IP/EA 를
다시 내고, 편차 σ 로 판정 규칙을 정한다.

  σ < 0.10 V         단일값 판정 유지
  0.10 ≤ σ < 0.20    Molecular Model 신뢰도 하향 (Medium)
  σ ≥ 0.20 V         단일값 대신 «범위»로만 판정 (Model 신뢰도 Low)

임계값은 기획서 3.6 이 제시한 초기 운영값이며 벤치마크 후 조정한다.

이 모듈은 DFT 를 부르지 않는다 — 엔진이 conformer 마다 낸 에너지·IP/EA 를
받아 통계와 규칙만 계산한다. 그래서 단위 테스트가 실계산 없이 돈다.
"""

import math

HARTREE2KCAL = 627.5095
KB_KCAL = 1.98720425e-3   # kcal/(mol·K)

#: 기획서 3.6 초기 운영 기준 — Model 신뢰도 하향 / 범위 판정
SPREAD_DOWNGRADE_V = 0.10
SPREAD_RANGE_ONLY_V = 0.20
#: 이보다 높은 conformer 는 실온 분포에 사실상 기여하지 않아 민감도 대상에서 뺀다
ENERGY_WINDOW_KCAL = 5.0

RULE_LABEL = {
    "ok": "단일값 판정 유지",
    "downgrade": "Model 신뢰도 하향 — conformer 편차 0.10 V 이상",
    "range_only": "범위 판정 — conformer 편차 0.20 V 이상, 단일값 판정 부적절",
    "n/a": "편차 미산출",
}


def rule_for(spread_v) -> str:
    if spread_v is None:
        return "n/a"
    if spread_v >= SPREAD_RANGE_ONLY_V:
        return "range_only"
    if spread_v >= SPREAD_DOWNGRADE_V:
        return "downgrade"
    return "ok"


def _stats(values: list[float], weights: list[float]) -> dict:
    n = len(values)
    mean = sum(values) / n
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / n)   # 모집단 σ (N 이 작다)
    z = sum(weights)
    boltz = sum(w * v for w, v in zip(weights, values)) / z
    return {"mean": round(mean, 3), "std": round(std, 3),
            "min": round(min(values), 3), "max": round(max(values), 3),
            "boltzmann": round(boltz, 3)}


def summarize(members: list[dict], temperature: float, basis: str,
              e_abs: float | None = None) -> dict:
    """conformer 별 (e_hartree, ip_ev, ea_ev) → 분포·편차·규칙.

    members 각 항목: {"conformer": 번호, "e_hartree": 최종 단일점 에너지,
                      "ip_ev": IP, "ea_ev": EA, "dominant": 지배 여부}
    basis: "단열" 또는 "수직" — IP/EA 를 어느 수준에서 냈는가.
    e_abs: 기준 전극 절대 전위. 있으면 전위(V)도 함께 낸다.
    """
    if len(members) < 2:
        return {"n_conformers": len(members), "basis": basis, "rule": "n/a",
                "window_kcal": ENERGY_WINDOW_KCAL,
                "note": ("비교할 저에너지 conformer 가 하나뿐이라 편차를 낼 수 없습니다 — "
                         "탐색 범위 안에서는 구조 의존성이 드러나지 않았다는 뜻이지, "
                         "없다는 뜻은 아닙니다")}

    kT = KB_KCAL * temperature
    e_min = min(m["e_hartree"] for m in members)
    rows, weights = [], []
    for m in members:
        rel = (m["e_hartree"] - e_min) * HARTREE2KCAL
        w = math.exp(-rel / kT)
        weights.append(w)
        rows.append({**m, "rel_e_kcal": round(rel, 2)})
    z = sum(weights)
    for r, w in zip(rows, weights):
        r["population_pct"] = round(100 * w / z, 1)
        if e_abs is not None:
            r["reduction_v"] = round(r["ea_ev"] - e_abs, 3)
            r["oxidation_v"] = round(r["ip_ev"] - e_abs, 3)

    ea = _stats([m["ea_ev"] for m in members], weights)
    ip = _stats([m["ip_ev"] for m in members], weights)
    # 1 eV 의 EA 차이는 1 V 의 전위 차이 — 기준 전극과 무관하게 편차는 같다
    spread = max(ea["std"], ip["std"])
    rule = rule_for(spread)
    out = {
        "n_conformers": len(members),
        "basis": basis,
        "temperature_k": temperature,
        "window_kcal": ENERGY_WINDOW_KCAL,
        "members": rows,
        "ea_ev": ea, "ip_ev": ip,
        "spread_v": spread,
        "rule": rule,
        "rule_label": RULE_LABEL[rule],
        "thresholds_v": {"downgrade": SPREAD_DOWNGRADE_V, "range_only": SPREAD_RANGE_ONLY_V},
    }
    if e_abs is not None:
        out["reduction_v"] = {k: round(v - e_abs, 3) if k != "std" else v
                              for k, v in ea.items()}
        out["oxidation_v"] = {k: round(v - e_abs, 3) if k != "std" else v
                              for k, v in ip.items()}
    out["note"] = _note(out)
    return out


def _note(s: dict) -> str:
    n, sp = s["n_conformers"], s["spread_v"]
    head = (f"저에너지 conformer {n}개에서 {s['basis']} IP/EA 를 각각 계산 — "
            f"전위 편차 σ {sp:.2f} V (환원 σ {s['ea_ev']['std']:.2f} · 산화 σ {s['ip_ev']['std']:.2f}). ")
    if s["rule"] == "range_only":
        return head + ("0.20 V 이상이라 단일값으로 판정하지 않고 범위로 판정합니다 — "
                       "구조 선택에 따라 결론이 바뀔 수 있는 물질입니다.")
    if s["rule"] == "downgrade":
        return head + ("0.10 V 이상이라 Molecular Model 신뢰도를 Medium 으로 낮춥니다 — "
                       "판정 값은 지배 conformer 기준이지만 범위를 함께 보세요.")
    return head + "0.10 V 미만 — 구조 선택이 판정을 바꾸지 않습니다."


def judgement_range(sens: dict | None) -> dict | None:
    """«범위 판정» 규칙일 때, 지배 conformer 값 대비 전위 편차 구간을 돌려준다.

    판정 값(ΔG 기반)은 지배 conformer 에서만 열보정까지 했으므로, 다른 conformer 의
    전자 IP/EA 차이를 «지배 conformer 대비 오프셋»으로 옮겨 붙인다.
    반환: {"red": (lo, hi), "ox": (lo, hi)} — 판정 전위에 더할 오프셋.
    """
    if not sens or sens.get("rule") != "range_only":
        return None
    dom = next((m for m in sens.get("members", []) if m.get("dominant")), None)
    if dom is None:
        return None
    eas = [m["ea_ev"] for m in sens["members"]]
    ips = [m["ip_ev"] for m in sens["members"]]
    return {
        "red": (round(min(eas) - dom["ea_ev"], 3), round(max(eas) - dom["ea_ev"], 3)),
        "ox": (round(min(ips) - dom["ip_ev"], 3), round(max(ips) - dom["ip_ev"], 3)),
        "spread_v": sens["spread_v"],
        "n_conformers": sens["n_conformers"],
    }
