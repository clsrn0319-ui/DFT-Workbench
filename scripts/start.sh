#!/usr/bin/env bash
# RhoBench 실행 — 시연·연구실 공유용 한 줄 실행기.
#
#   ./scripts/start.sh                 비밀번호를 물어본 뒤 시작
#   ./scripts/start.sh 내비밀번호       비밀번호를 인자로 지정
#   RHOBENCH_ACCESS_PASSWORD=... ./scripts/start.sh    환경변수로 지정
#
# 접속 주소(로컬 + 같은 네트워크)를 눈에 띄게 출력하고 uvicorn을 띄운다.

set -u
cd "$(dirname "$0")/.."

BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; RED=$'\033[31m'; OFF=$'\033[0m'

# ── 1. 파이썬 환경 ────────────────────────────────────────────────
if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  . .venv/bin/activate
fi

PY=$(command -v python3 || command -v python) || {
  echo "${RED}python3 을 찾을 수 없습니다.${OFF}  sudo apt install -y python3-pip python3-venv" >&2
  exit 1
}

if ! "$PY" -c "import pyscf, rdkit, fastapi" 2>/dev/null; then
  echo "${RED}필요한 패키지가 설치되어 있지 않습니다.${OFF}"
  echo "  아래를 먼저 실행하세요:"
  echo "    python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

# ── 2. 접속 비밀번호 ──────────────────────────────────────────────
# 한 번 정해 두면 data/access.json 에 해시로 남아, 재부팅 후에도 그대로 쓰인다.
if [ -f data/access.json ]; then FIRST_RUN=0; else FIRST_RUN=1; fi

PASSWORD="${1:-${RHOBENCH_ACCESS_PASSWORD:-}}"
# RHOBENCH_NO_PROMPT=1 이면 묻지 않고 저장된 비밀번호로 바로 시작 (바탕화면 아이콘용).
# 저장된 비밀번호가 아직 없으면(최초 실행) 물어봐야 하므로 이 설정을 무시한다.
if [ -z "$PASSWORD" ] && { [ "$FIRST_RUN" = "1" ] || [ -z "${RHOBENCH_NO_PROMPT:-}" ]; }; then
  if [ "$FIRST_RUN" = "1" ]; then
    printf '공유할 접속 비밀번호를 정하세요 (그냥 Enter = 무작위 발급): '
  else
    printf '접속 비밀번호 (그냥 Enter = 지난번 그대로, 바꾸려면 새로 입력): '
  fi
  read -r PASSWORD
fi
[ -n "$PASSWORD" ] && export RHOBENCH_ACCESS_PASSWORD="$PASSWORD"

# ── 3. 접속 주소 안내 ─────────────────────────────────────────────
PORT="${RHOBENCH_PORT:-8000}"
LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')

echo
echo "${BOLD}================================================================${OFF}"
echo "${BOLD}  RhoBench 시작${OFF}"
echo
echo "  이 컴퓨터에서        ${GREEN}${BOLD}http://localhost:${PORT}${OFF}"
[ -n "${LAN_IP:-}" ] && \
echo "  같은 네트워크에서    ${GREEN}${BOLD}http://${LAN_IP}:${PORT}${OFF}"
if [ -n "$PASSWORD" ]; then
echo "  접속 비밀번호        ${GREEN}${BOLD}${PASSWORD}${OFF}"
elif [ "$FIRST_RUN" = "1" ]; then
echo "  접속 비밀번호        ${DIM}아래 로그에 한 번 출력됩니다 — 기록해 두세요${OFF}"
else
echo "  접속 비밀번호        ${DIM}지난번에 쓰던 비밀번호 그대로${OFF}"
fi
echo
echo "  ${DIM}이 창을 닫으면 서버가 멈춥니다. 종료하려면 Ctrl+C.${OFF}"
echo "${BOLD}================================================================${OFF}"
echo

# ── 4. 실행 ──────────────────────────────────────────────────────
exec uvicorn server.main:app --host 0.0.0.0 --port "$PORT"
