"""기계적 물성 (Step 2) — 탄성 관계식 · 문헌 조회 · 사용 온도 상태 판정.

**탄성 상수를 구조에서 예측하지 않는다.** 유리질 참조 10종으로 Rao/Hartmann
몰함수와 E·ν 를 중첩 교차검증한 결과 네 목표 모두 「평균값 찍기」보다 나빴다.

    E     중첩 CV 0.564 GPa   vs 평균찍기 0.396   (42 % 나쁨)
    ν     0.0244              vs 0.0189
    U_R   1259                vs 906
    U_H   947                 vs 679

이유는 데이터 부족만이 아니다. 유리질 고분자의 E 는 2.3~3.5 GPa (평균 2.97,
표준편차 0.41) 로 폭이 좁다. **유리질이기만 하면 모듈러스는 다 비슷하다.**
그래서 후보를 가르는 것은 모듈러스 값이 아니라 «사용 온도에서 유리질인가»다.
이 모듈의 중심이 state_at() 인 이유다.

싣는 것은 셋이다.
  1. 탄성 관계식 — 적합이 아니라 정확한 물리. 둘을 주면 나머지가 나온다
  2. 문헌 E·ν — 알려진 고분자는 인용, 미지 구조는 «예측 불가»
  3. 사용 온도 상태 판정 — 유리질 / 전이 구간 / 고무질, Tg 불확실성 전파
"""

import math

from . import polymer

R_GAS = 8.31446261815324          # J/(mol·K)

# 전이는 계단이 아니다. 모듈러스가 떨어지는 구간이 20 K 안팎으로 퍼져 있어
# 이 폭 안에서는 단일 모듈러스를 말할 수 없다.
TRANSITION_HALFWIDTH_K = 20.0
# 문헌 Tg 자체의 불확실성 — uncertain 표시가 붙은 값은 훨씬 넓다
TG_UNCERTAINTY_K = 10.0
TG_UNCERTAINTY_UNCERTAIN_K = 40.0

# 반결정성 고분자의 융점 Tm [°C]. **Tg 위/아래만으로는 상태를 다 말할 수 없다** —
# 반결정성이면 Tg 를 넘어도 결정이 하중을 받아 Tm 까지 강성이 유지된다.
# PTFE 가 180 °C 건식 공정에서 형태를 유지하는 이유가 이것이다 (Tm 327 °C).
# 값이 None 이면 「녹기 전에 분해」를 뜻한다.
# semicrystalline=False 는 「비정질이라 융점 자체가 없음」, tm_c=None 은
# 「녹기 전에 분해」를 뜻한다. 둘은 다른 상태이므로 섞지 않는다.
MELTING = {
    "C=C": {"tm_c": 135, "semicrystalline": True, "name": "폴리에틸렌 (HDPE)"},
    "C=CC": {"tm_c": 165, "semicrystalline": True, "name": "폴리프로필렌 (아이소택틱)"},
    "FC(F)=C(F)F": {"tm_c": 327, "semicrystalline": True, "name": "PTFE"},
    "C=C(F)F": {"tm_c": 177, "semicrystalline": True, "name": "PVDF"},
    "COCCOCCOC": {"tm_c": 65, "semicrystalline": True, "name": "폴리에틸렌옥사이드"},
    "C=CO": {"tm_c": 230, "semicrystalline": True, "name": "폴리비닐알코올",
             "decomp_c": 240, "note": "융해와 분해가 겹쳐 가공 창이 좁다"},
    "C=CC#N": {"tm_c": None, "semicrystalline": True, "decomp_c": 250,
               "name": "폴리아크릴로나이트릴",
               "note": "250~300 °C 에서 고리화·분해가 먼저 일어난다"},
    "C=CC(=O)O": {"tm_c": None, "semicrystalline": False, "decomp_c": 200,
                  "name": "폴리아크릴산",
                  "note": "비정질이라 융점이 없다 — 200 °C 부근에서 무수물화·분해"},
}

