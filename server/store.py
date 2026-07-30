"""작업(Job) 저장소 — 메모리 + JSON 파일 영속화."""

import json
import threading
import time
import uuid
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
JOBS_FILE = DATA_DIR / "jobs.json"

_lock = threading.RLock()
_jobs: dict[str, dict] = {}
_loaded = False


def _load():
    global _loaded
    if _loaded:
        return
    _loaded = True
    if JOBS_FILE.exists():
        try:
            for job in json.loads(JOBS_FILE.read_text(encoding="utf-8")):
                # 서버 재시작 시 미완료 작업은 실패 처리 (워커 상태가 사라졌으므로)
                if job.get("status") in ("QUEUED", "RUNNING"):
                    job["status"] = "FAILED"
                    job["error"] = "서버 재시작으로 중단됨"
                _jobs[job["id"]] = job
        except (json.JSONDecodeError, OSError):
            pass


def _persist():
    DATA_DIR.mkdir(exist_ok=True)
    tmp = JOBS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(list(_jobs.values()), ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(JOBS_FILE)


def create_job(material: dict, settings: dict) -> dict:
    with _lock:
        _load()
        job_id = "JOB-" + time.strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6].upper()
        job = {
            "id": job_id,
            "material": material,
            "settings": settings,
            "status": "QUEUED",
            "progress": 0,
            "stage": "큐 대기",
            "logs": [f"작업 생성 — {material.get('name', material.get('smiles'))} · {settings['envType']}"],
            "createdAt": time.time(),
            "finishedAt": None,
            "error": None,
            "result": None,
            "cancelRequested": False,
        }
        _jobs[job_id] = job
        _persist()
        return job


def update_job(job_id: str, patch: dict):
    with _lock:
        _load()
        job = _jobs.get(job_id)
        if job is None:
            return None
        job.update(patch)
        _persist()
        return job


def get_job(job_id: str):
    with _lock:
        _load()
        return _jobs.get(job_id)


def list_jobs():
    with _lock:
        _load()
        return sorted(_jobs.values(), key=lambda j: j["createdAt"], reverse=True)


def delete_job(job_id: str) -> bool:
    with _lock:
        _load()
        if job_id in _jobs:
            del _jobs[job_id]
            _persist()
            return True
        return False


def request_cancel(job_id: str) -> bool:
    with _lock:
        _load()
        job = _jobs.get(job_id)
        if job is None or job["status"] not in ("QUEUED", "RUNNING"):
            return False
        job["cancelRequested"] = True
        if job["status"] == "QUEUED":
            job["status"] = "FAILED"
            job["error"] = "사용자 취소"
            job["stage"] = "취소됨"
        _persist()
        return True
