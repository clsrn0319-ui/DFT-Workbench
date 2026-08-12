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


def test_snapshot_html_is_self_contained():
    """HTML 사본은 서버 참조 없이 결과를 품고 있어야 한다."""
    import json as _json
    import re
    from server.main import _snapshot_html

    job = {
        "id": "JOB-TEST-1", "status": "PUBLISHED",
        "material": {"id": None, "name": "물", "smiles": "O"},
        "createdAt": 0, "finishedAt": 1,
        "result": {
            "descriptors": {"homo_ev": -7.5, "gap_ev": 8.0},
            "conditions": {"method": "PBE0-D3(BJ)/def2-svp",
                           "solvent_model": "SMD", "temperature_k": 298.15},
            "wall_time_s": 1.0,
        },
    }
    html = _snapshot_html([job])

    # 서버에서 받아오던 스크립트가 파일 안으로 들어왔는지
    assert '<script src="/static/app.js">' not in html
    assert "window.__RB_SNAPSHOT__" in html
    assert "rbRenderCompare" in html          # app.js 본문이 인라인됨

    # 심어 둔 데이터가 실제 결과를 담고 있는지
    payload = _json.loads(re.search(r"window\.__RB_SNAPSHOT__ = (.*?);\n", html, re.S).group(1))
    assert len(payload["jobs"]) == 1
    assert payload["jobs"][0]["result"]["descriptors"]["homo_ev"] == -7.5
    assert "presets" in payload and "materials" in payload["presets"]
    assert payload["csv"].startswith("﻿") and "homo_ev" in payload["csv"]

    # 데이터 리터럴이 HTML 파서를 깨뜨리지 않도록 <, > 가 이스케이프되었는지
    literal = re.search(r"window\.__RB_SNAPSHOT__ = (.*?);\n", html, re.S).group(1)
    assert "<" not in literal and ">" not in literal


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


def test_pfas_gate_follows_oecd_definition():
    """완전 불소화 탄소가 있어야 PFAS — 단일 불소 치환은 해당하지 않는다."""
    from server.binder import pfas_check
    assert pfas_check("FC(F)=C(F)F")["status"] == "pfas"        # PTFE
    assert pfas_check("C=C(F)F")["status"] == "pfas"            # PVDF
    assert pfas_check("OC(=O)C(F)(F)C(F)(F)F")["status"] == "pfas"   # PFOA 조각
    assert pfas_check("Fc1ccccc1")["status"] == "fluorinated"   # 단일 불소 — PFAS 아님
    assert pfas_check("C=CC(=O)O")["status"] == "pfas_free"     # PAA
    assert pfas_check("C=C")["n_fluorine"] == 0


def test_binder_candidates_are_valid_and_classified():
    from rdkit import Chem
    from server import binder
    cands = binder.candidates()
    assert len(cands) >= 14
    for c in cands:
        assert Chem.MolFromSmiles(c["smiles"]) is not None, c["abbr"]
    # 기준군(PTFE·PVDF)만 PFAS 로 분류되어야 한다
    pfas = {c["abbr"] for c in cands if c["pfas"]["status"] == "pfas"}
    assert pfas == {"PTFE", "PVDF"}
    assert all(c["reference"] for c in cands if c["abbr"] in pfas)


def test_binder_report_gates_on_pfas():
    """PFAS 는 다른 축이 아무리 좋아도 탈락시킨다."""
    from server import binder
    good = {"reduction_potential_v": -2.0, "bde_min_298_kj": 400.0}
    ok = binder.report({"smiles": "C=C"}, good)
    assert ok["overall"] == binder.VERDICT_OK
    blocked = binder.report({"smiles": "FC(F)=C(F)F"}, good)
    assert blocked["overall"] == binder.VERDICT_NO
    assert "PFAS" in blocked["summary"]


def test_binder_reduction_verdict_uses_anode_potential():
    from server import binder
    # 환원 전위가 음극 전위보다 높으면 위험
    risky = binder.report({"smiles": "C=C"}, {"reduction_potential_v": 1.0})
    red = next(a for a in risky["absolute"] if a["axis"] == "환원 안정성")
    assert red["verdict"] == binder.VERDICT_NO
    safe = binder.report({"smiles": "C=C"}, {"reduction_potential_v": -3.0})
    red2 = next(a for a in safe["absolute"] if a["axis"] == "환원 안정성")
    assert red2["verdict"] == binder.VERDICT_OK
    assert all(p["stable"] for p in red2["per_anode"])


