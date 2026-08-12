"""전기화학 안정 창(ESW) 진단 — 「왜 이 판정인가」를 근거까지 되짚는다.

ESW 막대와 전극 전위선만 보여주면 «경계»가 왜 나왔는지 알 수 없다. 이 모듈은
판정을 인과 사슬로 분해한다.

    구조(환원되기 쉬운 작용기) → 낮은 LUMO → 높은 EA → 높은 환원 전위
      → 전극 구동 범위가 ESW 안에 들어오지 못함 → 그 전극에서 환원 분해

전위 환산은 엔진과 같은 식이다: E_red = EA − E_abs(기준전극).
따라서 사슬의 마지막 두 단계는 해석이 아니라 항등식이다.

**판정 기준은 포함 관계다.** 전극이 안정하려면 그 «구동 범위 전체»가 물질의
ESW 안에 들어와야 한다. 한쪽 끝만 봐서는 안 된다.

작용기 귀속은 계산이 아니라 **해석 보조**다. 어떤 구조가 LUMO를 낮추는지는
잘 알려져 있지만, 이 모듈이 그것을 계산해서 확인한 것은 아니다.
"""

from rdkit import Chem

# 전극 구동 «범위» (V vs Li/Li⁺). 단일 값이 아니라 범위인 것이 중요하다 —
# 흑연은 리튬화가 0.20 · 0.11 · 0.08 V 단계 평탄부에 걸쳐 일어난다.
ELECTRODE_WINDOWS = [
    {"key": "graphite", "label": "흑연 (Graphite)", "side": "anode",
     "low": 0.01, "high": 0.25, "nominal": 0.10,
     "note": "리튬화 단계 평탄부 0.20 · 0.11 · 0.08 V — 방전 시 0.01 V 까지 내려간다"},
    {"key": "si", "label": "실리콘 (Si)", "side": "anode",
     "low": 0.05, "high": 0.60, "nominal": 0.40,
     "note": "합금화 0.1~0.3 V · 탈합금화 0.3~0.5 V 로 흑연보다 범위가 넓다"},
    {"key": "li", "label": "리튬 금속", "side": "anode",
     "low": 0.0, "high": 0.0, "nominal": 0.0,
     "note": "기준점 — 가장 가혹한 환원 조건"},
    {"key": "lfp", "label": "LFP", "side": "cathode",
     "low": 3.40, "high": 3.50, "nominal": 3.45,
     "note": "2상 평탄부 — 충방전 내내 거의 일정"},
    {"key": "ncm811", "label": "NCM811 (4.3 V 충전)", "side": "cathode",
     "low": 3.00, "high": 4.30, "nominal": 4.30,
     "note": "충전 상단 4.3 V 가 산화 부담의 최대치"},
]
ELECTRODE_BY_KEY = {e["key"]: e for e in ELECTRODE_WINDOWS}

