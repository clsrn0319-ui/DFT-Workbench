"""백그라운드 계산 워커 — DFT는 CPU 집약적이므로 순차 실행 큐.

우선순위 큐: 화면에서 직접 제출한 단건 작업(priority 0)이 배치 스크리닝
작업(priority 10)보다 먼저 처리된다 — 배치가 돌아도 일상 사용이 굶지 않는다.
같은 우선순위 안에서는 제출 순서(FIFO)를 지킨다.
"""

import itertools
import os
import queue
import threading

from . import engine, store

# 동시 계산 워커 수 — DFT는 CPU 집약적이므로 기본 1개, 다중 사용자면 상향
N_WORKERS = max(1, int(os.environ.get("RHOBENCH_WORKERS", "1")))

PRIORITY_INTERACTIVE = 0   # 화면에서 직접 제출한 단건 작업
PRIORITY_BATCH = 10        # 배치 스크리닝 캠페인 작업

_queue: "queue.PriorityQueue[tuple[int, int, str]]" = queue.PriorityQueue()
_seq = itertools.count()   # 같은 우선순위 안 FIFO 보장용 일련번호
_started = False
_start_lock = threading.Lock()


def submit(job_id: str, priority: int = PRIORITY_INTERACTIVE):
    ensure_started()
    _queue.put((priority, next(_seq), job_id))


def _worker_loop():
    while True:
        _priority, _n, job_id = _queue.get()
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


def resubmit_pending() -> int:
    """서버 시작 시 QUEUED 상태로 남은 작업(중단된 작업 포함)을 큐에 다시 넣는다.

    캠페인 작업은 배치 우선순위, 단건은 대화형 우선순위 — 제출 순서(createdAt)를 지킨다.
    """
    n = 0
    for job in sorted(store.list_jobs(), key=lambda j: j.get("createdAt") or 0):
        if job.get("status") != "QUEUED":
            continue
        submit(job["id"], priority=PRIORITY_BATCH if job.get("campaign") else PRIORITY_INTERACTIVE)
        n += 1
    return n


def ensure_started():
    global _started
    with _start_lock:
        if not _started:
            for i in range(N_WORKERS):
                threading.Thread(target=_worker_loop, daemon=True,
                                 name=f"dft-worker-{i + 1}").start()
            _started = True
