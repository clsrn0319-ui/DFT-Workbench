"""전역 설정 및 도메인 고정 상수.

여기에 정의된 값 중 도메인 상수는 NCM811 비용량(210 mAh/g)과 공정 순서뿐이다.
기획서에 등장하는 조성비 96:2:2, 목표 5 mAh/cm² 등의 수치는 예시이며
사용자 구성 가능한 입력으로 처리한다 (CLAUDE.md 3장 주의사항).
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# 경로 규약 (기능정의서 12.2 파일 산출물 규약)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(os.environ.get("DRY_PROCESS_AI_ROOT", Path(__file__).resolve().parent.parent))

DATA_DIR = PROJECT_ROOT / "data"
DATA_RAW_DIR = DATA_DIR / "raw"
DATA_PROCESSED_DIR = DATA_DIR / "processed"
DATA_POOL_DIR = DATA_DIR / "pool"
DATA_REFERENCE_DIR = DATA_DIR / "reference"

ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
MODELS_DIR = ARTIFACTS_DIR / "models"
REGISTRY_DIR = ARTIFACTS_DIR / "registry"

OUTPUTS_DIR = PROJECT_ROOT / "outputs"
PREDICTIONS_DIR = OUTPUTS_DIR / "predictions"
IMPORTANCE_DIR = OUTPUTS_DIR / "importance"
RECOMMENDATIONS_DIR = OUTPUTS_DIR / "recommendations"
EVALUATION_DIR = OUTPUTS_DIR / "evaluation"

DB_PATH = DATA_DIR / "dry_process.db"
DB_URL = f"sqlite:///{DB_PATH}"


def ensure_directories() -> None:
    """산출물 디렉터리를 생성한다 (존재 시 무시)."""
    for d in (
        DATA_RAW_DIR, DATA_PROCESSED_DIR, DATA_POOL_DIR, DATA_REFERENCE_DIR,
        MODELS_DIR, REGISTRY_DIR,
        PREDICTIONS_DIR, IMPORTANCE_DIR, RECOMMENDATIONS_DIR, EVALUATION_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 도메인 고정 상수
# ---------------------------------------------------------------------------
# NCM811 비용량 (mAh/g). 변수 사전에 상수로 등록되며 실측 확보 시 갱신한다.
NCM811_SPECIFIC_CAPACITY_MAH_G = 210.0

# 조성 합계 제약 (wt%)
COMPOSITION_TOTAL_WT = 100.0

# 공정 순서 (고정, 변경 불가)
PROCESS_ORDER = ("mixing", "kneading", "cutting", "milling", "rolling", "laminating")

# 압연 단계 인덱스 — stage_measure의 stage_index 값. 순서가 곧 공정 진행 순서다.
STAGES = ("M1", "M2", "M3", "M4", "R1", "R2", "L1", "L2")

# 집전체가 부착되는 단계 (Laminating 구간). 이 단계의 측정 두께는
# 적재 시점(FD-05)에 집전체 두께를 차감하여 합제층 기준으로 환산한다 (규칙 R1).
COLLECTOR_ATTACHED_STAGES = ("L1", "L2")

# 단계별 예측 3항목
STAGE_TARGETS = ("areal_capacity_mah_cm2", "composite_thickness_um", "composite_density_gcc")

# 질량 보존식 허용 오차 (FP-01): |로딩 − 두께×밀도×0.1| / 로딩 > 3% 이면 이상치
MASS_BALANCE_TOLERANCE = 0.03

# 의사 라벨 필터(FT-04)의 정합성 허용 오차 — 계측 오차 기준(3%)과 달리 초기
# 미성숙 모델의 예측 자기일관성에 적용되므로 완화된 값으로 시작한다.
# 실측 축적·모델 성숙에 따라 폐루프(FE-07)에서 단계적으로 조인다.
PSEUDO_FILTER_TOLERANCE = 0.20

# 재현성 (규칙 R8): 학습·의사 라벨·최적화 전 구간에서 사용하는 기본 seed
DEFAULT_SEED = 42

# MC Dropout 반복 횟수 기본값 (성능 설계 15장: 30~50회, 응답 시간 예산 내 조정)
MC_DROPOUT_SAMPLES = 30

# B등급(간헐 측정) 변수를 역방향 최적화 제약으로 사용하기 위한 최소 실측 건수 (FB-07)
INTERMITTENT_CONSTRAINT_MIN_COUNT = 10

# 의사 라벨 물리 정합성 필터 최소 통과율 (FT-04): 미만이면 Student 학습 중단
PSEUDO_LABEL_MIN_PASS_RATE = 0.5

# 스프링백: 각 단계 두께 > 해당 단계 롤 갭. 이력 데이터가 없을 때의 초기 여유율.
# FV-04에 따라 실측 이력이 쌓이면 동적으로 재산출된다 (고정 판정선 아님).
DEFAULT_SPRINGBACK_RATIO = 0.05

# 단계별 최대 압하율(두께 감소율) 초기값 — 실측 이력 축적 시 동적 갱신 대상
DEFAULT_MAX_REDUCTION_RATIO = 0.55

# 합제밀도 상한 여유폭 (조성별 실측 최대 밀도 + 여유폭, g/cc)
DENSITY_HEADROOM_GCC = 0.15

# 저변동 변수 자동 제외 기준 (FP-05): (max-min)/|median| 이 이 값 미만이면 상수 취급
LOW_VARIANCE_THRESHOLD = 1e-6
