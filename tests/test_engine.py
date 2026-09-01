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
    이를 결합 강건성 통과로 요약하면 근거 없는 합격 판정이 된다.
    """
    from server import binder
    rep = binder.report({"smiles": "C=C"}, {"reduction_potential_v": -4.275})
    assert rep["overall"] == binder.VERDICT_MID          # 양호가 아니라 주의
    assert "결합 강건성" not in rep["summary"].split("통과")[0]
    axes = [u["axis"] for u in rep["unevaluated"]]
    # v2.0 5.4 — BDE 는 「그 온도에서 버티는가」가 아니라 결합 강도 지표다
    assert axes == ["결합 강건성"]
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


def test_elastic_relations_are_exact_and_invertible():
    """탄성 관계식은 적합이 아니라 정확한 물리 — 왕복해도 값이 보존된다."""
    from server.mechanical import elastic_constants
    a = elastic_constants(e_gpa=3.2, poisson=0.33, density_g_cm3=1.05)
    back = elastic_constants(bulk_gpa=a["bulk_gpa"], shear_gpa=a["shear_gpa"])
    assert back["e_gpa"] == pytest.approx(3.2, abs=1e-3)
    assert back["poisson"] == pytest.approx(0.33, abs=1e-3)
    # 종파는 항상 횡파보다 빠르다
    assert a["longitudinal_wave_m_s"] > a["shear_wave_m_s"]
    with pytest.raises(ValueError):
        elastic_constants(e_gpa=3.0, poisson=0.5)      # ν = 0.5 는 비압축성 극한
    with pytest.raises(ValueError):
        elastic_constants(e_gpa=3.0)                   # 한 쌍을 주어야 한다


def test_elastic_prediction_is_refused():
    """탄성 상수는 예측하지 않는다 — 검증에서 «평균 찍기»에 졌다."""
    from server import mechanical
    for t in mechanical.REFUSAL["targets"]:
        assert t["nested_cv"] > t["mean_baseline"], \
            f"{t['key']}: 검증을 통과했다면 예측을 실어야 합니다"
    unknown = mechanical.literature_elastic("C=CCCCCN")
    assert unknown["available"] is False and unknown["e_gpa"] is None
    known = mechanical.literature_elastic("C=Cc1ccccc1")          # PS
    assert known["available"] and known["e_gpa"] == 3.2


def test_state_gate_separates_crystalline_from_rubbery():
    """Tg 위여도 반결정성이면 고무질이 아니다 — 결정이 하중을 받는다."""
    from server.mechanical import state_at
    # PTFE: Tg −73, Tm 327 → 180 °C 에서 결정이 남아 있다
    ptfe = state_at("FC(F)=C(F)F", 180)
    assert ptfe["state"].startswith("반결정") and ptfe["tm_c"] == 327
    # PE: Tm 135 → 180 °C 는 용융
    assert state_at("C=C", 180)["state"] == "용융"
    # PAN: 녹지 않고 분해한다
    assert state_at("C=CC#N", 180)["state"] == "반결정 (융해 없음)"
    # PAA: 비정질이라 융점 자체가 없다 — 「반결정」으로 부르면 안 된다
    paa = state_at("C=CC(=O)O", 180)
    assert paa["state"] == "고무질" and paa["decomp_c"] == 200
    # 상온에서는 유리질
    assert state_at("C=CC(=O)O", 25)["state"] == "유리질"


def test_state_gate_holds_judgement_near_tg():
    """Tg 근처에서는 단일 상태를 주장하지 않는다."""
    from server.mechanical import state_at
    near = state_at("C=CC(=O)O", 106)              # PAA Tg = 106 °C
    assert near["state"] == "전이 구간" and near["confident"] is False
    unknown = state_at("C=CCCCCN", 25)             # Tg 문헌값 없음
    assert unknown["state"] == "불가" and unknown["confident"] is False


def test_rubbery_modulus_scales_with_entanglement():
    """고무 탄성 E = 3ρRT/Me — Me 가 커지면 무르고, 온도가 오르면 단단해진다."""
    from server.mechanical import rubbery_modulus
    soft = rubbery_modulus(0.855, 453.15, 2400)
    stiff = rubbery_modulus(0.855, 453.15, 1200)
    # Me 를 절반으로 줄이면 정확히 두 배 — 반올림(소수 3자리)만큼만 허용
    assert stiff["e_mpa"] == pytest.approx(2 * soft["e_mpa"], abs=0.002)
    hotter = rubbery_modulus(0.855, 500.0, 1200)
    assert hotter["e_mpa"] > stiff["e_mpa"]
    # 유리질(GPa)보다 두 자릿수 이상 낮아야 한다
    assert stiff["e_gpa"] < 0.1
    with pytest.raises(ValueError):
        rubbery_modulus(0.855, 453.15, 0)


def test_esw_containment_uses_whole_operating_range():
    """판정은 포함 관계다 — 전극 구동 «범위 전체»가 ESW 안에 들어와야 안정하다.

    한 점(0.1 V)만 보면 구동 범위 중간에서 분해되는 경우를 놓친다.
    """
    from server.esw import ELECTRODE_BY_KEY, containment
    gr = ELECTRODE_BY_KEY["graphite"]
    assert gr["low"] == 0.01 and gr["high"] == 0.25
    # 환원 전위가 구동 범위 하단보다 위 → 그 구간에서 환원된다
    bad = containment(0.60, 5.5, gr)
    assert bad["verdict"] != "안정"
    assert any(f["side"] == "환원" for f in bad["fails"])
    assert bad["reduce_gap_v"] == pytest.approx(0.59, abs=1e-6)
    # 0.1 V 한 점만 보면 통과하지만 범위 하단(0.01 V)에서는 환원되는 경우
    edge = containment(0.05, 5.5, gr)
    assert edge["verdict"] != "안정", "한 점 기준이었다면 놓쳤을 사례"
    # 구동 범위 전체가 안쪽 → 안정
    ok = containment(-1.97, 6.03, gr)
    assert ok["verdict"] == "안정" and not ok["fails"]


def test_esw_detects_conjugated_vinyl_as_reduction_risk():
    """스타이렌의 «방향족과 공액된 비닐»이 환원 취약 작용기로 잡혀야 한다."""
    from server.esw import reducible_groups
    names = [g["name"] for g in reducible_groups("C=Cc1ccccc1")]
    assert "방향족과 공액된 비닐" in names
    assert names[0] == "방향족과 공액된 비닐", "가장 강한 원인이 먼저 와야 한다"
    # 포화 사슬에는 아무 것도 없어야 한다 — 중합되면 C=C 가 사라진다
    assert reducible_groups("CCCC") == []
    assert "나이트릴 (C≡N)" in [g["name"] for g in reducible_groups("C=CC#N")]


def test_esw_causal_chain_is_labelled_measured_or_interpreted():
    """사슬의 각 단계가 계산값인지 해석인지 구분되어야 한다."""
    from server.esw import diagnose
    desc = {"lumo_ev": -0.30, "ea_adiabatic_ev": 0.90,
            "reduction_potential_v": -0.54, "oxidation_potential_v": 5.6}
    d = diagnose({"name": "Styrene", "smiles": "C=Cc1ccccc1"}, desc)
    assert d["available"] is True
    chain = {c["label"]: c for c in d["chain"]}
    assert chain["LUMO"]["measured"] is True
    assert chain["환원 전위"]["measured"] is True
    assert chain["구조"]["measured"] is False, "작용기 귀속은 해석이지 계산이 아니다"
    assert chain["판정"]["measured"] is False
    # E_red = EA − 1.44 항등식이 사슬에 드러나야 한다
    assert "1.44" in chain["환원 전위"]["note"]
    assert len(d["all_electrodes"]) == len(d["electrodes"])


def test_esw_diagnose_reports_missing_potentials():
    """전위가 없으면 조용히 빠지지 않고 이유와 해결책을 말한다."""
    from server.esw import diagnose
    d = diagnose({"name": "X", "smiles": "C=Cc1ccccc1"}, {"lumo_ev": -0.3})
    assert d["available"] is False and "산화/환원 전위" in d["note"]


def test_esw_chain_identity_holds_on_screen():
    """3단계 EA 와 4단계 전위는 E_red = EA − E_abs 를 만족해야 한다.

    ΔG 기반 전위를 쓰면서 단열 EA 를 보여주면 화면에서 항등식이 깨져 보인다.
    실제 스타이렌 값(단열 1.734 / ΔG 1.884)에서 0.15 eV 어긋났던 사례다.
    """
    from server.esw import diagnose
    full = {"lumo_ev": -1.126, "ea_vertical_ev": -0.505, "ea_adiabatic_ev": 1.734,
            "ea_gibbs_ev": 1.884, "reduction_potential_v": 0.294,
            "reduction_potential_gibbs_v": 0.444, "oxidation_potential_v": 4.573,
            "oxidation_potential_gibbs_v": 4.549}
    for desc in (full, {k: v for k, v in full.items() if "gibbs" not in k}):
        chain = {c["step"]: c for c in
                 diagnose({"name": "S", "smiles": "C=Cc1ccccc1"}, desc)["chain"]}
        assert chain[3]["value"] - 1.44 == pytest.approx(chain[4]["value"], abs=1e-6)


def test_esw_separates_partial_from_whole_range_decomposition():
    """구동 범위 «안»에서 환원되는 것과 «들어가기 전»에 환원되는 것은 다르다."""
    from server.esw import ELECTRODE_BY_KEY, containment
    gr, si = ELECTRODE_BY_KEY["graphite"], ELECTRODE_BY_KEY["si"]
    # 스타이렌 실측: E_red +0.444 V
    on_graphite = containment(0.444, 4.549, gr)     # 0.444 > 0.25 (범위 상단)
    assert on_graphite["verdict"] == "분해 우려"
    assert "전 구간" in on_graphite["summary"]
    on_si = containment(0.444, 4.549, si)           # 0.05 ~ 0.60 사이에 들어옴
    assert on_si["verdict"] == "경계"
    assert "일부 구간" in on_si["summary"]


def test_esw_ea_stages_show_where_verdict_flips():
    """수직 → 단열 → ΔG 로 가며 환원 전위가 어떻게 올라가는지 단계로 낸다."""
    from server.esw import ea_stages
    st = ea_stages({"ea_vertical_ev": -0.505, "ea_adiabatic_ev": 1.734,
                    "ea_gibbs_ev": 1.884})["steps"]
    assert [s["key"] for s in st] == ["ea_vertical_ev", "ea_adiabatic_ev", "ea_gibbs_ev"]
    assert st[0]["reduction_v"] == pytest.approx(-1.945, abs=1e-3)   # 안전해 보임
    assert st[-1]["reduction_v"] == pytest.approx(0.444, abs=1e-3)   # 실제는 위험
    assert st[1]["delta_ev"] == pytest.approx(2.239, abs=1e-3)       # 구조 완화+용매화


def test_first_present_falls_back_over_null_values():
    """키가 None 값으로 «존재»해도 다음 후보로 넘어가야 한다.

    dict.get(a, desc.get(b)) 는 a 가 None 으로 존재하면 폴백하지 않는다.
    엔진은 값이 있을 때만 키를 쓰지만, API로 외부에서 넘어온 descriptors 나
    예전에 저장된 결과에는 None 이 섞일 수 있다.
    """
    from server.esw import first_present
    assert first_present({"a": None, "b": 2.0}, "a", "b") == 2.0
    assert first_present({"a": 1.0, "b": 2.0}, "a", "b") == 1.0
    assert first_present({"b": 2.0}, "a", "b") == 2.0
    assert first_present({"a": None, "b": None}, "a", "b") is None
    assert first_present({}, "a", "b") is None
    assert first_present({"a": 0.0, "b": 2.0}, "a", "b") == 0.0   # 0 은 값이다


def test_null_gibbs_potentials_fall_back_to_adiabatic():
    """ΔG 전위가 None 으로 존재하면 단열 전위로 판정해야 한다.

    이 경로에서 단열 전위 0.294 V 를 두고 「전위 없음」으로 처리하던 버그가 있었다.
    """
    from server import screening
    from server.esw import diagnose
    desc = {"lumo_ev": -1.126, "ea_adiabatic_ev": 1.734,
            "reduction_potential_v": 0.294, "oxidation_potential_v": 4.573,
            "reduction_potential_gibbs_v": None, "oxidation_potential_gibbs_v": None}
    d = diagnose({"name": "스타이렌", "smiles": "C=Cc1ccccc1"}, desc)
    assert d["available"] is True
    assert d["reduction_potential_v"] == pytest.approx(0.294)
    assert d["containment"]["verdict"] == "분해 우려"
    assert screening._potentials(desc) == (0.294, 4.573)
    # ΔG 가 실제로 있으면 그쪽이 우선이어야 한다 (회귀 방지)
    with_g = {**desc, "reduction_potential_gibbs_v": 0.444,
              "oxidation_potential_gibbs_v": 4.549}
    assert screening._potentials(with_g) == (0.444, 4.549)


def test_null_thermal_bde_falls_back_to_electronic():
    """bde_min_298_kj 가 None 이면 bde_min_kj 로 채점해야 한다.

    열보정을 안 한 결과가 섞이면 화학적 안정성 축이 통째로 결측으로 잡혔다.
    """
    from server import scoring
    axes = scoring.axis_scores({"bde_min_298_kj": None, "bde_min_kj": 310.0},
                               0.5, ["graphite"])
    assert axes["chemstab"]["value"] == 310.0
    assert axes["chemstab"]["score"] is not None
    assert axes["chemstab"]["note"] is None
    # 298 K 값이 있으면 그쪽 우선
    axes2 = scoring.axis_scores({"bde_min_298_kj": 300.0, "bde_min_kj": 310.0},
                                0.5, ["graphite"])
    assert axes2["chemstab"]["value"] == 300.0


def test_redox_reference_is_a_convention_not_an_identity():
    """1.44 V 는 자연상수가 아니라 «채택한 기준 변환 규약»이다 (v2.0 P0-2).

    규약을 바꾸면 전위가 통째로 이동한다. 그 사실이 값에 남아 있어야 다른
    그룹의 계산과 비교할 수 있다.
    """
    from server import protocol
    a = protocol.redox_from_ea(1.884, "Li/Li+ (1.44 V)")
    b = protocol.redox_from_ea(1.884, "Li/Li+ (1.40 V)")
    assert a["value_v"] == pytest.approx(0.444, abs=1e-6)
    assert b["value_v"] == pytest.approx(0.484, abs=1e-6)
    assert b["value_v"] - a["value_v"] == pytest.approx(0.04, abs=1e-6)
    for key in ("convention", "absolute_v", "electrode", "formula"):
        assert a[key]
    assert protocol.convention(a["convention"])["source"]


def test_qrrho_only_matters_for_floppy_molecules():
    """준조화 보정은 저진동수 모드가 있을 때만 유의미해야 한다 (v2.0 P0-3).

    강체 분자에서 큰 보정이 나오면 구현이 잘못된 것이다.
    """
    from server import thermo
    floppy = thermo.quasi_rrho_entropy([25, 42, 68, 95, 140, 900, 2950], 298.15)
    rigid = thermo.quasi_rrho_entropy([620, 880, 1200, 1600, 3000, 3100], 298.15)
    # 조화 근사는 저진동수 엔트로피를 과대평가한다 → 보정하면 엔트로피가 줄고 G 는 오른다
    assert floppy["delta_s_j_mol_k"] < 0 and floppy["delta_g_kcal"] > 0.5
    assert abs(rigid["delta_g_kcal"]) < 0.05
    assert floppy["n_low_freq"] == 4 and rigid["n_low_freq"] == 0


def test_standard_state_correction_matches_literature():
    """1 atm → 1 M 보정은 298.15 K 에서 +1.89 kcal/mol."""
    from server import thermo
    ss = thermo.standard_state_correction(298.15)
    assert ss["delta_g_kcal"] == pytest.approx(1.89, abs=0.01)
    assert thermo.standard_state_correction(350.0)["delta_g_kcal"] > ss["delta_g_kcal"]


def test_anion_basis_is_separate_and_recorded():
    """음이온에는 diffuse 기저를 따로 쓸 수 있어야 한다 (v2.0 P0-1)."""
    from server import presets
    from server.engine import _resolve_params
    p = _resolve_params(_settings(accuracy="표준"))
    assert p["basis_anion"] == "ma-def2-tzvp" and p["basis_anion"] != p["basis_sp"]
    assert _resolve_params(_settings(accuracy="빠름"))["basis_anion"] is None
    # 전문가 설정이 프리셋보다 우선
    p2 = _resolve_params(_settings(accuracy="표준", expert={"basisAnion": "def2-tzvpd"}))
    assert p2["basis_anion"] == "def2-tzvpd"
    for b in presets.DIFFUSE_BASIS_SETS:
        assert b in presets.BASIS_SETS


def test_confidence_is_five_axes_and_capped_by_calibration():
    """정밀한 계산과 정확한 예측을 분리한다 (v2.0 P0-8).

    참조 데이터셋 검증이 없으면 다른 축이 아무리 좋아도 전체는 Low 다.
    """
    from server import protocol
    perfect = {"zpe_kcal": 80.0, "n_imaginary_freqs": 0,
               "reduction_potential_gibbs_v": -2.0}
    c = protocol.confidence(perfect, {"envType": "진공·기체"},
                            redox_basis="def2-tzvpd", chain_converged=True)
    by = {a["key"]: a["level"] for a in c["axes"]}
    assert by["numerical"] == "High" and by["model"] == "High"
    assert by["calibration"] == "Low"
    assert c["overall"] == "Low", "한 축의 약점이 평균에 가려지면 안 된다"
    assert len(c["axes"]) == 5


def test_mixture_solvation_is_labelled_as_approximation():
    """부피 가중 SMD 혼합은 «검증된 혼합용매»가 아니다 (v2.0 P0-4)."""
    from server import protocol
    mix = protocol.environment_level(
        {"envType": "배터리 전해액",
         "customMixedSolvent": {"components": [{"abbr": "EC", "ratio": 3}]}})
    assert mix["level"] == "L1" and mix["confidence_cap"] == "Medium"
    assert "근사" in mix["label"]
    pure = protocol.environment_level({"envType": "배터리 전해액", "solventId": "sol-ec"})
    assert pure["level"] == "L0" and pure["confidence_cap"] == "High"


def test_validation_separates_software_from_science():
    """«테스트 119건 통과»는 소프트웨어 증거이지 예측 정확도 증거가 아니다 (v2.0 1.2)."""
    from server import protocol
    st = {s["stage"][0]: s["status"] for s in protocol.validation_status()["stages"]}
    assert st["A"] == "통과"
    assert st["C"] == "미실시" and st["D"] == "미실시"


def test_hard_gate_uses_uncertainty_band():
    """임계값 근처 후보를 점추정만으로 탈락시키지 않는다 (v2.0 6.3)."""
    from server.esw import ELECTRODE_BY_KEY, gate_with_uncertainty
    gr = ELECTRODE_BY_KEY["graphite"]
    assert gate_with_uncertainty(-1.97, 6.03, gr)["grade"] == "Robust Pass"
    assert gate_with_uncertainty(0.444, 4.55, gr)["grade"] == "Robust Fail"
    # 점추정으로는 «안정»이지만 구간이 임계값과 겹치는 후보는 보류해야 한다
    border = gate_with_uncertainty(-0.10, 5.0, gr)
    assert border["grade"] == "Borderline" and border["point_verdict"] == "안정"
    assert "잠정" in border["uncertainty_source"] or "검증" in border["uncertainty_source"]


def test_convergence_thresholds_follow_property_type():
    """물성마다 수렴 기준이 달라야 한다 (v2.0 4.4)."""
    from server import convergence as c
    assert c.THRESHOLDS["reduction_potential_v"] == 0.10   # 판정에 직접 쓰이는 값
    assert c.THRESHOLDS["gap_ev"] == 0.15                  # 정성 지표는 느슨하게
    assert c.THRESHOLDS["li_binding_kj"] == 10.0
    # 쌍극자는 사슬 길이에 딸려 커지므로 절대 임계값으로 판정하지 않는다
    r = c.analyze_property("dipole_debye", [(2, 0.5), (3, 0.9), (5, 1.4)])
    assert r["status"] == "size_dependent" and "환산" in r["note"]
