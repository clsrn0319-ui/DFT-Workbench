"""엔진 단위 테스트. 실행: python -m pytest tests/ -v

빠른 테스트만 기본 실행하며, 실제 DFT SCF를 포함하는 테스트는 STO-3G로 수 초 내에 끝난다.
"""

import pytest

from server import presets
from server.engine import _resolve_params, _solvent_key, run_job
from server.geometry import smiles_to_xyz, GeometryError


def _settings(**over):
    s = {
        **presets.DEFAULT_SETTINGS,
        "expert": dict(presets.DEFAULT_SETTINGS["expert"]),
    }
    exp = over.pop("expert", {})
    s.update(over)
    s["expert"].update(exp)
    return s


def test_geometry_from_smiles():
    atoms, info = smiles_to_xyz("C=CC#N", n_conformers=3)
    assert len(atoms) == 7  # C3H3N
    assert info["n_conformers"] >= 1


def test_geometry_invalid_smiles():
    with pytest.raises(GeometryError):
        smiles_to_xyz("not-a-smiles(((")


def test_solvent_key_vacuum():
    assert _solvent_key(_settings(envType="진공·기체", solventId=None)) is None


def test_solvent_key_mixed_electrolyte():
    assert _solvent_key(_settings()) == "smd:ec-dmc-11"


def test_custom_solvents_registered():
    from pyscf.solvent import smd
    for sol in presets.SOLVENTS:
        if sol.get("smd"):
            assert sol["modelKey"] in smd.solvent_db


def test_resolve_params_accuracy_presets():
    p = _resolve_params(_settings(accuracy="빠름"))
    assert p["do_opt"] is False and p["basis_sp"] == "def2-svp"
    assert p["do_thermo"] is False and p["redox_adiabatic"] is False
    p = _resolve_params(_settings(accuracy="표준"))
    assert p["do_opt"] is True and p["basis_sp"] == "def2-tzvp"
    assert p["do_thermo"] is True and p["redox_adiabatic"] is True
    # expert 오버라이드가 프리셋보다 우선
    p = _resolve_params(_settings(accuracy="표준", expert={"basis": "sto-3g", "optimizeGeometry": False}))
    assert p["do_opt"] is False and p["basis_sp"] == "sto-3g"
    # 단열 전위는 기본적으로 구조 최적화 여부를 따르되 명시 오버라이드 가능
    assert p["redox_adiabatic"] is False
    p = _resolve_params(_settings(accuracy="빠름", expert={"redoxAdiabatic": True, "thermochemistry": True}))
    assert p["redox_adiabatic"] is True and p["do_thermo"] is True


def test_build_cluster_geometry():
    from server.geometry import build_cluster
    atoms, frags, info = build_cluster("O", [("O", 2)], n_conformers=3)
    assert len(atoms) == 9 and len(frags) == 3
    assert frags[0]["label"] == "용질"


def test_reactivity_indices():
    from server.descriptors import reactivity_indices
    r = reactivity_indices(9.0, 1.0)
    assert r["chemical_hardness_ev"] == 4.0
    assert r["chemical_potential_ev"] == -5.0
    assert r["electrophilicity_ev"] == pytest.approx(3.125, abs=1e-3)


def test_guest_placement_is_relaxed():
    """호스트 고정 이완 배치가 물리적 접촉 거리를 만드는지 확인."""
    import numpy as np
    from server.geometry import build_cluster_from_atoms, smiles_to_xyz
    host, _ = smiles_to_xyz("O", 3)
    atoms, frags, _ = build_cluster_from_atoms(host, "O", "O")
    xyz = np.array([a[1:] for a in atoms])
    d = np.linalg.norm(xyz[:3, None] - xyz[None, 3:], axis=2)
    assert 1.5 < d.min() < 3.2
    assert frags[1]["start"] == 3


def test_run_job_real_scf_minimal():
    """실제 SCF 포함 최소 계산 — 물 분자, STO-3G, 수 초 이내."""
    job = {
        "id": "TEST-1",
        "material": {"id": None, "name": "water", "smiles": "O"},
        "settings": _settings(
            envType="배터리 전해액", solventId="sol-water", accuracy="빠름",
            expert={"basis": "sto-3g", "nConformers": 1},
        ),
        "logs": [],
    }
    state = {}
    run_job(job, update=state.update)
    assert state["status"] == "PUBLISHED", state.get("error")
    d = state["result"]["descriptors"]
    assert d["homo_ev"] < 0 and d["gap_ev"] > 0
    assert "solvation_energy_kcal" in d
    assert state["result"]["result_origin"].startswith("SERVER_CALCULATION")


def test_breakable_bonds():
    from server.descriptors import breakable_bonds
    bonds = breakable_bonds("CCO")
    labels = [b[0] for b in bonds]
    assert any("C" in l and "O" in l for l in labels)
    for _, f1, f2 in bonds:
        assert set(f1).isdisjoint(f2)


