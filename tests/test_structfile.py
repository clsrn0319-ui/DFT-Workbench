"""3D 구조 파일 입력(SDF/MOL·XYZ) 단위 테스트.

실행: python -m pytest tests/test_structfile.py -v
"""

import pytest
from rdkit import Chem
from rdkit.Chem import AllChem

from server import screening, store, structfile


def _molblock(smiles: str, name: str = "mol", three_d: bool = True,
              with_h: bool = True) -> str:
    mol = Chem.MolFromSmiles(smiles)
    if with_h:
        mol = Chem.AddHs(mol)
    if three_d:
        AllChem.EmbedMolecule(mol, randomSeed=7)
        AllChem.MMFFOptimizeMolecule(mol)
    else:
        AllChem.Compute2DCoords(mol)
    mol.SetProp("_Name", name)
    return Chem.MolToMolBlock(mol)


def _xyzblock(smiles: str, comment: str = "") -> str:
    mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
    AllChem.EmbedMolecule(mol, randomSeed=7)
    AllChem.MMFFOptimizeMolecule(mol)
    conf = mol.GetConformer()
    lines = [str(mol.GetNumAtoms()), comment]
    for a in mol.GetAtoms():
        p = conf.GetAtomPosition(a.GetIdx())
        lines.append(f"{a.GetSymbol()} {p.x:.4f} {p.y:.4f} {p.z:.4f}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- SDF/MOL
def test_sdf_single_3d():
    out = structfile.parse_structures(_molblock("CCO", "에탄올"), "ethanol.mol")
    assert out["format"] == "sdf" and out["n_ok"] == 1
    m = out["molecules"][0]
    assert m["name"] == "에탄올"
    assert m["smiles"] == "CCO"
    assert m["n_atoms"] == 9          # C2H6O
    assert len(m["atoms"]) == 9
    assert m["atoms"][0][0] in ("C", "O", "H")


def test_sdf_multi_molecule():
    content = _molblock("CCO", "a") + "$$$$\n" + _molblock("C=C", "b") + "$$$$\n"
    out = structfile.parse_structures(content, "two.sdf")
    assert out["n_ok"] == 2
    assert [m["name"] for m in out["molecules"]] == ["a", "b"]


def test_sdf_2d_coordinates_fall_back():
    """2D 몰파일 — 결합 정보(SMILES)만 취하고 좌표는 쓰지 않는다."""
    out = structfile.parse_structures(_molblock("CCO", "flat", three_d=False))
    m = out["molecules"][0]
    assert m["ok"] and m["smiles"] == "CCO"
    assert m["atoms"] is None
    assert "2D" in m["note"]


def test_sdf_implicit_hydrogens_completed():
    """수소 생략 파일 — AddHs(addCoords)로 좌표를 보완한다."""
    out = structfile.parse_structures(_molblock("CCO", "noH", with_h=False))
    m = out["molecules"][0]
    assert m["ok"] and m["n_atoms"] == 9
    assert "수소" in m["note"]


def test_sdf_broken_block_reports_error():
    out = structfile.parse_structures("깨진 내용\nV2000\n", "bad.sdf")
    assert out["n_ok"] == 0 and out["n_error"] == 1
    assert "해석 실패" in out["molecules"][0]["error"]


# ---------------------------------------------------------------- XYZ
def test_xyz_single():
    out = structfile.parse_structures(_xyzblock("O", "물"), "water.xyz")
    assert out["format"] == "xyz" and out["n_ok"] == 1
    m = out["molecules"][0]
    assert m["name"] == "물" and m["smiles"] == "O" and m["n_atoms"] == 3


def test_xyz_multi_frame():
    content = _xyzblock("O", "w") + _xyzblock("C", "m")
    out = structfile.parse_structures(content, "multi.xyz")
    assert out["n_ok"] == 2
    assert {m["smiles"] for m in out["molecules"]} == {"O", "C"}


def test_xyz_truncated():
    content = "5\n잘린 프레임\nC 0 0 0\n"
    out = structfile.parse_structures(content, "cut.xyz")
    assert out["n_error"] == 1
    assert "끊겨" in out["molecules"][0]["error"]


def test_xyz_not_xyz_text():
    out = structfile.parse_structures("이건 xyz 가 아님", "wat.xyz")
    assert out["n_error"] >= 1


# ---------------------------------------------------------------- 형식 감지
def test_detect_by_extension_and_content():
    assert structfile.detect_format("anything", "a.sdf") == "sdf"
    assert structfile.detect_format("anything", "a.xyz") == "xyz"
    assert structfile.detect_format("...V2000...", "") == "sdf"
    assert structfile.detect_format("3\ncomment\nO 0 0 0", "") == "xyz"


# ---------------------------------------------------------------- 배치 연동
@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(screening, "CAMPAIGNS_FILE", tmp_path / "campaigns.json")
    monkeypatch.setattr(screening, "DATA_DIR", tmp_path)
    monkeypatch.setattr(screening, "_campaigns", {})
    monkeypatch.setattr(screening, "_loaded", True)
    monkeypatch.setattr(store, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_jobs", {})
    monkeypatch.setattr(store, "_loaded", True)
    monkeypatch.setattr(screening, "ensure_started", lambda: None)
    from server import worker
    monkeypatch.setattr(worker, "submit", lambda job_id, priority=0: None)
    monkeypatch.setattr(screening, "BATCH_PARALLEL", 10)


def test_campaign_geometry_reaches_job_material(isolated_state):
    """후보의 업로드 좌표가 작업 material.geometry 로 전달된다."""
    atoms = [["O", 0.0, 0.0, 0.0], ["H", 0.96, 0.0, 0.0], ["H", -0.24, 0.93, 0.0]]
    cand = screening.parse_candidates("물,O")["rows"][0]
    cand["geometry"] = {"atoms": atoms, "source": "xyz", "rescan": False}
    camp = screening.create_campaign(
        name="g", candidates=[cand], electrodes=["ncm811"], margin_v=0.3,
        stages=[{"accuracy": "빠름"}],
        settings={"envType": "진공·기체", "solventId": None, "temperature": 298.15,
                  "structure": "모노머", "referenceElectrode": "Li/Li+",
                  "accuracy": "빠름", "purpose": screening.SCREEN_PURPOSE,
                  "expert": {"functional": "PBE0-D3(BJ)", "basis": None,
                             "charge": 0, "multiplicity": 1}})
    screening._advance(camp)
    jid = camp["candidates"][0]["jobs"]["0"]
    job = store.get_job(jid)
    assert job["material"]["geometry"]["atoms"] == atoms
    assert job["material"]["geometry"]["source"] == "xyz"


def test_campaign_geometry_skips_cache(isolated_state):
    """업로드 좌표가 있는 후보는 기존 결과를 재사용하지 않는다 — 좌표가 다르면 다른 계산."""
    settings = {"envType": "진공·기체", "solventId": None, "temperature": 298.15,
                "structure": "모노머", "referenceElectrode": "Li/Li+",
                "accuracy": "빠름", "purpose": screening.SCREEN_PURPOSE,
                "expert": {"functional": "PBE0-D3(BJ)", "basis": None,
                           "charge": 0, "multiplicity": 1}}
    # 같은 구조·같은 조건의 완료 결과를 미리 만들어 둔다
    cand0 = screening.parse_candidates("물,O")["rows"][0]
    camp0 = screening.create_campaign("c0", [cand0], ["ncm811"], 0.3,
                                      [{"accuracy": "빠름"}], settings)
    screening._advance(camp0)
    j0 = camp0["candidates"][0]["jobs"]["0"]
    store.update_job(j0, {"status": "PUBLISHED",
                          "result": {"descriptors": {"reduction_potential_v": -1.0,
                                                     "oxidation_potential_v": 5.0}}})
    # 좌표를 가진 같은 분자 — 캐시를 쓰면 안 된다
    cand1 = screening.parse_candidates("물,O")["rows"][0]
    cand1["geometry"] = {"atoms": [["O", 0, 0, 0], ["H", 1, 0, 0], ["H", 0, 1, 0]],
                         "source": "xyz", "rescan": False}
    camp1 = screening.create_campaign("c1", [cand1], ["ncm811"], 0.3,
                                      [{"accuracy": "빠름"}], settings)
    screening._advance(camp1)
    j1 = camp1["candidates"][0]["jobs"]["0"]
    assert j1 != j0
