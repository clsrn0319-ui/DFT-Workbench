"""반복단위 전개 — 비닐 C=C 부가형과 연결점(*) 축합형(셀룰로오스·폴리에스터·폴리에테르)."""

import pytest
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors

from server import geometry as g


def _formula(smiles):
    return rdMolDescriptors.CalcMolFormula(Chem.AddHs(Chem.MolFromSmiles(smiles)))


def test_cellulose_repeat_unit_gives_cellobiose_and_cellotriose():
    unit = "*C1OC(CO)C(O*)C(O)C1O"             # 무수 글루코스, C1 · O4 가 연결점
    assert _formula(g.oligomerize(unit, 1)) == "C6H12O6"     # 글루코스 (양 끝 OH)
    assert _formula(g.oligomerize(unit, 2)) == "C12H22O11"   # 셀로비오스
    assert _formula(g.oligomerize(unit, 3)) == "C18H32O16"   # 셀로트리오스
    # 1→4 글리코사이드: 고리 사이를 잇는 O 가 두 고리 탄소에 하나씩 붙는다
    m = Chem.MolFromSmiles(g.oligomerize(unit, 2))
    bridges = [a for a in m.GetAtoms() if a.GetSymbol() == "O" and not a.IsInRing()
               and sum(1 for n in a.GetNeighbors() if n.IsInRing()) == 2]
    assert len(bridges) == 1


def test_hexanoyl_cellulose_record_expands():
    unit = "*OC1OC(CO)C(OC2OC(COC(=O)CCCC)C(*)C(O)C2O)C(O)C1O"
    assert _formula(g.oligomerize(unit, 1)) == "C17H30O12"
    assert _formula(g.oligomerize(unit, 2)) == "C34H58O23"   # 2단위 − H2O


def test_end_caps_follow_linkage_partner():
    assert g.oligomerize("*CCO*", 2) == "OCCOCCO"             # PEO: HO–(CH2CH2O)2–H
    assert _formula(g.oligomerize("*OC(=O)CCCCC*", 2)) == "C12H22O5"   # PCL: 산 · 알코올 말단
    assert _formula(g.oligomerize("*CC(*)(F)F", 3)) == "C6H8F6"         # 비닐계는 H 말단
    assert g.oligomerize("*CC(*)(F)F", 3) == g.oligomerize("C=C(F)F", 3)


def test_vinyl_path_unchanged_and_errors():
    assert g.oligomerize("C=C(F)F", 1) == "C=C(F)F"
    assert g.oligomerize("C=C(F)F", 2) == "CC(F)(F)CC(F)F"
    assert g.has_attachment_points("*CCO*") and not g.has_attachment_points("CCO")
    with pytest.raises(g.GeometryError, match="2개"):
        g.oligomerize("*CC", 2)
    with pytest.raises(g.GeometryError, match=r"연결점\(\*\)"):
        g.oligomerize("OCC1OC(O)C(O)C(O)C1O", 2)


def test_engine_caps_attachment_points_left_in_job():
    """예전 서버에서 * 가 남은 채 제출된 작업도 엔진이 말단을 막아 계산한다."""
    from server import presets
    from server.engine import run_job
    s = {**presets.DEFAULT_SETTINGS, "expert": dict(presets.DEFAULT_SETTINGS["expert"])}
    s.update(envType="진공·기체", solventId=None, accuracy="빠름")
    s["expert"].update(basis="sto-3g", nConformers=1)
    job = {"id": "TEST-STAR", "material": {"id": None, "name": "PEO unit", "smiles": "*CCO*"},
           "settings": s, "logs": []}
    state = {}
    run_job(job, update=state.update)
    assert state["status"] == "PUBLISHED", state.get("error")
    assert state["result"]["structure_xyz"].count("\n") >= 11     # HOCH2CH2OH = 10원자 + 머리 2줄
