#!/usr/bin/env bash
# 건식 음극 바인더 스크리닝 전용 인스턴스.
#
#   ./scripts/start_binder.sh
#
# 전해액용 서버(8000번, data/)와 **완전히 분리된** 서버를 8001번 포트에
# data-binder/ 저장소로 띄운다. 두 서버는 결과·비밀번호를 공유하지 않으므로
# 동시에 켜 두고 용도별로 나눠 쓸 수 있다.
#
#   전해액·분자 반응성   http://localhost:8000   data/
#   건식 음극 바인더     http://localhost:8001   data-binder/
#
# 포트·저장소를 바꾸려면 아래 두 값만 고치면 된다.

set -u
cd "$(dirname "$0")/.."

export RHOBENCH_PORT="${RHOBENCH_PORT:-8001}"
export RHOBENCH_DATA_DIR="${RHOBENCH_DATA_DIR:-$PWD/data-binder}"
export RHOBENCH_PROFILE="binder"

mkdir -p "$RHOBENCH_DATA_DIR"

echo
echo "  용도: 건식 음극 바인더(PFAS-free) 스크리닝"
echo "  저장소: $RHOBENCH_DATA_DIR  (전해액용 data/ 와 분리)"
echo

exec ./scripts/start.sh "$@"
