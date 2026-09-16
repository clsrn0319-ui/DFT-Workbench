#!/usr/bin/env bash
# 프로그램 업데이트 — GitHub 의 배포 브랜치(main)를 받아 계산이 없는 때를 골라 서버를 재시작한다.
# 네이버 클라우드(systemd)와 WSL(수동 실행) 양쪽에서 같은 명령으로 쓴다.
#
#   ./scripts/update.sh                # 새 커밋 확인 → 받기 → 계산이 끝날 때까지 대기 → 재시작
#   ./scripts/update.sh --now          # 기다리지 않고 바로 재시작 (진행 중 작업은 체크포인트에서 재개)
#   ./scripts/update.sh --check        # 무엇이 바뀌는지만 보고 끝
#   ./scripts/update.sh --test         # 재시작 전에 가벼운 테스트(약 15초)를 돌린다
#   ./scripts/update.sh --ref <브랜치>  # 배포 브랜치 대신 특정 브랜치/커밋으로 (관리자 시험용)
#   ./scripts/update.sh --no-restart   # 코드만 받고 재시작은 하지 않는다
#   ./scripts/update.sh --keep-local   # 이 PC 의 로컬 수정이 있으면 되돌리지 않고 중단
#
# 관리자 한 명만 프로그램을 고친다는 원칙:
#   - 프로그램은 GitHub 의 배포 브랜치(main, RHOBENCH_RELEASE_BRANCH 로 변경 가능)에서만 받는다.
#   - 이 PC 에서 코드를 손댔거나 다른 브랜치로 옮겨 놓았어도, 업데이트 때 관리자가 배포한 버전으로
#     되돌린다(git reset --hard). 되돌린 파일 목록은 화면에 남긴다. 결과·설정(data/)은 건드리지 않는다.
#   - 저장소가 비공개면 처음 한 번 읽기 전용 토큰으로 로그인해 둔다 (docs/08 참고).
#
# 재시작 뒤 60초 안에 HTTP 응답이 없으면 이전 커밋으로 되돌리고 다시 띄운다(롤백).

set -u
cd "$(dirname "$0")/.."
DIR=$(pwd)
BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; RED=$'\033[31m'; YEL=$'\033[33m'; OFF=$'\033[0m'
die() { echo; echo "${RED}실패: $1${OFF}" >&2; exit 1; }
envval() { [ -f /etc/rhobench.env ] && grep -E "^$1=" /etc/rhobench.env | tail -1 | cut -d= -f2- | tr -d ' ' || true; }
PORT="${RHOBENCH_PORT:-$(envval RHOBENCH_PORT)}"; PORT="${PORT:-8000}"
DATA_DIR="${RHOBENCH_DATA_DIR:-$(envval RHOBENCH_DATA_DIR)}"; DATA_DIR="${DATA_DIR:-$DIR/data}"
RELEASE_BRANCH="${RHOBENCH_RELEASE_BRANCH:-$(envval RHOBENCH_RELEASE_BRANCH)}"; RELEASE_BRANCH="${RELEASE_BRANCH:-main}"

WAIT=1; CHECK=0; TEST=0; RESTART=1; REF=""; KEEP_LOCAL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --now) WAIT=0 ;;
    --check) CHECK=1 ;;
    --test) TEST=1 ;;
    --no-restart) RESTART=0 ;;
    --keep-local) KEEP_LOCAL=1 ;;
    --ref) REF="$2"; shift ;;
    *) die "알 수 없는 옵션: $1" ;;
  esac
  shift
done

