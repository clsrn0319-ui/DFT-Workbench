"""표면·계면 — 집전체(Al 산화막 등) 흡착과 용매 경쟁 교환 에너지.

슬랩이 아닌 작은 클러스터 모델이라 절대값은 쓰지 않는다. 여기서는 모델이 성립하는지,
경쟁 판정과 기술자·주석이 제대로 나오는지, 설정 검증이 되는지를 본다.
"""

import pytest
from rdkit import Chem

from server import engine, presets, store


@pytest.fixture(autouse=True)
def _tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "LOGS_DIR", tmp_path / "logs")
    yield


def _settings(**over):
    s = {**presets.DEFAULT_SETTINGS, "expert": dict(presets.DEFAULT_SETTINGS["expert"])}
    exp = over.pop("expert", {})
    s.update(over)
    s["expert"].update(exp)
    return s


def test_surface_models_are_valid_and_closed_shell():
    keys = [s["key"] for s in presets.SURFACES]
    assert len(keys) == len(set(keys)) and "al_oxide_oh" in keys
    for s in presets.SURFACES:
        mol = Chem.MolFromSmiles(s["smiles"])
        assert mol is not None, s["key"]
        mh = Chem.AddHs(mol)
        n_elec = sum(a.GetAtomicNum() for a in mh.GetAtoms()) - Chem.GetFormalCharge(mh)
        assert n_elec % 2 == 0, f"{s['key']}: 홀전자 — 분자 DFT 로 다루기 어렵다"
        assert s["group"] in ("집전체", "활물질") and s["desc"]
    # 집전체는 금속이 아니라 산화막 모델이어야 한다 (실제 Al 표면은 자연 산화막)
    for s in presets.SURFACES:
        if s["group"] == "집전체":
            assert "O" in s["smiles"], s["key"]


def test_unknown_surface_is_rejected():
    from fastapi import HTTPException
    from server.main import _check_surface
    _check_surface({"surfaceId": None})
    _check_surface({"surfaceId": "al_oxide_oh"})
    with pytest.raises(HTTPException) as ei:
        _check_surface({"surfaceId": "al_metal"})
    assert ei.value.status_code == 400


def _fake_pair(binder_e, solvent_e, geometry=None):
    """pair_energy 를 대신해 정해진 상호작용 에너지를 돌려준다 (DFT 없이 판정만 본다)."""
    calls = []

    def pair_energy(host_atoms, guest_smiles, label, prog, charge=0, mult=1, host_smiles=None,
                    info=None):
        calls.append({"guest": guest_smiles, "host_smiles": host_smiles, "label": label})
        if info is not None and geometry is not None:
            info.update(geometry)
        return (solvent_e if len(calls) > 1 else binder_e), list(host_atoms)
    return pair_energy, calls


@pytest.mark.parametrize("binder,solv,verdict", [
    (-60.0, -20.0, "binder"),        # 바인더가 용매를 밀어낸다
    (-22.0, -20.0, "competitive"),   # 비슷하다
    (-5.0, -40.0, "solvent"),        # 용매가 더 붙는다
])
def test_surface_competition_verdict(binder, solv, verdict):
    settings = _settings(envType="사용자 정의", solventId="sol-nmp",
                         surfaceId="al_oxide_oh", surfaceCompetition=True)
    params = engine._resolve_params(settings)
    pair, calls = _fake_pair(binder, solv)
    atoms = [("C", 0.0, 0.0, 0.0), ("H", 0.0, 0.0, 1.1)]
    out = engine._surface_interaction(atoms, "C", settings, params, "smd:nmp",
                                      lambda *_: None, lambda *_: None, pair)
    si = out["descriptors"]["surface_interaction"]
    assert si["verdict"] == verdict and si["solvent"] == "NMP"
    assert si["binding_kj"] == binder and si["solvent_binding_kj"] == solv
    assert out["descriptors"]["surface_exchange_kj"] == round(binder - solv, 1)
    assert "surface_complex" in out["structures"] and "surface_solvent" in out["structures"]
    assert any("집전체" in n for n in out["notes"])
    # 용매 쪽 계산은 표면을 호스트로 넘겨야 한다 (바인더 SMILES 를 쓰면 구조가 어긋난다)
    assert calls[1]["host_smiles"] == presets.SURFACES_BY_ID["al_oxide_oh"]["smiles"]


def test_surface_without_solvent_reports_binding_only():
    settings = _settings(envType="진공·기체", solventId=None, surfaceId="graphite")
    params = engine._resolve_params(settings)
    pair, _ = _fake_pair(-30.0, -10.0)
    out = engine._surface_interaction([("C", 0.0, 0.0, 0.0)], "C", settings, params, None,
                                      lambda *_: None, lambda *_: None, pair)
    d = out["descriptors"]
    assert d["surface_binding_kj"] == -30.0 and "surface_exchange_kj" not in d
    assert "exchange_kj" not in d["surface_interaction"]
    assert any("미계산" in n for n in out["notes"])


@pytest.mark.parametrize("geom,needle", [
    ({"relaxed": True, "converged": False, "steps": 40, "max_steps": 40}, "수렴하지 못했습니다"),
    ({"relaxed": False}, "역장 구조"),
])
def test_unconverged_contact_geometry_is_reported(geom, needle):
    """접촉 구조가 수렴하지 않으면 값 옆에 반드시 표시해야 한다.

    셀로비오스 이량체에서 이완을 12스텝에서 끊었을 때 -15.2 kJ/mol, 40스텝까지 돌렸을 때
    -81.6 kJ/mol 로 5배 차이가 났다. 표시가 없으면 미수렴 값이 그대로 인용된다.
    """
    settings = _settings(envType="진공·기체", solventId=None, surfaceId="graphite")
    params = engine._resolve_params(settings)
    pair, _ = _fake_pair(-30.0, -10.0, geometry=geom)
    out = engine._surface_interaction([("C", 0.0, 0.0, 0.0)], "C", settings, params, None,
                                      lambda *_: None, lambda *_: None, pair)
    assert any(needle in n for n in out["notes"])
    assert out["descriptors"]["surface_interaction"]["geometry"] == geom


def test_converged_contact_geometry_has_no_warning():
    settings = _settings(envType="진공·기체", solventId=None, surfaceId="graphite")
    params = engine._resolve_params(settings)
    pair, _ = _fake_pair(-30.0, -10.0,
                         geometry={"relaxed": True, "converged": True, "steps": 12, "max_steps": 100})
    out = engine._surface_interaction([("C", 0.0, 0.0, 0.0)], "C", settings, params, None,
                                      lambda *_: None, lambda *_: None, pair)
    assert not any("수렴하지 못했습니다" in n or "역장 구조" in n for n in out["notes"])


def test_run_job_with_surface_real_scf():
    """실계산 — 물 분자 + 보에마이트 사이트, STO-3G 진공 (수십 초)."""
    job = {"id": "TEST-SURF", "material": {"id": None, "name": "water", "smiles": "O"},
           "settings": _settings(envType="진공·기체", solventId=None, accuracy="빠름",
                                 surfaceId="al_oxide_boehmite",
                                 expert={"basis": "sto-3g", "nConformers": 1}),
           "logs": []}
    state = {}
    engine.run_job(job, update=state.update)
    assert state["status"] == "PUBLISHED", state.get("error")
    d = state["result"]["descriptors"]
    si = d["surface_interaction"]
    assert si["surface"] == "al_oxide_boehmite" and isinstance(si["binding_kj"], float)
    assert d["surface_binding_kj"] == si["binding_kj"]
    assert state["result"]["fingerprint_structures"]["surface_complex"].count("\n") > 3
