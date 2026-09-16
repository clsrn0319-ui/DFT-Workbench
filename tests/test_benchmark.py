"""벤치마크 세트 — 참조 데이터 파일의 정합성, 작업 생성, 참조값 비교 보고서."""

import json
import re
from collections import Counter

import pytest

from server import benchmark, geometry, presets, store, worker
from server.engine import _resolve_params

SET_ID = "kim2025_binders"


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(store, "_jobs", {})
    monkeypatch.setattr(store, "_loaded", True)
    submitted = []
    monkeypatch.setattr(worker, "submit", lambda jid, priority=0: submitted.append(jid))
    return submitted


def _formula(atoms):
    c = Counter(a[0] for a in atoms)
    return "".join(f"{el}{c[el] if c[el] > 1 else ''}" for el in ("C", "H", "F") if c.get(el))


def test_reference_set_is_consistent():
    """참조 파일: 좌표·화학식·SMILES·참조값이 서로 맞고, 프로토콜은 엔진이 아는 범함수·기저여야 한다."""
    doc = benchmark.get_set(SET_ID)
    assert doc and doc["source"]["doi"] == "10.1038/s41467-025-66082-3"
    assert doc["protocol"]["functional"] in presets.FUNCTIONALS
    assert doc["protocol"]["basis"] in presets.BASIS_SETS
    assert 0 < doc["tolerance_ev"]["pass"] < doc["tolerance_ev"]["review"]
    keys = [q[0] for q in doc["quantities"]]
    assert keys == ["homo_ev", "lumo_ev", "gap_ev"]
    assert len(doc["entries"]) == 3
    for e in doc["entries"]:
        assert re.fullmatch(r"[a-z0-9_]+", e["id"])
        assert len(e["atoms"]) == 20
        assert _formula(e["atoms"]) == e["formula"], e["id"]
        assert geometry.atom_count(e["smiles"]) == len(e["atoms"]), e["id"]
        for a in e["atoms"]:
            assert isinstance(a[0], str) and all(isinstance(v, float) for v in a[1:])
        ref = e["reference"]
        assert abs((ref["lumo_ev"] - ref["homo_ev"]) - ref["gap_ev"]) < 0.02   # 논문 그림 값의 내부 일관성
        rep = e["reproduced"]
        assert all(abs(rep[k] - ref[k]) <= doc["tolerance_ev"]["pass"] for k in keys), e["id"]


def test_list_sets_omits_coordinates():
    sets = benchmark.list_sets()
    s = next(x for x in sets if x["id"] == SET_ID)
    assert all("atoms" not in e and e["n_atoms"] == 20 for e in s["entries"])


def test_job_settings_freeze_geometry_and_use_protocol():
    """세트 프로토콜 → 엔진 설정: 좌표 고정 단일점(최적화·열보정·민감도 없음), 진공, B3LYP5/6-311+G**."""
    doc = benchmark.get_set(SET_ID)
    s = benchmark.job_settings(doc)
    assert s["envType"] == "진공·기체" and s["solventId"] is None
    p = _resolve_params(s)
    assert p["xc"] == "b3lyp5" and p["disp"] is None
    assert p["basis_sp"] == "6-311+g**"
    assert p["do_opt"] is False and p["do_thermo"] is False and p["conf_sens"] == 0
    m = benchmark.job_material(doc, doc["entries"][0])
    assert m["geometry"]["rescan"] is False and len(m["geometry"]["atoms"]) == 20
    assert m["name"].startswith("[벤치마크]")


def test_submit_set_creates_tagged_jobs(isolated_store):
    jobs = benchmark.submit_set(SET_ID)
    assert len(jobs) == 3 and isolated_store == [j["id"] for j in jobs]
    for j in jobs:
        assert j["benchmark"]["set"] == SET_ID and j["status"] == "QUEUED"
        assert j["settings"]["expert"]["functional"] == "B3LYP5 (VWN5)"
        assert j["material"]["geometry"]["source"].startswith("벤치마크")
    only = benchmark.submit_set(SET_ID, ["pvdf"])
    assert [j["benchmark"]["entry"] for j in only] == ["pvdf"]
    with pytest.raises(KeyError):
        benchmark.submit_set("없는-세트")


def _job(jid, entry, status, created, homo=None, lumo=None, gap=None, error=None):
    j = {"id": jid, "status": status, "createdAt": created, "benchmark": {"set": SET_ID, "entry": entry},
         "progress": 50, "stage": "x", "error": error, "validation": {"grade": "PASS"} if status == "PUBLISHED" else None}
    if status == "PUBLISHED":
        j["result"] = {"descriptors": {"homo_ev": homo, "lumo_ev": lumo, "gap_ev": gap}}
    return j