# 상온 유리질 비정질 상태의 문헌 E [GPa] · 푸아송비 ν.
# 흡습성(PVA·PAA·PVP)과 반결정성+수분 민감(PA6·PA66)은 「유리질 비정질」값이
# 아니라 넣지 않았다 — 수분·결정화도에 따라 크게 변해 구조의 함수가 아니다.
ELASTIC_LITERATURE = {
    "PS":   {"name": "폴리스타이렌", "smiles": "*CC(c1ccccc1)*",
             "e_gpa": 3.2, "poisson": 0.33, "confidence": "high"},
    "PMMA": {"name": "폴리메틸메타크릴레이트", "smiles": "*CC(C)(C(=O)OC)*",
             "e_gpa": 3.0, "poisson": 0.37, "confidence": "high"},
    "PC":   {"name": "폴리카보네이트",
             "smiles": "*Oc1ccc(cc1)C(C)(C)c1ccc(cc1)OC(=O)*",
             "e_gpa": 2.3, "poisson": 0.38, "confidence": "high"},
    "PVC":  {"name": "폴리염화비닐 (경질)", "smiles": "*CC(Cl)*",
             "e_gpa": 3.0, "poisson": 0.38, "confidence": "high"},
    "PET":  {"name": "폴리에틸렌테레프탈레이트 (비정질)",
             "smiles": "*OCCOC(=O)c1ccc(cc1)C(=O)*",
             "e_gpa": 2.8, "poisson": 0.40, "confidence": "medium"},
    "PSU":  {"name": "폴리설폰",
             "smiles": "*Oc1ccc(cc1)C(C)(C)c1ccc(cc1)Oc1ccc(cc1)S(=O)(=O)c1ccc(cc1)*",
             "e_gpa": 2.5, "poisson": 0.37, "confidence": "medium"},
    "PPE":  {"name": "폴리페닐렌옥사이드", "smiles": "*Oc1c(C)cc(*)cc1C",
             "e_gpa": 2.5, "poisson": 0.35, "confidence": "medium"},
    "PLA":  {"name": "폴리락트산", "smiles": "*OC(C)C(=O)*",
             "e_gpa": 3.5, "poisson": 0.36, "confidence": "medium"},
    "PMS":  {"name": "폴리-α-메틸스타이렌", "smiles": "*CC(C)(c1ccccc1)*",
             "e_gpa": 3.4, "poisson": 0.34, "confidence": "medium"},
    "PAN":  {"name": "폴리아크릴로나이트릴", "smiles": "*CC(C#N)*",
             "e_gpa": 3.5, "poisson": 0.35, "confidence": "medium"},
}

# 예측을 싣지 않은 근거 — 화면과 보고서에서 그대로 인용한다
REFUSAL = {
    "targets": [
        {"key": "E", "unit": "GPa", "nested_cv": 0.564, "mean_baseline": 0.396},
        {"key": "ν", "unit": "", "nested_cv": 0.0244, "mean_baseline": 0.0189},
        {"key": "U_R (Rao)", "unit": "", "nested_cv": 1259.0, "mean_baseline": 906.0},
        {"key": "U_H (Hartmann)", "unit": "", "nested_cv": 947.0, "mean_baseline": 679.0},
    ],
    "n_reference": len(ELASTIC_LITERATURE),
    "note": ("유리질 참조 10종으로 중첩 교차검증한 결과 네 목표 모두 «평균값 찍기»보다 "
             "나빴습니다. 유리질 고분자의 E 는 2.3~3.5 GPa (표준편차 0.41) 로 폭이 좁아, "
             "구조로 그 안을 가르려면 지금보다 훨씬 많은 데이터가 필요합니다. "
             "후보를 가르는 것은 모듈러스 값이 아니라 «사용 온도에서 유리질인가» 입니다."),
}


# ── 1. 탄성 관계식 — 적합이 아니라 정확한 물리 ─────────────────────────

