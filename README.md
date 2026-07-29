# DFT-Workbench — AI 기반 건식 전극 공정 최적화 예측 프로그램

KETI 차세대전지연구센터 · NCM811 / PTFE / Super C 3성분 고정 소재계

`Mixing → Kneading → Cutting → Milling(M1~M4) → Rolling(R1~R2) → Laminating(L1~L2)`
6단 건식 공정에서 **조성비 → 공정 조건 → 단계별 물성 → 전기화학 성능**의 연쇄를
ML로 학습하여 **순방향 예측(F1)** 과 **역방향 설계(F2)** 를 제공하는
오프라인 단일 PC 프로그램입니다.

기준 문서: 개발기획서 Rev.1.0 (2026-07-21) · 기능정의서·기술스택서 통합본 Rev.1.0 (2026-07-22) · `CLAUDE.md`

## 주요 기능

| 요구 기능 | 화면 | 내용 |
|---|---|---|
| F1 순방향 | SC-01 | 조성비 + 목표 사양 → 갭 스케줄 + 단계별(M1~L2) 24항목 예측 + 신뢰 구간 |
| F2 역방향 | SC-02 | 목표 성능 → NSGA-II Pareto front + 추천 레시피 5건 |
| F3 스펙 검증 | SC-01/02 | 실측 이력 기반 6항목 판정, 정보/주의/경고 알람, 대안 스펙 제안 |
| F4 변수 분석 | SC-03 | Permutation importance, 조성-공정 상호작용 히트맵 |
| F5 실험 추천 | SC-04 | MC Dropout 불확실성 기반 능동학습 Top-K 추천 |
| F6 재학습 | SC-05 | Teacher/Student 준지도 학습, 모델 버전 관리, 평가 리포트 |

## 설치 (오프라인 드라이룸 PC)

```bash
# 1) 외부망 PC에서 wheel 수집
pip download -r requirements.txt -d wheelhouse --platform win_amd64 --python-version 311

# 2) 대상 PC — 가상환경 생성 후 오프라인 설치
python -m venv .venv
.venv\Scripts\activate
pip install --no-index --find-links=wheelhouse -r requirements.txt
```

## 실행

```bash
run.bat          # Windows: venv 활성화 → Streamlit 기동 (localhost 바인딩)

# 또는 직접 실행
PYTHONPATH=. streamlit run dry_process_ai/app/Home.py --server.address 127.0.0.1
```

첫 실행 순서: **SC-06 데이터 관리**에서 Lot 등록(또는 합성 데이터 생성) →
**SC-05 모델 관리**에서 학습 실행 → **SC-01 순방향 예측** 사용.

## 시험

```bash
pytest tests/ -v
pytest tests/unit/test_physics.py       # 물리 계산식 — 기준값 대비 오차 0
pytest tests/regression/ -v             # 동일 seed 결과 동일성 (NFR-07)
```

## 아키텍처 — 5계층 단방향 의존

```
dry_process_ai/
├─ app/              L1 Streamlit 화면 (SC-01~06)
├─ services/         L2 유스케이스 조립·입력 검증·알람 판정 (Pydantic)
├─ core/             L3 ML 코어 (TF/Keras · skopt · pymoo)
│   ├─ model/        다중 출력 모델, 마스킹 손실, 출력 제약층
│   ├─ train/        Teacher/Student, 의사 라벨 물리 필터, 버전 관리
│   ├─ infer/        MC Dropout 추론, 갭 스케줄 탐색, 정합성 검사
│   ├─ optimize/     역방향 설계(NSGA-II/BO), 능동학습 추천
│   └─ analyze/      Permutation importance, 평가·리포트
├─ data_access/      L4 리포지터리·전처리·scaling registry (SQLAlchemy)
├─ rules/            물리 규칙 엔진 — 학습과 분리, 판정선 동적 산출
├─ data/ artifacts/ outputs/   L5 저장 (Git 제외)
└─ tests/            단위 · 통합 · 회귀
```

## 설계 핵심 규칙 (CLAUDE.md 절대 규칙 요약)

- 모든 두께·밀도·로딩은 **합제층 기준** — Laminating 은 적재 시점에 집전체 차감 (R1)
- 공극률은 어디에도 사용하지 않음 — 치밀화 지표는 합제밀도 단독 (R2)
- 생성 데이터는 회귀 시험·제약 학습 전용 — 평가·해석에서 코드 수준 자동 제외 (R3)
- 전극 면적은 모델 입력이 아닌 Lot 속성 — 절대량 환산 전용 (R4)
- 출력 제약층 + 독립 정합성 검사기 이중 방어 — 물리 위반 출력 0 % (R5)
- 물리 규칙 엔진은 학습과 분리 — 판정선은 실측 이력에서 동적 산출 (R6)
- 외부망 의존 금지 — wheelhouse 오프라인 설치 (R7)
- seed 고정 + 버전 잠금 + 모델·registry 1:1 짝 보관, 로드 시 검증 (R8)
