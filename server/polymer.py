"""고분자 자체 물성 예측 (Step 1) — 공정과 무관하게 물질이 보유한 성질.

설계 원칙은 «검증된 것만 계산값으로 낸다» 이다. 아래 세 종류를 명확히 구분한다.

  계산   물리적 근거가 있고 교차검증(LOO)으로 오차를 측정한 값
  문헌   실측이 표준인 물성 — 예측하지 않고 문헌값을 인용
  불가   현재 데이터로는 신뢰할 수 없어 값을 내지 않음

특히 유리전이온도 Tg 는 **예측하지 않는다**. 참조 고분자 20종으로 회귀를 세워
leave-one-out 검증한 결과 최선의 조합에서도 평균 절대오차 45 K, 최대 136 K 였다.
후보 간 Tg 차이가 대개 그보다 작아 순위가 뒤집히므로, 값을 내면 오히려 해롭다.
알려진 고분자는 문헌값을 쓰고, 미지 구조는 «예측 불가»로 남긴다.
"""

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, rdMolDescriptors

# ── van der Waals 부피 (Zhao·Abraham·Zissimos 2003, J. Org. Chem.) ──────
# Vw = Σ(원자 기여) − 5.92·결합수 − 14.7·방향족고리 − 3.8·비방향족고리  [Å³]
# 검증: 에탄·벤젠·메탄올·아세톤·톨루엔 문헌값 대비 오차 ±5 % 이내
_ATOM_VW = {"H": 7.24, "C": 20.58, "N": 15.60, "O": 14.71, "F": 13.31,
            "Cl": 22.45, "Br": 26.52, "I": 32.52, "P": 24.43, "S": 24.43,
            "Si": 38.79}
_A3_TO_CM3_MOL = 0.6023

# 회귀 계수 — 참조 고분자 20종으로 적합. 상수항이 앞에 온다.
# 밀도  ρ = f(vw_per_mw, logp_per_vw, halogen)   LOO MAE 0.050 g/cm³ (최대 0.189)
_RHO_COEF = (1.756468, -0.799654, -5.706789, 1.269616)
# 용해도 δ = f(tpsa_per_vw, ring)                LOO MAE 1.43 MPa^0.5 (최대 4.03)
_DELTA_COEF = (16.271496, 9.834685, 17.272336)

RELIABILITY = {
    "vdw_volume": ("계산", "±5 % (소분자 문헌 대조)"),
    "molar_volume": ("계산", "밀도와 동일 근거"),
    "density": ("계산", "LOO 평균절대오차 0.05 g/cm³"),
    "solubility_parameter": ("계산", "LOO 평균절대오차 1.43 MPa^0.5"),
    "ced": ("계산", "δ²에서 유도 — δ와 동일 근거"),
    "ced_dft": ("계산", "이량체 결합 에너지 기반 — 순위만 유효"),
    "rotatable_density": ("구조", "구조에서 직접 셈 — 오차 없음"),
    "glass_transition_c": ("문헌", "예측하지 않음 — 문헌값 인용"),
}


def _mol(smiles):
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        raise ValueError(f"SMILES를 해석할 수 없습니다: {smiles}")
    return m


def vdw_volume(smiles: str) -> float:
    """반복 단위의 van der Waals 부피 (cm³/mol)."""
    mh = Chem.AddHs(_mol(smiles))
    total = sum(_ATOM_VW.get(a.GetSymbol(), 0.0) for a in mh.GetAtoms())
    ring = mh.GetRingInfo()
    aromatic = sum(1 for r in ring.AtomRings()
                   if all(mh.GetAtomWithIdx(i).GetIsAromatic() for i in r))
    non_aromatic = ring.NumRings() - aromatic
    a3 = total - 5.92 * mh.GetNumBonds() - 14.7 * aromatic - 3.8 * non_aromatic
    return round(a3 * _A3_TO_CM3_MOL, 2)


