"""화학물질 조회 — 인터넷 검색 없이 RhoBench 안에서 특성 파악.

세 단계 소스를 합쳐서 반환한다:
  1. RDKit 로컬 기술자 (오프라인에서도 항상 동작): 분자식·분자량·LogP·TPSA·수소결합 등
  2. PubChem PUG REST (무료, 키 불필요): CID·CAS·IUPAC명·실험 물성·설명
  3. Materials Project (선택): 환경변수 MP_API_KEY 설정 시 분자 요약 조회 시도

이름(영문)·CAS 번호·SMILES 어느 것으로도 조회할 수 있다.
"""

import json
import os
import re
import urllib.parse
import urllib.request

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, rdMolDescriptors
from rdkit import RDLogger

RDLogger.DisableLog("rdApp.*")  # 이름 입력을 SMILES로 시도할 때의 파싱 경고 억제

PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound"
MP_MOLECULES = "https://api.materialsproject.org/molecules/summary/"
TIMEOUT = 12
CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")


def _get_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": "RhoBench/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def local_descriptors(smiles: str):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    return {
        "canonical_smiles": Chem.MolToSmiles(mol),
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "mw": round(Descriptors.MolWt(mol), 2),
        "logp_crippen": round(Crippen.MolLogP(mol), 2),
        "tpsa": round(rdMolDescriptors.CalcTPSA(mol), 1),
        "hbd": rdMolDescriptors.CalcNumHBD(mol),
        "hba": rdMolDescriptors.CalcNumHBA(mol),
        "rotatable_bonds": rdMolDescriptors.CalcNumRotatableBonds(mol),
        "rings": rdMolDescriptors.CalcNumRings(mol),
        "heavy_atoms": mol.GetNumHeavyAtoms(),
        "formal_charge": Chem.GetFormalCharge(mol),
    }


def _looks_like_smiles(query: str) -> bool:
    # 순수 알파벳/공백(이름일 가능성)이 아니고 RDKit이 파싱하면 SMILES로 취급
    if re.fullmatch(r"[A-Za-z ,'\-]+", query) and not re.fullmatch(r"[BCNOPSFIbcnops]+", query):
        return False
    return Chem.MolFromSmiles(query) is not None


def _pubchem(query: str, namespace: str):
    enc = urllib.parse.quote(query, safe="")
    base = f"{PUBCHEM}/{namespace}/{enc}"
    props = ("MolecularFormula,MolecularWeight,IUPACName,XLogP,TPSA,"
             "HBondDonorCount,HBondAcceptorCount,RotatableBondCount,Charge")
    data = _get_json(f"{base}/property/{props}/JSON")["PropertyTable"]["Properties"][0]
    cid = data.get("CID")
    # SMILES 속성명은 PubChem 개편(2025) 전후 호환 처리
    for prop in ("SMILES", "IsomericSMILES", "CanonicalSMILES"):
        try:
            v = _get_json(f"{base}/property/{prop}/JSON")["PropertyTable"]["Properties"][0].get(prop)
            if v:
                data["ResolvedSMILES"] = v
                break
        except Exception:
            continue
    out = {
        "cid": cid,
        "iupac_name": data.get("IUPACName"),
        "formula": data.get("MolecularFormula"),
        "mw": data.get("MolecularWeight"),
        "xlogp": data.get("XLogP"),
        "tpsa": data.get("TPSA"),
        "hbd": data.get("HBondDonorCount"),
        "hba": data.get("HBondAcceptorCount"),
        "rotatable_bonds": data.get("RotatableBondCount"),
        "charge": data.get("Charge"),
        "smiles": data.get("ResolvedSMILES"),
        "cas": None,
        "synonyms": [],
        "description": None,
        "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}" if cid else None,
    }
    try:
        syns = _get_json(f"{PUBCHEM}/cid/{cid}/synonyms/JSON")[
            "InformationList"]["Information"][0]["Synonym"]
        out["synonyms"] = syns[:8]
        out["cas"] = next((s for s in syns if CAS_RE.fullmatch(s)), None)
    except Exception:
        pass
    try:
        infos = _get_json(f"{PUBCHEM}/cid/{cid}/description/JSON")[
            "InformationList"]["Information"]
        out["title"] = infos[0].get("Title") if infos else None
        out["description"] = next(
            (it["Description"] for it in infos if it.get("Description")), None)
    except Exception:
        pass
    return out


def _materials_project(formula: str):
    key = os.environ.get("MP_API_KEY")
    if not key:
        return None, "MP_API_KEY 환경변수가 없어 Materials Project 조회를 생략했습니다 (선택 사항)."
    try:
        url = (f"{MP_MOLECULES}?formula_alphabetical={urllib.parse.quote(formula)}"
               f"&_limit=3&_fields=molecule_id,formula_alphabetical,charge,spin_multiplicity")
        docs = _get_json(url, headers={"X-API-KEY": key}).get("data", [])
        return docs or None, None if docs else "Materials Project에서 일치 항목을 찾지 못했습니다."
    except Exception as exc:  # noqa: BLE001 — 외부 API 실패는 조회 결과에 메모로만 남김
        return None, f"Materials Project 조회 실패: {exc}"


def lookup(query: str):
    query = query.strip()
    result = {"query": query, "local": None, "pubchem": None, "mp": None, "notes": []}

    is_smiles = _looks_like_smiles(query)
    if is_smiles:
        result["local"] = local_descriptors(query)

    try:
        result["pubchem"] = _pubchem(query, "smiles" if is_smiles else "name")
    except Exception as exc:  # noqa: BLE001 — 오프라인/미등록 물질도 로컬 결과로 응답
        result["notes"].append(
            f"PubChem 조회 실패 ({type(exc).__name__}) — 인터넷 연결 또는 물질명을 확인하세요. "
            "영문 이름·CAS 번호·SMILES로 검색할 수 있습니다.")

    # 이름으로 검색했다면 PubChem이 알려준 SMILES로 로컬 기술자 보강
    if result["local"] is None and result["pubchem"] and result["pubchem"].get("smiles"):
        result["local"] = local_descriptors(result["pubchem"]["smiles"])

    if result["local"] is None and result["pubchem"] is None:
        result["notes"].append("구조를 해석하지 못했습니다 — SMILES 형식인지 확인하세요.")

    formula = (result["local"] or {}).get("formula") or (result["pubchem"] or {}).get("formula")
    if formula:
        mp, note = _materials_project(formula)
        result["mp"] = mp
        if note:
            result["notes"].append(note)
    return result
