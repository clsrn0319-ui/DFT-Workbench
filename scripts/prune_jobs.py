"""공유 전 정리 — 테스트로 만든 작업을 골라 지운다.

공유용 웹앱 페이지에는 완료된 결과가 전부 담기므로, 그 전에 시험 삼아 돌린
작업을 정리하면 받는 사람이 볼 목록이 깔끔해진다.

사용:
    python -m scripts.prune_jobs --list                 지울 후보만 확인 (기본 동작)
    python -m scripts.prune_jobs --match 테스트,지문      이름에 포함되면 삭제 대상
    python -m scripts.prune_jobs --failed               실패한 작업 삭제 대상
    python -m scripts.prune_jobs --match 테스트 --yes    실제로 삭제

--yes 없이는 절대 지우지 않는다.
"""

import argparse
import sys

from server import store


def main(argv=None):
    ap = argparse.ArgumentParser(description="작업 정리 (기본은 미리보기)")
    ap.add_argument("--match", default="",
                    help="쉼표로 구분한 문자열 — 소재 이름에 포함되면 대상")
    ap.add_argument("--ids", default="", help="쉼표로 구분한 작업 id")
    ap.add_argument("--failed", action="store_true", help="실패한 작업 전부 대상")
    ap.add_argument("--list", action="store_true", help="현재 작업 전체 보기")
    ap.add_argument("--yes", action="store_true", help="실제로 삭제 (없으면 미리보기)")
    args = ap.parse_args(argv)

    jobs = store.list_jobs()
    if args.list or not (args.match or args.ids or args.failed):
        print(f"작업 {len(jobs)}건")
        for j in jobs:
            print(f"  {j['id']}  {j['status']:10}  {j['material']['name']}")
        if not (args.match or args.ids or args.failed):
            print("\n지우려면 --match / --ids / --failed 로 대상을 고르세요.")
        return 0

    needles = [m.strip() for m in args.match.split(",") if m.strip()]
    ids = {i.strip() for i in args.ids.split(",") if i.strip()}
    targets = [
        j for j in jobs
        if (j["id"] in ids)
        or (needles and any(n in j["material"]["name"] for n in needles))
        or (args.failed and j["status"] == "FAILED")
    ]

    if not targets:
        print("조건에 맞는 작업이 없습니다.")
        return 0

    print(f"삭제 대상 {len(targets)}건:")
    for j in targets:
        print(f"  {j['id']}  {j['status']:10}  {j['material']['name']}")

    if not args.yes:
        print(f"\n미리보기입니다. 실제로 지우려면 같은 명령에 --yes 를 붙이세요.")
        return 0

    for j in targets:
        store.delete_job(j["id"])
    print(f"\n{len(targets)}건 삭제 · 남은 작업 {len(store.list_jobs())}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
