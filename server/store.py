"""작업(Job) 저장소 — 메모리 + JSON 파일 영속화."""

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

# RHOBENCH_DATA_DIR 로 저장 위치를 바꿀 수 있다 — 용도별(전해액/바인더)로
# 서버를 따로 띄울 때 결과와 비밀번호를 완전히 분리하기 위한 것.
DATA_DIR = Path(os.environ.get(
    "RHOBENCH_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
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
                # 서버 재시작 시 미완료 작업은 «재개 대기»로 — 워커가 다시 뜨면
                # 단계별 체크포인트에서 이어서 계산한다 (예전에는 실패 처리했다)
                if job.get("status") in ("QUEUED", "RUNNING"):
                    was = job["status"]
                    job["status"] = "QUEUED"
                    job["interrupted"] = True
                    job["stage"] = "서버 재시작 — 재개 대기"
                    job.setdefault("logs", []).append(
                        time.strftime("%H:%M:%S") + (" 서버 재시작으로 중단됨 — 체크포인트에서 재개 예정"
                                                     if was == "RUNNING" else
                                                     " 서버 재시작 — 대기열에 다시 넣음"))
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
            # name 이 None 값으로 존재해도 SMILES 로 떨어지도록 or 를 쓴다
            "logs": [f"작업 생성 — {material.get('name') or material.get('smiles')}"
                     f" · {settings['envType']}"],
            "createdAt": time.time(),
            "finishedAt": None,
            "error": None,
            "result": None,
            "cancelRequested": False,
        }
        _jobs[job_id] = job
        _persist()
        return job


def update_job(job_id: str, patch: dict, persist: bool = True):
    """작업 갱신. persist=False 면 메모리만 바꾼다 — SCF 반복마다 오는 모니터
    요약처럼 잦은 갱신이 jobs.json 전체를 매번 다시 쓰지 않게 한다. 다음 persist
    갱신(단계 전환·완료) 때 함께 저장된다."""
    with _lock:
        _load()
        job = _jobs.get(job_id)
        if job is None:
            return None
        job.update(patch)
        if persist:
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


def count_active() -> int:
    """대기·실행 중인 전체 작업 수 (공유 서버 기준)."""
    with _lock:
        _load()
        return sum(1 for j in _jobs.values() if j["status"] in ("QUEUED", "RUNNING"))


LOGS_DIR = DATA_DIR / "logs"


def safe_id(job_id: str) -> str:
    return "".join(c for c in str(job_id) if c.isalnum() or c in "-_")


def raw_log_path(job_id: str):
    """PySCF 원본 로그 파일 위치. 크기가 커질 수 있어 jobs.json 밖에 둔다."""
    return LOGS_DIR / f"{safe_id(job_id)}.log"


def job_files(job_id: str) -> list:
    """작업에 딸린 파일 전부 — 원본 로그·구조화 이벤트·최적화 궤적·등가면 격자."""
    s = safe_id(job_id)
    return [LOGS_DIR / f"{s}.log", LOGS_DIR / f"{s}.events.jsonl",
            LOGS_DIR / f"{s}.trajectory.xyz", grid_path(job_id)]


def grid_path(job_id: str):
    """궤도·전자밀도 격자(float16 base64) 파일 — 결과당 수백 KB 라 jobs.json 밖에 둔다."""
    return DATA_DIR / "grids" / f"{safe_id(job_id)}.json"


def save_grids(job_id: str, grids: dict) -> None:
    path = grid_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(grids, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_grids(job_id: str):
    path = grid_path(job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def delete_grids(job_id: str) -> None:
    try:
        grid_path(job_id).unlink()
    except OSError:
        pass


def _all_job_files(job_id: str) -> list:
    """작업에 딸린 파일 전부 + 체크포인트 — 휴지통 이동·영구 삭제의 대상."""
    return job_files(job_id) + [DATA_DIR / "checkpoints" / f"{safe_id(job_id)}.json"]


def delete_job(job_id: str) -> bool:
    """즉시 영구 삭제 (내부·테스트용). 화면의 «삭제»는 trash_job 을 쓴다."""
    with _lock:
        _load()
        if job_id in _jobs:
            del _jobs[job_id]
            _persist()
            # 작업을 지우면 로그·체크포인트도 함께 지운다 — 남겨 두면 디스크만 먹는다
            for p in _all_job_files(job_id):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
            return True
        return False


# ── 휴지통 ─────────────────────────────────────────────────────────────
# 결과와 계산 모니터 기록은 같은 작업 레코드(jobs.json)와 그 파일(로그·이벤트·궤적·격자·체크포인트)
# 에서 나온다. 삭제하면 레코드는 trash.json 으로, 파일은 data/trash/<작업>/ 로 옮겨
# 결과 목록·모니터·비교·라이브러리 계산 이력에서 함께 사라지고, 되살리면 그대로 돌아온다.
ACTIVE_STATUSES = ("QUEUED", "RUNNING")


class JobActiveError(Exception):
    """진행 중인 작업은 휴지통으로 옮길 수 없다 — 먼저 취소."""


def _trash_dir() -> Path:
    return DATA_DIR / "trash"


def _trash_file() -> Path:
    return DATA_DIR / "trash.json"


def _load_trash() -> list:
    if not _trash_file().exists():
        return []
    try:
        return json.loads(_trash_file().read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_trash(items: list) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    tmp = _trash_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_trash_file())


def trash_job(job_id: str) -> bool:
    """작업을 휴지통으로 옮긴다. 없으면 False, 진행 중이면 JobActiveError."""
    with _lock:
        _load()
        job = _jobs.get(job_id)
        if job is None:
            return False
        if job.get("status") in ACTIVE_STATUSES:
            raise JobActiveError(job_id)
        folder = _trash_dir() / safe_id(job_id)
        folder.mkdir(parents=True, exist_ok=True)
        files = []
        for src in _all_job_files(job_id):
            if src.exists():
                # 원래 자리 — 데이터 폴더 기준 상대 경로 (서버를 옮겨도 되살릴 수 있게), 밖이면 절대 경로
                try:
                    rel = src.relative_to(DATA_DIR).as_posix()
                except ValueError:
                    rel = str(src)
                dst = folder / (src.parent.name + "__" + src.name)
                shutil.move(str(src), str(dst))
                files.append({"path": rel, "name": dst.name, "bytes": dst.stat().st_size})
        items = [t for t in _load_trash() if t["job"]["id"] != job_id]
        items.insert(0, {"job": job, "deletedAt": time.time(), "files": files})
        _save_trash(items)
        del _jobs[job_id]
        _persist()
        return True


def list_trash() -> list:
    with _lock:
        return _load_trash()


def restore_job(job_id: str) -> bool:
    """휴지통의 작업을 되살린다 — 레코드와 파일을 원래 자리로."""
    with _lock:
        _load()
        items = _load_trash()
        item = next((t for t in items if t["job"]["id"] == job_id), None)
        if item is None:
            return False
        folder = _trash_dir() / safe_id(job_id)
        for f in item.get("files", []):
            src, dst = folder / f["name"], (DATA_DIR / f["path"]) if not Path(f["path"]).is_absolute() else Path(f["path"])
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
        shutil.rmtree(folder, ignore_errors=True)
        job = item["job"]
        job.setdefault("logs", []).append(time.strftime("%H:%M:%S") + " 휴지통에서 되살림")
        _jobs[job_id] = job
        _persist()
        _save_trash([t for t in items if t["job"]["id"] != job_id])
        return True


def purge_trash(job_id: str) -> bool:
    """휴지통의 작업을 영구 삭제한다 (되돌릴 수 없음)."""
    with _lock:
        items = _load_trash()
        if not any(t["job"]["id"] == job_id for t in items):
            return False
        shutil.rmtree(_trash_dir() / safe_id(job_id), ignore_errors=True)
        _save_trash([t for t in items if t["job"]["id"] != job_id])
        return True


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