def _features(smiles):
    m = _mol(smiles)
    mw = Descriptors.MolWt(m)
    vw = vdw_volume(smiles)
    heavy = max(m.GetNumHeavyAtoms(), 1)
    return {
        "mw": mw, "vw": vw, "heavy": heavy,
        "vw_per_mw": vw / mw,
        "logp_per_vw": Crippen.MolLogP(m) / vw,
        "tpsa_per_vw": Descriptors.TPSA(m) / vw,
        "ring": rdMolDescriptors.CalcNumRings(m) / heavy,
        "halogen": sum(1 for a in m.GetAtoms()
                       if a.GetSymbol() in ("F", "Cl", "Br", "I")) / heavy,
        "rot": rdMolDescriptors.CalcNumRotatableBonds(m),
    }


def predict(smiles: str) -> dict:
    """구조만으로 즉시 산출되는 물성 (DFT 불필요) — Step 1의 L1 계층."""
    f = _features(smiles)
    c = _RHO_COEF
    density = c[0] + c[1] * f["vw_per_mw"] + c[2] * f["logp_per_vw"] + c[3] * f["halogen"]
    d = _DELTA_COEF
    delta = d[0] + d[1] * f["tpsa_per_vw"] + d[2] * f["ring"]
    density = max(density, 0.5)          # 물리적으로 불가능한 외삽 방지
    delta = max(delta, 5.0)
    molar_volume = f["mw"] / density

    # δ 회귀는 극성(TPSA)과 고리 항만 쓴다. 둘 다 0인 비극성·비고리 고분자는
    # 전부 절편값(~16.3)으로 수렴해 서로 구분되지 않는다. 참조 20종에 불소계가
    # PTFE·PVDF 둘뿐이라 할로겐 항을 넣으면 LOO 오차가 오히려 커져(1.43→1.69)
    # 넣지 않았다. 해당 구조에서는 δ를 순위 근거로 쓰지 말아야 한다.
    warnings = []
    if f["tpsa_per_vw"] == 0 and f["ring"] == 0:
        warnings.append(
            "극성기·고리가 없어 δ가 절편값으로 고정됩니다 — 이 구조군(PE·PP·PTFE 등)"
            "끼리는 δ로 구분할 수 없습니다. 문헌값이나 DFT 경로(CED)를 쓰세요.")

    return {
        "repeat_unit_mw": round(f["mw"], 2),
        "vdw_volume_cm3": f["vw"],
        "molar_volume_cm3": round(molar_volume, 1),
        "density_g_cm3": round(density, 3),
        "solubility_parameter_mpa05": round(delta, 1),
        "ced_j_cm3": round(delta ** 2, 0),
        "rotatable_bonds": f["rot"],
        "rotatable_density": round(f["rot"] / f["heavy"], 3),
        "packing_fraction": round(f["vw"] / molar_volume, 3),
        "warnings": warnings,
    }


def ced_from_dft(dimer_binding_kj: float, molar_volume_cm3: float) -> float | None:
    """이량체 결합 에너지(DFT)로 구한 응집 에너지 밀도 (J/cm³).

    구조 회귀와 독립된 경로이므로, 두 값을 대조하면 예측을 교차 검증할 수 있다.
    """
    if dimer_binding_kj is None or not molar_volume_cm3:
        return None
    # 결합 에너지는 음수 — 응집 에너지는 그 크기
    return round(abs(dimer_binding_kj) * 1000.0 / molar_volume_cm3, 0)