# 환원되기 쉬운 작용기 — LUMO를 낮추는 구조. 위에 있을수록 영향이 크다.
# (SMARTS, 이름, LUMO를 낮추는 이유)
REDUCIBLE_GROUPS = [
    ("[CX3]=[CX3][c]", "방향족과 공액된 비닐",
     "비닐의 π* 와 방향고리의 π* 가 섞여 공액계가 넓어집니다. 공액이 길어질수록 "
     "π* 준위가 내려가 LUMO가 낮아지고, 그만큼 전자를 받기 쉬워집니다. "
     "스타이렌이 전형입니다."),
    ("[CX3]=[CX3][CX3]=[CX3]", "공액 다이엔",
     "이중결합 두 개가 이어져 π* 가 분리되면서 낮은 쪽이 더 내려갑니다."),
    ("[CX3]=[CX3][CX3]=[OX1]", "α,β-불포화 카보닐",
     "카보닐의 강한 전자 끌기와 C=C 공액이 겹쳐 LUMO가 크게 내려갑니다."),
    ("[NX1]#[CX2]", "나이트릴 (C≡N)",
     "질소의 전기음성도가 높아 π* 가 낮게 놓입니다."),
    ("[NX3](=[OX1])=[OX1]", "나이트로기",
     "가장 강한 전자 끌기 작용기 중 하나로 LUMO를 크게 낮춥니다."),
    ("[$([NX3+](=[OX1])[O-])]", "나이트로기 (이온 표기)",
     "가장 강한 전자 끌기 작용기 중 하나로 LUMO를 크게 낮춥니다."),
    ("[CX3](=[OX1])[OX2]", "에스터·카보네이트 카보닐",
     "C=O 의 π* 가 LUMO를 이룹니다 — EC 가 흑연에서 환원되어 SEI를 만드는 이유입니다."),
    ("[CX3]=[OX1]", "카보닐 (케톤·알데하이드·산)",
     "C=O 의 π* 가 LUMO를 이루어 포화 사슬보다 훨씬 환원되기 쉽습니다."),
    ("c1ccccc1", "방향족 고리",
     "고리의 π* 가 LUMO를 이룹니다. 단독으로는 환원이 어렵지만 치환기와 공액되면 "
     "함께 내려갑니다."),
    ("[CX3]=[CX3]", "고립 이중결합 (C=C)",
     "π* 가 LUMO를 이루지만 공액이 없으면 비교적 높이 놓여 환원이 쉽지 않습니다."),
]

# 참고점 — 모두 «표준» 프리셋(PBE0-D3(BJ)/def2-TZVP · 구조 최적화 · SMD 카보네이트)
# 에서 실제로 계산한 값이다. 어림값을 눈금으로 쓰면 정작 관심 구조가 자기 참고선
# 아래에 찍히는 일이 생긴다 — 실제로 그런 오차가 있어 실측값으로 교체했다.
LUMO_REFERENCE = [
    {"label": "포화 알케인 (부탄 — PE 사슬)", "lumo_ev": 1.486,
     "reduction_v": -1.97, "source": "표준 계산",
     "note": "σ* 밖에 받을 자리가 없어 LUMO가 높다 — 환원에 매우 강하다"},
    {"label": "스타이렌 (방향족 공액 비닐)", "lumo_ev": -1.126,
     "reduction_v": 0.44, "source": "표준 계산",
     "note": "비닐 π* 와 고리 π* 가 섞여 내려간다"},
    {"label": "아크릴로나이트릴 (나이트릴)", "lumo_ev": -1.419,
     "reduction_v": 0.71, "source": "표준 계산",
     "note": "나이트릴의 강한 전자 끌기로 π* 가 더 낮다"},
]

# LUMO 만으로 환원 전위를 짐작하면 얼마나 빗나가는지 — 실측 사례
LUMO_CAVEAT = {
    "example": "스타이렌",
    "naive_v": -0.31,      # −LUMO − 1.44 로 짐작한 값
    "actual_v": 0.44,      # ΔG 기반 실제 환원 전위
    "note": ("LUMO 는 «전자를 넣기 전»의 사진입니다. 실제로 전자가 들어가면 분자가 "
             "구조를 바꾸고(완화) 용매가 음이온을 감싸(용매화) 훨씬 안정해집니다. "
             "스타이렌은 LUMO 로 짐작하면 −0.31 V 로 안전해 보이지만 실제 환원 전위는 "
             "+0.44 V 로, 0.75 V 나 낙관하게 됩니다. 판정은 반드시 EA 기반 전위로 하세요."),
}


def _mol(smiles):
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        raise ValueError(f"SMILES를 해석할 수 없습니다: {smiles}")
    return m


def reducible_groups(smiles: str) -> list[dict]:
    """환원되기 쉬운 작용기를 찾는다 — 해석 보조이지 계산이 아니다."""
    try:
        mol = _mol(smiles)
    except ValueError:
        return []
    found, seen = [], set()
    for smarts, name, why in REDUCIBLE_GROUPS:
        patt = Chem.MolFromSmarts(smarts)
        if patt is None:
            continue
        matches = mol.GetSubstructMatches(patt)
        if not matches:
            continue
        atoms = frozenset(a for m in matches for a in m)
        # 이미 더 강한(위쪽) 작용기가 같은 원자를 설명했으면 중복으로 세지 않는다
        if atoms <= seen:
            continue
        seen |= atoms
        found.append({"name": name, "smarts": smarts, "why": why,
                      "count": len(matches)})
    return found


