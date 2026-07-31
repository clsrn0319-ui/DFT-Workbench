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
