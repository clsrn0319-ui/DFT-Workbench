"""단계별 체크포인트 — 서버가 꺼져도 끝난 단계는 다시 계산하지 않는다 (기획서 v2.1 10.2).

계산은 «conformer 탐색·최적화 → 진동수 → 용매화 → 전위 → conformer 민감도 →
물성 지문(MEP·Li⁺·이량체·흡착·BDE·TDDFT)» 순서이고, 단계 하나가 몇 분에서
수십 분이다. 지금까지는 중간 결과가 메모리에만 있어 서버가 꺼지면 처음부터였다.

엔진이 단계를 끝낼 때마다 그때까지의 상태(구조·에너지·기술자·주석)를
data/checkpoints/<job>.json 에 쓴다. 다시 시작하면 같은 조건인지 지문으로 확인한
뒤 끝난 단계를 건너뛰고 다음 단계부터 계산한다. 작업이 끝나면 파일을 지운다.

지문(fingerprint)은 분자(SMILES·업로드 좌표)와 설정 전체의 해시다. 설정을 하나라도
바꾸면 지문이 달라 처음부터 계산한다 — 다른 조건의 중간 결과를 섞지 않기 위해서다.
"""

import hashlib
import json
import os
import threading
import time

import numpy as np

from . import store

#: 단계 순서 — 화면 표시와 «어디까지 왔는가» 판단용
STAGES = ["geometry", "thermo", "solvation", "interaction", "redox", "confsens",
          "mep", "li", "dimer", "adsorption", "bde", "tddft"]
STAGE_LABEL = {
    "geometry": "구조 생성·최적화", "thermo": "진동수·열보정", "solvation": "용매화 에너지",
    "interaction": "클러스터 상호작용", "redox": "산화/환원 전위", "confsens": "conformer 민감도",
    "mep": "MEP·반응성 지표", "li": "Li⁺ 상호작용", "dimer": "이량체 결합",
    "adsorption": "표면 흡착", "bde": "결합 해리에너지", "tddft": "UV-Vis",
}
_lock = threading.Lock()


def checkpoints_dir():
    return store.DATA_DIR / "checkpoints"


def path_for(job_id: str):
    return checkpoints_dir() / f"{store.safe_id(job_id)}.json"


def fingerprint(job: dict) -> str:
    """분자 + 설정 전체의 해시. 무엇 하나 바뀌면 이어서 계산하지 않는다."""
    mat = job.get("material") or {}
    body = {
        "smiles": mat.get("smiles"),
        "geometry": (mat.get("geometry") or {}).get("atoms"),
        "rescan": (mat.get("geometry") or {}).get("rescan"),
        "settings": job.get("settings"),
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False, default=_json_default).encode()
    ).hexdigest()[:16]


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, tuple):
        return list(o)
    return str(o)


def load(job: dict) -> dict:
    """저장된 체크포인트. 없거나 지문이 다르면 빈 dict."""
    p = path_for(job["id"])
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if data.get("fingerprint") != fingerprint(job):
        return {"stale": True, "done": [], "saved_at": data.get("saved_at")}
    return data


def save(job: dict, done, state: dict) -> dict:
    """단계가 끝난 직후의 상태를 기록한다. 원자적으로(tmp → rename) 쓴다."""
    p = path_for(job["id"])
    ordered = [s for s in STAGES if s in set(done)] + [s for s in done if s not in STAGES]
    payload = {"job_id": job["id"], "fingerprint": fingerprint(job), "done": ordered,
               "saved_at": time.time(), "saved_at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
               **state}
    with _lock:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, default=_json_default),
                           encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            pass
    return {"done": ordered, "savedAt": payload["saved_at"],
            "labels": [STAGE_LABEL.get(s, s) for s in ordered]}


def clear(job_id: str):
    try:
        path_for(job_id).unlink(missing_ok=True)
    except OSError:
        pass


def copy(src_id: str, dst_id: str) -> bool:
    """재시도로 새 작업을 만들 때 원본 작업의 체크포인트를 물려준다."""
    src = path_for(src_id)
    if not src.exists():
        return False
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    data["job_id"] = dst_id
    dst = path_for(dst_id)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return True
    except OSError:
        return False


def summary(job_id: str) -> dict | None:
    """화면용 — 어떤 단계까지 저장돼 있는가."""
    p = path_for(job_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    done = data.get("done") or []
    return {"done": done, "labels": [STAGE_LABEL.get(s, s) for s in done],
            "savedAt": data.get("saved_at"), "savedAtText": data.get("saved_at_text")}


def as_tuples(atoms):
    return [tuple(a) for a in atoms] if atoms else atoms
