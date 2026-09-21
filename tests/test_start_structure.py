"""시작 구조 설정 — 주사슬 인식 · 비틀림 패턴 · all-trans 구조 · 엔진 경로(대표값 기준)."""

import pytest
from rdkit import Chem

from server import geometry as g
from server import presets
from server.engine import _resolve_params, run_job


def _settings(**over):
    s = {**presets.DEFAULT_SETTINGS, "expert": dict(presets.DEFAULT_SETTINGS["expert"])}
    exp = over.pop("expert", {})
    s.update(over)
    s["expert"].update(exp)
    return s


def _chain(smiles):
    m = Chem.AddHs(Chem.MolFromSmiles(smiles))
    return "".join(m.GetAtomWithIdx(i).GetSymbol() for i in g.backbone_path(m))


def test_parse_torsion_pattern():
    assert g.parse_torsion_pattern("T") == [180.0]
    assert g.parse_torsion_pattern("T G T G'") == [180.0, 60.0, 180.0, -60.0]
    assert g.parse_torsion_pattern("TGTG′") == [180.0, 60.0, 180.0, -60.0]   # 프라임 기호
    assert g.parse_torsion_pattern("165") == [165.0]
    assert g.parse_torsion_pattern("180, -60") == [180.0, -60.0]
    assert g.parse_torsion_pattern("300") == [-60.0]
    for bad in ("", "X", "T Q", "999"):
        with pytest.raises(g.GeometryError):
            g.parse_torsion_pattern(bad)


def test_backbone_path_skips_side_groups():
    # 곁가지(할로젠 · 카복실 · 나이트릴 · 에스터 · 페닐 · OH)는 주사슬에서 빠진다
    assert _chain("CC(F)(F)CC(F)(F)CC(F)F") == "CCCCCC"                 # VDF 3량체
    assert _chain(g.oligomerize("C=CC(=O)O", 3)) == "CCCCCC"            # PAA
    assert _chain(g.oligomerize("C=CC#N", 3)) == "CCCCCC"               # PAN
    assert _chain(g.oligomerize("C=Cc1ccccc1", 3)) == "CCCCCC"          # PS
    assert _chain(g.oligomerize("C=COC(C)=O", 3)) == "CCCCCC"           # PVAc
    assert _chain(g.oligomerize("C=CO", 3)) == "CCCCCC"                 # PVA
    assert _chain("COCCOCCOC") == "COCCOCCOC"                           # PEO — 주사슬 O 유지
    assert _chain("C=C(F)F") == "CC"                                    # 모노머 — 비틀림 없음


def test_build_torsion_start_sets_pattern():
    atoms, info = g.build_torsion_start("CC(F)(F)CC(F)(F)CC(F)F", "T")
    assert len(info["torsions"]) == 3
    assert all(abs(abs(t["value"]) - 180) < 2 for t in info["torsions"])
    # 좌표에서 다시 잰 값도 같다
    assert all(abs(abs(g.dihedral_deg(atoms, t["atoms"])) - 180) < 2 for t in info["torsions"])
    _, info2 = g.build_torsion_start("CC(F)(F)CC(F)(F)CC(F)F", "T G T G'")
    vals = [t["value"] for t in info2["torsions"]]
    assert abs(abs(vals[0]) - 180) < 2 and abs(vals[1] - 60) < 2 and abs(abs(vals[2]) - 180) < 2
    _, info3 = g.build_torsion_start("C=C(F)F", "T")
    assert info3["torsions"] == []


def test_resolve_params_start_structure():
    p = _resolve_params(_settings())
    assert p["start_mode"] == "auto" and p["representative"] == "lowest" and not p["fix_torsions"]
    p = _resolve_params(_settings(expert={"startStructure": "all-trans"}))
    assert p["torsion_pattern"] == [180.0] and p["representative"] == "start"
    p = _resolve_params(_settings(expert={"startStructure": "pattern", "torsionPattern": "T G T G'",
                                          "representative": "lowest", "fixBackboneTorsions": True}))
    assert p["torsion_pattern"] == [180.0, 60.0, 180.0, -60.0] and p["representative"] == "lowest"
    assert p["fix_torsions"]
    with pytest.raises(ValueError):
        _resolve_params(_settings(expert={"startStructure": "pattern"}))


def _run(expert):
    job = {"id": "TEST-START", "material": {"id": None, "name": "pentane", "smiles": "CCCCC"},
           "settings": _settings(envType="진공·기체", solventId=None, accuracy="빠름",
                                 expert={"basis": "sto-3g", **expert}),
           "logs": []}
    state = {}
    run_job(job, update=state.update)
    assert state["status"] == "PUBLISHED", state.get("error")
    return state


def _xyz_atoms(block):
    rows = [ln.split() for ln in block.strip().splitlines()[2:]]
    return [(r[0], float(r[1]), float(r[2]), float(r[3])) for r in rows]


def test_run_job_all_trans_is_reported_structure():
    """빠름(최적화 없음) + 민감도 켬 → 시작 구조 + 다른 conformer 2개를 DFT 재순위, 대표는 시작 구조."""
    state = _run({"startStructure": "all-trans", "conformerSensitivity": True, "nConformers": 6})
    gi = state["result"]["geometry_info"]["start_structure"]
    assert gi["mode"] == "all-trans" and gi["representative"] == "start"
    assert len(gi["torsions"]) == 2 and "rel_e_kcal" in gi
    atoms = _xyz_atoms(state["result"]["structure_xyz"])
    for t in gi["torsions"]:
        assert abs(abs(g.dihedral_deg(atoms, t["atoms"])) - 180) < 3


def test_run_job_start_only_skips_conformer_search():
    state = _run({"startStructure": "pattern", "torsionPattern": "T G", "conformerSensitivity": False})
    gi = state["result"]["geometry_info"]
    assert gi["n_conformers"] == 1 and gi["start_structure"]["pattern"] == "T G"
    vals = [t["value"] for t in gi["start_structure"]["torsions"]]
    assert abs(abs(vals[0]) - 180) < 2 and abs(vals[1] - 60) < 2


def test_fixed_torsion_optimization_keeps_chain_shape():
    """geomeTRIC 이 있으면 최적화 중 주사슬 비틀림을 고정한다 — gauche(60°) 부탄이 풀리지 않는다."""
    pytest.importorskip("geometric")
    from server import engine
    atoms, info = g.build_torsion_start("CCCC", "G")
    params = _resolve_params(_settings(envType="진공·기체", solventId=None, accuracy="빠름",
                                       expert={"basis": "sto-3g", "startStructure": "pattern",
                                               "torsionPattern": "G", "fixBackboneTorsions": True}))
    params["basis_opt"] = "sto-3g"
    params["opt_max_steps"] = 30
    q = tuple(info["torsions"][0]["atoms"])
    params["torsion_constraints"] = {"symbols": [a[0] for a in atoms], "torsions": [(q, 60.0)]}
    logs = []
    out = engine._optimize_state(atoms, params, 0, 1, logs.append)
    assert any("비틀림 1개 고정" in line for line in logs)
    assert abs(g.dihedral_deg(out, q) - 60.0) < 1.0
