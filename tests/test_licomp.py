"""Li⁺ 용매 경쟁 — v2.0 개정 기획서 P0-6 · 5.2.

클러스터 초기 구조 · 결합 site 탐색 · ΔE_exchange 조합·판정 · 참조 캐시 ·
Score 축 전환 · 프리셋 · sto-3g 실계산 (물 용매, Li(H2O)2⁺ 참조).
"""

import json

import numpy as np
import pytest

from server import licomp, presets, scoring


def _settings(**over):
    s = {**presets.DEFAULT_SETTINGS, "expert": dict(presets.DEFAULT_SETTINGS["expert"])}
    exp = over.pop("expert", {})
    s.update(over)
    s["expert"].update(exp)
    return s


# ---------------------------------------------------------------- 기하
def test_li_cluster_puts_coordinating_atoms_at_li_distance():
    """Li(EC)n⁺ 초기 구조 — 배위 O 가 Li 에서 1.95 Å, 용매끼리 겹치지 않는다."""
    for n in (2, 3, 4, 6):
        atoms, frags = licomp.build_li_cluster("O=C1OCCO1", n)
        assert atoms[0][0] == "Li" and len(frags) == n + 1
        xyz = np.array([a[1:4] for a in atoms])
        d_li = np.linalg.norm(xyz[1:] - xyz[0], axis=1)
        # 분자마다 정확히 하나의 원자(카보닐 O)가 1.95 Å — 나머지는 더 멀다
        assert int(np.sum(np.isclose(d_li, licomp.LI_DIST, atol=1e-6))) == n
        assert d_li.min() >= licomp.LI_DIST - 1e-6
        # 용매 분자 간 최소 거리 — 겹침 없음
        for fa in frags[1:]:
            for fb in frags[1:]:
                if fa["start"] >= fb["start"]:
                    continue
                a, b = xyz[fa["start"]:fa["end"]], xyz[fb["start"]:fb["end"]]
                assert np.linalg.norm(a[:, None] - b[None], axis=2).min() > 1.6
    # 물 — 배위 원자는 O
    atoms, _ = licomp.build_li_cluster("O", 4)
    assert sum(1 for a in atoms if a[0] == "O") == 4


def test_coordinating_atom_prefers_carbonyl_then_ether():
    from rdkit import Chem
    mol = Chem.AddHs(Chem.MolFromSmiles("CCOC(=O)OC"))     # EMC — 카보닐 O 가 우선
    idx = licomp.coordinating_atom(mol)
    assert mol.GetAtomWithIdx(idx).GetSymbol() == "O"
    assert licomp.atom_kind(mol.GetAtomWithIdx(idx)) == "카보닐 O"
    mol = Chem.AddHs(Chem.MolFromSmiles("COC"))            # 에테르만 있으면 에테르 O
    assert licomp.atom_kind(mol.GetAtomWithIdx(licomp.coordinating_atom(mol))) == "에테르 O"
    mol = Chem.AddHs(Chem.MolFromSmiles("CC#N"))
    assert licomp.atom_kind(mol.GetAtomWithIdx(licomp.coordinating_atom(mol))) == "나이트릴 N"


def test_li_sites_finds_heteroatoms_and_dedupes_with_mep():
    from server.geometry import smiles_to_xyz
    atoms, _ = smiles_to_xyz("CC(=O)OC", n_conformers=1)          # 아세트산메틸
    sites = licomp.li_sites(atoms, "CC(=O)OC", mep_site=None, max_sites=4)
    kinds = [s["kind"] for s in sites]
    assert kinds[0] == "카보닐 O" and "에테르 O" in kinds
    # Li 는 배위 원자에서 1.95 Å
    xyz = np.array([a[1:4] for a in atoms])
    for s in sites:
        assert abs(np.linalg.norm(np.array(s["pos"]) - xyz[s["atom"] - 1]) - licomp.LI_DIST) < 1e-6
    # MEP 최소점이 카보닐 site 와 겹치면 하나로 합쳐진다
    mep = sites[0]["pos"]
    merged = licomp.li_sites(atoms, "CC(=O)OC", mep_site=mep, max_sites=4)
    assert merged[0]["kind"] == "MEP" and sum(1 for s in merged if s["kind"] == "카보닐 O") == 0
    # max_sites=1 이면 예전 동작 — MEP 하나
    assert [s["kind"] for s in licomp.li_sites(atoms, "CC(=O)OC", mep_site=mep, max_sites=1)] == ["MEP"]
    # 원자 순서가 다르면 헤테로 site 를 만들지 않는다
    assert licomp.li_sites(atoms[::-1], "CC(=O)OC", mep_site=mep, max_sites=4) == [
        {"label": "MEP 최소점", "kind": "MEP", "atom": None, "pos": [float(x) for x in mep]}]
    # 헤테로원자가 없는 분자 — 폴백 site 하나
    at2, _ = smiles_to_xyz("CCC", 1)
    assert licomp.li_sites(at2, "CCC", None, 3)[0]["kind"] == "fallback"