def elastic_constants(e_gpa: float = None, poisson: float = None,
                      bulk_gpa: float = None, shear_gpa: float = None,
                      density_g_cm3: float = None) -> dict:
    """등방 탄성체의 상수 환산. (E, ν) 또는 (K, G) 중 한 쌍을 준다.

    밀도를 함께 주면 음속까지 낸다 — van Krevelen 의 Rao/Hartmann 몰함수가
    쓰는 양이다.
    """
    if e_gpa is not None and poisson is not None:
        if not -1.0 < poisson < 0.5:
            raise ValueError(f"푸아송비는 −1 < ν < 0.5 여야 합니다: {poisson}")
        E, nu = float(e_gpa), float(poisson)
        G = E / (2 * (1 + nu))
        K = E / (3 * (1 - 2 * nu))
    elif bulk_gpa is not None and shear_gpa is not None:
        K, G = float(bulk_gpa), float(shear_gpa)
        if K <= 0 or G <= 0:
            raise ValueError("K·G 는 양수여야 합니다.")
        E = 9 * K * G / (3 * K + G)
        nu = (3 * K - 2 * G) / (2 * (3 * K + G))
    else:
        raise ValueError("(E, ν) 또는 (K, G) 중 한 쌍을 주어야 합니다.")

    out = {"e_gpa": round(E, 3), "poisson": round(nu, 4),
           "bulk_gpa": round(K, 3), "shear_gpa": round(G, 3),
           "longitudinal_gpa": round(K + 4 * G / 3, 3)}
    if density_g_cm3:
        rho = float(density_g_cm3) * 1000.0                  # kg/m³
        out["shear_wave_m_s"] = round(math.sqrt(G * 1e9 / rho), 1)
        out["longitudinal_wave_m_s"] = round(
            math.sqrt((K + 4 * G / 3) * 1e9 / rho), 1)
    return out


def rubbery_modulus(density_g_cm3: float, temperature_k: float,
                    entanglement_mw: float) -> dict:
    """고무질(T > Tg) 탄성률 — 고무 탄성 이론 E = 3ρRT/Me.

    Me(엉킴 분자량)는 구조에서 예측되지 않는다. 실측하거나 문헌에서 받아야
    한다 — 그래서 인자로 받는다. PE 의 Me 는 약 1,000~1,300 g/mol 이다.
    """
    if entanglement_mw <= 0:
        raise ValueError("엉킴 분자량 Me 는 양수여야 합니다.")
    rho = float(density_g_cm3) * 1e6                          # g/m³
    g_pa = rho * R_GAS * float(temperature_k) / float(entanglement_mw)
    e_pa = 3 * g_pa
    return {
        "shear_mpa": round(g_pa / 1e6, 3),
        "e_mpa": round(e_pa / 1e6, 3),
        "e_gpa": round(e_pa / 1e9, 5),
        "basis": "고무 탄성 이론 E = 3ρRT/Me — 엉킴이 형성된 고분자량 전제",
    }


# ── 2. 문헌 조회 ────────────────────────────────────────────────────

def literature_elastic(smiles: str) -> dict:
    """구조에 해당하는 문헌 E·ν — 없으면 «예측 불가»."""
    try:
        unit = polymer.repeat_unit(smiles)["smiles"]
        from rdkit import Chem
        canon = Chem.MolToSmiles(Chem.MolFromSmiles(unit))
        for key, entry in ELASTIC_LITERATURE.items():
            ref = Chem.MolFromSmiles(entry["smiles"])
            if ref is not None and Chem.MolToSmiles(ref) == canon:
                return {"available": True, "source": "문헌", "key": key, **entry}
    except (polymer.RepeatUnitError, ValueError):
        pass
    return {"available": False, "source": None, "e_gpa": None, "poisson": None,
            "note": ("이 구조의 탄성 상수 문헌값이 등록되어 있지 않습니다. "
                     "구조 기반 예측은 검증 결과 평균값을 찍는 것보다 나빠 "
                     "값을 내지 않습니다 — 실측하거나 문헌값을 등록하세요.")}


