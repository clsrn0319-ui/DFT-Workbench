#!/usr/bin/env bash
# 네이버 클라우드(또는 아무 Ubuntu 서버) 최초 설치 — 한 번만 실행한다.
#
#   git clone https://github.com/clsrn0319-ui/DFT-Workbench && cd DFT-Workbench
#   ./scripts/ncp_setup.sh                 # 서비스 등록까지 (nginx 포함)
#   ./scripts/ncp_setup.sh --no-nginx      # 8000 번을 직접 쓸 때
#   ./scripts/ncp_setup.sh --branch main   # 특정 브랜치로 맞춘 뒤 설치
#
# 하는 일:
#   1. apt 패키지(git·python3-venv·nginx)  2. .venv + PySCF 등 설치(setup.sh)
#   3. /etc/rhobench.env 생성(비밀번호)      4. systemd 서비스 등록·시작
#   5. nginx 리버스 프록시(80 → 8000)        6. 접속 주소·다음 할 일 안내
#
# 이미 끝난 단계는 건너뛰므로 실패한 자리에서 다시 실행해도 된다.

set -u
cd "$(dirname "$0")/.."
DIR=$(pwd)
USER_NAME=$(id -un)
BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; RED=$'\033[31m'; OFF=$'\033[0m'
step() { echo; echo "${BOLD}[$1/6] $2${OFF}"; }
die()  { echo; echo "${RED}실패: $1${OFF}" >&2; exit 1; }

WITH_NGINX=1
BRANCH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-nginx) WITH_NGINX=0 ;;
    --branch) BRANCH="$2"; shift ;;
    *) die "알 수 없는 옵션: $1" ;;
  esac
  shift
done

echo "${BOLD}================================================================${OFF}"
echo "${BOLD}  RhoBench 서버 설치 (${USER_NAME} @ $(hostname))${OFF}"
echo "  ${DIM}저장소: $DIR${OFF}"
echo "${BOLD}================================================================${OFF}"

# ── 1. 시스템 패키지 ──────────────────────────────────────────────
step 1 "시스템 패키지"
PKGS="git python3-pip python3-venv curl"
[ "$WITH_NGINX" = "1" ] && PKGS="$PKGS nginx"
sudo apt-get update -qq || die "apt update 실패 — 인터넷·ACG(아웃바운드) 확인"
# shellcheck disable=SC2086
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $PKGS || die "패키지 설치 실패"
echo "  준비됨: $PKGS"

if [ -n "$BRANCH" ]; then
  git fetch --quiet origin && git checkout --quiet "$BRANCH" && git pull --ff-only --quiet || die "브랜치 전환 실패: $BRANCH"
  echo "  브랜치: $BRANCH ($(git log --format=%h -1))"
fi

# ── 2. 파이썬 환경 ───────────────────────────────────────────────
step 2 "가상환경·계산 패키지 (처음이면 5~10분)"
./scripts/setup.sh >/tmp/rhobench-setup.log 2>&1 || { tail -20 /tmp/rhobench-setup.log; die "setup.sh 실패 — /tmp/rhobench-setup.log"; }
.venv/bin/python -c "import pyscf, rdkit; print('  PySCF', pyscf.__version__, '· RDKit', rdkit.__version__)"

# ── 3. 환경 파일 ─────────────────────────────────────────────────
step 3 "/etc/rhobench.env"
if [ -f /etc/rhobench.env ]; then
  echo "  이미 있습니다 — 그대로 둡니다 (바꾸려면 sudo nano /etc/rhobench.env)"