# ---------------------------------------------------------------- 에너지·판정
def test_exchange_energy_and_verdict():
    ref = {"n": 2, "e_cluster": -100.0, "e_solvent": -20.0, "e_li": -7.0}
    # ΔE = E(BLi) + 2E(S) − E(B) − E(LiS2) = (-60) + (-40) − (-50) − (-100) = +50 Ha… 단위만 확인
    assert licomp.exchange_kj(-60.0, -50.0, ref) == pytest.approx(50.0 * licomp.HARTREE2KJ)
    assert licomp.verdict(-80.0)["key"] == "trapping"
    assert licomp.verdict(10.0)["key"] == "competitive"
    assert licomp.verdict(150.0)["key"] == "solvent"
    assert licomp.verdict(None)["key"] == "n/a"


def test_summarize_picks_strongest_site_and_primary_solvent():
    sites = [{"label": "MEP", "kind": "MEP", "e_complex": -110.0, "binding_kj": -180.0},
             {"label": "O2 (에테르 O)", "kind": "에테르 O", "e_complex": -109.99, "binding_kj": -120.0}]
    e_binder = -102.0
    # EC 가 DMC 보다 용매화가 강하다 → EC 가 기준 용매
    refs = [{"abbr": "EC", "name": "EC", "n": 4, "e_cluster": -400.0, "e_solvent": -98.0,
             "e_li": -7.0, "solvation_kj_per_molecule": -150.0, "cached": True},
            {"abbr": "DMC", "name": "DMC", "n": 4, "e_cluster": -399.9, "e_solvent": -98.0,
             "e_li": -7.0, "solvation_kj_per_molecule": -100.0, "cached": False}]
    s = licomp.summarize(sites, refs, e_binder, 298.15, "competition", 4)
    assert s["primary_solvent"] == "EC" and s["strongest_site"] == "MEP"
    assert s["binding_min_kj"] == -180.0 and s["n_sites"] == 2
    # 첫 site 가 훨씬 안정 → 분포 거의 100 %
    assert s["sites"][0]["population_pct"] > 99
    ex_mep_ec = (-110.0 + 4 * -98.0 - e_binder - (-400.0)) * licomp.HARTREE2KJ
    assert s["sites"][0]["exchange_kj"]["EC"] == pytest.approx(ex_mep_ec, abs=0.1)
    assert s["exchange_min_kj"] == min(r["exchange_primary_kj"] for r in s["sites"])
    assert s["verdict"]["key"] in ("trapping", "competitive", "solvent")
    assert "ΔE_exchange" in s["note"]
    # 참조가 없으면 결합만 — 경쟁 미계산 문구
    s0 = licomp.summarize(sites, [], e_binder, 298.15, "bare", 4)
    assert "exchange_min_kj" not in s0 and "미계산" in s0["note"]


def test_reference_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(licomp, "_CACHE_OVERRIDE", tmp_path / "li_ref.json")
    params = {"functional": "PBE0-D3(BJ)", "basis_opt": "def2-svp", "basis_sp": "def2-tzvp",
              "disp": "d3bj", "do_opt": True, "opt_in_solvent": False, "scf_tol": 1e-8}
    comp = {"abbr": "EC", "name": "Ethylene carbonate", "smiles": "O=C1OCCO1"}
    calls = []

    def compute():
        calls.append(1)
        return {"e_cluster": -400.0, "e_solvent": -98.0, "e_li": -7.0, "optimized": True, "n_atoms": 41}

    r1 = licomp.get_reference(comp, 4, params, "smd:ec", compute)
    assert r1["cached"] is False and len(calls) == 1
    assert r1["solvation_kj_per_molecule"] == pytest.approx((-400 + 7 + 4 * 98) * licomp.HARTREE2KJ / 4, abs=0.1)
    r2 = licomp.get_reference(comp, 4, params, "smd:ec", compute)
    assert r2["cached"] is True and len(calls) == 1 and r2["e_cluster"] == -400.0
    # 프로토콜이 다르면 다른 키
    licomp.get_reference(comp, 4, {**params, "basis_sp": "def2-svp"}, "smd:ec", compute)
    assert len(calls) == 2
    assert len(licomp.list_references()) == 2
    assert json.loads((tmp_path / "li_ref.json").read_text(encoding="utf-8"))


def test_solvent_components_from_settings():
    assert licomp.solvent_components(_settings(envType="진공·기체")) == []
    one = licomp.solvent_components(_settings(solventId="sol-ec"))
    assert [c["abbr"] for c in one] == ["EC"]
    mix = licomp.solvent_components(_settings(solventId="sol-ecdmc"))
    assert [c["abbr"] for c in mix] == ["EC", "DMC"]
    custom = licomp.solvent_components(_settings(
        customMixedSolvent={"name": "EC/EMC 3:7", "components": [{"abbr": "EC", "ratio": 3},
                                                                 {"abbr": "EMC", "ratio": 7}]}))
    assert [(c["abbr"], c["ratio"]) for c in custom] == [("EC", 3.0), ("EMC", 7.0)]