# ── 3. 사용 온도 상태 판정 — Step 2 의 핵심 산출 ──────────────────────

def melting(smiles: str) -> dict:
    """반결정성 여부와 융점 — 등록된 구조만. Tg 판정을 보정하는 데 쓴다."""
    from rdkit import Chem
    try:
        canon = Chem.MolToSmiles(Chem.MolFromSmiles(smiles))
    except (ValueError, TypeError):
        return {"known": False}
    for key, entry in MELTING.items():
        ref = Chem.MolFromSmiles(key)
        if ref is not None and Chem.MolToSmiles(ref) == canon:
            return {"known": True, **entry}
    return {"known": False}


def state_at(smiles: str, temperature_c: float) -> dict:
    """사용 온도에서의 역학 상태 — Tg 불확실성과 결정성을 함께 본다.

    모듈러스는 Tg 를 지나며 1000 배 달라진다. 그래서 «Tg 가 얼마인가»보다
    «사용 온도가 Tg 의 어느 쪽인가»가 먼저다. 불확실성 안에 걸치면 단일
    상태를 주장하지 않고 보류한다.

    다만 Tg 만으로는 부족하다. 반결정성 고분자는 Tg 를 넘어도 결정이 하중을
    받아 Tm 까지 강성이 남는다 — 「고무질」이라 부르면 틀린다.
    """
    tg = polymer.glass_transition(smiles)
    melt = melting(smiles)
    out = {"temperature_c": temperature_c, "glass_transition": tg, "melting": melt}
    if not tg.get("available"):
        out.update({"state": "불가", "confident": False,
                    "note": ("Tg 를 모르면 사용 온도에서의 상태를 판정할 수 없습니다. "
                             "Tg 는 예측하지 않으므로(중첩 CV 61.6 K) 문헌값을 "
                             "등록하거나 실측해야 합니다.")})
        return out

    tg_c = float(tg["tg_c"])
    unc = TG_UNCERTAINTY_UNCERTAIN_K if tg.get("uncertain") else TG_UNCERTAINTY_K
    band = TRANSITION_HALFWIDTH_K + unc
    margin = temperature_c - tg_c
    out.update({"tg_c": tg_c, "margin_k": round(margin, 1),
                "band_k": round(band, 1), "tg_uncertainty_k": unc})

    if margin < -band:
        out.update({"state": "유리질", "confident": True,
                    "note": (f"사용 온도가 Tg 보다 {abs(margin):.0f} K 낮습니다 "
                             f"(판정 폭 ±{band:.0f} K) — 단단한 유리질입니다. "
                             "이 영역의 E 는 대부분 2.3~3.5 GPa 로 좁아, "
                             "모듈러스로 후보를 가르기는 어렵습니다.")})
    elif margin > band:
        # Tg 위여도 반결정성이면 결정이 하중을 받는다 — 상태를 나눠야 한다
        decomp = melt.get("decomp_c")
        if melt.get("known") and not melt.get("semicrystalline"):
            # 비정질인데 융점이 없는 경우 — 고무질이되 분해 상한이 따로 있다
            over = decomp is not None and temperature_c >= decomp
            out.update({"state": "분해" if over else "고무질", "confident": True,
                        "decomp_c": decomp,
                        "note": (f"{melt.get('note', '비정질이라 융점이 없습니다')}. "
                                 + (f"사용 온도가 분해 온도 {decomp} °C 이상이라 "
                                    "물성을 논할 수 없습니다."
                                    if over else
                                    f"Tg 보다 {margin:.0f} K 높아 고무질이며, "
                                    f"공정 상한은 융점이 아니라 분해 온도 "
                                    f"{decomp} °C 입니다."))})
        elif melt.get("known"):
            tm = melt.get("tm_c")
            if tm is None:
                out.update({"state": "반결정 (융해 없음)", "confident": True,
                            "decomp_c": decomp,
                            "note": (f"Tg 보다 {margin:.0f} K 높지만 이 고분자는 녹지 "
                                     f"않습니다 — {melt.get('note', '')}. 고무질로 "
                                     "보면 안 되고, 분해 온도"
                                     + (f" {decomp} °C" if decomp else "")
                                     + "를 공정 상한으로 잡아야 합니다.")})
            elif temperature_c < tm - 10:
                out.update({"state": "반결정 (고무질 비정질 + 결정)", "confident": True,
                            "tm_c": tm,
                            "note": (f"Tg 보다 {margin:.0f} K 높지만 융점 {tm} °C 아래라 "
                                     "결정이 남아 하중을 받습니다. 강성은 고무질 값이 "
                                     "아니라 결정화도에 좌우되며, 결정화도는 구조가 "
                                     "아니라 가공 이력의 함수라 예측하지 않습니다.")})
            else:
                out.update({"state": "용융", "confident": True, "tm_c": tm,
                            "note": (f"융점 {tm} °C 이상입니다 — 녹아 흐르는 상태라 "
                                     "탄성률을 말할 수 없습니다. 점도가 지배합니다.")})
        else:
            out.update({"state": "고무질", "confident": True,
                        "note": (f"사용 온도가 Tg 보다 {margin:.0f} K 높습니다 "
                                 f"(판정 폭 ±{band:.0f} K) — 비정질 고무질입니다. "
                                 "E 는 유리질보다 약 1000 배 낮고 엉킴 분자량 Me 에 "
                                 "좌우됩니다. rubbery_modulus() 에 Me 를 주세요. "
                                 "※ 반결정성 여부가 등록되지 않은 구조입니다 — "
                                 "결정성이 있으면 이 판정은 틀립니다.")})
    else:
        out.update({"state": "전이 구간", "confident": False,
                    "note": (f"사용 온도가 Tg({tg_c:.0f} °C) 에서 {margin:+.0f} K 로, "
                             f"판정 폭 ±{band:.0f} K 안에 들어옵니다 — 유리질인지 "
                             "고무질인지 확정할 수 없어 모듈러스를 내지 않습니다. "
                             "(전이 폭 20 K + Tg 불확실성 "
                             f"{unc:.0f} K). 실측 DMA 로 확인하세요.")})
    return out


