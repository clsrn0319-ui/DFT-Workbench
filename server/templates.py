"""계산 템플릿 — 정확도·용매·목적·전문가 설정·활물질을 묶어 이름 붙인 preset (기획서 2.2 Templates).

«계산» 화면과 캠페인 위저드에서 한 번에 적용한다. 기본 템플릿 3개는 코드에 있고(수정 불가),
사용자가 저장한 템플릿은 data/templates.json 에 공유 저장된다(서버를 쓰는 모두가 본다).
"""
from __future__ import annotations

import json
import threading
import time
import uuid

from . import presets, store

_lock = threading.RLock()


def _file():
    return store.DATA_DIR / "templates.json"


BUILTIN = [
    {
        "id": "tpl-ncm811-binder", "name": "NCM811 바인더 안정성", "builtin": True,
        "desc": "표준 · SMD EC/DMC 1:1 · 전자구조 + 전위 · conformer 민감도 3 · 활물질 NCM811·흑연",
        "settings": {"envType": "사용자 정의", "solventId": "sol-ecdmc", "temperature": 298.15,
                     "accuracy": "표준", "purpose": "전자구조 + 산화/환원 전위", "structure": "모노머",
                     "referenceElectrode": "Li/Li+",
                     "expert": {"functional": "PBE0-D3(BJ)", "conformerSensitivity": True}},
        "electrodes": ["ncm811", "graphite"], "margin_v": 0.3,
    },
    {
        "id": "tpl-li-coordination", "name": "Li⁺ 배위 비교", "builtin": True,
        "desc": "정밀 · 용매 경쟁 Li(solv)₄⁺ · site 3 · 물성 지문",
        "settings": {"envType": "사용자 정의", "solventId": "sol-ecdmc", "temperature": 298.15,
                     "accuracy": "정밀", "purpose": "물성 지문 (확장 기술자 전체)", "structure": "모노머",
                     "referenceElectrode": "Li/Li+",
                     "expert": {"functional": "PBE0-D3(BJ)", "liModel": "competition",
                                "liCoordination": 4, "liMaxSites": 3}},
        "electrodes": ["graphite"], "margin_v": 0.3,
    },
    {
        "id": "tpl-fast-screen", "name": "1차 대량 거르기", "builtin": True,
        "desc": "빠름 · 전자구조 + 전위 · 배치 Top-N 20 · 마진 0.3 V",
        "settings": {"envType": "사용자 정의", "solventId": "sol-ecdmc", "temperature": 298.15,
                     "accuracy": "빠름", "purpose": "전자구조 + 산화/환원 전위", "structure": "2량체",
                     "referenceElectrode": "Li/Li+",
                     "expert": {"functional": "PBE0-D3(BJ)"}},
        "electrodes": ["ncm811", "graphite"], "margin_v": 0.3, "top_n": 20,
    },
]


def _load_user() -> list[dict]:
    f = _file()
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return [t for t in data if isinstance(t, dict) and t.get("id")]
    except (json.JSONDecodeError, OSError):
        return []


def _save_user(items: list[dict]):
    store.DATA_DIR.mkdir(exist_ok=True)
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_file())


def list_templates() -> list[dict]:
    with _lock:
        return [dict(t) for t in BUILTIN] + _load_user()


def get(template_id: str) -> dict | None:
    return next((t for t in list_templates() if t["id"] == template_id), None)


def validate_settings(settings: dict) -> dict:
    """저장 전 최소 검증 — 프리셋에 없는 값은 거른다."""
    s = dict(settings or {})
    if s.get("accuracy") and s["accuracy"] not in presets.ACCURACY:
        raise ValueError(f"알 수 없는 정확도: {s['accuracy']}")
    if s.get("purpose") and s["purpose"] not in presets.PURPOSES:
        raise ValueError(f"알 수 없는 목적: {s['purpose']}")
    if s.get("solventId") and s["solventId"] not in presets.SOLVENTS_BY_ID:
        raise ValueError(f"알 수 없는 용매: {s['solventId']}")
    exp = s.get("expert") or {}
    if exp.get("functional") and exp["functional"] not in presets.FUNCTIONALS:
        raise ValueError(f"지원하지 않는 범함수: {exp['functional']}")
    return s


def save(name: str, settings: dict, desc: str = "", electrodes=None, margin_v=None, top_n=None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("템플릿 이름이 비어 있습니다.")
    if len(name) > 60:
        raise ValueError("템플릿 이름은 60자까지입니다.")
    tpl = {
        "id": "tpl-" + uuid.uuid4().hex[:8], "name": name, "builtin": False,
        "desc": (desc or "").strip()[:200], "settings": validate_settings(settings),
        "electrodes": list(electrodes or []), "margin_v": margin_v, "top_n": top_n,
        "createdAt": time.time(),
    }
    with _lock:
        items = _load_user()
        if any(t["name"] == name for t in items) or any(t["name"] == name for t in BUILTIN):
            raise ValueError(f"같은 이름의 템플릿이 이미 있습니다: {name}")
        items.append(tpl)
        _save_user(items)
    return tpl


def delete(template_id: str) -> bool:
    if any(t["id"] == template_id for t in BUILTIN):
        raise ValueError("기본 템플릿은 지울 수 없습니다.")
    with _lock:
        items = _load_user()
        keep = [t for t in items if t["id"] != template_id]
        if len(keep) == len(items):
            return False
        _save_user(keep)
    return True