def test_binder_rank_orders_relative_axes():
    from server import binder
    reps = [
        {"material": "A", "report": binder.report(
            {"smiles": "C=C"}, {"dimer_binding_kj": -30.0})},
        {"material": "B", "report": binder.report(
            {"smiles": "C=C"}, {"dimer_binding_kj": -10.0})},
    ]
    ranks = binder.rank(reps)
    order = ranks["dimer_binding_kj"]["order"]
    assert order[0]["material"] == "A"   # 더 음수 = 강한 응집 = 1위


def test_binder_does_not_claim_unevaluated_axes_passed():
    """값이 없는 축을 «통과»로 보고하면 안 된다.

    에틸렌(C=C)처럼 주사슬 단일결합이 없는 비닐 모노머는 BDE가 산출되지 않는데,
    이를 열 안정성 통과로 요약하면 근거 없는 합격 판정이 된다.
    """
    from server import binder
    rep = binder.report({"smiles": "C=C"}, {"reduction_potential_v": -4.275})
    assert rep["overall"] == binder.VERDICT_MID          # 양호가 아니라 주의
    assert "열 안정성" not in rep["summary"].split("통과")[0]
    axes = [u["axis"] for u in rep["unevaluated"]]
    assert axes == ["열 안정성"]
    assert "2량체" in rep["unevaluated"][0]["reason"]     # 해결 방법 안내

    # 두 축이 모두 평가되면 미평가 목록은 비고 양호로 판정된다
    full = binder.report({"smiles": "C=CC"},
                         {"reduction_potential_v": -4.374, "bde_min_kj": 467.0})
    assert full["overall"] == binder.VERDICT_OK
    assert full["unevaluated"] == []


def test_vdw_volume_matches_literature():
    """Zhao 법 van der Waals 부피 — 소분자 문헌값 대비 ±8 % 이내."""
    from server.polymer import molecule_vdw_volume
    for smiles, lit in [("CC", 27.3), ("c1ccccc1", 48.4), ("CO", 21.7),
                        ("CC(C)=O", 39.2), ("Cc1ccccc1", 59.5)]:
        calc = molecule_vdw_volume(smiles)
        assert abs(calc - lit) / lit < 0.08, f"{smiles}: {calc} vs {lit}"


def test_repeat_unit_vdw_volume_matches_literature():
    """반복 단위 Vw 는 van Krevelen 그룹표 값과 ±5 % 안에서 맞아야 한다.

    모노머를 그대로 쓰면 C=C 때문에 결합 수가 모자라 10~25 % 부풀려진다.
    """
    from server.polymer import molecule_vdw_volume, vdw_volume
    for monomer, lit in [("C=C", 20.46), ("C=CC", 30.68),
                         ("C=CC#N", 34.0), ("C=CO", 25.05)]:
        calc = vdw_volume(monomer)
        assert abs(calc - lit) / lit < 0.05, f"{monomer}: {calc} vs {lit}"
        # 모노머 부피와는 명확히 달라야 한다 (같으면 정정이 안 된 것)
        assert molecule_vdw_volume(monomer) > calc * 1.05


def test_repeat_unit_distinguishes_pva_from_peo():
    """PVA(-CH2CH(OH)-)와 PEO(-CH2CH2O-)는 서로 다른 물성을 내야 한다.

    양 끝을 H로 막으면 둘 다 에탄올로 축약되어 구분이 사라진다. 결합 자리를
    더미 원자로 남겨야 수산기와 에터가 구분된다.
    """
    from server.polymer import predict, repeat_unit
    pva, peo = predict("C=CO"), predict("COCCOCCOC")
    assert repeat_unit("C=CO")["smiles"] != repeat_unit("COCCOCCOC")["smiles"]
    assert abs(pva["density_g_cm3"] - 1.260) < 0.06     # 문헌 1.260
    assert abs(peo["density_g_cm3"] - 1.130) < 0.06     # 문헌 1.130
    assert pva["solubility_parameter_mpa05"] > peo["solubility_parameter_mpa05"]


def test_repeat_unit_refuses_undefined_structures():
    """반복 단위를 확정할 수 없으면 근사하지 않고 거부한다."""
    from server.polymer import RepeatUnitError, predict, property_card
    cmc = "OCC1OC(O)C(OCC(=O)O)C(O)C1O"
    with pytest.raises(RepeatUnitError):
        predict(cmc)
    card = property_card({"name": "CMC", "smiles": cmc})
    assert card["repeat_unit_available"] is False
    assert card["computed"] is None and card["errors"]
    # 구조 기반 물성은 막히더라도 문헌 Tg 는 계속 제공되어야 한다
    assert card["glass_transition"]["available"] is True