def report(smiles: str, temperature_c: float, entanglement_mw: float = None,
           name: str = None) -> dict:
    """Step 2 산출물 — 후보 1종의 기계적 물성 카드."""
    card = {"name": name, "smiles": smiles, "temperature_c": temperature_c,
            "refusal": REFUSAL, "errors": []}
    card["state"] = state_at(smiles, temperature_c)
    lit = literature_elastic(smiles)
    card["literature"] = lit

    if lit.get("available"):
        try:
            rho = polymer.predict(smiles)["density_g_cm3"]
        except (polymer.RepeatUnitError, ValueError):
            rho = None
        card["derived"] = elastic_constants(
            e_gpa=lit["e_gpa"], poisson=lit["poisson"], density_g_cm3=rho)
        card["derived"]["density_g_cm3"] = rho
        card["derived"]["valid_state"] = "유리질"
        if card["state"].get("state") != "유리질":
            card["errors"].append(
                f"문헌 E·ν 는 상온 유리질 값입니다 — 판정된 상태가 "
                f"«{card['state'].get('state')}» 라 이 온도에는 적용되지 않습니다.")
    else:
        card["derived"] = None

    if entanglement_mw and card["state"].get("state") == "고무질":
        try:
            rho = polymer.predict(smiles)["density_g_cm3"]
            card["rubbery"] = rubbery_modulus(
                rho, temperature_c + 273.15, entanglement_mw)
        except (polymer.RepeatUnitError, ValueError) as exc:
            card["errors"].append(str(exc))
    return card
