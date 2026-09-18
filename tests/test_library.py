"""분자 라이브러리 — 기본 레코드 · 등록/검증 · 검색 4종 · 혼합 용매 비율(부피·몰·질량) · 계산 설정 연결."""

import json

import pytest

from server import library, presets, store


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return library


def _ids(res):
    return [r["id"] for r in res["rows"]]


def test_builtin_records_cover_presets_and_solvents(lib):
    mols = {m["id"]: m for m in lib.molecules()}
    for mat in presets.MATERIALS:                          # 소재 프리셋 → 바인더 모노머 (약어·영어 이름)
        rec = mols["MOL-" + mat["id"].upper()]
        assert rec["presetId"] == mat["id"] and rec["category"] == "monomer"
        assert all(ord(ch) < 0x3130 or ch in "·" for ch in rec["name"])   # 한글 없음
    for sol in [s for s in presets.SOLVENTS if s["kind"] == "single"]:   # 용매 프리셋 → 용매 역할 레코드
        rec = next(m for m in mols.values() if m.get("solventId") == sol["id"])
        assert "solvent" in rec["roles"] and "solute" in rec["roles"] and rec["density"]
    assert mols["MOL-WATER"]["name"] == "Water"
    assert mols["MOL-TFSI"]["charge"] == -1 and mols["MOL-LIPF6"]["fragments"] == 2
    assert any(m["id"].startswith("MOL-BENCH-") for m in mols.values())   # 벤치마크 올리고머
    assert {x["id"] for x in lib.mixtures()} >= {"sol-ecdmc"}


def test_listing_has_svg_solvent_view_and_job_links(lib):
    job = {"id": "JOB-X1", "status": "PUBLISHED", "createdAt": 1, "finishedAt": 2,
           "material": {"id": None, "name": "custom", "smiles": "C(=C)C#N"},      # AN — 다른 표기
           "settings": {"structure": "모노머", "envType": "진공·기체", "expert": {}},
           "result": {"descriptors": {"homo_ev": -7.1, "lumo_ev": -0.9, "gap_ev": 6.2},
                      "conditions": {"method": "PBE0/def2-SVP", "solvent_model": "vacuum"}}}
    out = lib.listing(jobs=[job])
    an = next(m for m in out["molecules"] if m["id"] == "MOL-AN")
    assert an["svg"].startswith("<svg") and an["n_jobs"] == 1 and an["jobs"][0]["homo"] == -7.1
    ec = next(m for m in out["molecules"] if m["id"] == "MOL-EC")
    assert ec["solvent"]["eps"] == pytest.approx(89.78) and ec["solvent"]["density"]
    assert next(m for m in out["molecules"] if m["id"] == "MOL-FEC")["solvent"] is None
    assert "smd" not in an and json.dumps(out)


def test_parse_reports_errors_and_existing(lib):
    assert "괄호" in lib.parse("C(C")["error"]
    assert "고리 번호" in lib.parse("C1CC")["error"]
    v = lib.parse("CN(C)(C)(C)C")
    assert not v["ok"] and "원자가" in v["error"] and "원자 2" in v["error"]
    assert "Li" in lib.parse("CCLi")["error"] and "[Li+]" in lib.parse("CCLi")["error"]   # 대괄호 없는 원소
    ok = lib.parse("O=C1OCCO1")
    assert ok["ok"] and ok["existing"] == "MOL-EC" and ok["formula"] == "C3H4O3"
    inchi = lib.parse("InChI=1S/C3H4O3/c4-3-5-1-2-6-3/h1-2H2")
    assert inchi["ok"] and inchi["existing"] == "MOL-EC"


def test_add_update_delete_user_molecule(lib):
    rec = lib.add_molecule({"smiles": "CC1COC(=O)O1", "name": "PC", "full": "Propylene carbonate",
                            "category": "solvent", "roles": ["solvent", "solute"],
                            "smd": {"n": 1.4189, "eps": 64.9, "beta": 0.40, "gamma": 60.0}, "density": 1.205})
    assert rec["id"].startswith("MOL-U") and rec["formula"] == "C4H6O3" and rec["smd"][5] == 64.9
    assert lib.get(rec["id"])["name"] == "PC"
    with pytest.raises(ValueError, match="이미 라이브러리"):
        lib.add_molecule({"smiles": "O=C1OC(C)CO1"})                 # 같은 구조 다른 표기
    with pytest.raises(ValueError, match="SMD"):
        lib.add_molecule({"smiles": "CCOCC", "roles": ["solvent"]})   # 용매인데 SMD 없음
    lib.update_molecule(rec["id"], {"tags": ["고유전율", "고유전율"], "fav": True})
    assert lib.get(rec["id"])["tags"] == ["고유전율"] and lib.get(rec["id"])["fav"] is True
    lib.update_molecule("MOL-EC", {"fav": True, "note": "표준"})           # 기본 레코드는 덮어쓰기만
    assert lib.get("MOL-EC")["fav"] is True and lib.get("MOL-EC")["note"] == "표준"
    with pytest.raises(ValueError):
        lib.delete_molecule("MOL-EC")
    assert lib.delete_molecule(rec["id"]) is True and lib.get(rec["id"]) is None
    saved = json.loads((store.DATA_DIR / "library.json").read_text(encoding="utf-8"))
    assert saved["overrides"]["MOL-EC"]["fav"] is True and saved["molecules"] == []