def test_polymer_density_and_delta_against_literature():
    """회귀 모델이 문헌 밀도·용해도 파라미터를 검증된 오차 안에서 재현한다.

    LOO 교차검증 기준 밀도 0.05 g/cm³, δ 1.43 MPa^0.5 였으므로
    적합에 쓰인 물질에 대해서는 그보다 넉넉한 한계로 회귀를 확인한다.
    """
    from server.polymer import predict
    for smiles, rho, delta in [("C=C", 0.855, 16.2),        # PE
                               ("C=CC(=O)O", 1.22, 24.5),   # PAA
                               ("C=C(F)F", 1.77, 17.5)]:    # PVDF
        p = predict(smiles)
        assert abs(p["density_g_cm3"] - rho) < 0.20, (smiles, p["density_g_cm3"])
        assert abs(p["solubility_parameter_mpa05"] - delta) < 4.5, (smiles, p)
    # CED 는 δ² 이어야 한다 (δ는 소수 첫째 자리로 반올림해 보고하므로 그만큼 허용)
    p = predict("C=CC(=O)O")
    delta = p["solubility_parameter_mpa05"]
    assert abs(p["ced_j_cm3"] - delta ** 2) < 0.1 * delta + 0.5


def test_delta_distinguishes_nonpolar_polymers():
    """비극성 포화 사슬끼리도 δ가 구분되어야 한다.

    참조 20종 시절에는 극성·고리 항만 써서 PE·PP·PTFE 가 모두 절편값으로
    모였다. 47종으로 늘리며 회전 결합 밀도가 들어와 축퇴가 풀렸다.
    """
    from server.polymer import predict
    pe = predict("C=C")["solubility_parameter_mpa05"]
    pp = predict("C=CC")["solubility_parameter_mpa05"]
    ptfe = predict("FC(F)=C(F)F")["solubility_parameter_mpa05"]
    assert len({pe, pp, ptfe}) == 3, f"축퇴: PE {pe} PP {pp} PTFE {ptfe}"
    assert pe > ptfe, "PTFE 는 참조셋에서 가장 낮은 δ 를 갖는다"


def test_polymer_warns_on_strong_hydrogen_bonding():
    """δ 오차가 가장 큰 영역(강한 수소결합)에서는 경고를 붙인다."""
    from server.polymer import predict
    assert any("수소결합" in w for w in predict("C=CO")["warnings"]), \
        "PVA 는 수소결합 경고가 있어야 한다"
    assert not predict("C=CC(=O)OC")["warnings"], \
        "에스터(주개 없음)는 경고 없음"


def test_glass_transition_is_quoted_not_predicted():
    """Tg 는 예측하지 않는다 — 문헌값이 없으면 값을 내지 않아야 한다."""
    from server.polymer import glass_transition
    known = glass_transition("C=CC#N")               # PAN
    assert known["available"] and known["tg_c"] == 85 and known["source"] == "문헌"
    unknown = glass_transition("CCCCCCCCCCN")        # 등록되지 않은 구조
    assert unknown["available"] is False and unknown["tg_c"] is None
    assert "45 K" in unknown["note"]                 # 예측하지 않는 이유를 밝힌다
    # 문헌 자체가 흩어지는 항목은 표시된다
    assert glass_transition("FC(F)=C(F)F").get("uncertain") is True


def test_property_card_cross_checks_dft_route():
    """DFT 이량체 결합 에너지로 구한 CED가 구조 회귀와 대조된다."""
    from server import polymer
    card = polymer.property_card({"name": "PAA", "smiles": "C=CC(=O)O"},
                                 {"dimer_binding_kj": -35.0})
    assert card["computed"]["density_g_cm3"] > 1.0
    assert card["dft"]["ced_j_cm3"] > 0
    assert "delta_vs_structure" in card["dft"]      # 두 경로의 차이를 보고한다
    # 미지 구조는 오류가 아니라 빈 카드로 처리
    bad = polymer.property_card({"name": "x", "smiles": "not-a-smiles((("})
    assert bad["errors"] and bad["computed"] is None


def test_convergence_detects_and_extrapolates():
    from server import convergence as cv
    conv = cv.analyze_property("homo_ev", [(2, -8.60), (3, -8.45), (5, -8.42)])
    assert conv["converged"] and conv["status"] == "converged"
    assert conv["extrapolation"]["limit"] < -8.0     # 1/n 외삽 극한값
    not_conv = cv.analyze_property("homo_ev", [(1, -9.10), (2, -8.30), (3, -7.60)])
    assert not not_conv["converged"]
    # 크기값은 판정 대상이 아니다
    ext = cv.analyze_property("total_energy_hartree", [(1, -78.0), (2, -156.0)])
    assert ext["status"] == "extensive"


