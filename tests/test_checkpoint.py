"""단계별 체크포인트와 재개 — 기획서 v2.1 10.2.

서버가 꺼져 작업이 중단되면, 다시 시작했을 때 끝난 단계는 건너뛰고 다음 단계부터
계산해야 한다. 설정이 바뀌면 처음부터.
"""

import json

import pytest

from server import checkpoint, presets, store, worker


@pytest.fixture(autouse=True)
def _tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(store, "_jobs", {})
    monkeypatch.setattr(store, "_loaded", True)
    yield


def _settings(**over):
    s = {**presets.DEFAULT_SETTINGS, "expert": dict(presets.DEFAULT_SETTINGS["expert"])}
    exp = over.pop("expert", {})
    s.update(over)
    s["expert"].update(exp)
    return s


def _job(jid="J-1", **over):
    return {"id": jid, "material": {"id": None, "name": "water", "smiles": "O"},
            "settings": _settings(**over), "logs": []}


# ---------------------------------------------------------------- 모듈 단위
def test_checkpoint_roundtrip_and_fingerprint():
    job = _job()
    assert checkpoint.load(job) == {}
    info = checkpoint.save(job, {"geometry"}, {"atoms": [("O", 0.0, 0.0, 0.0)], "descriptors": {"homo_ev": -1.0},
                                                "notes": ["a"], "rx": None})
    assert info["done"] == ["geometry"] and info["labels"] == ["구조 생성·최적화"]
    data = checkpoint.load(job)
    assert data["done"] == ["geometry"] and data["descriptors"]["homo_ev"] == -1.0
    assert data["atoms"] == [["O", 0.0, 0.0, 0.0]]          # JSON 이라 리스트로 돌아온다
    assert checkpoint.as_tuples(data["atoms"]) == [("O", 0.0, 0.0, 0.0)]
    # 단계 순서는 STAGES 순으로 정렬된다
    info = checkpoint.save(job, {"redox", "geometry", "thermo"}, {})
    assert info["done"] == ["geometry", "thermo", "redox"]
    # 설정이 바뀌면 지문이 달라 stale
    other = _job(accuracy="정밀")
    st = checkpoint.load(other)
    assert st.get("stale") is True and st["done"] == []
    # 요약·삭제
    assert checkpoint.summary("J-1")["done"] == ["geometry", "thermo", "redox"]
    checkpoint.clear("J-1")
    assert checkpoint.load(job) == {} and checkpoint.summary("J-1") is None


def test_checkpoint_copy_for_retry():
    job = _job("J-A")
    checkpoint.save(job, {"geometry", "thermo"}, {"atoms": [["O", 0, 0, 0]]})
    assert checkpoint.copy("J-A", "J-B") is True
    assert checkpoint.load(_job("J-B"))["done"] == ["geometry", "thermo"]
    assert checkpoint.copy("J-NONE", "J-C") is False


def test_store_requeues_interrupted_jobs_and_worker_resubmits(monkeypatch):
    """서버 재시작 — 실행 중이던 작업은 실패가 아니라 «재개 대기»가 되고 큐에 다시 들어간다."""
    jobs = [
        {"id": "J-RUN", "status": "RUNNING", "createdAt": 1.0, "logs": [], "campaign": None},
        {"id": "J-Q", "status": "QUEUED", "createdAt": 2.0, "logs": [],
         "campaign": {"id": "CAM-1"}},
        {"id": "J-DONE", "status": "PUBLISHED", "createdAt": 0.5, "logs": []},
    ]
    store.JOBS_FILE.write_text(json.dumps(jobs), encoding="utf-8")
    monkeypatch.setattr(store, "_loaded", False)
    monkeypatch.setattr(store, "_jobs", {})
    store._load()
    j = store.get_job("J-RUN")
    assert j["status"] == "QUEUED" and j["interrupted"] is True and "체크포인트" in j["logs"][-1]
    assert store.get_job("J-DONE")["status"] == "PUBLISHED"
    submitted = []
    monkeypatch.setattr(worker, "submit", lambda jid, priority=0: submitted.append((jid, priority)))
    assert worker.resubmit_pending() == 2
    # 제출 순서는 createdAt, 캠페인 작업은 배치 우선순위
    assert submitted == [("J-RUN", worker.PRIORITY_INTERACTIVE), ("J-Q", worker.PRIORITY_BATCH)]