def test_search_modes(lib):
    assert _ids(lib.search("name", "EC"))[0] == "MOL-EC"
    assert _ids(lib.search("name", "C3H6O3")) == ["MOL-DMC"]            # 화학식 → 동분자식만
    assert "MOL-AN" in _ids(lib.search("name", "C=CC#N"))                # SMILES 로 이름 검색
    assert _ids(lib.search("exact", "C(=C)C#N")) == ["MOL-AN"]
    salt = lib.search("exact", "[Li+].F[P-](F)(F)(F)(F)F", strip_salts=True)
    assert "MOL-PF6" in _ids(salt) and "MOL-LIPF6" in _ids(salt)          # 가장 큰 조각 비교
    sub = lib.search("sub", "C=C")
    assert {"MOL-VDF", "MOL-AA", "MOL-AN", "MOL-MMA", "MOL-STYRENE"} <= set(_ids(sub))
    assert "MOL-EC" not in _ids(sub) and sub["rows"][0]["match"] and sub["rows"][0]["svg"]
    sim = lib.search("sim", "O=C1OCCO1", threshold=0.2)
    assert sim["rows"][0]["id"] == "MOL-EC" and sim["rows"][0]["score"] == 1.0
    assert all(a["score"] >= b["score"] for a, b in zip(sim["rows"], sim["rows"][1:]))
    assert lib.search("exact", "C1CC")["error"]


def test_mixture_ratio_bases(lib):
    vol = lib.resolve_mixture({"basis": "부피비", "components": [{"id": "MOL-EC", "ratio": 1}, {"id": "MOL-DMC", "ratio": 1}]})
    ecdmc = presets.SOLVENTS_BY_ID["sol-ecdmc"]["smd"]
    assert vol["vector"][5] == pytest.approx(ecdmc[5], abs=0.01) and vol["vector"][0] == pytest.approx(ecdmc[0], abs=1e-3)
    assert vol["name"] == "EC/DMC 1:1"
    mol = lib.resolve_mixture({"basis": "몰비", "components": [{"id": "MOL-EC", "ratio": 3}, {"id": "MOL-EMC", "ratio": 7}]})
    ec, emc = lib.get("MOL-EC"), lib.get("MOL-EMC")
    v_ec, v_emc = 0.3 * ec["mw"] / ec["density"], 0.7 * emc["mw"] / emc["density"]
    assert mol["components"][0]["volume_fraction"] == pytest.approx(v_ec / (v_ec + v_emc), abs=1e-4)
    mass = lib.resolve_mixture({"basis": "질량비", "components": [{"id": "MOL-EC", "ratio": 1}, {"id": "MOL-DMC", "ratio": 1}]})
    f_ec = (0.5 / ec["density"]) / (0.5 / ec["density"] + 0.5 / lib.get("MOL-DMC")["density"])
    assert mass["components"][0]["volume_fraction"] == pytest.approx(f_ec, abs=1e-4)
    legacy = lib.resolve_mixture({"components": [{"abbr": "EC", "ratio": 1}, {"abbr": "H2O", "ratio": 1}]})
    assert legacy["vector"][5] == pytest.approx((89.78 + presets.WATER_SMD_FOR_MIX[5]) / 2)
    with pytest.raises(ValueError, match="밀도"):
        pc = lib.add_molecule({"smiles": "CC1COC(=O)O1", "name": "PC", "roles": ["solvent"], "smd": {"n": 1.42, "eps": 64.9}})
        lib.resolve_mixture({"basis": "몰비", "components": [{"id": pc["id"], "ratio": 1}, {"id": "MOL-EC", "ratio": 1}]})
    with pytest.raises(ValueError, match="용매 역할"):
        lib.resolve_mixture({"components": [{"id": "MOL-FEC", "ratio": 1}]})


