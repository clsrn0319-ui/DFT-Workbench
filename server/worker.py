"""백그라운드 계산 워커 — DFT는 CPU 집약적이므로 순차 실행 큐."""

import os
import queue
import threading

from . import engine, store

# 동시 계산 워커 수 — DFT는 CPU 집약적이므로 기본 1개, 다중 사용자면 상향
N_WORKERS = max(1, int(os.environ.get("RHOBENCH_WORKERS", "1")))

_queue: "queue.Queue[str]" = queue.Queue()
_started = False
_start_lock = threading.Lock()


def submit(job_id: str):
    ensure_started()
    _queue.put(job_id)


def _worker_loop():
    while True:
        job_id = _queue.get()
        try:
            job = store.get_job(job_id)
            if job is None or job["status"] != "QUEUED":
                continue
            store.update_job(job_id, {"status": "RUNNING", "stage": "워커 할당"})
            engine.run_job(
                job,
                update=lambda patch: store.update_job(job_id, patch),
                is_cancelled=lambda: bool((store.get_job(job_id) or {}).get("cancelRequested")),
            )
        except Exception as exc:  # noqa: BLE001 — 워커 스레드는 죽지 않아야 함
            store.update_job(job_id, {"status": "FAILED", "error": f"워커 오류: {exc}"})
        finally:
            _queue.task_done()


def ensure_started():
    global _started
    with _start_lock:
        if not _started:
            for i in range(N_WORKERS):
                threading.Thread(target=_worker_loop, daemon=True,
                                 name=f"dft-worker-{i + 1}").start()
            _started = True
