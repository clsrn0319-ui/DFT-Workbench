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

# 회귀 계수 — 참조 고분자 20종을 «반복 단위(더미 원자 표현)» 기준으로 적합.
# 상수항이 앞에 온다.
# 밀도  ρ = f(vw_per_mw, logp_per_vw, halogen)   LOO MAE 0.049 g/cm³ (최대 0.205)
_RHO_COEF = (1.678859, -0.730943, -6.03356, 1.297632)
# 용해도 δ = f(tpsa_per_vw, ring)                LOO MAE 1.37 MPa^0.5 (최대 4.04)
_DELTA_COEF = (16.297126, 9.579774, 17.055988)

RELIABILITY = {
    "vdw_volume": ("계산", "반복 단위 기준 — PE 20.8 vs 문헌 20.5 cm³/mol"),
    "molar_volume": ("계산", "밀도와 동일 근거"),
    "density": ("계산", "LOO 평균절대오차 0.05 g/cm³"),
    "solubility_parameter": ("계산", "LOO 평균절대오차 1.38 MPa^0.5"),
    "ced": ("계산", "δ²에서 유도 — δ와 동일 근거"),
    "ced_dft": ("계산", "이량체 결합 에너지 기반 — 순위만 유효"),
    "rotatable_density": ("구조", "구조에서 직접 셈 — 오차 없음"),
    "glass_transition_c": ("문헌", "예측하지 않음 — 문헌값 인용"),
}


class RepeatUnitError(ValueError):
    """반복 단위를 확정할 수 없어 물성을 낼 수 없는 경우."""


# 자동 규칙(C=C 포화)으로는 얻을 수 없는 반복 단위 — 명시 등록.
# 값은 더미 원자 * 로 «이웃 단위와 붙는 자리»를 표시한 반복 단위 SMILES 이다.
# 이 표시가 없으면 PVA(-CH2CH(OH)-)와 PEO(-CH2CH2O-)가 둘 다 에탄올로
# 축약되어 구분되지 않는다 — 수산기인지 에터인지가 사라지기 때문이다.
REPEAT_UNITS = {
    "C=CC=C": ("*CC=CC*", "1,4-부가 중합 — 주사슬에 이중결합이 남는다"),
    "COCCOCCOC": ("*CCO*", "폴리에틸렌옥사이드 반복 단위 -CH2CH2O-"),
}


def _mol(smiles):
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        raise ValueError(f"SMILES를 해석할 수 없습니다: {smiles}")
    return m


def repeat_unit(smiles: str) -> dict:
    """모노머 → «반복 단위» (더미 원자 * 로 이웃과 붙는 자리를 표시).

    그룹 기여법은 사슬 안의 반복 단위에 대해 정의된다. 비닐 모노머를 그대로
    넣으면 C=C가 남아 결합 수가 달라지고 Vw 가 10~25 % 부풀려진다 — 사슬 길이
    수렴에서 «n=1은 다른 화학종»이라 판정한 것과 같은 이유다.

    확정할 수 없으면 조용히 근사하지 않고 RepeatUnitError 를 낸다. 그룹 기여법의
    특징적 실패는 틀린 값이 아니라 «학습 범위 밖에서 그럴듯한 값»이기 때문이다.
    """
    canon = Chem.MolToSmiles(_mol(smiles))
    for key, (unit, note) in REPEAT_UNITS.items():
        if Chem.MolToSmiles(_mol(key)) == canon:
            return {"smiles": unit, "source": "등록", "note": note}

    m = _mol(smiles)
    for bond in m.GetBonds():
        if (bond.GetBondType() == Chem.BondType.DOUBLE and not bond.GetIsAromatic()
                and not bond.IsInRing()
                and bond.GetBeginAtom().GetSymbol() == "C"
                and bond.GetEndAtom().GetSymbol() == "C"):
            rw = Chem.RWMol(m)
            a, b = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
            rw.GetBondBetweenAtoms(a, b).SetBondType(Chem.BondType.SINGLE)
            for idx in (a, b):              # 이중결합이 열린 자리가 이웃과 붙는다
                d = rw.AddAtom(Chem.Atom(0))
                rw.AddBond(idx, d, Chem.BondType.SINGLE)
            out = rw.GetMol()
            Chem.SanitizeMol(out)
            return {"smiles": Chem.MolToSmiles(out), "source": "비닐 자동",
                    "note": "C=C를 포화시키고 그 자리를 결합 지점으로 잡았습니다."}

    raise RepeatUnitError(
        f"반복 단위를 확정할 수 없습니다: {smiles} — 중합 가능한 C=C가 없고 "
        "등록된 반복 단위도 없습니다. 축합 중합체·다당류는 반복 단위가 모노머에서 "
        "물 등이 빠진 형태라 구조마다 다릅니다. REPEAT_UNITS 에 등록하세요.")


