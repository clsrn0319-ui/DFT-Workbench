"""휴지통 — 삭제하면 결과·모니터 기록·파일이 함께 옮겨지고, 되살리면 그대로 돌아온다."""

import json

import pytest

from server import store


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(store, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(store, "_jobs", {})
    monkeypatch.setattr(store, "_loaded", True)
    return tmp_path


def _done_job():
    job = store.create_job({"name": "VDF", "smiles": "C=C(F)F"}, {"envType": "진공·기체"})
    store.update_job(job["id"], {"status": "PUBLISHED", "result": {"conditions": {"method": "m", "solvent_model": "s"}},
                                 "monitor": {"anomalies": []}})
    # 딸린 파일 — 원본 로그 · 이벤트 · 격자 · 체크포인트
    for p in store._all_job_files(job["id"]):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x" + p.name, encoding="utf-8")
    return job["id"]


def test_trash_restore_roundtrip(data):
    jid = _done_job()
    files = [p for p in store._all_job_files(jid)]
    assert all(p.exists() for p in files)
    assert store.trash_job(jid)
    # 결과·모니터 목록에서 사라지고 파일은 휴지통 폴더로
    assert store.get_job(jid) is None and all(j["id"] != jid for j in store.list_jobs())
    assert not any(p.exists() for p in files)
    items = store.list_trash()
    assert [t["job"]["id"] for t in items] == [jid] and len(items[0]["files"]) == len(files)
    assert json.loads((data / "trash.json").read_text(encoding="utf-8"))
    # 되살리기 — 레코드와 파일이 원래 자리로
    assert store.restore_job(jid)
    job = store.get_job(jid)
    assert job and job["status"] == "PUBLISHED" and job["monitor"] == {"anomalies": []}
    assert all(p.exists() and p.read_text(encoding="utf-8") == "x" + p.name for p in files)
    assert store.list_trash() == [] and not (data / "trash" / jid).exists()


def test_trash_refuses_active_and_purges(data):
    job = store.create_job({"name": "AN", "smiles": "C=CC#N"}, {"envType": "진공·기체"})
    with pytest.raises(store.JobActiveError):
        store.trash_job(job["id"])            # QUEUED — 먼저 취소
    assert store.trash_job("JOB-NONE") is False
    jid = _done_job()
    assert store.trash_job(jid)
    assert store.purge_trash(jid)
    assert store.list_trash() == [] and not (data / "trash" / jid).exists()
    assert store.restore_job(jid) is False and store.purge_trash(jid) is False
