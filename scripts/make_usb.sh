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
mkdir -p "$OUT/app" "$OUT/wheels" "$OUT/debs"

# 1) 소스 — 계산 결과(data*)와 가상환경은 제외한다
echo "[1/5] 소스 복사"
tar --exclude='./.git' --exclude='./.venv' --exclude='./data' \
    --exclude='./data-*' --exclude='./RhoBench-USB' \
    --exclude='__pycache__' --exclude='*.pyc' \
    -cf - . | tar -xf - -C "$OUT/app"

# 2) 파이썬 라이브러리(wheel) — 인터넷 없이 설치하기 위한 핵심
echo "[2/5] 파이썬 라이브러리 내려받기 (수백 MB, 몇 분 걸립니다)"
"$PY" -m pip download -q -r requirements.txt -d "$OUT/wheels"
"$PY" -m pip download -q pip setuptools wheel -d "$OUT/wheels" 2>/dev/null || true

# 3) 시스템 패키지(.deb) — 대상 컴퓨터에 python3-venv 가 없을 때 필요하다.
#    wheel 은 pip 이 있어야 설치되고, pip 은 가상환경이 있어야 쓸 수 있으며,
#    가상환경은 python3-venv 가 있어야 만들어진다. 우분투는 이 셋을 파이썬
#    본체와 따로 떼어 배포하므로, 인터넷 없는 컴퓨터에서는 여기서 막힌다.
echo "[3/5] 시스템 패키지(.deb) 내려받기"
# 저장소 목록이 낡으면 개별 .deb 가 404 로 실패한다 (버전이 밀려 사라짐).
if [ "$(id -u)" = "0" ]; then apt-get update -qq >/dev/null 2>&1 || true
else sudo -n apt-get update -qq >/dev/null 2>&1 || true; fi

DEB_SEED="python3-venv python3-pip python${PYVER}-venv"
DEB_LIST="$(apt-cache depends --recurse --no-recommends --no-suggests --no-conflicts \
              --no-breaks --no-replaces --no-enhances $DEB_SEED 2>/dev/null \
            | grep -E '^[a-zA-Z0-9]' | sed 's/:.*$//' | sort -u \
            | grep -E '^python3|^libpython3|-whl$' || true)"
# libpython3.X-stdlib 까지 담는 이유: 대상 컴퓨터의 python3.X 가 우리보다
# 조금 낮은 점 버전이면 python3.X-venv 의 «= 정확히 같은 버전» 의존이 깨진다.
# 그때 python3.X 본체까지 같이 올려야 하고, 그러려면 stdlib 이 필요하다.
DEB_N=0
DEB_FAIL=""
for p in $DEB_LIST; do
  if ( cd "$OUT/debs" && apt-get download "$p" >/dev/null 2>&1 ); then
    DEB_N=$((DEB_N + 1))
  else
    DEB_FAIL="$DEB_FAIL $p"
  fi
done

# 갯수만 세면 안 된다 — python3-venv 는 1 KB 짜리 메타패키지일 뿐이고,
# 실제 venv 모듈은 버전이 붙은 python3.X-venv 안에 들어 있다. 그것이
# 빠지면 대상 컴퓨터에서 dpkg 가 의존성 오류로 멈춘다.
DEB_OK=0
ls "$OUT/debs"/python3.[0-9]*-venv_*.deb >/dev/null 2>&1 && DEB_OK=1

if [ "$DEB_OK" = "1" ]; then
  echo "  $DEB_N 개 확보 — 대상 컴퓨터에 python3-venv 가 없어도 설치됩니다."