def molecule_vdw_volume(smiles: str) -> float:
    """«독립 분자» 하나의 van der Waals 부피 (cm³/mol) — Zhao 법 원형."""
    mh = Chem.AddHs(_mol(smiles))
    total = sum(_ATOM_VW.get(a.GetSymbol(), 0.0) for a in mh.GetAtoms())
    ring = mh.GetRingInfo()
    aromatic = sum(1 for r in ring.AtomRings()
                   if all(mh.GetAtomWithIdx(i).GetIsAromatic() for i in r))
    non_aromatic = ring.NumRings() - aromatic
    a3 = total - 5.92 * mh.GetNumBonds() - 14.7 * aromatic - 3.8 * non_aromatic
    return round(a3 * _A3_TO_CM3_MOL, 2)


def vdw_volume(smiles: str) -> float:
    """«사슬 안 반복 단위»의 van der Waals 부피 (cm³/mol). 인자는 모노머 SMILES.

    독립 분자 부피가 필요하면 molecule_vdw_volume() 을 쓴다 — 둘은 다른 값이다
    (에틸렌 24.4 vs PE 반복 단위 20.8).
    """
    return _vw_unit(repeat_unit(smiles)["smiles"])


def _vw_unit(unit: str) -> float:
    """더미 표현 반복 단위 → 사슬 안 반복 단위의 Vw.

    더미는 원자에서 빼고, 더미 결합도 결합 수에서 뺀 뒤 이웃 단위와의 결합
    1개를 더한다. 무한 사슬에서 단위 간 결합 수는 단위 수와 같으므로
    반복 단위당 정확히 1개다.
    """
    mh = Chem.AddHs(_mol(unit))
    total = sum(_ATOM_VW.get(a.GetSymbol(), 0.0)
                for a in mh.GetAtoms() if a.GetAtomicNum() > 0)
    n_dummy_bonds = sum(1 for b in mh.GetBonds()
                        if b.GetBeginAtom().GetAtomicNum() == 0
                        or b.GetEndAtom().GetAtomicNum() == 0)
    ring = mh.GetRingInfo()
    aromatic = sum(1 for r in ring.AtomRings()
                   if all(mh.GetAtomWithIdx(i).GetIsAromatic() for i in r))
    non_aromatic = ring.NumRings() - aromatic
    a3 = (total - 5.92 * (mh.GetNumBonds() - n_dummy_bonds + 1)
          - 14.7 * aromatic - 3.8 * non_aromatic)
    return round(a3 * _A3_TO_CM3_MOL, 2)


def _features(smiles):
    unit = repeat_unit(smiles)
    m = _mol(unit["smiles"])
    mh = Chem.AddHs(m)
    mw = sum(a.GetMass() for a in mh.GetAtoms() if a.GetAtomicNum() > 0)
    vw = _vw_unit(unit["smiles"])
    heavy = max(sum(1 for a in m.GetAtoms() if a.GetAtomicNum() > 0), 1)
    return {
        "unit": unit, "mw": mw, "vw": vw, "heavy": heavy,
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
        "repeat_unit_smiles": f["unit"]["smiles"],
        "repeat_unit_source": f["unit"]["source"],
        "repeat_unit_note": f["unit"]["note"],
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
    except RepeatUnitError as exc:
        # 반복 단위가 없으면 구조 기반 물성은 전부 무효다 — 근사하지 않고 멈춘다
        card["errors"].append(str(exc))
        card["repeat_unit_available"] = False
        card["glass_transition"] = glass_transition(smiles)
        return card
    except ValueError as exc:
        card["errors"].append(str(exc))
        return card
    card["repeat_unit_available"] = True

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