# ---------------------------------------------------------------- 프리셋 · Score
def test_resolve_params_li_model_presets():
    from server.engine import _resolve_params
    p = _resolve_params(_settings(accuracy="표준"))
    assert p["li_model"] == "bare" and p["li_max_sites"] == 1 and p["li_coordination"] == 4
    p = _resolve_params(_settings(accuracy="정밀"))
    assert p["li_model"] == "competition" and p["li_max_sites"] == 3
    p = _resolve_params(_settings(accuracy="빠름", expert={"liModel": "competition",
                                                          "liCoordination": 2, "liMaxSites": 2}))
    assert p["li_model"] == "competition" and p["li_coordination"] == 2 and p["li_max_sites"] == 2
    with pytest.raises(ValueError):
        _resolve_params(_settings(expert={"liModel": "magic"}))


def test_ion_axis_switches_to_solvent_competition():
    bare = scoring.axis_scores({"li_binding_kj": -180.0}, None, ["graphite"])["ion"]
    assert bare["basis"] == "bare_li" and bare["score"] == 100.0 and "탈용매화" in bare["note"]
    comp = scoring.axis_scores({"li_binding_kj": -180.0, "li_exchange_kj": 10.0,
                                "li_exchange_solvent": "EC"}, None, ["graphite"])["ion"]
    assert comp["basis"] == "solvent_competition" and comp["value"] == 10.0 and comp["score"] == 100.0
    trap = scoring.axis_scores({"li_exchange_kj": -140.0}, None, ["graphite"])["ion"]
    assert trap["score"] == 0.0            # −40 보다 100 아래 → 0점
    none = scoring.axis_scores({}, None, ["graphite"])["ion"]
    assert none["score"] is None


def test_protocol_card_marks_competition_model():
    from server import protocol
    from server.engine import _resolve_params
    s = _settings(accuracy="정밀")
    on = protocol.card(s, _resolve_params(s))
    assert on["li_model"] == "solvent_competition(n=4)"
    off = protocol.card(_settings(accuracy="표준"), _resolve_params(_settings(accuracy="표준")))
    assert "li_model" not in off


# ---------------------------------------------------------------- 실계산 (sto-3g, 물)
def test_li_interaction_real_scf_with_water_reference(monkeypatch):
    """메탄올 + 물 용매 — Li(H2O)2⁺ 참조를 새로 만들고 두 번째 호출은 캐시를 쓴다."""
    from server import descriptors as desc_mod
    from server import engine
    from server.geometry import smiles_to_xyz
    settings = _settings(envType="사용자 정의", solventId="sol-water", accuracy="빠름",
                         expert={"basis": "sto-3g", "nConformers": 1, "liModel": "competition",
                                 "liCoordination": 2, "liMaxSites": 3})
    params = engine._resolve_params(settings)
    solvent_key = engine._solvent_key(settings)
    # 고립 Li⁺ 의 SMD DFT 는 격자 생성이 수십 초 걸리는 진단용 상수 — 고정값으로 대체
    monkeypatch.setattr(engine, "_li_ion_energy", lambda p, sk, log: -7.301)
    atoms, _ = smiles_to_xyz("CO", n_conformers=1)
    mol = engine._build_mol(atoms, params["basis_sp"], 0, 1)
    mf = engine._make_mf(mol, params["xc"], params["disp"], solvent_key, params["scf_tol"])
    logs = []
    e_total = engine._run_scf(mf, "메탄올", logs.append)
    mep = desc_mod.mep_extremes(mf, mol)
    assert mep
    out = engine._li_interaction(atoms, mol, e_total, "CO", params, settings, solvent_key,
                                 298.15, mep, logs.append, lambda n, p: None, site_search=True)
    d = out["descriptors"]
    li = d["li_interaction"]
    assert d["li_binding_kj"] < 0 and li["n_sites"] >= 1
    assert li["model"] == "competition" and li["coordination"] == 2
    assert li["references"] and li["references"][0]["abbr"] == "H2O"
    assert li["references"][0]["cached"] is False
    assert "li_exchange_kj" in d and d["li_exchange_solvent"] == "H2O"
    assert li["verdict"]["key"] in ("trapping", "competitive", "solvent")
    assert "li_complex" in out["structures"]
    assert any("ΔE_exchange" in n for n in out["notes"])
    # 두 번째 호출 — 참조는 캐시에서 온다
    out2 = engine._li_interaction(atoms, mol, e_total, "CO", params, settings, solvent_key,
                                  298.15, mep, logs.append, lambda n, p: None, site_search=True)
    assert out2["descriptors"]["li_interaction"]["references"][0]["cached"] is True
    assert any("캐시 재사용" in l for l in logs)