else
  rm -f "$OUT/debs"/*.deb
  echo "  ⚠ 핵심 패키지(python3.X-venv)를 받지 못해 debs/ 를 비웠습니다."
  echo "    이 USB 는 «대상 컴퓨터에 python3-venv 가 이미 있어야» 설치됩니다."
  echo "    이 컴퓨터에서 아래를 실행한 뒤 다시 만드세요:"
  echo "      sudo apt-get update"
fi
[ -n "$DEB_FAIL" ] && echo "  받지 못한 패키지:$DEB_FAIL"

# 4) 대상 컴퓨터용 설치 스크립트
echo "[4/5] 설치 스크립트 생성"
cat > "$OUT/설치.sh" <<'INSTALL'
#!/usr/bin/env bash
# RhoBench 설치 — USB 를 꽂은 컴퓨터에서 한 번만 실행합니다.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"

BUILD_PYVER=""; BUILD_OS=""; BUILD_ARCH=""
# shellcheck disable=SC1091
[ -f "$HERE/build-info" ] && . "$HERE/build-info"

echo "── RhoBench 설치 ──────────────────────────────────────"

# ── 쓸 수 있는 파이썬 고르기 ──────────────────────────────────────
# 「python3 가 있다」로는 부족하다는 것이 실제로 드러났다:
#   · 이름만 python3 이고 우분투가 준 것이 아닐 수 있다 (pyenv·conda·소스빌드).
#     그런 파이썬은 apt 로 venv 를 보충할 수도 없다 — 저장소에 패키지가 없다.
#   · wheels/ 는 «제작 시 파이썬 버전 전용»이다. 버전이 다르면 설치가 안 된다.
# 그래서 이름이 아니라 «실제로 venv 를 만들 수 있는가»로 고르고,
# 제작 버전과 일치하는 것을 먼저 찾는다.

_pyver() { "$1" -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null; }

_can_venv() {   # 흉내가 아니라 실제로 만들어 본다 — ensurepip 누락까지 걸러진다
  local tmp rc=1
  tmp="$(mktemp -d 2>/dev/null)" || return 1
  "$1" -m venv "$tmp/probe" >/dev/null 2>&1 && rc=0
  rm -rf "$tmp"
  return $rc
}

_candidates() {
  [ -n "${PYTHON:-}" ] && echo "$PYTHON"
  if [ -n "$BUILD_PYVER" ]; then
    echo "/usr/bin/python$BUILD_PYVER"; echo "python$BUILD_PYVER"
  fi
  echo python3; echo /usr/bin/python3
  for v in 3.13 3.12 3.11 3.10 3.9; do echo "/usr/bin/python$v"; done
}

_find_python() {   # $1: strict = 제작 버전과 같은 것만 / any = 되는 것 아무거나
  local py seen="" v
  while read -r py; do
    [ -n "$py" ] || continue
    command -v "$py" >/dev/null 2>&1 || continue
    py="$(command -v "$py")"
    case " $seen " in *" $py "*) continue ;; esac
    seen="$seen $py"
    v="$(_pyver "$py")" || continue
    [ -n "$v" ] || continue
    if [ "$1" = strict ] && [ -n "$BUILD_PYVER" ] && [ "$v" != "$BUILD_PYVER" ]; then
      continue
    fi
    if _can_venv "$py"; then echo "$py"; return 0; fi
  done < <(_candidates)
  return 1
}

_report_pythons() {
  local py v seen=""
  while read -r py; do
    command -v "$py" >/dev/null 2>&1 || continue
    py="$(command -v "$py")"
    case " $seen " in *" $py "*) continue ;; esac
    seen="$seen $py"
    v="$(_pyver "$py")"
    if _can_venv "$py"; then echo "    $py  (Python ${v:-?})  venv 가능" >&2
    else                     echo "    $py  (Python ${v:-?})  venv 불가" >&2; fi
  done < <(_candidates)
}

echo "  쓸 수 있는 파이썬을 찾는 중… (몇 초 걸립니다)"
PY="$(_find_python strict || true)"

if [ -z "$PY" ] && ls "$HERE"/debs/*.deb >/dev/null 2>&1; then
  echo "  가상환경 모듈(python3-venv)이 없습니다 — USB 의 시스템 패키지로 설치합니다."
  echo "  관리자 권한이 필요합니다. 우분투 비밀번호를 물어볼 수 있습니다."
  sudo dpkg -i "$HERE"/debs/*.deb >/dev/null 2>&1 || true
  PY="$(_find_python strict || true)"
  [ -n "$PY" ] && echo "  ✓ python3-venv 설치 완료"
fi

if [ -z "$PY" ]; then
  # 제작 버전과 일치하는 것이 없다. 되는 것이라도 쓰되, 사실대로 알린다.
  PY="$(_find_python any || true)"
  if [ -n "$PY" ]; then
    echo "  ⚠ 제작 시 파이썬(${BUILD_PYVER:-?})과 다른 $(_pyver "$PY") 를 씁니다."
    echo "    USB 의 라이브러리는 ${BUILD_PYVER:-제작} 버전 전용이라 다음 단계에서"
    echo "    실패할 수 있습니다. 실패하면 ${BUILD_PYVER:-해당} 버전을 설치하거나"
    echo "    USB 를 이 컴퓨터의 파이썬 버전으로 다시 만드세요."
  fi
fi

if [ -z "$PY" ]; then
  echo >&2
  echo "✗ venv 를 만들 수 있는 파이썬을 찾지 못했습니다." >&2
  echo "  이 컴퓨터: $( . /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-unknown}")" >&2
  echo "  USB 제작 시: Python ${BUILD_PYVER:-?} / ${BUILD_OS:-?}" >&2
  echo "  찾아본 파이썬:" >&2
  _report_pythons
  echo >&2
  echo "  · 위 목록에 «venv 가능» 이 하나도 없고 우분투 기본 파이썬" >&2
  echo "    (/usr/bin/python3.10, 3.12 등)이 보이면, 인터넷이 되는 곳에서" >&2
  echo "      sudo apt update && sudo apt install -y python3-venv" >&2
  echo "  · 쓰고 싶은 파이썬을 직접 지정할 수도 있습니다:" >&2
  echo "      PYTHON=/usr/bin/python3.12 ./설치.sh" >&2
  exit 1
fi

PYVER="$(_pyver "$PY")"
echo "  사용할 파이썬: $PY  (Python $PYVER)"

# USB 는 쓰기가 느리고 파일시스템 제약이 있어, 설치는 «내장 디스크»에 한다
TARGET="${1:-$HOME/RhoBench}"
echo "  설치 위치: $TARGET"
mkdir -p "$TARGET"
cp -r "$HERE/app/." "$TARGET/"
cd "$TARGET"

echo "[1/2] 가상환경 만들기"
rm -rf .venv
"$PY" -m venv .venv

echo "[2/2] 오프라인 설치 (인터넷 불필요)"
if ! .venv/bin/pip install -q --no-index --find-links "$HERE/wheels" -r requirements.txt; then
  echo >&2
  echo "⚠ 오프라인 설치 실패 — USB 의 라이브러리가 이 파이썬과 맞지 않습니다." >&2
  echo "    이 컴퓨터: Python $PYVER   /   USB 제작 시: Python ${BUILD_PYVER:-?}" >&2
  if [ -n "$BUILD_PYVER" ] && [ "$PYVER" != "$BUILD_PYVER" ]; then
    echo "  두 버전이 다릅니다. 이것이 원인입니다." >&2
    echo "    · 이 컴퓨터에 Python $BUILD_PYVER 이 있다면:" >&2
    echo "        PYTHON=/usr/bin/python$BUILD_PYVER ./설치.sh" >&2
    echo "    · 없다면 USB 를 Python $PYVER 컴퓨터에서 다시 만드세요." >&2
  fi
  echo "  인터넷이 있으면:  cd $TARGET && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

echo
echo "✓ 설치 완료 — $TARGET"
echo "  실행:  cd $TARGET && ./scripts/start.sh"
INSTALL
chmod +x "$OUT/설치.sh"

# 설치 스크립트가 「제작 시 파이썬 버전」을 알아야 그 버전을 먼저 찾을 수 있다.
# wheels/ 가 그 버전 전용이기 때문이다.
cat > "$OUT/build-info" <<INFO
BUILD_PYVER=$PYVER
BUILD_OS="$( . /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-Linux}")"
BUILD_ARCH=$ARCH
INFO

# 5) 안내문
echo "[5/5] 안내문 생성"
cat > "$OUT/읽어보세요.txt" <<GUIDE
RhoBench — 다른 컴퓨터에서 실행하기
===================================================
제작 환경: Linux / $ARCH / Python $PYVER
제작 일시: $(date '+%Y-%m-%d %H:%M')

■ 준비물
  - Ubuntu(WSL 포함) 또는 Linux 컴퓨터
  - Python $PYVER (다른 버전이면 인터넷 설치가 필요합니다)

  ※ 인터넷은 필요 없습니다. 파이썬 라이브러리(wheels/)뿐 아니라
    가상환경 모듈 python3-venv 의 설치 파일(debs/)까지 담겨 있습니다.
    다만 파이썬 «본체»(python3)는 대상 컴퓨터에 이미 있어야 합니다.
    WSL 우분투에는 기본으로 들어 있습니다.

  ※ PySCF 는 네이티브 윈도우를 지원하지 않습니다.
    윈도우라면 WSL(Ubuntu)을 먼저 설치하세요:
      관리자 PowerShell 에서  wsl --install

■ 설치 (한 번만)
  1. USB 를 꽂습니다.
  2. Ubuntu 터미널을 엽니다.
  3. USB 를 WSL 에 연결합니다. WSL 은 USB 를 «자동으로 붙이지 않습니다».
     윈도우 탐색기의 «내 PC» 에서 USB 드라이브 문자를 확인한 뒤 (예: E:)
       sudo mkdir -p /mnt/e
       sudo mount -t drvfs E: /mnt/e
     ※ 드라이브 문자가 D: 면 위의 e / E: 를 d / D: 로 바꾸세요.
  4. USB 폴더로 이동합니다. 폴더 이름은 대소문자를 구분합니다.
       cd /mnt/e/RhoBench-USB
  5. 설치를 실행합니다.
       ./설치.sh
  6. 다 끝나면 USB 를 뽑기 전에
       cd ~ && sudo umount /mnt/e

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
  - "cd: /mnt/d/RhoBench-USB: No such file or directory"
      USB 가 WSL 에 안 붙어 있습니다. 위 «설치» 3번을 먼저 하세요.
      확인:  ls /mnt      ← 드라이브 문자가 보여야 합니다
  - "python3: command not found"
      파이썬 본체는 USB 로 해결되지 않습니다. 인터넷이 있는 곳에서
      sudo apt update && sudo apt install -y python3
  - "venv 를 만들 수 있는 파이썬을 찾지 못했습니다"
      설치 스크립트가 찾아본 파이썬 목록을 함께 출력합니다.
      «venv 가능» 이 하나도 없으면 USB 의 debs/ 로 자동 보충을 시도하고,
      그래도 안 되면 우분투 버전이 USB 제작 시와 다른 것입니다.
      쓰고 싶은 파이썬을 직접 지정할 수 있습니다:
        PYTHON=/usr/bin/python$PYVER ./설치.sh
  - "Package 'python3.XX-venv' has no installation candidate"
      그 파이썬은 우분투가 준 것이 아닙니다 (pyenv·conda·소스빌드 등).
      apt 로는 해결되지 않습니다. 우분투 기본 파이썬을 쓰세요:
        ls /usr/bin/python3.*
        PYTHON=/usr/bin/python$PYVER ./설치.sh
  - "오프라인 설치 실패"
      USB 의 라이브러리는 «Python $PYVER 전용» 입니다. 대상 컴퓨터가 다른
      버전을 쓰면 설치되지 않습니다. 위의 PYTHON= 지정으로 맞추거나,
      대상 컴퓨터의 파이썬 버전으로 USB 를 다시 만드세요.
  - 오프라인 설치 실패
      이 컴퓨터의 Python 버전이 USB 제작 시와 다릅니다.
      인터넷이 있으면:  cd ~/RhoBench && .venv/bin/pip install -r requirements.txt
  - 계산 도중 서버를 끄지 마세요 — 진행 중이던 계산이 사라집니다.
GUIDE

SIZE="$(du -sh "$OUT" | cut -f1)"
echo
echo "✓ 완료 — $OUT  (총 $SIZE, 시스템 패키지 $DEB_N 개 포함)"
echo "  이 폴더를 통째로 USB 에 복사하세요."
echo "  대상 컴퓨터에서는 «설치.sh» 를 실행하면 됩니다."
