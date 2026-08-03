"""시연용 결과를 미리 계산해 둔다.

시연 중에 '표준' 프리셋으로 실계산을 돌리면 분자당 수 분~수십 분이 걸려
대기 시간이 생긴다. 이 스크립트를 시연 전에 한 번 돌려 두면 'DFT 계산 결과'와
'물질 비교' 화면에 바로 보여줄 결과가 채워진다.

사용:
    python -m scripts.seed_demo              기본 5종 (빠름 프리셋, 약 3~6분)
    python -m scripts.seed_demo --accuracy 표준     연구용 정확도 (오래 걸림)
    python -m scripts.seed_demo --only EC,AN        일부만
    python -m scripts.seed_demo --list              무엇을 계산할지만 보기

전위를 함께 계산하므로 '전기화학 안정성(ESW)' 차트가 바로 그려진다.
"""

import argparse
import sys
import time

from server import presets, store
from server.engine import run_job

# 바인더 후보 3종 + 전해액 용매 2종 — 비교 화면에서 성격 차이가 뚜렷하게 보인다.
DEMO_SET = [
    ("EC",  "에틸렌 카보네이트 (EC)",      "O=C1OCCO1",  "전해액 표준 용매"),
    ("DMC", "다이메틸 카보네이트 (DMC)",   "COC(=O)OC",  "저점도 선형 카보네이트"),
    ("VDF", "비닐리덴 플루오라이드 (VDF)", "C=C(F)F",    "PVDF 바인더 반복 단위"),
    ("AN",  "아크릴로나이트릴 (AN)",       "C=CC#N",     "PAN 바인더 반복 단위"),
    ("AA",  "아크릴산 (AA)",               "C=CC(=O)O",  "수계 바인더(PAA) 반복 단위"),
]


def settings_for(accuracy: str) -> dict:
    s = {
        **presets.DEFAULT_SETTINGS,
        "accuracy": accuracy,
        # 전위까지 계산해야 전기화학 안정성 차트에 나타난다
        "purpose": "전자구조 + 산화/환원 전위",
        "referenceElectrode": "Li/Li+",
        "expert": dict(presets.DEFAULT_SETTINGS["expert"]),
    }
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description="시연용 결과 미리 계산")
    ap.add_argument("--accuracy", default="빠름", choices=list(presets.ACCURACY),
                    help="정확도 프리셋 (기본: 빠름)")
    ap.add_argument("--only", default="", help="쉼표로 구분한 약어 (예: EC,AN)")
    ap.add_argument("--list", action="store_true", help="계산 대상만 출력하고 종료")
    args = ap.parse_args(argv)

    wanted = {a.strip().upper() for a in args.only.split(",") if a.strip()}
    targets = [d for d in DEMO_SET if not wanted or d[0].upper() in wanted]
    if not targets:
        print(f"'{args.only}' 에 해당하는 항목이 없습니다. "
              f"사용 가능: {', '.join(d[0] for d in DEMO_SET)}")
        return 1

    print(f"정확도 '{args.accuracy}' · 용매 EC/DMC 1:1 · 기준 전극 Li/Li+")
    for abbr, name, smiles, note in targets:
        print(f"  - {abbr:4} {name}  ({smiles})  — {note}")
    if args.list:
        return 0
    print()

    settings = settings_for(args.accuracy)
    ok = 0
    t_all = time.time()

    for i, (abbr, name, smiles, _note) in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {name}")
        job = store.create_job({"id": None, "name": name, "smiles": smiles}, settings)
        job_id = job["id"]
        store.update_job(job_id, {"status": "RUNNING", "stage": "시연 데이터 준비"})

        last = [-1]

        def update(patch, _job_id=job_id, _last=last):
            store.update_job(_job_id, patch)
            p = patch.get("progress")
            if p is not None and p != _last[0]:
                _last[0] = p
                print(f"      [{p:>3}%] {patch.get('stage', '')}", flush=True)

        t0 = time.time()
        try:
            run_job(store.get_job(job_id), update=update)
        except Exception as exc:  # noqa: BLE001 — 한 건이 실패해도 나머지는 계속
            store.update_job(job_id, {"status": "FAILED", "error": str(exc)})

        state = store.get_job(job_id)
        if state["status"] == "PUBLISHED":
            d = state["result"]["descriptors"]
            ok += 1
            print(f"      완료 {time.time() - t0:.0f}초 · {job_id} · "
                  f"HOMO {d.get('homo_ev')} eV · 갭 {d.get('gap_ev')} eV · "
                  f"산화 {d.get('oxidation_potential_v')} V")
        else:
            print(f"      실패 — {state.get('error')}")
        print()

    print(f"{ok}/{len(targets)}건 성공 · 전체 {time.time() - t_all:.0f}초")
    if ok:
        print("서버를 켜고 'DFT 계산 결과' 화면을 열면 바로 보입니다.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
