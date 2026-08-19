# CLAUDE.md

AI 기반 건식 전극 공정 최적화 예측 프로그램 — 개발 가이드
KETI 차세대전지연구센터 | 기준 문서: 개발기획서 Rev.1.0, 기능정의서·기술스택서 통합본 Rev.1.0

---

## 1. 프로젝트 한 줄 정의

NCM811 / PTFE / Super C **3성분 고정 소재계**의 건식 전극 공정에서,
조성비 → 6단 공정 조건 → 단계별 물성 → 전기화학 성능의 연쇄를 ML로 학습하여
**순방향 예측(F1)** 과 **역방향 설계(F2)** 를 제공하는 오프라인 단일 PC 프로그램.

공정 순서 (고정, 변경 불가):
`Mixing → Kneading → Cutting → Milling(M1~M4) → Rolling(R1~R2) → Laminating(L1~L2)`

---

## 2. 절대 규칙 (위반 시 설계 오류로 간주)

아래 8개는 도메인 판단이 이미 끝난 사항이다. 코드 작성 중 "이렇게 하면 더 편할 것 같다"는 이유로 우회하지 말 것.

| # | 규칙 | 배경 |
|---|---|---|
| **R1** | **모든 두께·밀도·로딩은 합제층(composite layer) 기준.** Laminating 구간은 적재 시점(FD-05)에서 집전체 두께를 차감한다. 예측 시점 차감 금지. | 차감하지 않으면 Laminating 구간만 밀도가 비정상적으로 낮아져 단계 간 밀도 단조 증가 제약이 깨지고 모델이 잘못된 압축 거동을 학습한다. |
| **R2** | **공극률(electrode_porosity)은 예측·제약·알람 어디에도 사용하지 않는다.** 진밀도 가정에 의한 이론 계산 금지. 치밀화 지표는 **합제밀도 단독**. | 실측 라벨이 없고, 가정값 오차가 그대로 결과에 실린다. DB 스키마에는 자리만 남겨 둔다. |
| **R3** | **생성(합성) 데이터는 회귀 시험과 제약 학습에만 사용.** 정확도 평가(FE)와 변수 중요도 해석(FA)에서는 출처 플래그로 **코드 수준에서 자동 제외**한다. | 소수 실측에서 부트스트랩한 데이터로 성능을 재면 순환 논리. 평가·해석 함수는 `source_flag == 'measured'` 레코드만 입력으로 받도록 시그니처를 설계할 것. |
| **R4** | **전극 면적(`electrode_area_cm2`)은 모델 입력 벡터에 넣지 않는다.** Lot 속성으로만 기록하고 절대량 환산에만 사용. | 면적당 값은 정의상 면적으로 나눈 값이므로 중복 정보. 초기 소량 데이터에서 "면적이 크면 밀도가 높다" 같은 실험 일정의 흔적을 학습할 위험. |
| **R5** | **물리적으로 불가능한 예측은 화면에 절대 나오지 않는다.** 출력 제약층(FT-07) + 독립 정합성 검사기(FF-08) 이중 방어. | NFR-04: 제약 위반 출력 0 %. |
| **R6** | **물리 규칙 엔진(`rules/`)은 학습(`core/`)과 분리.** 규칙 추가·판정선 갱신이 재학습을 요구해서는 안 된다. | FV 기능군의 판정선은 실측 이력에서 동적으로 산출된다. 고정 상수 하드코딩 금지. |
| **R7** | **외부망 의존 금지.** 외부 API, CDN, 클라우드 서비스, 온라인 설치 전제 코드 모두 배제. wheelhouse 기반 오프라인 설치. | 드라이룸 PC 실행 환경. |
| **R8** | **재현성 3중 기록.** 난수 seed 고정 + 패키지 버전 `==` 잠금 + (모델 · scaling registry · 데이터셋) 버전의 짝 기록. 모델과 registry는 **항상 1:1로 함께 보관**. | registry가 어긋나면 역스케일링이 조용히 틀린다. 로드 시 버전 일치 검증 필수. |

---

## 3. 도메인 공식 (하드코딩 대상 — 단위 주의)

