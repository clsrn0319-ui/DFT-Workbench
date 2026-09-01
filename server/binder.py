"""건식 음극 바인더(PFAS-free) 후보 스크리닝.

전해액 반응성 스크리닝과 판정 기준이 다르다:

  전해액 소재       — 양극/음극 양쪽 전위를 견디는지 (산화 + 환원)
  건식 음극 바인더  — 음극(0.05~0.4 V)에서 **환원**을 견디는지가 핵심이고,
                     여기에 PFAS 규제 · 건식 공정 열안정성 · 활물질 접착 ·
                     피브릴화(응집) · 전해액 분자 친화도가 더해진다

이 모듈은 그 판정 축과 후보 라이브러리, 그리고 축별 채점을 담당한다.
DFT 계산 자체는 engine.py가 그대로 수행하고, 여기서는 산출된 기술자를
"바인더로 쓸 수 있는가"라는 질문으로 번역한다.
"""

from rdkit import Chem

# ── PFAS 판정 ──────────────────────────────────────────────────────
# OECD(2021) 정의: 완전 불소화된 메틸(-CF3) 또는 메틸렌(-CF2-) 탄소를
# 최소 하나 포함하면 PFAS. 단일 불소 치환(예: 플루오로벤젠)은 해당하지 않는다.
PFAS_PATTERNS = [
    ("perfluoromethyl", "[CX4](F)(F)F", "퍼플루오로메틸 -CF3"),
    ("perfluoromethylene", "[CX4;H0](F)(F)", "퍼플루오로메틸렌 -CF2-"),
    ("perfluoro_alkene", "[CX3;H0](F)(F)", "완전 불소화 알켄 탄소 (중합 시 -CF2- 가 됨)"),
]
_ANY_CF = "[#6]-[#9]"