def test_counterpoise_ghost_atoms_build():
    """고스트 원자로 조각을 구성해도 전자 수는 조각만큼만 잡히는지 확인."""
    from pyscf import gto
    atoms = [("O", 0.0, 0.0, 0.0), ("H", 0.0, -0.76, 0.59), ("H", 0.0, 0.76, 0.59),
             ("O", 0.0, 0.0, 3.0), ("H", 0.0, -0.76, 3.6), ("H", 0.0, 0.76, 3.6)]
    spec = [(sym if i < 3 else f"ghost:{sym}", (x, y, z))
            for i, (sym, x, y, z) in enumerate(atoms)]
    mol = gto.M(atom=spec, basis="sto-3g", verbose=0)
    assert mol.nelectron == 10           # 물 한 분자분
    assert mol.nao > gto.M(atom=atoms[:3], basis="sto-3g").nao   # basis는 이량체 전체


def test_provenance_fields():
    from server.engine import _provenance, _resolve_params
    settings = {**presets.DEFAULT_SETTINGS, "expert": dict(presets.DEFAULT_SETTINGS["expert"])}
    prov = _provenance(_resolve_params(settings), settings, "smd:ec-dmc-11")
    for key in ["engine", "rdkit", "basis_singlepoint", "scf_conv_tol",
                "freq_scale_factor", "geometry_optimizer", "solvent_model"]:
        assert key in prov
    assert prov["engine"].startswith("PySCF")


def test_atomic_thermo_translation_only():
    """단원자 조각: ZPE 0, 엔탈피 보정 = 5/2 RT."""
    from server.engine import _atomic_thermo_fn, HARTREE2KJ
    th = _atomic_thermo_fn(298.15)
    assert th["zpe_hartree"] == 0.0
    expected_kj = 2.5 * 8.31446261815324 * 298.15 / 1000
    assert th["h_corr_hartree"] * HARTREE2KJ == pytest.approx(expected_kj, abs=1e-6)


def test_bde_flags_default_on():
    from server.engine import _resolve_params
    p = _resolve_params(_settings())
    assert p["bde_relax"] is True and p["bde_thermal"] is True
    p = _resolve_params(_settings(expert={"bdeRelaxFragments": False,
                                          "bdeThermalCorrection": False}))
    assert p["bde_relax"] is False and p["bde_thermal"] is False


def test_shared_password_auth(tmp_path, monkeypatch):
    """공유 비밀번호는 해시로만 저장되고, 틀린 비밀번호는 거부된다."""
    from server import auth
    monkeypatch.setattr(auth, "ACCESS_FILE", tmp_path / "access.json")
    monkeypatch.setattr(auth, "DATA_DIR", tmp_path)
    monkeypatch.setattr(auth, "_access", None)
    monkeypatch.setattr(auth, "_sessions", {})
    monkeypatch.setattr(auth, "_loaded", False)
    monkeypatch.setenv("RHOBENCH_ACCESS_PASSWORD", "lab-shared-1234")

    assert auth.login("wrong") is None
    token = auth.login("lab-shared-1234")
    assert token and auth.is_valid(token)

    saved = (tmp_path / "access.json").read_text(encoding="utf-8")
    assert "lab-shared-1234" not in saved      # 평문 저장 없음

    auth.logout(token)
    assert not auth.is_valid(token)
    assert not auth.is_valid(None)


def test_shared_password_change_revokes_sessions(tmp_path, monkeypatch):
    """비밀번호를 바꿔 재실행하면 기존 세션이 모두 끊긴다."""
    from server import auth
    monkeypatch.setattr(auth, "ACCESS_FILE", tmp_path / "access.json")
    monkeypatch.setattr(auth, "DATA_DIR", tmp_path)
    monkeypatch.setattr(auth, "_access", None)
    monkeypatch.setattr(auth, "_sessions", {})
    monkeypatch.setattr(auth, "_loaded", False)
    monkeypatch.setenv("RHOBENCH_ACCESS_PASSWORD", "first-password")
    token = auth.login("first-password")
    assert auth.is_valid(token)

    # 새 비밀번호로 서버 재시작 상황 재현
    monkeypatch.setenv("RHOBENCH_ACCESS_PASSWORD", "second-password")
    monkeypatch.setattr(auth, "_loaded", False)
    auth._load()
    assert not auth.is_valid(token)            # 기존 세션 무효
    assert auth.login("first-password") is None
    assert auth.login("second-password")


def test_active_job_count_is_global(tmp_path, monkeypatch):
    from server import store
    monkeypatch.setattr(store, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_jobs", {})
    monkeypatch.setattr(store, "_loaded", True)
    mat = {"id": None, "name": "t", "smiles": "O"}
    store.create_job(mat, presets.DEFAULT_SETTINGS)
    store.create_job(mat, presets.DEFAULT_SETTINGS)
    assert store.count_active() == 2
    assert len(store.list_jobs()) == 2