```
로딩 L/L (mg/cm²)      = 합제층 두께(μm) × 합제밀도(g/cc) × 0.1
면적당 용량 (mAh/cm²)   = 로딩 × 활물질 함량(wt 분율) × 비용량 ÷ 1000
합제층 두께 (μm)        = 측정 전체 두께 − 집전체 두께      # Laminating 구간
필요 로딩 (mg/cm²)      = 목표 면적당 용량 ÷ (활물질 함량 × 비용량) × 1000
최종 합제층 두께 (μm)    = 필요 로딩 ÷ 목표 합제밀도 ÷ 0.1
총 합제 질량 (g)        = 로딩 × 전극 면적(cm²) ÷ 1000     # 양면 도포는 × 도포 면수
총 용량 (mAh)          = 면적당 용량 × 전극 면적(cm²)
```

**고정 상수**
- NCM811 비용량 = **210 mAh/g** (변수 사전에 상수로 등록. 실측 확보 시 갱신)
- 조성 제약: `w(NCM811) + w(PTFE) + w(Super C) = 100 wt%` → **심플렉스 좌표계 2자유도**로 내부 처리

**정합성 제약 (모든 단계 출력에 적용)**
- 질량 보존: 세 값(두께·밀도·로딩) 중 둘이 정해지면 나머지는 종속
- 용량–로딩 연동: 조성 확정 시 비례
- 단계 간 단조성: **두께 단조 감소 / 합제밀도 단조 증가**
- 두께 하한: 각 단계 두께 > 해당 단계 롤 갭 (스프링백)
- 밀도 상한: 해당 조성 실측 최대 밀도 + 여유폭 (이력 테이블 참조, **동적 산출**)

> ⚠️ 기획서에 등장하는 조성비 96:2:2, 목표 5 mAh/cm², 3.2 g/cc 등의 수치는 **출력 형식을 설명하기 위한 예시**다. 고정 사양이 아니므로 사용자 구성 가능한 입력 폼으로 구현할 것. 비용량 210 mAh/g만 상수다.

---

## 4. 아키텍처 — 5계층 단방향 의존

```
L1 표현       Streamlit, Plotly           SC-01~06 화면
L2 응용 서비스  Python, Pydantic           유스케이스 조립, 입력 검증, 알람 판정
L3 ML 코어    TF/Keras, sklearn,          학습·추론·최적화·해석
              skopt, pymoo
L4 데이터 접근  pandas, SQLAlchemy, joblib  적재·정제·스케일링·조회
L5 저장       SQLite, 파일시스템           영속 저장, 산출물 보관
```

**L3 ML 코어는 L1을 알지 못한다.** Streamlit → 데스크톱 전환 시 L2~L5 코어 재사용률 100 %가 목표(NFR-10)이므로, UI 프레임워크 타입이 services/ 이하로 새어 들어가지 않게 할 것. 계층 간 인터페이스는 함수 시그니처 수준에서 고정한다.

### 디렉터리 구조

```
dry_process_ai/
├─ app/              L1 Streamlit 화면 (SC-01~06)
├─ services/         L2 순방향·역방향·검증·추천 서비스
├─ core/             L3 ML 코어
│   ├─ model/        모델 정의, custom loss, 출력 제약층
│   ├─ train/        Teacher/Student, 의사 라벨, 물리 필터
│   ├─ infer/        추론, MC Dropout, 정합성 검사
│   ├─ optimize/     BO 탐색, NSGA-II, 제약 필터
│   └─ analyze/      permutation importance, 상호작용
├─ data_access/      L4 리포지터리, 전처리 파이프라인, registry
├─ rules/            물리 규칙 엔진 (core와 분리 — R6)
├─ data/             raw / processed / pool / reference
├─ artifacts/        models / registry   (Git 제외)
├─ outputs/          predictions / importance / recommendations / evaluation
├─ tests/            단위 · 통합 · 회귀
├─ wheelhouse/       오프라인 설치용 wheel
├─ requirements.txt
└─ run.bat
```

---

## 5. 기능 ID 체계

기능 구현·수정 시 커밋 메시지와 docstring에 기능 ID를 명시한다. 총 64개.