def containment(red_v: float, ox_v: float, window: dict) -> dict:
    """전극 구동 «범위 전체»가 물질의 ESW 안에 들어오는지 — 포함 관계 판정.

    한쪽 끝만 보면 틀린다. 구동 범위 어느 지점에서든 ESW 밖으로 나가면
    그 지점에서 분해가 일어난다.
    """
    lo, hi = window["low"], window["high"]
    # 환원 쪽: 전극 전위가 물질의 환원 전위보다 «아래»로 내려가면 환원된다.
    # 구동 범위의 최저점(lo)이 red_v 보다 아래면 환원 구간에 들어간다.
    reduce_gap = red_v - lo            # >0 이면 구동 범위 안에서 환원됨
    # 산화 쪽: 전극 전위가 산화 전위보다 «위»로 올라가면 산화된다.
    oxidize_gap = hi - ox_v            # >0 이면 구동 범위 안에서 산화됨

    fails = []
    if reduce_gap > 0:
        fails.append({
            "side": "환원", "gap_v": round(reduce_gap, 3),
            "detail": (f"환원 전위 {red_v:+.2f} V 가 구동 범위 하단 {lo:.2f} V 보다 "
                       f"{reduce_gap:.2f} V 높습니다 — 전극 전위가 그 아래로 "
                       "내려가는 동안 이 물질이 먼저 전자를 받습니다."),
        })
    if oxidize_gap > 0:
        fails.append({
            "side": "산화", "gap_v": round(oxidize_gap, 3),
            "detail": (f"산화 전위 {ox_v:+.2f} V 가 구동 범위 상단 {hi:.2f} V 보다 "
                       f"{oxidize_gap:.2f} V 낮습니다 — 충전 상단에서 산화됩니다."),
        })

    if not fails:
        margin = min(lo - red_v, ox_v - hi)
        verdict, summary = "안정", (
            f"구동 범위 {lo:.2f}~{hi:.2f} V 가 ESW({red_v:+.2f}~{ox_v:+.2f} V) 안에 "
            f"완전히 들어옵니다 — 여유 {margin:.2f} V.")
    else:
        # 「구동 범위 안에서 환원」과 「범위에 들어가기도 전에 환원」은 다른 상황이다.
        # 전자는 리튬화 도중 일부 구간에서, 후자는 전 구간에서 분해가 일어난다.
        whole_range = red_v > hi or ox_v < lo
        verdict = "분해 우려" if whole_range else "경계"
        where = ("구동 «전 구간»에서" if whole_range else "구동 범위 «일부 구간»에서")
        worst = max(f["gap_v"] for f in fails)
        summary = (f"구동 범위 {lo:.2f}~{hi:.2f} V 가 ESW({red_v:+.2f}~{ox_v:+.2f} V) 안에 "
                   f"들어오지 못합니다 — " + " / ".join(f["side"] for f in fails)
                   + f" 쪽으로 최대 {worst:.2f} V 벗어나며, {where} 분해가 일어납니다.")
        if whole_range and red_v > hi:
            summary += (f" 환원 전위 {red_v:+.2f} V 가 범위 상단 {hi:.2f} V 보다 높아, "
                        "전극이 작동 전위에 도달하기 «전»에 이미 환원됩니다.")
    return {"verdict": verdict, "summary": summary, "fails": fails,
            "window": window, "reduce_gap_v": round(reduce_gap, 3),
            "oxidize_gap_v": round(oxidize_gap, 3)}


