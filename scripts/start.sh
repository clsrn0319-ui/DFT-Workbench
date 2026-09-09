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

# ── 0. 실행 모드 ──────────────────────────────────────────────────
#   ./scripts/start.sh --background   창을 닫아도 서버가 남는다 (nohup·setsid). 로그: data/server.log
#   ./scripts/start.sh --stop         백그라운드 서버 종료
#   ./scripts/start.sh --status       실행 중인지 확인
# 계산 도중 터미널을 닫아 서버가 죽는 사고를 막는다. 서버가 죽어도 작업은
# 단계별 체크포인트에서 재개되지만, 애초에 죽지 않는 편이 낫다.
BACKGROUND=0
MODE_ARGS=()
for a in "$@"; do
  case "$a" in
    --background|-b) BACKGROUND=1 ;;
    *) MODE_ARGS+=("$a") ;;
  esac
done
set -- "${MODE_ARGS[@]+"${MODE_ARGS[@]}"}"
PORT="${RHOBENCH_PORT:-8000}"
DATA_DIR="${RHOBENCH_DATA_DIR:-data}"
PIDFILE="$DATA_DIR/server.pid"
_server_pid() {
  local p=""
  [ -f "$PIDFILE" ] && p=$(cat "$PIDFILE" 2>/dev/null)
  if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then echo "$p"; return; fi
  pgrep -f "uvicorn server.main:app --host 0.0.0.0 --port $PORT" | head -1 || true
}
if [ "${1:-}" = "--status" ]; then
  p=$(_server_pid)
  if [ -n "$p" ]; then echo "${GREEN}실행 중${OFF} — PID $p · http://localhost:$PORT · 로그 $DATA_DIR/server.log"; exit 0
  else echo "꺼져 있음"; exit 1; fi
fi
if [ "${1:-}" = "--stop" ]; then
  p=$(_server_pid)
  [ -z "$p" ] && { echo "실행 중인 서버가 없습니다"; exit 0; }
  echo "서버(PID $p)를 종료합니다 — 계산 중이던 작업은 체크포인트에서 다음 실행 때 재개됩니다"
  kill "$p"; for i in $(seq 1 30); do sleep 1; kill -0 "$p" 2>/dev/null || break; done
  kill -0 "$p" 2>/dev/null && kill -9 "$p"
  rm -f "$PIDFILE"; echo "종료됨"; exit 0
fi

# ── 1. 파이썬 환경 ────────────────────────────────────────────────
if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  . .venv/bin/activate
fi

PY=$(command -v python3 || command -v python) || {
  echo "${RED}python3 을 찾을 수 없습니다.${OFF}  sudo apt install -y python3-pip python3-venv" >&2
  exit 1
}

MISSING=$("$PY" - <<'PYEOF' 2>/dev/null
mods = []
for m in ("pyscf", "rdkit", "fastapi", "uvicorn"):
    try:
        __import__(m)
    except ImportError:
        mods.append(m)
print(" ".join(mods))
PYEOF
)
if [ -n "${MISSING:-}" ]; then
  echo "${RED}필요한 패키지가 없습니다:${OFF} $MISSING"
  echo
  if [ -d .venv ]; then
    echo "  가상환경(.venv)은 있지만 패키지가 빠져 있습니다:"
    echo "    ${BOLD}. .venv/bin/activate && pip install -r requirements.txt${OFF}"
  else
    echo "  아래를 순서대로 실행하세요 (처음 한 번만):"
    echo "    ${BOLD}sudo apt install -y python3-pip python3-venv${OFF}"
    echo "    ${BOLD}python3 -m venv .venv${OFF}"
    echo "    ${BOLD}. .venv/bin/activate${OFF}"
    echo "    ${BOLD}pip install -r requirements.txt${OFF}"
  fi
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
if [ "$BACKGROUND" = "1" ]; then
echo "  ${DIM}백그라운드 실행 — 창을 닫아도 서버는 남습니다. 끄기: ./scripts/start.sh --stop${OFF}"
else
echo "  ${DIM}이 창을 닫으면 서버가 멈춥니다. 종료하려면 Ctrl+C.  (창을 닫아도 유지하려면 --background)${OFF}"
fi
echo "${BOLD}================================================================${OFF}"
echo

# ── 4. 실행 ──────────────────────────────────────────────────────
# `uvicorn` 명령이 PATH에 없어도 되도록 파이썬 모듈로 호출한다
if [ "$BACKGROUND" = "1" ]; then
  existing=$(_server_pid)
  if [ -n "$existing" ]; then
    echo "${GREEN}이미 실행 중입니다${OFF} (PID $existing) — http://localhost:$PORT"
    exit 0
  fi
  mkdir -p "$DATA_DIR"
  setsid nohup "$PY" -m uvicorn server.main:app --host 0.0.0.0 --port "$PORT" \
    >> "$DATA_DIR/server.log" 2>&1 < /dev/null &
  echo $! > "$PIDFILE"
  code=""
  for i in $(seq 1 60); do
    sleep 1
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/" 2>/dev/null || true)
    [ "$code" = "200" ] && break
  done
  if [ "$code" = "200" ]; then
    echo "${GREEN}${BOLD}  백그라운드로 실행 중${OFF} (PID $(cat "$PIDFILE")) — 이 창을 닫아도 계속 돕니다."
    echo "  끄기: ${BOLD}./scripts/start.sh --stop${OFF}   상태: ./scripts/start.sh --status   로그: $DATA_DIR/server.log"
    exit 0
  fi
  echo "${RED}서버가 60초 안에 응답하지 않습니다 — $DATA_DIR/server.log 를 확인하세요${OFF}" >&2
  exit 1
fi
exec "$PY" -m uvicorn server.main:app --host 0.0.0.0 --port "$PORT"