| 코드 | 기능군 | STEP | 계층 | 개수 |
|---|---|---|---|---|
| **FD** | 데이터 관리 | 1 | L4/L5 | 8 |
| **FP** | 전처리 | 2 | L4 | 5 |
| **FT** | 모델 학습 | 3 | L3 | 8 |
| **FF** | 순방향 예측 | 4 | L2/L3 | 9 |
| **FV** | 스펙 타당성 검증 | 4/7 | L2 | 4 |
| **FA** | 변수 중요도 분석 | 5 | L3 | 5 |
| **FR** | 실험 추천 | 6 | L3 | 6 |
| **FB** | 역방향 설계 | 7 | L3 | 7 |
| **FE** | 평가·리포트 | 8 | L2/L3 | 7 |
| **FS** | 공통·시스템 | 전체 | L1/L2 | 5 |

요구기능 매핑: F1→FF+FV / F2→FB / F3→FV / F4→FA / F5→FR / F6→FT-08·FR-06·FE

---

## 6. 모델 구조 (FT-01)

```
Input (조성 + 6공정 조건 + collector_attached 플래그)
  └─ 공유 기저층 (Dense + Dropout ← MC Dropout에 재사용)
       ├─ 단계별 물성 분기  → 8단계 × 3항목 = 24 출력   [A등급, 단조성 제약]
       │      └─ concat ─→ 최종 물성 분기 → sheet_resistance  [A등급, 표준 손실]
       │                       └─→ 보조 물성 분기 → tensile_strength, adhesion
       │                                              [B등급, 마스킹 손실 FT-06]
       └─ 공유층 + 물성 분기 출력 concat → 성능 분기
              → ICE, initial_discharge_capacity, interface_resistance, retention
                                              [C등급, 준지도 라벨, 신뢰구간 필수]
  └─ 출력 제약층 (clipping + 단조성 강제)
```

**성능 분기가 물성 분기 출력을 입력으로 받는 것은 의도된 설계다.** "전극의 물리적 구조가 결정되어야 전기화학 특성이 발현된다"는 도메인 인과를 신경망 연결에 직접 주입한 것이므로, 리팩터링 중 병렬 분기로 평탄화하지 말 것.

### 목표 변수 확보 등급 — 학습 처리가 다르다

| 등급 | 변수 | 학습 처리 |
|---|---|---|
| **A** 상시 측정 | 단계별 24항목, electrode_thickness, electrode_density, sheet_resistance | 정식 지도학습 라벨. **정확도 평가의 기준** |
| **B** 간헐 측정 | tensile_strength, electrode_adhesion | **마스킹 손실** — 측정 Lot만 손실 계산, 미측정은 역전파 제외. 실측 건수 병기. 건수 임계 미달 시 최적화 제약으로 사용 금지(FB-07) |
| **C** 지연 측정 | initial_discharge_capacity, ICE, interface_resistance, retention, DCIR, rate_capability | Teacher → 의사 라벨 → **물리 정합성 필터(FT-04)** → Student. 신뢰 구간 필수 표기 |

결측은 **0이나 평균으로 채우지 않는다.** NaN 상태를 스케일링 이후에도 유지하고 마스크 인덱스로 관리한다(FP-02).

---

## 7. 데이터 모델 (SQLite)

`lot` · `formulation` · `process_condition` · `stage_measure` · `collector_info` ·
`electrode_property` · `electrochem` · `variable_dict` · `model_version` ·
`prediction_log` · `evaluation`

**`stage_measure`는 세로(long) 구조를 반드시 유지한다.** `stage_index`(M1~L2)를 컬럼으로 두어, 압연 단수가 늘어나도 스키마 변경이 없게 한다. Lot 1건당 8개 관측치를 학습 신호로 쓰는 설계와 직결된다. `process_condition`도 같은 이유로 Long 포맷.

### 산출물 명명 규칙

모든 산출물 파일명에 **모델 버전 또는 학습 Lot 수**를 포함시켜, 파일명만으로 생성 시점의 데이터·모델 상태를 추적할 수 있게 한다.

