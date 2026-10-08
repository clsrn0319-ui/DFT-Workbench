"""Conformer 세트 — 탐색·기준 구조·저장·DFT 재순위·계산 제출 대상.

구조 준비(역장, 수 초)와 DFT 계산(큐, 수 시간)을 나누는 기능이다.
"""

import pytest

from server import conformers as C
from server import store


@pytest.fixture(autouse=True)
def _tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    yield


def _vdf(**over):
    req = {"smiles": "C=C(F)F", "name": "PVDF 3량체", "structure": "3량체",
           "reference": "all-trans", "nConformers": 10, "seed": 42, "pruneRms": 0.5}
    req.update(over)
    return C.search(req)


def test_search_puts_reference_first_and_records_settings():
    doc = _vdf()
    confs = doc["conformers"]
    assert doc["id"].startswith("CONF-") and len(confs) >= 2
    first = confs[0]
    assert first["is_reference"] and first["index"] == 1
    assert all(abs(abs(t) - 180) < 3 for t in first["torsions"])     # all-trans
    assert first["rmsd_to_reference"] == 0.0
    assert all(c["rmsd_to_reference"] > 0 for c in confs[1:])        # 기준과 겹치는 구조는 걸러진다
    s = doc["settings"]
    assert s["reference"] == "all-trans" and s["pattern"] == "T" and s["forcefield"] in ("MMFF94", "UFF")
    assert "".join(s["backbone"]) == "CCCCCC"
    assert doc["molecule"]["smiles"] == "CC(F)(F)CC(F)(F)CC(F)F"     # 3량체로 전개
    # 가장 안정한 구조가 0 기준이고, 기준 구조(all-trans)는 그보다 높을 수 있다
    assert min(c["ff_energy"] for c in confs) == 0.0
    assert C.reference_label(doc) == "all-trans"


def test_search_auto_policy_and_pattern():
    auto = _vdf(reference="auto")
    assert not any(c["is_reference"] for c in auto["conformers"])
    assert auto["conformers"][0]["ff_energy"] == 0.0                  # 최저 에너지가 1번
    pat = _vdf(reference="pattern", pattern="T G T G'")
    t = pat["conformers"][0]["torsions"]
    assert abs(abs(t[0]) - 180) < 3 and abs(t[1] - 60) < 3
    assert C.reference_label(pat).startswith("패턴")
    with pytest.raises(ValueError):
        _vdf(reference="pattern", pattern="")


def test_populations_follow_dft_when_ranked():
    doc = _vdf()
    confs = [dict(c) for c in doc["conformers"][:3]]
    pops_ff = C.populations(confs)
    for c in confs:
        c["dft_energy"] = 0.0 if c["index"] == 1 else 5.0            # 기준 구조가 DFT 로는 가장 안정
    pops_dft = C.populations(confs)
    assert pops_dft[0] > 95 and pops_dft[0] > pops_ff[0]
    assert abs(sum(pops_dft) - 100) < 0.01


def test_store_roundtrip_and_delete():
    doc = _vdf()
    assert C.get(doc["id"])["id"] == doc["id"]
    sets = C.list_sets()
    assert [s["id"] for s in sets] == [doc["id"]] and sets[0]["n_conformers"] == len(doc["conformers"])
    assert "atoms" not in C.public(doc, with_atoms=False)["conformers"][0]
    assert C.delete(doc["id"]) and C.get(doc["id"]) is None and C.delete(doc["id"]) is False


def test_job_targets_carry_geometry_and_reference():
    doc = _vdf()
    targets = C.job_targets(doc["id"], [1, 2])
    assert len(targets) == 2
    t = targets[0]
    assert t["geometry"]["source"] == "conformer" and t["geometry"]["rescan"] is False
    assert len(t["geometry"]["atoms"]) == doc["molecule"]["n_atoms"]
    assert t["conformer"] == {"set": doc["id"], "index": 1, "reference": "all-trans",
                              "structure": "3량체", "n_total": len(doc["conformers"]),
                              "ff_energy": doc["conformers"][0]["ff_energy"], "dft_energy": None}
    assert "conf #1" in t["name"]
    with pytest.raises(ValueError):
        C.job_targets(doc["id"], [999])
    with pytest.raises(KeyError):
        C.job_targets("CONF-NONE", [1])