def test_delete_job_removes_checkpoint():
    job = store.create_job({"id": None, "name": "w", "smiles": "O"}, _settings())
    checkpoint.save(job, {"geometry"}, {})
    assert checkpoint.path_for(job["id"]).exists()
    assert store.delete_job(job["id"])
    assert not checkpoint.path_for(job["id"]).exists()


# ---------------------------------------------------------------- 실계산 재개 (sto-3g)
def test_run_job_resumes_from_checkpoint_after_interruption():
    """전위 계산 도중 중단 → 다시 실행하면 구조·단일점 단계를 건너뛰고 전위부터 잇는다."""
    from server.engine import run_job
    job = _job("T-CKPT", envType="진공·기체", solventId=None, accuracy="빠름",
               purpose="전자구조 + 산화/환원 전위",
               expert={"basis": "sto-3g", "nConformers": 1})
    # 1차 실행 — 양이온 단계에 들어가면 «서버가 꺼진 것처럼» 취소한다
    state = {}
    seen = []

    def cancelled():
        st = state.get("stage") or ""
        seen.append(st)
        return "양이온" in st

    run_job(dict(job, logs=[]), update=state.update, is_cancelled=cancelled)
    assert state["status"] == "FAILED" and state["error"] == "사용자 취소"
    ck = checkpoint.load(job)
    assert "geometry" in ck["done"] and "redox" not in ck["done"], ck["done"]
    assert state["checkpoint"]["done"] == ck["done"]
    n_first = sum(1 for s in seen if "구조 생성" in s or "단일점 SCF" in s)

    # 2차 실행 — 같은 조건. 구조 생성·단일점 단계가 없고 «체크포인트에서 이어서» 로그가 있어야 한다
    state2 = {}
    run_job(dict(job, logs=[]), update=state2.update)
    assert state2["status"] == "PUBLISHED", state2.get("error")
    logs = "\n".join(state2["logs"])
    assert "체크포인트에서 이어서 계산" in logs and "구조 생성·최적화" in logs
    assert "[구조 생성 (conformer 탐색)]" not in logs
    assert "[체크포인트 복원]" in logs and "[체크포인트 복원 — 단일점 재계산]" in logs
    d = state2["result"]["descriptors"]
    assert "ea_vertical_ev" in d and "reduction_potential_v" in d
    assert d["homo_ev"] < 0 and d["conformer_populations"]
    # 끝나면 체크포인트는 지워지고 작업 필드도 비워진다
    assert checkpoint.load(job) == {} and state2["checkpoint"] is None
    # 주석은 중복되지 않는다
    assert len(state2["result"]["notes"]) == len(set(state2["result"]["notes"]))
    # 검증은 정상
    assert state2["result"]["validation"]["grade"] in ("PASS", "REVIEW")
    assert n_first >= 1


def test_run_job_ignores_stale_checkpoint():
    """설정이 바뀌면 체크포인트를 쓰지 않고 처음부터 계산한다."""
    from server.engine import run_job
    old = _job("T-STALE", envType="진공·기체", solventId=None, accuracy="빠름",
               expert={"basis": "sto-3g", "nConformers": 1})
    checkpoint.save(old, {"geometry"}, {"atoms": [["O", 0, 0, 0], ["H", 0.96, 0, 0], ["H", -0.24, 0.93, 0]],
                                        "descriptors": {"homo_ev": -9.9}, "notes": []})
    changed = _job("T-STALE", envType="진공·기체", solventId=None, accuracy="빠름",
                   expert={"basis": "sto-3g", "nConformers": 2})      # 설정 변경
    state = {}
    run_job(dict(changed, logs=[]), update=state.update)
    assert state["status"] == "PUBLISHED"
    logs = "\n".join(state["logs"])
    assert "조건(설정·분자)이 달라 처음부터" in logs and "[구조 생성 (conformer 탐색)]" in logs
    assert state["result"]["descriptors"]["homo_ev"] != -9.9