```
data/processed/       train_{YYYYMMDD}_{lotcount}.csv
data/pool/            pool_{YYYYMMDD}.csv
data/reference/       reference_{YYYYMMDD}.csv        # 원본 무변경 보존
artifacts/registry/   scaling_registry_{version}.pkl
artifacts/models/     dry_process_master_model_v{major}.{minor}/
outputs/predictions/  pred_{YYYYMMDD_HHMM}_{model_version}.json
outputs/evaluation/   eval_{model_version}.json / .docx
```

---

## 8. 기술 스택 (버전 고정 — 임의 상향 금지)

| 구분 | 패키지 | 비고 |
|---|---|---|
| 코어 | python 3.11.x, numpy **1.26.x**, pandas 2.1.x, scipy 1.11.x | numpy 2.x는 TF 2.15 의존 충돌로 보류 |
| ML | tensorflow **2.15.x**, scikit-learn 1.3.x | PyTorch 아님 — 다중 출력 + 출력별 손실 가중치 + 마스킹이 Keras 선언적 정의와 맞물림 |
| 최적화 | scikit-optimize 0.9 (EI), pymoo 0.6 (NSGA-II) | 탐색 차원 증가 시 BoTorch 교체 검토(R-07) |
| 데이터 | sqlalchemy 2.0, alembic, openpyxl 3.1, joblib 1.3 | |
| 검증 | pydantic 2.x | 조성 합계 100 wt% 등 도메인 제약을 스키마 수준에서 강제 |
| UI | streamlit 1.3x, plotly 5.x, matplotlib 3.8 | 조성 심플렉스는 Plotly Ternary |
| 리포트 | python-docx, jinja2 | |
| 시험 | pytest 7.x, pytest-cov | |

패키지 추가 시 **오프라인 wheelhouse 수집 가능 여부를 먼저 확인**한다(R7).

---

## 9. 개발 명령

```bash
# 가상환경 (Windows 드라이룸 PC 기준)
python -m venv .venv && .venv\Scripts\activate

# 오프라인 설치
pip install --no-index --find-links=wheelhouse -r requirements.txt

# 실행
run.bat                    # venv 활성화 → Streamlit 기동 → 브라우저 실행
                           # 서버는 localhost 바인딩만 허용

# 시험
pytest tests/ -v
pytest tests/unit/test_physics.py       # 물리 계산식 — 기준값 대비 오차 0
pytest tests/regression/ -v             # 동일 seed 결과 동일성

# 마이그레이션
alembic revision --autogenerate -m "..."
alembic upgrade head

# 오프라인 wheel 수집 (외부망 PC에서)
pip download -r requirements.txt -d wheelhouse --platform win_amd64 --python-version 311
```

---

## 10. 코딩 컨벤션

- **변수명은 변수 사전(`variable_dict`)과 일치시킨다.** 임의 축약 금지. 신규 변수는 사전 등록 → 마이그레이션 → 코드 순서.
- 단위를 변수명 또는 타입에 명시: `composite_thickness_um`, `loading_mg_cm2`, `areal_capacity_mah_cm2`.
- 물리 계산식은 `rules/` 또는 전용 모듈에 **단일 정의**하고 재구현하지 않는다. pytest로 오차 0 검증 대상.
- 모든 예측 결과 객체는 **신뢰 구간 + 확보 등급(A/B/C) 배지**를 반드시 동반한다(NFR-05). 등급 없는 예측값 반환 금지.
- 예측·평가 결과에는 **모델 버전과 학습 Lot 수**를 반드시 기록한다(NFR-08, FS-02).
- 판정 임계값을 상수로 박지 말 것 — 실측 이력에서 동적 산출(FV-04).
- 대용량 모델 파일은 Git에서 제외하고 `artifacts/`로 관리.

---

## 11. Phase 계획 (총 23주)