else
  printf '공유할 접속 비밀번호를 정하세요 (Enter = 무작위 발급, 로그에 한 번 출력): '
  read -r PW
  sudo install -m 600 /dev/null /etc/rhobench.env
  {
    [ -n "$PW" ] && echo "RHOBENCH_ACCESS_PASSWORD=$PW"
    echo "RHOBENCH_PORT=8000"
    [ "$WITH_NGINX" = "1" ] && echo "RHOBENCH_HOST=127.0.0.1" || echo "RHOBENCH_HOST=0.0.0.0"
    echo "RHOBENCH_WORKERS=1"
    echo "RHOBENCH_MAX_ACTIVE_JOBS=4"
    echo "RHOBENCH_MAX_ATOMS=60"
    echo "RHOBENCH_BATCH_PARALLEL=1"
    echo "RHOBENCH_MAX_BATCH=500"
    echo "RHOBENCH_BATCH_FAIL_RATIO=0.3"
  } | sudo tee /etc/rhobench.env >/dev/null
  echo "  만들었습니다 (권한 600)"
fi

# ── 4. systemd 서비스 ────────────────────────────────────────────
step 4 "systemd 서비스 rhobench"
sed -e "s|__USER__|$USER_NAME|g" -e "s|__DIR__|$DIR|g" deploy/ncp/rhobench.service \
  | sudo tee /etc/systemd/system/rhobench.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --quiet rhobench
sudo systemctl restart rhobench
for i in $(seq 1 60); do
  sleep 1
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/ || true)
  [ "$code" = "200" ] && break
done
[ "$code" = "200" ] || { sudo journalctl -u rhobench -n 30 --no-pager; die "서비스가 60초 안에 응답하지 않습니다 — journalctl -u rhobench"; }
echo "  실행 중 (HTTP $code) — 로그: sudo journalctl -u rhobench -f"

# ── 5. nginx ─────────────────────────────────────────────────────
step 5 "nginx 리버스 프록시 (80 → 8000)"
if [ "$WITH_NGINX" = "1" ]; then
  sudo cp deploy/ncp/nginx-rhobench.conf /etc/nginx/sites-available/rhobench
  sudo ln -sf /etc/nginx/sites-available/rhobench /etc/nginx/sites-enabled/rhobench
  sudo rm -f /etc/nginx/sites-enabled/default
  sudo nginx -t >/dev/null 2>&1 || die "nginx 설정 오류 — sudo nginx -t"
  sudo systemctl enable --quiet nginx && sudo systemctl reload nginx
  echo "  적용됨. 도메인이 있으면: sudo certbot --nginx -d <도메인>  (sudo apt install certbot python3-certbot-nginx)"
else
  echo "  건너뜀 (--no-nginx). ACG 에서 8000 번을 열어야 접속됩니다"
fi

# ── 6. 안내 ──────────────────────────────────────────────────────
step 6 "완료"
PUB_IP=$(curl -s --max-time 3 https://api.ipify.org || hostname -I | awk '{print $1}')
echo
echo "${GREEN}${BOLD}  RhoBench 가 서비스로 떠 있습니다.${OFF}"
echo
if [ "$WITH_NGINX" = "1" ]; then
echo "  접속 주소   ${BOLD}http://${PUB_IP}/${OFF}   (ACG 에서 80 — 도메인+HTTPS 면 443 — 을 허용하세요)"
else
echo "  접속 주소   ${BOLD}http://${PUB_IP}:8000/${OFF}   (ACG 에서 8000 을 허용하세요)"
fi
echo "  비밀번호    /etc/rhobench.env 의 RHOBENCH_ACCESS_PASSWORD (무작위 발급이면: sudo journalctl -u rhobench | grep -A3 '접속 비밀번호')"
echo
echo "  자주 쓰는 명령"
echo "    상태/로그   sudo systemctl status rhobench · sudo journalctl -u rhobench -f"
echo "    업데이트    ./scripts/update.sh            (계산이 끝날 때까지 기다렸다가 재시작)"
echo "    백업        ./scripts/backup_data.sh       (data/ → backups/ · Object Storage)"
echo
echo "  ${DIM}보안: 공인 IP + HTTP 는 세션 쿠키가 평문으로 오갑니다. ACG 접속 허용 IP 를 제한하거나"
echo "  도메인을 붙여 HTTPS(certbot)를 쓰세요. 8000 번은 외부에 열지 마세요.${OFF}"