def test_report_compares_latest_job_per_entry():
    """항목별 최신(끝난 것 우선) 작업을 참조값과 비교해 Δ·판정·MAE·전체 판정을 낸다."""
    jobs = [
        _job("J1", "ptfe", "PUBLISHED", 1.0, -9.689, -0.964, 8.725),      # PASS
        _job("J0", "ptfe", "PUBLISHED", 0.5, -12.0, -3.0, 9.0),           # 더 오래된 것 — 무시
        _job("J2", "pvdf", "PUBLISHED", 1.0, -9.30, -0.54, 8.76),         # HOMO Δ −0.25, gap +0.25 → REVIEW
        _job("J3", "parafilm", "RUNNING", 1.0),
        {"id": "X", "status": "PUBLISHED", "createdAt": 9.0, "result": {"descriptors": {"homo_ev": 0}}},  # 꼬리표 없음
    ]
    r = benchmark.report(SET_ID, jobs)
    rows = {row["entry"]: row for row in r["rows"]}
    assert rows["ptfe"]["job"] == "J1" and rows["ptfe"]["verdict"] == "PASS"
    assert rows["ptfe"]["delta"] == {"homo_ev": 0.001, "lumo_ev": 0.006, "gap_ev": 0.005}
    assert rows["pvdf"]["verdict"] == "REVIEW"
    assert rows["parafilm"]["verdict"] == "계산 중" and rows["parafilm"]["computed"] is None
    assert r["n_done"] == 2 and r["n_total"] == 3 and r["overall"] == "부분 완료"
    assert r["mae"]["homo_ev"] == round((0.001 + 0.25) / 2, 3)

    # 전부 끝나면 최악 판정이 전체 판정
    jobs.append(_job("J4", "parafilm", "PUBLISHED", 2.0, -8.0, 0.3, 8.3))   # FAIL (HOMO +0.45)
    r2 = benchmark.report(SET_ID, jobs)
    assert r2["overall"] == "FAIL" and r2["n_done"] == 3
    # 실패 작업은 «실패», 아무 작업도 없으면 «미실행»
    assert benchmark.report(SET_ID, [_job("J5", "ptfe", "FAILED", 3.0, error="SCF")])["rows"][0]["verdict"] == "실패"
    assert benchmark.report(SET_ID, [])["overall"] == "미실행"


def test_verdict_thresholds():
    tol = {"pass": 0.10, "review": 0.30}
    assert benchmark.verdict({"a": 0.1, "b": -0.05}, tol) == "PASS"
    assert benchmark.verdict({"a": 0.2, "b": None}, tol) == "REVIEW"
    assert benchmark.verdict({"a": -0.31}, tol) == "FAIL"
    assert benchmark.verdict({"a": None}, tol) == "판정 불가"


def test_presets_expose_gamess_b3lyp_and_pople_diffuse_basis():
    assert presets.FUNCTIONALS["B3LYP5 (VWN5)"] == ("b3lyp5", None)
    assert "B3LYP5 (VWN5)" in presets.FREQ_SCALE
    assert "6-311+g**" in presets.DIFFUSE_BASIS_SETS


def test_snapshot_inlines_bench_script():
    from server.main import _snapshot_html
    html = _snapshot_html([])
    assert '<script src="/static/bench.js">' not in html and "rbRenderBench" in html


def test_benchmark_job_runs_on_fixed_geometry_real_scf(tmp_path, monkeypatch):
    """실제 SCF — 벤치마크 작업은 좌표를 그대로 두고(최적화·conformer 탐색 없음) 프로토콜 범함수로
    단일점만 계산한다. 시간을 위해 기저만 STO-3G 로 바꾼다."""
    from server import engine
    doc = benchmark.get_set(SET_ID)
    entry = next(e for e in doc["entries"] if e["id"] == "parafilm")
    settings = benchmark.job_settings(doc)
    settings["expert"]["basis"] = "sto-3g"
    job = {"id": "TEST-BENCH", "material": benchmark.job_material(doc, entry), "settings": settings, "logs": []}
    state = {}
    engine.run_job(job, update=state.update)
    assert state.get("status") == "PUBLISHED", state.get("error")
    d = state["result"]["descriptors"]
    assert d["homo_ev"] < 0 < d["gap_ev"]
    assert any("사용자 제공 3D 구조" in line or "업로드 3D 구조" in line for line in state["logs"])
    # 최종 좌표가 입력 좌표와 같아야 한다 (최적화 없음)
    xyz = state["result"]["structure_xyz"].strip().splitlines()[2:]
    got = [(l.split()[0], [float(v) for v in l.split()[1:4]]) for l in xyz]
    assert len(got) == 20
    for (sym, pos), src in zip(got, entry["atoms"]):
        assert sym == src[0]
        assert all(abs(a - b) < 1e-3 for a, b in zip(pos, src[1:]))
    assert "b3lyp5" in json.dumps(state["result"]["conditions"], ensure_ascii=False).lower()