# ── 서버 상태 도우미 ───────────────────────────────────────────────
active_jobs() {
  .venv/bin/python - "$DATA_DIR" <<'PY' 2>/dev/null || echo "?"
import json, sys, pathlib
d = pathlib.Path(sys.argv[1])
try:
    jobs = json.load(open(d / "jobs.json", encoding="utf-8"))
except Exception:
    jobs = []
try:
    camps = json.load(open(d / "campaigns.json", encoding="utf-8"))
except Exception:
    camps = []
n = sum(1 for j in jobs if j.get("status") in ("RUNNING", "QUEUED"))
r = sum(1 for c in camps if c.get("status") == "RUNNING")
print(f"{n} {r}")
PY
}
uses_systemd() { command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^rhobench.service'; }
server_pid() { pgrep -f "uvicorn server.main:app" | head -1 || true; }
health() { curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/" 2>/dev/null || echo 000; }

restart_server() {
  if uses_systemd; then
    sudo systemctl restart rhobench
  else
    local pid; pid=$(server_pid)
    if [ -n "$pid" ]; then
      # 기존 프로세스의 환경변수(비밀번호 등)를 물려받는다
      ENVFILE=$(mktemp); tr '\0' '\n' < "/proc/$pid/environ" | grep -E '^RHOBENCH_' > "$ENVFILE" || true
      kill "$pid"; for i in $(seq 1 30); do sleep 1; kill -0 "$pid" 2>/dev/null || break; done
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid"
      set -a; . "$ENVFILE"; set +a; rm -f "$ENVFILE"
    fi
    export RHOBENCH_NO_PROMPT=1
    mkdir -p "$DATA_DIR"
    setsid nohup .venv/bin/python -m uvicorn server.main:app --host 0.0.0.0 --port "$PORT" \
      >> "$DATA_DIR/server.log" 2>&1 < /dev/null &
    echo $! > "$DATA_DIR/server.pid"
  fi
  for i in $(seq 1 60); do sleep 1; c=$(health); [ "$c" = "200" ] && return 0; done
  return 1
}

# ── 1. 새 커밋 확인 ────────────────────────────────────────────────
echo "${BOLD}[1/5] 새 커밋 확인${OFF}  ${DIM}(배포 브랜치: $RELEASE_BRANCH)${OFF}"
git fetch --quiet origin || die "git fetch 실패 — 인터넷·GitHub 접근(비공개 저장소면 읽기 전용 토큰) 확인"
CUR=$(git rev-parse HEAD)
if [ -n "$REF" ]; then
  if git rev-parse --verify --quiet "origin/$REF" >/dev/null; then TARGET="origin/$REF"
  elif git rev-parse --verify --quiet "$REF" >/dev/null; then TARGET="$REF"
  else die "없는 브랜치/커밋: $REF"; fi
  BRANCH_TO_TRACK="$REF"
else
  git rev-parse --verify --quiet "origin/$RELEASE_BRANCH" >/dev/null \
    || die "GitHub 에 배포 브랜치 '$RELEASE_BRANCH' 가 없습니다 — RHOBENCH_RELEASE_BRANCH 확인"
  TARGET="origin/$RELEASE_BRANCH"
  BRANCH_TO_TRACK="$RELEASE_BRANCH"
fi
NEW=$(git rev-parse "$TARGET")

# 이 PC 에서 손댄 흔적 — 관리자가 배포한 버전으로 되돌릴 대상
LOCAL_MODS=$(git status --porcelain --untracked-files=no)
LOCAL_COMMITS=$(git rev-list --count "$TARGET..HEAD" 2>/dev/null || echo 0)
CUR_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)

if [ "$CUR" = "$NEW" ] && [ -z "$LOCAL_MODS" ]; then
  echo "  이미 최신입니다: $(git log --format='%h %s' -1)"
  [ "$CHECK" = "1" ] && exit 0
  [ "$RESTART" = "1" ] || exit 0
  echo "  ${DIM}(코드 변경 없음 — 재시작만 진행)${OFF}"
else
  echo "  현재  $(git log --format='%h %s' -1 "$CUR")$( [ "$CUR_BRANCH" != "$BRANCH_TO_TRACK" ] && echo "  ${DIM}[$CUR_BRANCH]${OFF}")"
  echo "  대상  $(git log --format='%h %s' -1 "$NEW")  ${DIM}[$BRANCH_TO_TRACK]${OFF}"
  if [ "$CUR" != "$NEW" ]; then
    echo "  ${DIM}바뀌는 커밋:${OFF}"
    git log --format='    %h %s' "$CUR..$NEW" | head -20
    git diff --stat "$CUR" "$NEW" | tail -1 | sed 's/^/  /'
  fi
  if [ -n "$LOCAL_MODS" ] || [ "${LOCAL_COMMITS:-0}" != "0" ]; then
    echo "  ${YEL}이 PC 에서 수정된 흔적이 있습니다 — 프로그램 수정은 관리자만 하므로 배포 버전으로 되돌립니다:${OFF}"
    [ -n "$LOCAL_MODS" ] && echo "$LOCAL_MODS" | sed 's/^/    /'
    [ "${LOCAL_COMMITS:-0}" != "0" ] && echo "    (로컬 커밋 ${LOCAL_COMMITS}개)"
    [ "$KEEP_LOCAL" = "1" ] && die "--keep-local: 로컬 수정을 유지하려고 중단했습니다. 정리 후 다시 실행하세요"
  fi
fi
[ "$CHECK" = "1" ] && exit 0

# ── 2. 받기 (배포 버전으로 맞춤) ───────────────────────────────────
echo "${BOLD}[2/5] 코드 받기${OFF}"
if [ "$CUR" != "$NEW" ] || [ -n "$LOCAL_MODS" ]; then
  git checkout --quiet -B "$BRANCH_TO_TRACK" "$TARGET" 2>/dev/null \
    || git reset --hard --quiet "$TARGET" || die "배포 버전으로 맞추지 못했습니다 (git reset)"
  git reset --hard --quiet "$TARGET" || die "git reset 실패"
  git branch --quiet --set-upstream-to="$TARGET" "$BRANCH_TO_TRACK" 2>/dev/null || true
  echo "  $(git log --format='%h %s' -1)  ${DIM}[$(git rev-parse --abbrev-ref HEAD)]${OFF}"
  if git diff --name-only "$CUR" HEAD | grep -q '^requirements.txt$'; then
    echo "  requirements.txt 가 바뀌어 패키지를 다시 설치합니다 (수 분)"
    .venv/bin/python -m pip install -q -r requirements.txt || die "pip install 실패"
  fi
fi

# ── 3. 테스트 (선택) ───────────────────────────────────────────────
if [ "$TEST" = "1" ]; then
  echo "${BOLD}[3/5] 가벼운 테스트${OFF}"
  .venv/bin/python -m pytest tests/ -q -k 'not run_job and not real_scf' 2>&1 | tail -2 | sed 's/^/  /'
  .venv/bin/python -m pytest tests/ -q -k 'not run_job and not real_scf' >/dev/null 2>&1 \
    || { git checkout --quiet "$CUR"; die "테스트 실패 — 이전 커밋($(git log --format=%h -1 "$CUR"))으로 되돌렸습니다"; }
else
  echo "${DIM}[3/5] 테스트 생략 (--test 로 실행)${OFF}"
fi

[ "$RESTART" = "1" ] || { echo "${GREEN}코드만 받았습니다. 재시작은 나중에: ./scripts/update.sh${OFF}"; exit 0; }

# ── 4. 계산이 끝날 때까지 대기 ─────────────────────────────────────
echo "${BOLD}[4/5] 재시작 시점${OFF}"
if [ "$WAIT" = "1" ]; then
  last=""
  while true; do
    st=$(active_jobs)
    n=${st%% *}; r=${st##* }
    if [ "$n" = "0" ] && [ "$r" = "0" ]; then break; fi
    [ "$st" != "$last" ] && echo "  대기 — 활성 작업 $n · 진행 중 캠페인 $r  $(date '+%H:%M:%S')  ${DIM}(바로 재시작하려면 Ctrl+C 후 --now)${OFF}"
    last="$st"
    sleep 60
  done
  echo "  활성 작업 없음 — 재시작합니다"
else
  st=$(active_jobs); echo "  ${YEL}--now: 활성 작업 ${st%% *}개가 있어도 바로 재시작합니다 (체크포인트에서 재개)${OFF}"
fi

# ── 5. 재시작 + 확인 (실패 시 롤백) ──────────────────────────────
echo "${BOLD}[5/5] 재시작${OFF}"
if restart_server; then
  echo "${GREEN}${BOLD}  완료 — $(git log --format='%h %s' -1) · HTTP $(health) · $(date '+%Y-%m-%d %H:%M')${OFF}"
  uses_systemd && echo "  로그: sudo journalctl -u rhobench -f" || echo "  로그: $DATA_DIR/server.log"
  exit 0
fi
echo "${RED}  새 서버가 60초 안에 응답하지 않습니다 — 이전 커밋으로 롤백합니다${OFF}"
uses_systemd && sudo journalctl -u rhobench -n 30 --no-pager | sed 's/^/    /' || tail -n 30 "$DATA_DIR/server.log" | sed 's/^/    /'
git checkout --quiet "$CUR" || die "롤백 checkout 실패"
if restart_server; then
  echo "${YEL}  롤백 완료 — $(git log --format='%h %s' -1) 로 돌아왔습니다. 위 로그로 원인을 확인하세요${OFF}"
  exit 2
fi
die "롤백 후에도 서버가 뜨지 않습니다 — 로그를 확인하세요"