def causal_chain(smiles: str, desc: dict, cont: dict, e_abs: float) -> list[dict]:
    """판정을 구조까지 되짚는 인과 사슬. 각 단계에 실제 계산값을 붙인다."""
    groups = reducible_groups(smiles)
    lumo = desc.get("lumo_ev")
    win = cont["window"]
    # EA 와 전위는 «같은 기준»끼리 짝지어야 한다. ΔG 기반 전위를 쓰면서 단열 EA 를
    # 보여주면 E_red = EA − E_abs 항등식이 화면에서 깨져 보인다.
    if desc.get("reduction_potential_gibbs_v") is not None:
        red = desc["reduction_potential_gibbs_v"]
        ea, ea_label = desc.get("ea_gibbs_ev"), "ΔG 기반 전자 친화도 EA"
        ea_note = ("전자 하나를 붙이고 구조 완화와 298 K 열보정(ZPE·엔탈피·엔트로피)까지 "
                   "반영한 값입니다.")
    else:
        red = desc.get("reduction_potential_v")
        if desc.get("ea_adiabatic_ev") is not None:
            ea, ea_label = desc["ea_adiabatic_ev"], "단열 전자 친화도 EA"
            ea_note = "전자를 붙인 뒤 음이온 구조를 다시 최적화한 값 — 구조 완화 포함."
        else:
            ea, ea_label = desc.get("ea_vertical_ev"), "수직 전자 친화도 EA"
            ea_note = ("구조를 고정한 채 전자만 넣은 값 — 구조 완화가 빠져 있어 위험을 "
                       "낮잡을 수 있습니다.")

    top = groups[0] if groups else None
    return [
        {"step": 1, "label": "구조",
         "value": top["name"] if top else "환원되기 쉬운 작용기 없음",
         "unit": "", "measured": False,
         "note": top["why"] if top else
                 "포화 사슬만 있으면 σ* 밖에 받을 자리가 없어 환원에 강합니다."},
        {"step": 2, "label": "LUMO", "value": lumo, "unit": "eV", "measured": True,
         "note": "전자를 받는 자리의 에너지 — 낮을수록 받기 쉽습니다. DFT 계산값입니다."},
        {"step": 3, "label": ea_label, "value": ea, "unit": "eV", "measured": True,
         "note": ea_note},
        {"step": 4, "label": "환원 전위", "value": red, "unit": "V vs Li/Li⁺",
         "measured": True,
         "note": (f"E_red = EA − {e_abs} V. 해석이 아니라 기준전극 절대전위를 뺀 "
                  "항등식입니다 — 그래서 EA가 크면 환원 전위가 그대로 올라갑니다.")},
        {"step": 5, "label": f"{win['label']} 구동 범위",
         "value": f"{win['low']:.2f} ~ {win['high']:.2f}", "unit": "V vs Li/Li⁺",
         "measured": False, "note": win["note"]},
        {"step": 6, "label": "판정", "value": cont["verdict"], "unit": "",
         "measured": False, "note": cont["summary"]},
    ]


def ea_stages(desc: dict, e_abs: float = 1.44) -> dict:
    """수직 → 단열 → ΔG 로 EA 가 뛰는 과정 — 판정이 뒤집히는 지점을 드러낸다.

    구조를 고정한 «수직» EA 만 보면 안전해 보이는 물질이, 실제로 전자를 받고
    구조가 완화되고 용매가 음이온을 감싸면 환원 전위가 크게 올라간다.
    스타이렌이 정확히 그 사례다 (수직 −0.51 eV → 단열 +1.73 eV).
    """
    steps, prev = [], None
    for key, label, adds in [
        ("ea_vertical_ev", "수직 EA", "구조를 고정한 채 전자만 넣은 값"),
        ("ea_adiabatic_ev", "단열 EA", "음이온 구조를 다시 최적화 — 구조 완화가 더해진다"),
        ("ea_gibbs_ev", "ΔG 기반 EA", "298 K 열보정(ZPE·엔탈피·엔트로피)까지 더한다"),
    ]:
        v = desc.get(key)
        if v is None:
            continue
        step = {"key": key, "label": label, "ea_ev": v,
                "reduction_v": round(v - e_abs, 3), "adds": adds}
        if prev is not None:
            step["delta_ev"] = round(v - prev, 3)
        steps.append(step)
        prev = v
    return {"steps": steps, "e_abs": e_abs,
            "note": ("환원 전위는 이 사슬의 «마지막» 값으로 판정합니다. 수직 EA 만 보면 "
                     "위험을 크게 낮잡습니다.") if len(steps) > 1 else ""}


