"""벤치마크 세트 — 문헌 참조값과 이 프로그램의 계산값을 같은 조건에서 비교한다 (기획서 v2.1 «벤치마크/Calibration» 1단계).

세트 하나는 server/benchmarks/<id>.json 한 파일이다:
  - source: 논문·그림·데이터 출처
  - protocol: 재현에 쓸 계산 조건 (범함수·기저·환경·최적화 여부). 엔진 설정으로 그대로 변환된다.
  - entries: 분자별 좌표(논문이 공개한 최적화 구조)·참조값·이 프로그램으로 재현했던 기록
  - tolerance_ev: 판정 기준 (|Δ| ≤ pass → PASS, ≤ review → REVIEW, 그 외 FAIL)

실행하면 항목마다 «업로드 3D 구조» 경로의 작업이 만들어진다 — 좌표를 고정하고(conformer 탐색·최적화 없음)
프로토콜의 범함수·기저로 단일점만 계산한다. 작업에는 benchmark={set, entry} 꼬리표가 붙어
보고서에서 최신 작업을 찾아 참조값과 비교한다.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import presets, store, worker

SETS_DIR = Path(__file__).resolve().parent / "benchmarks"

_cache: dict[str, dict] = {}


def _load_all() -> dict[str, dict]:
    if not _cache:
        for p in sorted(SETS_DIR.glob("*.json")):
            doc = json.loads(p.read_text(encoding="utf-8"))
            _cache[doc["id"]] = doc
    return _cache


def list_sets() -> list[dict]:
    """세트 목록 — 좌표는 빼고 요약만."""
    out = []
    for doc in _load_all().values():
        out.append({k: v for k, v in doc.items() if k != "entries"}
                   | {"entries": [{k: v for k, v in e.items() if k != "atoms"} | {"n_atoms": len(e["atoms"])}
                                  for e in doc["entries"]]})
    return out


def get_set(set_id: str) -> dict | None:
    return _load_all().get(set_id)


def job_settings(doc: dict) -> dict:
    """세트의 protocol → 엔진 settings. 좌표 고정 단일점이 되도록 최적화·열보정·민감도를 끈다."""
    pr = doc["protocol"]
    s = {**presets.DEFAULT_SETTINGS, "expert": dict(presets.DEFAULT_SETTINGS["expert"])}
    s.update({
        "envType": pr.get("envType", "진공·기체"),
        "solventId": pr.get("solventId"),
        "customMixedSolvent": None,
        "accuracy": pr.get("accuracy", "빠름"),
        "purpose": pr.get("purpose", "전자구조(구조 최적화)"),
        "structure": "모노머",
        "explicitMolecules": [],
    })
    if s["envType"] == "진공·기체":
        s["solventId"] = None
    s["expert"].update({
        "functional": pr["functional"],
        "basis": pr.get("basis"),
        "optimizeGeometry": bool(pr.get("optimizeGeometry", False)),
        "thermochemistry": bool(pr.get("thermochemistry", False)),
        "conformerSensitivity": False,
        "boltzmannEnsemble": False,
        "nConformers": 1,
    })
    if pr["functional"] not in presets.FUNCTIONALS:
        raise ValueError(f"벤치마크 프로토콜의 범함수를 지원하지 않습니다: {pr['functional']}")
    return s


def job_material(doc: dict, entry: dict) -> dict:
    return {
        "id": None, "name": f"[벤치마크] {entry['name']}", "abbr": "벤치마크",
        "smiles": entry["smiles"],
        "geometry": {"atoms": [list(a) for a in entry["atoms"]], "source": f"벤치마크 {doc['id']}", "rescan": False},
    }


def submit_set(set_id: str, entry_ids: list[str] | None = None) -> list[dict]:
    """세트(또는 일부 항목)의 작업을 만들어 큐에 넣는다."""
    doc = get_set(set_id)
    if doc is None:
        raise KeyError(set_id)
    settings = job_settings(doc)
    jobs = []
    for entry in doc["entries"]:
        if entry_ids and entry["id"] not in entry_ids:
            continue
        job = store.create_job(job_material(doc, entry), settings)
        store.update_job(job["id"], {"benchmark": {"set": set_id, "entry": entry["id"]}})
        worker.submit(job["id"])
        jobs.append(store.get_job(job["id"]))
    return jobs


def _latest_jobs(set_id: str, jobs: list[dict]) -> dict[str, dict]:
    """항목별 최신 작업 — 끝난(PUBLISHED) 작업이 있으면 그것을, 없으면 가장 최근 것."""
    best: dict[str, dict] = {}
    for j in jobs:
        tag = j.get("benchmark") or {}
        if tag.get("set") != set_id:
            continue
        cur = best.get(tag["entry"])
        if cur is None:
            best[tag["entry"]] = j
            continue
        j_done = j.get("status") == "PUBLISHED"
        c_done = cur.get("status") == "PUBLISHED"
        if (j_done and not c_done) or (j_done == c_done and (j.get("createdAt") or 0) > (cur.get("createdAt") or 0)):
            best[tag["entry"]] = j
    return best


def verdict(deltas: dict[str, float | None], tol: dict) -> str:
    vals = [abs(v) for v in deltas.values() if v is not None]
    if not vals:
        return "판정 불가"
    worst = max(vals)
    if worst <= tol["pass"]:
        return "PASS"
    if worst <= tol["review"]:
        return "REVIEW"
    return "FAIL"


def report(set_id: str, jobs: list[dict] | None = None) -> dict:
    """세트의 항목별 참조값 · 최신 계산값 · 차이 · 판정과 전체 요약."""
    doc = get_set(set_id)
    if doc is None:
        raise KeyError(set_id)
    jobs = store.list_jobs() if jobs is None else jobs
    latest = _latest_jobs(set_id, jobs)
    keys = [q[0] for q in doc["quantities"]]
    tol = doc["tolerance_ev"]
    rows, abs_err = [], {k: [] for k in keys}
    n_done = 0
    for entry in doc["entries"]:
        job = latest.get(entry["id"])
        row = {"entry": entry["id"], "name": entry["name"], "model": entry["model"], "formula": entry["formula"],
               "n_atoms": len(entry["atoms"]), "reference": entry["reference"],
               "reproduced": entry.get("reproduced"),
               "job": None, "status": None, "computed": None, "delta": None, "verdict": "미실행"}
        if job:
            row["job"] = job["id"]
            row["status"] = job["status"]
            row["progress"] = job.get("progress")
            row["stage"] = job.get("stage")
            row["validation"] = (job.get("validation") or {}).get("grade")
            row["error"] = job.get("error")
            if job["status"] == "PUBLISHED" and job.get("result"):
                d = job["result"].get("descriptors") or {}
                computed = {k: d.get(k) for k in keys}
                delta = {k: (round(computed[k] - entry["reference"][k], 3)
                             if computed.get(k) is not None and entry["reference"].get(k) is not None else None)
                         for k in keys}
                row.update({"computed": computed, "delta": delta, "verdict": verdict(delta, tol)})
                n_done += 1
                for k in keys:
                    if delta[k] is not None:
                        abs_err[k].append(abs(delta[k]))
            elif job["status"] == "FAILED":
                row["verdict"] = "실패"
            else:
                row["verdict"] = "계산 중"
        rows.append(row)
    mae = {k: (round(sum(v) / len(v), 3) if v else None) for k, v in abs_err.items()}
    verdicts = [r["verdict"] for r in rows]
    if n_done == len(rows):
        overall = "FAIL" if "FAIL" in verdicts else ("REVIEW" if "REVIEW" in verdicts else "PASS")
    elif n_done:
        overall = "부분 완료"
    else:
        overall = "미실행"
    return {"set": set_id, "title": doc["title"], "quantities": doc["quantities"], "tolerance_ev": tol,
            "rows": rows, "n_done": n_done, "n_total": len(rows), "mae": mae, "overall": overall}