| Phase | 기간 | 기능 | 완료 판정 |
|---|---|---|---|
| 1 | 3주 | FD-01~08, FP-01~05 | 데이터 오류 없이 적재 + scaling registry 생성 |
| 2 | 4주 | FT-01~07 | 준지도 학습 완료, **물리 제약 위반 0건** |
| 3 | 3주 | FF-01~09, FV-01~03, FS-01·02·04 | 조성 입력 → 조건표 + 단계별 예측표, 알람 동작 |
| 4 | 2주 | FA-01~05 | 목표별 중요도 및 상호작용 맵 |
| 5 | 4주 | FR-01~06, FB-01~07 | 목표 성능 입력 → 실현 가능 후보 5건 |
| 6 | 3주 | FE-01~07, FT-08, FV-04, FS-03 | 평가 리포트 자동 생성, 폐루프 재학습 |
| 7 | 4주 | 실증 | 실증 실험 3~5건, 예측 구간 적중 3/5 이상 |

**Phase 1~3 = MVP.** 이 시점에서 순방향 예측(F1)이 실사용 가능해야 한다.

---

## 12. 자주 발생하는 함정 (안티패턴)

| 증상 | 원인 | 대응 |
|---|---|---|
| Laminating 구간만 밀도가 비정상적으로 낮음 | 집전체 두께 미차감 | R1 — 적재 시점 환산 확인 |
| 역스케일링 결과가 조용히 틀림 | model / registry 버전 불일치 | R8 — 로드 시 버전 일치 검증 (R-03) |
| 극단적 저항값·음수 용량 출력 | 저변동 변수의 Min-Max 스케일 발산 + 출력 범위 제약 누락 | FP-05 자동 제외 + 출력 제약층 병행 (R-04) |
| 정확도가 비현실적으로 높음 | 생성 데이터가 평가에 혼입 | R3 — 출처 플래그 격리 (R-02) |
| 특정 변수에 중요도가 과도 집중 | 초기 데이터 부족 | 리포트에 학습 Lot 수·신뢰 수준 병기, 시계열 관리 (R-01) |
| 무리한 저바인더 조건 추천 | 시트 강도 라벨 부족 | FB-07 제약 배제, 저바인더 실험 시 최소 1항목 측정 권고 (R-05) |
| 역방향 응답 60초 초과 | 탐색 차원 과다 | FA 중요도 상위 변수로 탐색 공간 축소 (R-07) |

---

## 13. 현재 제약 상황 (착수 시점)

- **실측 Lot 수가 매우 적다.** 정확도 지표(NFR-03: 두께 MAPE < 10 %, 합제밀도 MAPE < 5 %)는 **실측 30건 이상 확보 시점부터 적용**한다. 그 전까지 판정 기준은 워크플로우 정상 동작과 물리 제약 준수다.
- **기존 예비 모델은 사용할 수 없다.** 다중 바인더 · Extruder/Calender 스키마 기반이라 본 과제 범위(PTFE 고정, Mixing/Kneading/Rolling)와 호환되지 않는다. FT 기능군은 **신규 구축 전제**.
- mixing / kneader torque는 추가 비용 없이 설비 로그로 취득 가능하나 **현재 미확보**. 변수 사전에 사전 등록해 두고, 확보 시 PTFE 피브릴화의 직접 지표로 활용.
- 인장강도·접착력이 모두 간헐 측정이라 **시트 강도를 대변하는 상시 라벨이 없다.** 현재 데이터 체계의 가장 큰 약점.

---

## 14. 명시적 제외 범위

설비 제어(PLC) 연동 · 실시간 인라인 계측 · **공극률 예측** · 소재 종류 탐색 ·
클라우드 배포 · 다중 사용자 동시 접속 · 계정 기반 인증

이 항목들에 대한 코드나 스캐폴딩을 선제적으로 추가하지 말 것.

---

## 15. 참조 문서

| ID | 문서 | 판번호 |
|---|---|---|
| REF-01 | AI 기반 건식 공정 최적화 예측 프로그램 개발 기획서 | Rev. 1.0 (2026-07-21) |
| REF-02 | 기능정의서 · 기술스택서 통합본 | Rev. 1.0 (2026-07-22) |
| REF-03 | KETI 건식 전극 실험 Lot 데이터 정의서 (변수 사전) | — |

기능 또는 기술이 추가·변경되면 REF-02의 **18.3 기능–기술 매핑 표**와 본 파일을 함께 갱신한다.