# ── 유리전이온도 — 문헌값 ─────────────────────────────────────────────
# 예측하지 않는 이유는 모듈 설명 참조. 값은 비정질 상태 기준.
# uncertain=True 는 문헌 자체가 크게 흩어지는 항목 (다당류·폴리이미드 등).
GLASS_TRANSITION = {
    "C=C":                  {"tg_c": -120, "name": "폴리에틸렌"},
    "C=CC":                 {"tg_c": -10, "name": "폴리프로필렌"},
    "C=CC(=O)O":            {"tg_c": 106, "name": "폴리아크릴산"},
    "C=CC#N":               {"tg_c": 85, "name": "폴리아크릴로나이트릴"},
    "C=CO":                 {"tg_c": 85, "name": "폴리비닐알코올"},
    "C=COC(C)=O":           {"tg_c": 32, "name": "폴리비닐아세테이트"},
    "C=CC(=O)OC":           {"tg_c": 10, "name": "폴리메틸아크릴레이트"},
    "C=Cc1ccccc1":          {"tg_c": 100, "name": "폴리스타이렌"},
    "C=CC=C":               {"tg_c": -90, "name": "폴리부타디엔"},
    "COCCOCCOC":            {"tg_c": -67, "name": "폴리에틸렌옥사이드"},
    "C=C(F)F":              {"tg_c": -40, "name": "PVDF"},
    "FC(F)=C(F)F":          {"tg_c": -73, "name": "PTFE",
                             "uncertain": True,
                             "note": "문헌상 −73 °C 와 약 130 °C 두 전이가 보고됨"},
    "OCC1OC(O)C(OCC(=O)O)C(O)C1O": {
        "tg_c": 140, "name": "카복시메틸셀룰로스", "uncertain": True,
        "note": "다당류는 Tg 이전에 분해가 시작되어 값이 크게 흩어짐 (치환도 의존)"},
    "OC1OC(C(=O)O)C(O)C(O)C1O": {
        "tg_c": 150, "name": "알긴산", "uncertain": True,
        "note": "분해와 겹쳐 보고값 편차가 큼"},
    "NC1C(O)OC(CO)C(O)C1O": {
        "tg_c": 160, "name": "키토산", "uncertain": True,
        "note": "탈아세틸화도·수분 함량에 따라 크게 변동"},
    "O=C1N(C)C(=O)c2ccccc21": {
        "tg_c": 360, "name": "폴리이미드", "uncertain": True,
        "note": "구조에 따라 250~400 °C — 이 값은 방향족 폴리이미드 대표값"},
}


def glass_transition(smiles: str) -> dict:
    """Tg — 문헌값이 있으면 인용, 없으면 «예측 불가»."""
    canon = None
    try:
        canon = Chem.MolToSmiles(_mol(smiles))
    except ValueError:
        pass
    for key, entry in GLASS_TRANSITION.items():
        if canon and Chem.MolToSmiles(Chem.MolFromSmiles(key)) == canon:
            return {"available": True, "source": "문헌", **entry}
    return {
        "available": False, "source": None, "tg_c": None,
        "note": ("이 구조의 Tg 문헌값이 등록되어 있지 않습니다. "
                 "구조 기반 예측은 검증 결과 평균 오차 45 K로 신뢰할 수 없어 "
                 "값을 내지 않습니다 — 실측하거나 문헌값을 등록하세요."),
    }


def property_card(material: dict, descriptors: dict | None = None) -> dict:
    """Step 1 산출물 — 후보 1종의 물성 카드."""
    smiles = material.get("smiles", "")
    card = {"name": material.get("name"), "smiles": smiles,
            "computed": None, "glass_transition": None,
            "dft": {}, "reliability": RELIABILITY, "errors": []}
    try:
        card["computed"] = predict(smiles)
    except ValueError as exc:
        card["errors"].append(str(exc))
        return card

    card["glass_transition"] = glass_transition(smiles)

    d = descriptors or {}
    mv = card["computed"]["molar_volume_cm3"]
    ced_dft = ced_from_dft(d.get("dimer_binding_kj"), mv)
    if ced_dft is not None:
        card["dft"]["ced_j_cm3"] = ced_dft
        card["dft"]["solubility_parameter_mpa05"] = round(ced_dft ** 0.5, 1)
        # 구조 회귀와 DFT 경로의 일치도 — 크게 벌어지면 둘 중 하나를 의심해야 한다
        card["dft"]["delta_vs_structure"] = round(
            card["dft"]["solubility_parameter_mpa05"]
            - card["computed"]["solubility_parameter_mpa05"], 1)
    for key in ("bde_min_298_kj", "bde_min_kj", "reduction_potential_v",
                "dimer_binding_kj"):
        if d.get(key) is not None:
            card["dft"][key] = d[key]
    return card
