#!/usr/bin/env bash
# RhoBench USB 패키지 만들기 — 인터넷 없는 컴퓨터에서도 설치·실행할 수 있게 묶는다.
#
# 왜 「소스만 복사」로는 부족한가:
#   pyscf·rdkit·scipy 는 컴파일된 확장 모듈을 담고 있어 pip 설치가 필요하고,
#   설치에는 인터넷이 있어야 한다. 그래서 wheel(설치 파일)까지 함께 담는다.
#
# 왜 「가상환경 통째 복사」는 안 되는가:
#   .venv 안의 실행 스크립트에는 만들어진 컴퓨터의 «절대 경로»가 박혀 있어
#   다른 위치·다른 컴퓨터로 옮기면 동작하지 않는다.
#
# 사용:  ./scripts/make_usb.sh [출력폴더]
#        기본 출력은 ./RhoBench-USB

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
OUT="${1:-$ROOT/RhoBench-USB}"
PY="${PYTHON:-python3}"

PYVER="$("$PY" -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
ARCH="$(uname -m)"
OS="$(uname -s)"

echo "── RhoBench USB 패키지 만들기 ──────────────────────────"
echo "  이 컴퓨터: $OS / $ARCH / Python $PYVER"
echo "  출력 폴더: $OUT"
echo

if [ "$OS" != "Linux" ]; then
  echo "⚠ 이 스크립트는 Linux(WSL 포함)에서 실행해야 합니다." >&2
  echo "  PySCF 는 네이티브 윈도우를 지원하지 않습니다." >&2
  exit 1
fi

rm -rf "$OUT"
mkdir -p "$OUT/app" "$OUT/wheels"

# 1) 소스 — 계산 결과(data*)와 가상환경은 제외한다
echo "[1/4] 소스 복사"
tar --exclude='./.git' --exclude='./.venv' --exclude='./data' \
    --exclude='./data-*' --exclude='./RhoBench-USB' \
    --exclude='__pycache__' --exclude='*.pyc' \
    -cf - . | tar -xf - -C "$OUT/app"

# 2) 설치 파일(wheel) — 인터넷 없이 설치하기 위한 핵심
echo "[2/4] 설치 파일 내려받기 (수백 MB, 몇 분 걸립니다)"
"$PY" -m pip download -q -r requirements.txt -d "$OUT/wheels"
"$PY" -m pip download -q pip setuptools wheel -d "$OUT/wheels" 2>/dev/null || true

# 3) 대상 컴퓨터용 설치 스크립트
echo "[3/4] 설치 스크립트 생성"
cat > "$OUT/설치.sh" <<'INSTALL'
#!/usr/bin/env bash
# RhoBench 설치 — USB 를 꽂은 컴퓨터에서 한 번만 실행합니다.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"

echo "── RhoBench 설치 ──────────────────────────────────────"

if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ python3 가 없습니다." >&2
  echo "  Ubuntu 에서:  sudo apt update && sudo apt install -y python3 python3-venv" >&2
  exit 1
fi
PYVER="$(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "  Python $PYVER 확인"

# USB 는 쓰기가 느리고 파일시스템 제약이 있어, 설치는 «내장 디스크»에 한다
TARGET="${1:-$HOME/RhoBench}"
echo "  설치 위치: $TARGET"
mkdir -p "$TARGET"
cp -r "$HERE/app/." "$TARGET/"
cd "$TARGET"

echo "[1/2] 가상환경 만들기"
python3 -m venv .venv 2>/dev/null || {
  echo "✗ 가상환경 생성 실패 — python3-venv 가 필요합니다." >&2
  echo "  sudo apt install -y python3-venv" >&2
  exit 1
}

echo "[2/2] 오프라인 설치 (인터넷 불필요)"
if ! .venv/bin/pip install -q --no-index --find-links "$HERE/wheels" -r requirements.txt; then
  echo
  echo "⚠ 오프라인 설치 실패 — USB 의 설치 파일이 이 컴퓨터의 Python 버전과" >&2
  echo "  맞지 않을 수 있습니다 (USB 제작 시 Python 버전과 다름)." >&2
  echo "  인터넷이 있으면 아래로 대신 설치하세요:" >&2
  echo "    cd $TARGET && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

echo
echo "✓ 설치 완료 — $TARGET"
echo "  실행:  cd $TARGET && ./scripts/start.sh"
INSTALL
chmod +x "$OUT/설치.sh"

# 4) 안내문
echo "[4/4] 안내문 생성"
cat > "$OUT/읽어보세요.txt" <<GUIDE
RhoBench — 다른 컴퓨터에서 실행하기
===================================================
제작 환경: Linux / $ARCH / Python $PYVER
제작 일시: $(date '+%Y-%m-%d %H:%M')

■ 준비물
  - Ubuntu(WSL 포함) 또는 Linux 컴퓨터
  - Python $PYVER (다른 버전이면 인터넷 설치가 필요합니다)

  ※ PySCF 는 네이티브 윈도우를 지원하지 않습니다.
    윈도우라면 WSL(Ubuntu)을 먼저 설치하세요:
      관리자 PowerShell 에서  wsl --install

■ 설치 (한 번만)
  1. USB 를 꽂습니다.
  2. Ubuntu 터미널을 엽니다.
  3. USB 폴더로 이동합니다. 윈도우의 USB 가 D: 드라이브면
       cd /mnt/d/RhoBench-USB
  4. 설치를 실행합니다.
       ./설치.sh

  설치는 USB 가 아니라 «내장 디스크»(~/RhoBench)에 됩니다.
  USB 는 느리고 파일시스템 제약이 있어 그대로 실행하면 문제가 생깁니다.

■ 실행 (매번)
     cd ~/RhoBench
     ./scripts/start.sh
  그다음 브라우저에서  http://localhost:8000

■ 처음 실행하면 비밀번호를 정하라고 합니다.
  이 비밀번호로 접속합니다.

■ 계산 결과
  결과는 설치 폴더의 data/ 에 쌓입니다. USB 에는 들어 있지 않습니다.
  다른 컴퓨터로 결과를 옮기려면 data/ 폴더를 직접 복사하세요.

■ 자주 겪는 문제
  - "python3: command not found"
      sudo apt update && sudo apt install -y python3 python3-venv
  - "가상환경 생성 실패"
      sudo apt install -y python3-venv
  - 오프라인 설치 실패
      이 컴퓨터의 Python 버전이 USB 제작 시와 다릅니다.
      인터넷이 있으면:  cd ~/RhoBench && .venv/bin/pip install -r requirements.txt
  - 계산 도중 서버를 끄지 마세요 — 진행 중이던 계산이 사라집니다.
GUIDE

SIZE="$(du -sh "$OUT" | cut -f1)"
echo
echo "✓ 완료 — $OUT  (총 $SIZE)"
echo "  이 폴더를 통째로 USB 에 복사하세요."
echo "  대상 컴퓨터에서는 «설치.sh» 를 실행하면 됩니다."
