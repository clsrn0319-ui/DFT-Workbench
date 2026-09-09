#!/usr/bin/env bash
# 결과 백업 — data/ (작업·캠페인·로그·비밀번호 해시·Li⁺ 참조 캐시)를 날짜별 tar.gz 로 묶는다.
# 네이버 클라우드 Object Storage(S3 호환)에 올리려면 AWS CLI 자격증명을 넣어 둔다.
#
#   ./scripts/backup_data.sh                   # backups/rhobench-data-YYYYMMDD-HHMM.tar.gz
#   ./scripts/backup_data.sh --no-logs         # 원본 로그(용량 큼) 제외
#   ./scripts/backup_data.sh --upload 버킷이름  # Object Storage 로 업로드까지
#   ./scripts/backup_data.sh --keep 14         # 로컬 백업 14개만 남기고 오래된 것 삭제
#
# Object Storage 준비 (한 번):
#   sudo apt install -y awscli
#   aws configure            # NCP 콘솔 > 마이페이지 > 인증키 관리의 Access/Secret 키, region: kr-standard
#   (엔드포인트는 이 스크립트가 https://kr.object.ncloudstorage.com 으로 지정한다)
#
# 매일 새벽 3시 자동 백업 (crontab -e):
#   0 3 * * * /home/ubuntu/DFT-Workbench/scripts/backup_data.sh --upload rhobench-backup --keep 14 >> /home/ubuntu/backup.log 2>&1

set -u
cd "$(dirname "$0")/.."
DATA_DIR="${RHOBENCH_DATA_DIR:-$(pwd)/data}"
[ -f /etc/rhobench.env ] && grep -qE '^RHOBENCH_DATA_DIR=' /etc/rhobench.env \
  && DATA_DIR=$(grep -E '^RHOBENCH_DATA_DIR=' /etc/rhobench.env | cut -d= -f2 | tr -d ' ')
OUT_DIR="$(pwd)/backups"
ENDPOINT="${NCP_OBJECT_ENDPOINT:-https://kr.object.ncloudstorage.com}"
NO_LOGS=0; BUCKET=""; KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --no-logs) NO_LOGS=1 ;;
    --upload) BUCKET="$2"; shift ;;
    --keep) KEEP="$2"; shift ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 1 ;;
  esac
  shift
done

[ -d "$DATA_DIR" ] || { echo "data 폴더가 없습니다: $DATA_DIR" >&2; exit 1; }
mkdir -p "$OUT_DIR"
STAMP=$(date '+%Y%m%d-%H%M')
FILE="$OUT_DIR/rhobench-data-$STAMP.tar.gz"
EXCL=()
[ "$NO_LOGS" = "1" ] && EXCL=(--exclude='logs/*.log' --exclude='logs/*.trajectory.xyz')
# jobs.json 은 서버가 원자적으로(tmp → rename) 쓰므로 실행 중에 묶어도 반쪽 파일이 들어가지 않는다
tar -czf "$FILE" -C "$(dirname "$DATA_DIR")" "${EXCL[@]}" "$(basename "$DATA_DIR")" \
  || { echo "tar 실패" >&2; exit 1; }
echo "$(date '+%F %T') 백업: $FILE ($(du -h "$FILE" | cut -f1))"

if [ -n "$BUCKET" ]; then
  command -v aws >/dev/null 2>&1 || { echo "aws CLI 가 없습니다: sudo apt install -y awscli" >&2; exit 1; }
  aws --endpoint-url "$ENDPOINT" s3 cp "$FILE" "s3://$BUCKET/$(basename "$FILE")" \
    && echo "$(date '+%F %T') 업로드: s3://$BUCKET/$(basename "$FILE")" \
    || { echo "업로드 실패 — aws configure 와 버킷 이름 확인" >&2; exit 1; }
fi

if [ "$KEEP" -gt 0 ] 2>/dev/null; then
  ls -1t "$OUT_DIR"/rhobench-data-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
    rm -f "$old" && echo "정리: $(basename "$old")"
  done
fi