def test_resolve_solvent_settings(lib):
    vac = {"envType": "진공·기체", "solventId": "sol-ec"}
    assert lib.resolve_solvent(vac) is None
    assert lib.resolve_solvent({"envType": "사용자 정의", "solventId": "sol-ecdmc"})["key"] == "smd:ec-dmc-11"
    assert lib.resolve_solvent({"envType": "사용자 정의", "solventId": "MOL-DMC"})["key"] == "smd:dmc"   # 라이브러리 id → 프리셋
    mix = lib.save_mixture({"name": "EC/EMC 3:7", "basis": "부피비", "components": [{"id": "MOL-EC", "ratio": 3}, {"id": "MOL-EMC", "ratio": 7}]})
    r = lib.resolve_solvent({"envType": "사용자 정의", "solventId": mix["id"]})
    assert r["vector"] and r["mixture"]["components"][1]["volume_fraction"] == pytest.approx(0.7)
    with pytest.raises(ValueError, match="같은 이름"):
        lib.save_mixture({"name": "EC/EMC 3:7", "components": [{"id": "MOL-EC", "ratio": 1}, {"id": "MOL-DMC", "ratio": 1}]})
    cm = lib.resolve_solvent({"envType": "사용자 정의", "customMixedSolvent": {"name": "", "basis": "질량비",
                              "components": [{"id": "MOL-EC", "ratio": 1}, {"id": "MOL-DMC", "ratio": 1}, {"id": "MOL-EMC", "ratio": 1}]}})
    assert cm["label"].startswith("SMD(혼합: EC/DMC/EMC 1:1:1 · 질량비") and len(cm["mixture"]["components"]) == 3
    user = lib.add_molecule({"smiles": "CCOC(C)=O", "name": "EA", "roles": ["solvent"], "smd": {"n": 1.37, "eps": 6.0}})
    ru = lib.resolve_solvent({"envType": "사용자 정의", "solventId": user["id"]})
    assert ru["key"] == f"smd:lib-{user['id'].lower()}" and ru["vector"][5] == 6.0
    comps = lib.solvent_components({"envType": "사용자 정의", "solventId": mix["id"]})
    assert [c["abbr"] for c in comps] == ["EC", "EMC"]
    assert lib.delete_mixture(mix["id"]) and not lib.delete_mixture("sol-ecdmc")


def test_import_browser_items(lib):
    out = lib.import_browser([{"name": "PC", "smiles": "CC1COC(=O)O1"}, {"name": "EC again", "smiles": "O=C1OCCO1"},
                              {"name": "bad", "smiles": "C1CC"}, {"mixture": {"name": "EC/DMC 3:7", "components": [{"abbr": "EC", "ratio": 3}, {"abbr": "DMC", "ratio": 7}]}}])
    assert out["added"] == 1 and out["skipped"] == 1 and out["mixtures"] == 1 and len(out["errors"]) == 1
    assert any(m["name"] == "EC/DMC 3:7" for m in lib.mixtures())


def test_structure_and_export(lib):
    st = lib.structure("MOL-EC")
    assert st["xyz"].splitlines()[0].strip() == "10" and "RDKit" in st["source"]
    sdf, name = lib.export("MOL-EC", "sdf")
    assert name == "EC.sdf" and "$$$$" in sdf and "V2000" in sdf
    assert lib.export("MOL-EC", "smi")[0].startswith("O=C1OCCO1")
    with pytest.raises(ValueError):
        lib.export("MOL-EC", "pdb")


def test_api_handlers_and_job_validation(lib, monkeypatch):
    from fastapi import HTTPException
    from server import main
    out = main.library_list(_=True)
    assert out["molecules"] and out["bases"] == ["부피비", "몰비", "질량비"]
    assert main.library_search(main.LibrarySearchRequest(mode="name", query="DMC"), _=True)["rows"][0]["id"] == "MOL-DMC"
    with pytest.raises(HTTPException) as ei:
        main.library_add(main.LibraryMoleculeRequest(smiles="O=C1OCCO1"), _=True)
    assert ei.value.status_code == 409
    add = main.library_add(main.LibraryMoleculeRequest(smiles="CC1COC(=O)O1", name="PC"), _=True)["molecule"]
    assert main.library_patch(add["id"], main.LibraryPatchRequest(fav=True), _=True)["molecule"]["fav"] is True
    mx = main.library_mixture_add(main.LibraryMixtureRequest(name="EC/DMC 3:7", basis="몰비",
                                  components=[main.MixedSolventComponent(id="MOL-EC", ratio=3), main.MixedSolventComponent(id="MOL-DMC", ratio=7)]), _=True)
    assert mx["mixture"]["basis"] == "몰비"
    # 계산 설정 검증 — 라이브러리 용매 id · 저장 혼합 · 직접 구성 혼합(비율 기준) 모두 통과, 없는 성분은 400
    for s in ({"envType": "사용자 정의", "solventId": "MOL-EMC", "customMixedSolvent": None},
              {"envType": "사용자 정의", "solventId": mx["mixture"]["id"], "customMixedSolvent": None},
              {"envType": "사용자 정의", "solventId": None, "customMixedSolvent": {"name": "", "basis": "질량비", "components": [{"id": "MOL-EC", "ratio": 1, "abbr": None}, {"id": "MOL-WATER", "ratio": 2, "abbr": None}]}}):
        main._check_solvent(s)
    with pytest.raises(HTTPException) as e2:
        main._check_solvent({"envType": "사용자 정의", "solventId": None, "customMixedSolvent": {"name": "", "basis": "부피비", "components": [{"id": "MOL-FEC", "ratio": 1}]}})
    assert e2.value.status_code == 400 and "용매 역할" in e2.value.detail
    req = main.JobRequest(customMaterials=[main.CustomMaterial(smiles="CC1COC(=O)O1", name="PC", libraryId=add["id"])],
                          settings=main.JobSettings(solventId=None, customMixedSolvent=main.MixedSolvent(basis="몰비",
                              components=[main.MixedSolventComponent(id="MOL-EC", ratio=3), main.MixedSolventComponent(id="MOL-DMC", ratio=7)])))
    assert req.settings.customMixedSolvent.components[0].id == "MOL-EC"