def test_dft_rank_updates_energies_and_status():
    """실제 단일점 — 부탄 3개, STO-3G (수십 초). 본 계산 전역을 건드리지 않는다."""
    import time
    doc = C.search({"smiles": "CCCC", "name": "butane", "structure": "모노머",
                    "reference": "all-trans", "nConformers": 6})
    idx = [c["index"] for c in doc["conformers"][:2]]
    C.rank(doc["id"], idx, {"envType": "진공·기체", "solventId": None, "accuracy": "빠름",
                            "expert": {"basis": "sto-3g"}})
    for _ in range(120):
        time.sleep(2)
        cur = C.get(doc["id"])
        if cur["rank_status"]["state"] != "running":
            break
    st = cur["rank_status"]
    assert st["state"] == "done" and st["done"] == len(idx) and st["error"] is None
    assert "sto-3g" in st["method"]
    ranked = [c for c in cur["conformers"] if c["dft_energy"] is not None]
    assert len(ranked) == len(idx) and min(c["dft_energy"] for c in ranked) == 0.0


# ── 세트를 분자 라이브러리 아래로 묶기 ────────────────────────────────────────
# 같은 분자의 세트가 탐색 화면·계산 화면·라이브러리에 따로 흩어지면 같은 구조인지
# 매번 확인해야 한다. 세트는 분자의 «탐색 결과»이므로 분자 레코드 아래에 모은다.

LOOSE = "N#CCC1CCCCC1"          # 빌트인 라이브러리에 없는 분자


def _loose_set(**over):
    req = {"smiles": LOOSE, "name": "시험 분자", "structure": "모노머",
           "reference": "auto", "nConformers": 5, "seed": 1, "pruneRms": 0.5}
    req.update(over)
    return C.search(req)


def test_sets_attach_to_library_molecule_by_id():
    from server import library as lib

    mol = lib.get("MOL-VDF")
    _vdf(libraryId=mol["id"])
    s = C.list_sets()[0]
    assert s["library"] == {"id": "MOL-VDF", "name": mol["name"]}
    assert s["linked_by"] == "id"


def test_sets_without_library_id_attach_by_smiles():
    """libraryId 가 없던 시절의 세트도 같은 분자 아래로 모여야 한다."""
    _vdf()                                          # libraryId 없이 저장
    s = C.list_sets()[0]
    assert s["library"]["id"] == "MOL-VDF" and s["linked_by"] == "smiles"


def test_set_of_unknown_molecule_is_loose_until_registered():
    from server import library as lib

    doc = _loose_set()
    s = C.list_sets()[0]
    assert s["library"] is None and s["linked_by"] is None          # 라이브러리에 없는 세트

    out = C.link_library(doc["id"])                                  # «라이브러리에 등록»
    assert lib.get(out["library"]["id"])["name"] == "시험 분자"       # 새 레코드가 생겼다
    assert out["set"]["linked_by"] == "id"
    assert C.get(doc["id"])["molecule"]["libraryId"] == out["library"]["id"]   # 파일에도 적힌다
    assert C.list_sets()[0]["library"]["id"] == out["library"]["id"]


def test_link_reuses_existing_molecule_instead_of_duplicating():
    from server import library as lib

    before = len(lib.molecules())
    doc = _vdf()                                     # 빌트인에 이미 있는 분자
    out = C.link_library(doc["id"])
    assert out["library"]["id"] == "MOL-VDF" and len(lib.molecules()) == before


def test_link_unknown_set_raises():
    with pytest.raises(KeyError):
        C.link_library("CONF-NOPE")


# ── 작업 목록 묶음 ─────────────────────────────────────────────────────
# conformer 10~20개를 제출하면 작업 목록이 «이름 · conf #n» 으로 도배된다.
# 세트 하나를 한 줄로 접으려면 작업마다 «어느 세트에서 나왔는가»가 있어야 한다.

def test_job_targets_tag_every_job_with_the_set_so_one_key_covers_them_all():
    doc = _vdf()
    targets = C.job_targets(doc["id"], [1, 2])
    for t in targets:
        assert t["conformer"]["set"] == doc["id"]
        assert t["conformer"]["structure"] == "3량체"      # 세트의 구조를 작업이 지고 간다
    keys = {C.job_group({"material": t})["key"] for t in targets}
    assert keys == {"set:" + doc["id"]}                     # 같은 세트 → 한 묶음