def pfas_check(smiles: str) -> dict:
    """구조에서 PFAS 해당 여부를 판정한다 (계산 없이 구조만으로)."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {"status": "unknown", "label": "구조 해석 실패",
                "n_fluorine": 0, "matched": [], "regulated": None}

    n_f = sum(1 for a in mol.GetAtoms() if a.GetSymbol() == "F")
    matched = [desc for _key, smarts, desc in PFAS_PATTERNS
               if mol.HasSubstructMatch(Chem.MolFromSmarts(smarts))]

    if matched:
        return {"status": "pfas", "label": "PFAS 해당 — 규제 대상",
                "n_fluorine": n_f, "matched": matched, "regulated": True,
                "note": "완전 불소화 탄소를 포함합니다. PFAS-free 요건을 충족하지 않습니다."}
    if mol.HasSubstructMatch(Chem.MolFromSmarts(_ANY_CF)):
        return {"status": "fluorinated", "label": "불소 함유 (PFAS 정의에는 미해당)",
                "n_fluorine": n_f, "matched": [], "regulated": False,
                "note": "C–F 결합은 있으나 완전 불소화 탄소가 없어 OECD PFAS 정의에는 "
                        "해당하지 않습니다. 규제 범위는 관할 기준을 별도 확인하세요."}
    return {"status": "pfas_free", "label": "PFAS-free", "n_fluorine": 0,
            "matched": [], "regulated": False,
            "note": "불소를 포함하지 않습니다."}


# ── 음극 작동 전위 (V vs Li/Li+) ───────────────────────────────────
# 바인더는 이 전위까지 내려가도 환원 분해되지 않아야 한다.
ANODE_POTENTIALS = [
    {"key": "graphite", "label": "흑연", "potential_v": 0.05,
     "desc": "흑연 리튬화 하한 (0.05~0.25 V)"},
    {"key": "si", "label": "실리콘", "potential_v": 0.05,
     "desc": "Si 리튬화 구간 (0.05~0.6 V)"},
    {"key": "li_metal", "label": "리튬 금속", "potential_v": 0.0,
     "desc": "가장 가혹한 조건 — 리튬 금속 음극"},
]

# 건식 공정 조건 — 이 온도·전단에서 분해되지 않아야 한다.
DRY_PROCESS = {"temperature_c": 180, "note": "건식 전극 피브릴화 공정 대표 조건 (100~200 °C + 전단)"}


# ── 후보 라이브러리 ────────────────────────────────────────────────
# smiles 는 반복 단위 모델. 비닐계는 모노머를 주면 engine 이 올리고머화할 수 있다.
DRY_BINDER_CANDIDATES = [
    {"id": "pe", "abbr": "PE", "name": "폴리에틸렌 (UHMWPE)", "smiles": "C=C",
     "family": "폴리올레핀", "vinyl": True,
     "note": "PTFE를 대체할 대표적 피브릴화 가능 바인더 — 건식 전극 1순위 후보"},
    {"id": "pp", "abbr": "PP", "name": "폴리프로필렌", "smiles": "C=CC",
     "family": "폴리올레핀", "vinyl": True,
     "note": "폴리올레핀계 — 내환원성 우수, 접착력은 낮은 편"},
    {"id": "paa", "abbr": "PAA", "name": "폴리아크릴산", "smiles": "C=CC(=O)O",
     "family": "아크릴", "vinyl": True,
     "note": "Si 음극 표준 바인더 — 카복실기 수소결합으로 팽창 대응"},
    {"id": "pan", "abbr": "PAN", "name": "폴리아크릴로나이트릴", "smiles": "C=CC#N",
     "family": "아크릴", "vinyl": True,
     "note": "니트릴기 극성 — 내열성 우수, 탄화 전구체"},
    {"id": "pva", "abbr": "PVA", "name": "폴리비닐알코올", "smiles": "C=CO",
     "family": "비닐", "vinyl": True,
     "note": "수산기 수소결합 풍부 — 자가치유형 거동"},
    {"id": "pvac", "abbr": "PVAc", "name": "폴리비닐아세테이트", "smiles": "C=COC(C)=O",
     "family": "비닐", "vinyl": True,
     "note": "에스터 극성 — 유연성 높음"},
    {"id": "pma", "abbr": "PMA", "name": "폴리메틸아크릴레이트", "smiles": "C=CC(=O)OC",
     "family": "아크릴", "vinyl": True,
     "note": "아크릴 에스터계 — 유연성과 접착의 절충"},
    {"id": "sbr_st", "abbr": "SBR-S", "name": "스타이렌 단위 (SBR)", "smiles": "C=Cc1ccccc1",
     "family": "고무", "vinyl": True,
     "note": "SBR 경질 세그먼트 — CMC와 병용되는 수계 표준"},
    {"id": "sbr_bd", "abbr": "SBR-B", "name": "부타디엔 단위 (SBR)", "smiles": "C=CC=C",
     "family": "고무", "vinyl": True,
     "note": "SBR 연질 세그먼트 — 탄성 담당, 이중결합이 환원·산화에 취약"},
    {"id": "peo", "abbr": "PEO", "name": "폴리에틸렌옥사이드", "smiles": "COCCOCCOC",
     "family": "폴리에터", "vinyl": False,
     "note": "이온 전도성 바인더 — 에터 산소가 Li+ 배위"},
    {"id": "cmc", "abbr": "CMC", "name": "카복시메틸셀룰로스 (반복 단위 모델)",
     "smiles": "OCC1OC(O)C(OCC(=O)O)C(O)C1O", "family": "다당류", "vinyl": False,
     "note": "수계 음극 표준 — 건식 적용 시 취성이 관건"},
    {"id": "alginate", "abbr": "ALG", "name": "알긴산 (반복 단위 모델)",
     "smiles": "OC1OC(C(=O)O)C(O)C(O)C1O", "family": "다당류", "vinyl": False,
     "note": "Si 음극용 천연 고분자 — 카복실기 밀도 높음"},
    {"id": "chitosan", "abbr": "CS", "name": "키토산 (반복 단위 모델)",
     "smiles": "NC1C(O)OC(CO)C(O)C1O", "family": "다당류", "vinyl": False,
     "note": "아민기 보유 — 표면 상호작용 강함"},
    {"id": "pi", "abbr": "PI", "name": "폴리이미드 (반복 단위 모델)",
     "smiles": "O=C1N(C)C(=O)c2ccccc21", "family": "이미드", "vinyl": False,
     "note": "내열성 최고 수준 — 건식 고온 공정에 유리"},
]

# 비교 기준군 — 현행 표준이지만 PFAS 규제 대상
PFAS_REFERENCES = [
    {"id": "ptfe", "abbr": "PTFE", "name": "폴리테트라플루오로에틸렌 (현행 건식 표준)",
     "smiles": "FC(F)=C(F)F", "family": "불소계", "vinyl": True,
     "note": "건식 전극의 현행 표준 바인더 — 대체 대상"},
    {"id": "pvdf", "abbr": "PVDF", "name": "폴리비닐리덴 플루오라이드",
     "smiles": "C=C(F)F", "family": "불소계", "vinyl": True,
     "note": "습식 공정 표준 바인더 — 대체 대상"},
]


def candidates(include_reference: bool = True) -> list[dict]:
    """후보 목록에 PFAS 판정을 붙여 반환한다."""
    out = []
    for c in DRY_BINDER_CANDIDATES + (PFAS_REFERENCES if include_reference else []):
        item = dict(c)
        item["pfas"] = pfas_check(c["smiles"])
        item["reference"] = c in PFAS_REFERENCES
        out.append(item)
    return out


# ── 축별 판정 ──────────────────────────────────────────────────────
# 절대 기준으로 판정 가능한 축과, 후보끼리의 상대 순위로만 의미가 있는 축을
# 명확히 구분한다. 대용 클러스터 기반 흡착 에너지에 절대 기준을 붙이면
# 근거 없는 정밀도를 주장하게 된다.

VERDICT_OK, VERDICT_MID, VERDICT_NO = "양호", "주의", "위험"


def _reduction_verdict(desc: dict) -> dict | None:
    """음극 전위 대비 환원 안정성 — 절대 판정이 가능한 축."""
    red = desc.get("reduction_potential_gibbs_v")
    basis = "ΔG 기반"
    if red is None:
        red = desc.get("reduction_potential_v")
        basis = "단열/수직"
    if red is None:
        return None

    worst = min(a["potential_v"] for a in ANODE_POTENTIALS)   # 가장 가혹한 조건
    margin = worst - red          # 양수면 음극 전위보다 낮아 환원되지 않음
    if margin >= 0.5:
        verdict, why = VERDICT_OK, "가장 가혹한 음극 전위보다 0.5 V 이상 낮아 여유 있음"
    elif margin >= 0:
        verdict, why = VERDICT_MID, "음극 전위보다 낮지만 여유가 0.5 V 미만"
    else:
        verdict, why = VERDICT_NO, "음극 전위에서 환원 분해될 수 있음"
    return {
        "axis": "환원 안정성", "kind": "absolute", "verdict": verdict,
        "value": red, "unit": "V vs Li/Li+", "margin_v": round(margin, 3),
        "detail": f"환원 전위 {red:.3f} V ({basis}) · 기준 {worst:.2f} V — {why}",
        "per_anode": [
            {"label": a["label"], "potential_v": a["potential_v"],
             "stable": red < a["potential_v"]}
            for a in ANODE_POTENTIALS
        ],
    }


def _thermal_verdict(desc: dict) -> dict | None:
    """건식 공정 열안정성 — 최약 결합 해리에너지로 판정."""
    bde = desc.get("bde_min_298_kj")
    basis = "298 K"
    if bde is None:
        bde = desc.get("bde_min_kj")
        basis = "0 K 전자에너지"
    if bde is None:
        return None

    if bde >= 350:
        verdict, why = VERDICT_OK, "건식 공정 온도에서 결합 해리 여유 충분"
    elif bde >= 300:
        verdict, why = VERDICT_MID, "장시간 고온 전단에서 열화 가능"
    else:
        verdict, why = VERDICT_NO, "공정 중 사슬 절단 우려"
    bond = desc.get("bde_weakest_bond")
    return {
        "axis": "결합 강건성", "kind": "absolute", "verdict": verdict,
        "value": bde, "unit": "kJ/mol",
        "detail": f"최약 결합 {bond or '?'} BDE {bde:.0f} kJ/mol ({basis}) — {why} "
                  f"[공정 기준 {DRY_PROCESS['temperature_c']} °C]",
        # BDE 는 결합 강도 heuristic 이지 «그 온도에서 얼마나 버티는가»가 아니다.
        # 열분해는 활성화 장벽·연쇄 반응·산소·형태학·승온 속도에 좌우된다 (v2.0 5.4).
        "caveat": ("BDE 는 결합 강도 지표입니다 — 특정 온도에서의 사용 가능 시간을 "
                   "예측하지 않습니다. 열 안정성 판단은 TGA/DSC 실측을 근거로 하세요."),
        "hard_filter": False,
    }


# 상대 순위로만 의미가 있는 축 — (기술자 키, 표시명, 낮을수록 유리한가, 설명)
RELATIVE_AXES = [
    ("adhesion_anode_kj", "활물질 접착", True,
     "음극 활물질(흑연·Si) 표면 흡착 에너지 평균 — 더 음수일수록 강한 접착"),
    ("dimer_binding_kj", "사슬 간 응집", True,
     "이량체 결합 에너지 — 피브릴화·필름 형성에 필요하나 과하면 분산 불량"),
    ("solvation_energy_kcal", "전해액 분자 친화도", False,
     "올리고머 한 개의 용매화 에너지 — 덜 음수일수록 전해액과 덜 상호작용한다. "
     "«팽윤»이 아니다: 실제 팽윤은 자유부피·결정화도·가교·분자량·용매 흡수량이 "
     "함께 결정하며, 분자 하나의 용매화로는 예측되지 않는다 (v2.0 5.3)."),
    ("dipole_debye", "표면 극성", False,
     "쌍극자 모멘트 — 클수록 극성 표면·집전체와의 상호작용에 유리"),
]


def anode_adhesion(desc: dict) -> float | None:
    """음극 활물질(흑연·Si) 흡착 에너지 평균. 양극 모델은 제외한다."""
    ads = desc.get("surface_adsorption") or {}
    vals = [v["energy_kj"] for k, v in ads.items()
            if k in ("graphite", "si") and isinstance(v, dict) and "energy_kj" in v]
    return round(sum(vals) / len(vals), 1) if vals else None


def report(material: dict, descriptors: dict) -> dict:
    """한 물질에 대한 바인더 적합성 보고 — 게이트 + 절대 판정 + 상대 축 원값."""
    desc = dict(descriptors or {})
    adh = anode_adhesion(desc)
    if adh is not None:
        desc["adhesion_anode_kj"] = adh

    gate = pfas_check(material.get("smiles", ""))
    absolute = [v for v in (_reduction_verdict(desc), _thermal_verdict(desc)) if v]
    relative = [
        {"axis": label, "key": key, "value": desc[key], "lower_is_better": lower,
         "detail": detail}
        for key, label, lower, detail in RELATIVE_AXES if desc.get(key) is not None
    ]
    # 평가되지 않은 절대 축 — 통과로 오인하지 않도록 사유·해결책과 함께 남긴다.
    # 예: 에틸렌(C=C)처럼 주사슬 단일결합이 없는 모노머는 BDE 자체가 나오지 않는다.
    judged = {a["axis"] for a in absolute}
    unevaluated = [
        {"axis": axis, "reason": reason}
        for axis, reason in (
            ("환원 안정성",
             "환원 전위가 없습니다 — 목적을 «전자구조 + 산화/환원 전위» 이상으로 두고 "
             "기준 전극을 Li/Li+로 지정해 다시 계산하세요."),
            ("결합 강건성",
             "끊을 수 있는 주사슬 단일결합이 없어 BDE가 산출되지 않았습니다 — "
             "비닐 모노머는 구조를 «2량체» 이상으로 두면 주사슬 C–C가 생겨 계산됩니다."),
        ) if axis not in judged
    ]

    if gate["status"] == "pfas":
        overall = VERDICT_NO
        summary = "PFAS 해당 — PFAS-free 요건에서 탈락"
    elif any(a["verdict"] == VERDICT_NO for a in absolute):
        overall = VERDICT_NO
        failed = [a["axis"] for a in absolute if a["verdict"] == VERDICT_NO]
        summary = f"{' · '.join(failed)}에서 부적합"
    elif not absolute:
        overall = None
        summary = ("판정할 값이 없습니다 — 목적을 «건식 음극 바인더 스크리닝»으로 두고 "
                   "다시 계산하세요")
    else:
        # 실제로 판정한 축만 요약에 적는다. 미평가 축이 있으면 «일부»임을 밝힌다.
        passed = " · ".join(["PFAS-free"] + sorted(judged))
        if any(a["verdict"] == VERDICT_MID for a in absolute):
            overall = VERDICT_MID
            summary = f"{passed} 통과 — 다만 여유가 크지 않음"
        else:
            overall = VERDICT_OK
            summary = f"{passed} 통과"
        if unevaluated:
            overall = VERDICT_MID if overall == VERDICT_OK else overall
            summary += (f" · {' · '.join(u['axis'] for u in unevaluated)}은(는) "
                        "평가되지 않아 판정 보류")

    return {
        "pfas": gate, "overall": overall, "summary": summary,
        "absolute": absolute, "unevaluated": unevaluated, "relative": relative,
        "adhesion_anode_kj": adh,
        "notes": [
            "환원 안정성은 열역학 기준입니다 — 실제로는 SEI 형성이 보호막으로 작용할 수 있습니다.",
            "접착·응집 에너지는 대용 클러스터 모델 기반이라 절대값이 아닌 후보 간 상대 비교로만 쓰세요.",
            "집전체(Cu) 접착과 사슬 얽힘·결정화도는 분자 단위 DFT로 다루지 않습니다.",
        ],
    }


def rank(reports: list[dict]) -> dict:
    """여러 후보의 상대 축을 순위로 환산한다 (1위가 가장 유리)."""
    ranks: dict[str, list] = {}
    for key, label, lower, _detail in RELATIVE_AXES:
        rows = [(r["material"], r["report"]) for r in reports
                if any(x["key"] == key for x in r["report"]["relative"])]
        if len(rows) < 2:
            continue
        scored = [
            (name, next(x["value"] for x in rep["relative"] if x["key"] == key))
            for name, rep in rows
        ]
        scored.sort(key=lambda t: t[1], reverse=not lower)
        ranks[key] = {"axis": label, "lower_is_better": lower,
                      "order": [{"material": n, "value": v, "rank": i + 1}
                                for i, (n, v) in enumerate(scored)]}
    return ranks