def test_engine_solvent_key_registers_mixture(lib):
    from pyscf.solvent import smd
    from server import engine
    s = {"envType": "사용자 정의", "solventId": None, "customMixedSolvent": {"name": "EC/EMC", "basis": "몰비",
         "components": [{"id": "MOL-EC", "ratio": 3}, {"id": "MOL-EMC", "ratio": 7}]}}
    key = engine._solvent_key(s)
    assert key.startswith("smd:mix-") and smd.solvent_db[key][5] > 2.958
    assert engine._solvent_label(s, key).startswith("SMD(혼합: EC/EMC · 몰비")
    assert engine._solvent_mixture(s)["basis"] == "몰비"
    assert engine._solvent_key({"envType": "사용자 정의", "solventId": "sol-water"}) == "water"


def test_snapshot_includes_library_script_and_data(lib):
    from server.main import _snapshot_html
    html = _snapshot_html([])
    assert '<script src="/static/library.js">' not in html and "rbRenderMolSearch" in html
    assert '"library": {"molecules"' in html or '"library":{"molecules"' in html


def test_submit_job_links_library_id_and_mixture(lib, monkeypatch):
    """계산 제출 — 라이브러리 분자는 libraryId 로 연결되고, 직접 구성한 혼합 용매(몰비)가 설정에 그대로 남는다."""
    from server import main, worker
    made = []
    monkeypatch.setattr(store, "create_job", lambda material, settings: made.append((material, settings)) or {"id": f"JOB-T{len(made)}", "material": material})
    monkeypatch.setattr(store, "count_active", lambda: 0)
    monkeypatch.setattr(worker, "submit", lambda job_id: None)
    pc = lib.add_molecule({"smiles": "CC1COC(=O)O1", "name": "PC", "roles": ["solvent", "solute"],
                           "smd": {"n": 1.42, "eps": 64.9}, "density": 1.205})
    req = main.JobRequest(
        materialIds=["an"],
        customMaterials=[main.CustomMaterial(smiles=pc["smiles"], name="PC", libraryId=pc["id"])],
        settings=main.JobSettings(envType="사용자 정의", solventId=None, customMixedSolvent=main.MixedSolvent(
            name="", basis="몰비", components=[main.MixedSolventComponent(id="MOL-EC", ratio=3),
                                              main.MixedSolventComponent(id=pc["id"], ratio=7)])))
    out = main.submit_jobs(req, _=True)
    assert len(out["jobs"]) == 2
    (m1, s1), (m2, _s2) = made
    assert m1["libraryId"] == "MOL-AN" and m2["libraryId"] == pc["id"] and m2["abbr"] == "라이브러리"
    assert s1["customMixedSolvent"]["basis"] == "몰비"
    assert s1["customMixedSolvent"]["components"] == [{"id": "MOL-EC", "ratio": 3.0}, {"id": pc["id"], "ratio": 7.0}]
    # 이 작업은 두 레코드의 계산 이력으로 연결된다
    jobs = [{"id": "JOB-T1", "status": "QUEUED", "createdAt": 5, "material": m1, "settings": s1},
            {"id": "JOB-T2", "status": "QUEUED", "createdAt": 6, "material": m2, "settings": s1}]
    idx = lib.job_index(jobs)
    assert [j["id"] for j in idx["MOL-AN"]] == ["JOB-T1"] and [j["id"] for j in idx[pc["id"]]] == ["JOB-T2"]