def test_job_group_describes_the_set_from_the_job_tag():
    doc = _vdf()
    t = C.job_targets(doc["id"], [2])[0]
    g = C.job_group({"material": t, "settings": {"structure": "모노머"}})
    assert g == {"key": "set:" + doc["id"], "setId": doc["id"], "name": "PVDF 3량체",
                 "index": 2, "reference": "all-trans", "structure": "3량체",
                 "nTotal": len(doc["conformers"]), "resolvedBy": "set"}
    # 꼬리표의 구조가 작업 설정(모노머)보다 앞선다 — 세트가 실제로 어떤 구조였는지가 맞다


def test_job_group_falls_back_to_the_name_for_jobs_without_the_tag():
    """conformer 꼬리표가 없던 시절의 작업도 같은 분자 아래로 모여야 한다."""
    old = [{"material": {"name": f"Styrene · conf #{i}"}, "settings": {"structure": "모노머"}}
           for i in (1, 2, 10)]
    gs = [C.job_group(j) for j in old]
    assert {g["key"] for g in gs} == {"name:Styrene"}       # 세트 id 는 몰라도 한 묶음
    assert [g["index"] for g in gs] == [1, 2, 10]
    assert all(g["setId"] is None and g["resolvedBy"] == "name" for g in gs)
    assert gs[0]["structure"] == "모노머"                    # 세트를 모르니 작업 설정에서
    assert gs[0]["reference"] is None and gs[0]["nTotal"] is None


def test_job_group_fallback_survives_the_functional_suffix():
    """범함수를 비교하면 이름 뒤가 더 붙는다 — «분자 · conf #4 · B3LYP»."""
    g = C.job_group({"material": {"name": "PVDF · conf #4 · B3LYP"}})
    assert g["key"] == "name:PVDF" and g["index"] == 4 and g["name"] == "PVDF"


def test_job_group_keeps_different_sets_of_one_molecule_apart():
    a, b = _vdf(), _vdf(reference="auto")
    assert a["id"] != b["id"]
    key = lambda d: C.job_group({"material": C.job_targets(d["id"], [1])[0]})["key"]
    assert key(a) != key(b)          # 같은 분자라도 세트가 다르면 따로 접힌다


@pytest.mark.parametrize("name", ["PVDF", "PVDF · B3LYP", "conf #3 분해물", ""])
def test_job_group_is_none_for_ordinary_jobs(name):
    """세트에서 나오지 않은 작업은 묶지 않는다 — 지금처럼 소재 이름으로 묶인다."""
    assert C.job_group({"material": {"name": name}}) is None


def test_attach_job_groups_leaves_the_stored_jobs_alone():
    """목록용 파생값이 jobs.json 에 섞여 들어가면 안 된다."""
    doc = _vdf()
    stored = {"id": "JOB-1", "material": C.job_targets(doc["id"], [1])[0], "settings": {}}
    plain = {"id": "JOB-2", "material": {"name": "PVDF"}, "settings": {}}
    out = C.attach_job_groups([stored, plain])
    assert out[0]["conformerGroup"]["setId"] == doc["id"]
    assert out[1]["conformerGroup"] is None
    assert "conformerGroup" not in stored and "conformerGroup" not in plain


def test_jobs_api_hands_the_group_key_to_the_screen(monkeypatch, tmp_path):
    """화면은 /api/jobs 의 conformerGroup 으로 묶는다 — 응답에 실려 나가야 한다."""
    from server import main

    monkeypatch.setattr(store, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(store, "_jobs", {})
    monkeypatch.setattr(store, "_loaded", True)
    doc = _vdf()
    for t in C.job_targets(doc["id"], [1, 2]):
        store.create_job(t, {"envType": "진공·기체", "structure": "3량체"})
    store.create_job({"name": "PVDF"}, {"envType": "진공·기체", "structure": "모노머"})

    jobs = main.list_jobs(_=True)["jobs"]
    groups = {j["conformerGroup"]["key"] for j in jobs if j["conformerGroup"]}
    assert groups == {"set:" + doc["id"]}
    assert sum(1 for j in jobs if j["conformerGroup"] is None) == 1


def test_screen_reads_the_group_key_the_server_sends():
    """열쇠 이름이 서버·화면에서 어긋나면 묶음이 조용히 깨진다."""
    from pathlib import Path

    app_js = (Path(__file__).resolve().parent.parent / "web" / "app.js").read_text(encoding="utf-8")
    assert "job.conformerGroup" in app_js
    assert "data-group-del" in app_js and "data-group-sel" in app_js
