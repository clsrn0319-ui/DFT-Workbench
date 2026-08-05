#!/usr/bin/env bash
# RhoBench 설치 — 처음 한 번만 실행합니다.
#
#   ./scripts/setup.sh
#
# 가상환경을 만들고 필요한 패키지를 모두 설치한 뒤, 실제 계산 한 건으로
# 설치가 제대로 됐는지 확인까지 합니다. 중간에 실패하면 그 자리에서 멈추고
# 무엇이 잘못됐는지 알려줍니다.

set -u
cd "$(dirname "$0")/.."

BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; RED=$'\033[31m'; OFF=$'\033[0m'
step() { echo; echo "${BOLD}[$1/4] $2${OFF}"; }
die()  { echo; echo "${RED}실패: $1${OFF}" >&2; exit 1; }

echo "${BOLD}================================================================${OFF}"
echo "${BOLD}  RhoBench 설치${OFF}"
echo "  ${DIM}10분쯤 걸립니다. 끝날 때까지 창을 닫지 마세요.${OFF}"
echo "${BOLD}================================================================${OFF}"

# ── 1. 시스템 패키지 ──────────────────────────────────────────────
step 1 "파이썬 도구 설치 (관리자 비밀번호를 물어볼 수 있습니다)"
if ! python3 -m venv --help >/dev/null 2>&1; then
  sudo apt update || die "apt update 실패 — 인터넷 연결을 확인하세요."
  sudo apt install -y python3-pip python3-venv \
    || die "python3-venv 설치 실패."
else
  echo "  이미 준비되어 있습니다."
fi

# ── 2. 가상환경 ──────────────────────────────────────────────────
step 2 "가상환경(.venv) 만들기"
if [ -f .venv/bin/activate ]; then
  echo "  이미 있습니다 — 그대로 씁니다."
else
  python3 -m venv .venv || die "가상환경 생성 실패."
  echo "  만들었습니다."
fi
# shellcheck disable=SC1091
. .venv/bin/activate || die ".venv 활성화 실패."

# ── 3. 계산 패키지 ───────────────────────────────────────────────
step 3 "계산 패키지 설치 (PySCF·RDKit 등 — 여기서 가장 오래 걸립니다)"
python -m pip install --quiet --upgrade pip
python -m pip install -r requirements.txt \
  || die "패키지 설치 실패 — 위 오류 메시지를 확인하세요."

# ── 4. 확인 ──────────────────────────────────────────────────────
step 4 "설치 확인"
MISSING=$(python - <<'PYEOF'
mods = []
for m in ("pyscf", "rdkit", "fastapi", "uvicorn"):
    try:
        __import__(m)
    except ImportError:
        mods.append(m)
print(" ".join(mods))
PYEOF
)
[ -n "${MISSING:-}" ] && die "설치됐어야 할 패키지가 없습니다: $MISSING"

python -c "import pyscf, rdkit; print('  PySCF', pyscf.__version__, '· RDKit', rdkit.__version__)"

echo
echo "${GREEN}${BOLD}설치가 끝났습니다.${OFF}"
echo
echo "  이제 아래 한 줄로 프로그램을 켭니다:"
echo "    ${BOLD}./scripts/start.sh${OFF}"
echo
echo "  ${DIM}실제 계산이 되는지까지 확인하려면 (약 1분):${OFF}"
echo "    ${DIM}. .venv/bin/activate && python -m scripts.smoke_test${OFF}"
echo
