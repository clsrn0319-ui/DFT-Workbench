"""서버 없이 엔진만 직접 호출하는 엔드투엔드 스모크 테스트.

사용:  python -m scripts.smoke_test
아크릴로나이트릴 1건을 '빠름' 프리셋(EC/DMC SMD, 전위 포함)으로 실제 계산한다.
"""

import json

from server import presets
from server.engine import run_job

job = {
    "id": "SMOKE-1",
    "material": {"id": "an", "name": "아크릴로나이트릴 (AN)", "smiles": "C=CC#N"},
    "settings": {
        **presets.DEFAULT_SETTINGS,
        "accuracy": "빠름",
        "purpose": "전자구조 + 산화/환원 전위",
        "expert": dict(presets.DEFAULT_SETTINGS["expert"]),
    },
    "logs": [],
}

state = dict(job)


def update(patch):
    state.update(patch)
    if "stage" in patch:
        print(f"  [{patch.get('progress', '?'):>3}%] {patch['stage']}")


run_job(job, update)

print("\nstatus:", state["status"])
if state["status"] != "PUBLISHED":
    print("error:", state.get("error"))
    raise SystemExit(1)
print(json.dumps(state["result"]["descriptors"], ensure_ascii=False, indent=2))
print("wall time:", state["result"]["wall_time_s"], "s")
