"""공유용 웹앱 페이지 한 장을 만든다 — 서버가 떠 있지 않아도 된다.

계산 결과를 담은 자체 완결형 HTML을 파일로 뽑는다. 이 파일은
  - 웹 호스팅에 그대로 올려도 되고 (정적 파일 한 개),
  - 구글 드라이브·메일로 보내 받는 사람이 더블클릭해 열어도 되고,
  - 사내 웹서버의 아무 폴더에 두어도 링크로 공유된다.

사용:
    python -m scripts.build_webapp                     완료된 결과 전체
    python -m scripts.build_webapp --list              무엇이 담길지만 확인
    python -m scripts.build_webapp --ids JOB-A,JOB-B   일부만
    python -m scripts.build_webapp --out 공유.html      저장 위치 지정

계산 제출·물질 조회는 PySCF 서버가 필요하므로 이 페이지에서는 잠깁니다.
결과 열람·3D 구조·물성 지문·물질 비교·전기화학 안정성은 모두 동작합니다.
"""

import argparse
import sys
from pathlib import Path

from server import store
from server.main import _snapshot_html

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "build" / "rhobench_webapp.html"


def main(argv=None):
    ap = argparse.ArgumentParser(description="공유용 웹앱 페이지 생성")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="저장할 파일 경로")
    ap.add_argument("--ids", default="", help="쉼표로 구분한 작업 id (기본: 전체)")
    ap.add_argument("--list", action="store_true", help="담길 결과만 출력하고 종료")
    args = ap.parse_args(argv)

    wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
    jobs = [j for j in store.list_jobs()
            if j["status"] == "PUBLISHED" and j.get("result")
            and (not wanted or j["id"] in wanted)]

    if not jobs:
        print("담을 수 있는 완료 결과가 없습니다.", file=sys.stderr)
        print("먼저 계산을 완료하거나 `python -m scripts.seed_demo` 로 시연 데이터를 만드세요.",
              file=sys.stderr)
        return 1

    print(f"담길 결과 {len(jobs)}건")
    for j in jobs:
        c = j["result"]["conditions"]
        print(f"  - {j['material']['name']:32} {c.get('method', '')} · {c.get('solvent_model', '')}")
    if args.list:
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    html = _snapshot_html(jobs)
    out.write_text(html, encoding="utf-8")

    print(f"\n생성 완료: {out}  ({len(html.encode('utf-8')) / 1024 / 1024:.1f} MB)")
    print("이 파일 하나만 있으면 서버·인터넷 없이 열립니다.")
    print("공유 방법: 웹서버에 업로드 / 구글 드라이브 업로드 / 메일 첨부")
    return 0


if __name__ == "__main__":
    sys.exit(main())