def test_convergence_refuses_two_point_extrapolation():
    """두 점은 직선이 정확히 지나 1/n 형태를 검증할 수 없으므로 외삽하지 않는다."""
    from server.convergence import extrapolate
    assert extrapolate([(1, -6.1), (2, -7.8)]) is None
    three = extrapolate([(2, -7.8), (3, -8.3), (5, -8.5)])
    assert three is not None and "max_residual" in three


def test_convergence_excludes_vinyl_monomer():
    """비닐 단량체의 n=1 은 포화 사슬과 다른 화학종이라 판정에서 빠진다."""
    from server import convergence as cv
    assert cv.monomer_is_chain_segment("C=C")["same_species"] is False      # PE
    assert cv.monomer_is_chain_segment("C=CC(=O)O")["same_species"] is False  # PAA
    assert cv.monomer_is_chain_segment("COCCOCCOC")["same_species"] is True   # PEO

    series = [{"n": 1, "descriptors": {"homo_ev": -6.1}},
              {"n": 2, "descriptors": {"homo_ev": -7.8}},
              {"n": 3, "descriptors": {"homo_ev": -8.0}}]
    res = cv.analyze(series, base_smiles="C=C")
    assert res["excluded_lengths"] == [1] and res["lengths"] == [2, 3]
    assert res["exclusion_note"] and "비닐" in res["exclusion_note"]
    # 남은 길이가 둘뿐이므로 외삽을 내지 않고 그 이유를 알린다
    assert res["extrapolation_available"] is False and "외삽" in res["warning"]
    # 비닐이 아니면 n=1 을 그대로 쓴다
    keep = cv.analyze(series, base_smiles="COCCOCCOC")
    assert keep["excluded_lengths"] == [] and keep["lengths"] == [1, 2, 3]


def test_minimum_defined_length_flags_missing_bde():
    from server.convergence import minimum_defined_length
    pe = minimum_defined_length("C=C")
    assert pe["bde_min_n"] == 2 and "n=2" in pe["note"]
    paa = minimum_defined_length("C=CC(=O)O")
    assert paa["bde_min_n"] == 1


def test_reference_dataset_is_well_formed():
    """참조셋 47종 — SMILES가 모두 파싱되고 더미가 정확히 2개여야 한다.

    더미 2개는 «반복 단위가 이웃과 붙는 자리»를 뜻한다. 개수가 틀리면 Vw 의
    결합 수 보정이 어긋나 모든 하위 물성이 조용히 밀린다.
    """
    from rdkit import Chem
    from server.polymer import _vw_unit
    from server.reference_polymers import REFERENCE, family_counts
    assert len(REFERENCE) >= 47
    for ab, name, smi, tg, rho, delta, fam, conf in REFERENCE:
        mol = Chem.MolFromSmiles(smi)
        assert mol is not None, f"{ab}: SMILES 파싱 실패 {smi}"
        n_dummy = sum(1 for a in mol.GetAtoms() if a.GetAtomicNum() == 0)
        assert n_dummy == 2, f"{ab}: 더미 {n_dummy}개 (2개여야 함)"
        assert _vw_unit(smi) > 0, f"{ab}: Vw 가 양수가 아님"
        assert 0.5 < rho < 3.0, f"{ab}: 밀도 범위 이상 {rho}"
        assert conf in ("high", "medium")
    # 비닐 주사슬만으로는 새 후보로 외삽되지 않는다 — 계열이 다양해야 한다
    fams = family_counts()
    assert len(fams) >= 6, f"주사슬 계열이 부족합니다: {fams}"
    for required in ("아마이드", "방향족", "에스터", "에터"):
        assert fams.get(required, 0) >= 2, f"{required} 계열이 2종 미만: {fams}"


def test_tg_prediction_still_refused():
    """참조를 47종으로 늘려도 Tg 는 여전히 예측하지 않는다.

    중첩 교차검증 61.6 K, 최대 581 K(PDMS). 참조셋 Tg 표준편차가 89 K 이므로
    평균값을 찍는 것과 크게 다르지 않다. 회귀 계수를 넣는 순간 이 테스트가
    깨져야 한다 — 검증 없이 Tg 를 싣는 것을 막는 장치다.
    """
    import server.polymer as pol
    assert not any("TG" in n.upper() and "COEF" in n.upper() for n in dir(pol)), \
        "Tg 회귀 계수가 추가되었습니다 — 중첩 CV 로 오차를 먼저 확인하세요"
    unknown = pol.glass_transition("CCCCCCCCCCN")
    assert unknown["available"] is False and unknown["tg_c"] is None
