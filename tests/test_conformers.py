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
                              "n_total": len(doc["conformers"]),
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