def diagnose(material: dict, desc: dict, electrode: str = "graphite",
             e_abs: float = 1.44) -> dict:
    """ESW 판정 하나를 근거까지 펼친다."""
    win = ELECTRODE_BY_KEY.get(electrode)
    if win is None:
        raise ValueError(f"알 수 없는 전극: {electrode}")
    red = desc.get("reduction_potential_gibbs_v", desc.get("reduction_potential_v"))
    ox = desc.get("oxidation_potential_gibbs_v", desc.get("oxidation_potential_v"))
    smiles = material.get("smiles", "")
    out = {"name": material.get("name"), "smiles": smiles,
           "electrode": win, "electrodes": ELECTRODE_WINDOWS,
           "reduction_potential_v": red, "oxidation_potential_v": ox,
           "lumo_ev": desc.get("lumo_ev"),
           "ea_ev": desc.get("ea_adiabatic_ev", desc.get("ea_vertical_ev")),
           "lumo_reference": LUMO_REFERENCE, "lumo_caveat": LUMO_CAVEAT,
           "e_abs": e_abs}
    if red is None or ox is None:
        out["available"] = False
        out["note"] = ("환원·산화 전위가 없어 진단할 수 없습니다 — 'DFT 계산'에서 "
                       "목적을 «전자구조 + 산화/환원 전위»로, 기준 전극을 Li/Li⁺ 로 "
                       "두고 다시 계산하세요.")
        return out

    out["available"] = True
    out["ea_stages"] = ea_stages(desc, e_abs)
    cont = containment(red, ox, win)
    out["containment"] = cont
    out["groups"] = reducible_groups(smiles)
    out["chain"] = causal_chain(smiles, desc, cont, e_abs)
    out["remedies"] = _remedies(cont, out["groups"])
    # 다른 전극에서는 어떤지도 함께 — 「음극만 문제인가」를 바로 알 수 있다
    out["all_electrodes"] = [
        {"key": e["key"], "label": e["label"], "side": e["side"],
         **{k: v for k, v in containment(red, ox, e).items()
            if k in ("verdict", "summary")}}
        for e in ELECTRODE_WINDOWS]
    return out


def _remedies(cont: dict, groups: list[dict]) -> list[str]:
    """판정을 바꾸려면 무엇을 해야 하는가 — 구조 쪽 처방."""
    out = []
    if any(f["side"] == "환원" for f in cont["fails"]):
        names = ", ".join(g["name"] for g in groups[:2])
        if groups:
            out.append(f"LUMO를 올려야 합니다 — {names} 의 공액을 끊거나 포화시키면 "
                       "π* 가 사라지거나 위로 올라가 환원 전위가 내려갑니다.")
        out.append("잔류 단량체라면 중합률을 올려 없애는 것이 근본 대책입니다 — "
                   "사슬에 들어간 반복 단위는 C=C가 소모되어 환원에 훨씬 강합니다.")
        out.append("전해액 첨가제(FEC·VC)로 SEI를 먼저 형성시켜 동역학적으로 "
                   "보호하는 방법도 실무에서 쓰입니다 — 다만 이 판정은 열역학 기준이라 "
                   "그 효과는 반영되어 있지 않습니다.")
    if any(f["side"] == "산화" for f in cont["fails"]):
        out.append("HOMO를 내려야 합니다 — 전자 끌기 치환기(F 등)를 넣으면 "
                   "산화 전위가 올라갑니다.")
    if not cont["fails"]:
        out.append("이 전극 구동 범위에서는 열역학적으로 안정합니다.")
    return out
