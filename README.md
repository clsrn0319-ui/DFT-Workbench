# DFT-Workbench (RhoBench)

배터리 바인더/전해액 후보 분자의 물성을 **실제 DFT 계산**으로 산출하는 웹 워크벤치입니다.
기존 RhoBench UI 프로토타입(모의 데이터)의 설정 체계를 그대로 따르되, 백엔드를
PySCF 기반 실계산 엔진으로 구현했습니다.

## 아키텍처

```
web/       프론트엔드 (환경 설정 → 작업 제출 → 결과 조회, 한국어 UI)
server/
  main.py      FastAPI API + 정적 파일 서빙
  presets.py   환경·용매(SMD 파라미터)·소재·정확도 프리셋
  geometry.py  RDKit: SMILES → ETKDG conformer → MMFF/UFF → 최저 에너지 구조
  engine.py    PySCF: DFT 구조 최적화 · SMD 용매화 · D3(BJ) · 기술자/전위 산출
  worker.py    백그라운드 순차 계산 큐
  store.py     작업 저장 (data/jobs.json)
```

## 설치 및 실행

### Windows (WSL2)

PySCF는 Windows 네이티브를 지원하지 않으므로 WSL2에서 백엔드를 실행합니다.
설치 후에는 Windows 브라우저에서 그대로 `http://localhost:8000`으로 접속됩니다.

```powershell
# PowerShell (관리자 권한) — WSL2 + Ubuntu 설치 후 재부팅
wsl --install -d Ubuntu
```

재부팅 후 시작 메뉴 → "Ubuntu" 실행. 이하 우분투 터미널에서 **한 줄씩** 입력합니다
(여러 줄을 한 번에 붙여넣으면 `apt`가 `python3`·`venv`·`pip`까지 설치할 패키지
이름으로 받아들여 엉뚱하게 동작합니다):

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv git
git clone https://github.com/clsrn0319-ui/DFT-Workbench
cd DFT-Workbench
./scripts/setup.sh        # 가상환경 생성 + 패키지 설치 + 설치 확인 (5~10분)
./scripts/start.sh        # 실행 — 접속 주소와 비밀번호를 함께 출력
```

`setup.sh`는 이미 끝난 단계는 건너뛰므로 실패한 자리에서 다시 실행해도 됩니다.
직접 단계를 밟고 싶다면:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m uvicorn server.main:app --host 0.0.0.0 --port 8000
```

> `uvicorn` 명령이 PATH에 없어 `Command 'uvicorn' not found`가 뜨면 위처럼
> `python3 -m uvicorn`으로 실행하세요. 이때 안내되는 `sudo apt install uvicorn`은
> **다른 패키지**이므로 설치해도 해결되지 않습니다.

메모리가 부족해 계산이 느리면 `C:\Users\<이름>\.wslconfig`에 `[wsl2]` /
`memory=12GB` 식으로 상향한 뒤 `wsl --shutdown`으로 재시작합니다.

### 리눅스 · 맥

```bash
./scripts/setup.sh
./scripts/start.sh
# → http://localhost:8000
```

빠른 검증:

```bash
python -m scripts.smoke_test   # 아크릴로나이트릴 1건 실계산 (~1분)
python -m pytest tests/ -v     # 단위 테스트 (실 SCF 포함, ~30초)
```

## 시연 (한 줄 실행)

```bash
./scripts/start.sh             # 비밀번호를 물어본 뒤 시작 — 접속 주소를 함께 출력
./scripts/start.sh 비밀번호     # 비밀번호를 인자로 지정
```

Windows에서는 `RhoBench-start.bat`을 더블클릭하면 WSL 안의 서버를 켜고
브라우저를 자동으로 엽니다 (파일 안의 `WSLDIR` 경로만 한 번 확인).

시연 전에 보여줄 결과를 미리 만들어 두면 대기 시간이 없습니다:

```bash
python -m scripts.seed_demo              # EC·DMC·VDF·AN·AA 5종, '빠름', 약 3분
python -m scripts.seed_demo --list       # 무엇을 계산할지만 확인
python -m scripts.seed_demo --only EC,AN --accuracy 표준
```

전위까지 계산하므로 «전기화학 안정성(ESW)» 차트가 바로 그려집니다.

인터넷으로 공개해야 하면 `notebooks/RhoBench_Colab.ipynb`를 Google Colab에서
열어 실행하세요 — 무료로 공개 HTTPS 주소가 만들어집니다. 자세한 비교는
아래 [원격 공유](#원격-공유-사내망-밖에서-보여주기) 참고.

## 용도 분리 — 전해액 / 건식 음극 바인더

같은 설치본으로 **결과와 접속 비밀번호가 분리된 두 프로그램**을 동시에 운용합니다.
판정 기준이 다르기 때문입니다 — 전해액 첨가제는 용매에 잘 녹어야 유리하지만,
바인더는 전해액에 녹으면 전극이 무너지므로 같은 «용매화 에너지»를 반대로 읽습니다.

```bash
./scripts/start.sh          # 전해액·분자 반응성 — 8000번, data/
./scripts/start_binder.sh   # 건식 음극 바인더  — 8001번, data-binder/
```

| | 전해액 · 분자 반응성 | 건식 음극 바인더 |
|---|---|---|
| 핵심 질문 | 양극·음극 양쪽 전위를 견디는가 | 음극 환원 + 건식 공정을 견디는가 |
| 1차 관문 | 없음 | **PFAS 여부** — 계산 없이 구조로 즉시 판정 |
| 결정 지표 | 산화 · 환원 전위 | **환원 전위** (기준 0.05 V vs Li/Li⁺) |
| 열 조건 | 상온 298 K | 건식 공정 180 °C + 전단 |
| 용매화 해석 | 클수록(음수) 유리 — 잘 녹아야 함 | 작을수록 유리 — **덜 녹아야** 함 |

저장 위치는 `RHOBENCH_DATA_DIR`로 바꿉니다. 두 서버는 `data/`와 `data-binder/`를
각각 쓰므로 결과·비밀번호를 공유하지 않습니다.

### 바인더 스크리닝 화면

사이드바 «건식 바인더» 그룹:

- **바인더 후보군** — PFAS-free 후보 14종 + 현행 표준 기준군(PTFE·PVDF) 2종.
  PFAS 배지가 즉시 표시되고, 계열 필터·일괄 선택 후 한 번에 제출합니다.
  임의 SMILES의 PFAS 판정도 계산 없이 바로 확인됩니다.
- **후보 순위** — 완료된 결과를 바인더 관점으로 판정합니다.
  PFAS 게이트와 절대 판정(환원·열 안정성)은 통과/탈락, 접착·응집·팽윤·극성은
  후보 간 상대 순위로만 제시합니다.

결과 상세 상단에는 «건식 음극 바인더 적합성» 스코어카드가 붙습니다.

| 축 | 종류 | 기준 |
|---|---|---|
| PFAS 게이트 | 통과/탈락 | OECD 2021 — 완전 불소화 탄소(-CF₃/-CF₂-) 포함 여부 |
| 환원 안정성 | 절대 판정 | 가장 가혹한 음극 전위(리튬 금속 0 V) 대비 여유 |
| 열 안정성 | 절대 판정 | 최약 결합 BDE(298 K) — 350/300 kJ/mol 경계 |
| 접착 · 응집 · 팽윤 저항 · 극성 | **상대 순위만** | 대용 클러스터 기반이라 절대 기준을 두지 않음 |

> 현행 표준인 PTFE·PVDF를 기준군으로 함께 계산하세요. PFAS라 탈락이지만 성능 축에서는
> 상위권에 나와야 정상이며, 그렇지 않다면 판정 축 설계를 재검토해야 한다는 신호입니다.

자세한 배경과 보완 계획은 `docs/05_RhoBench_건식음극바인더_기획서.docx` 참고.

## 연구실 내부 공유 (공유 비밀번호)

서버 한 대에 띄우면 다른 사람은 **설치 없이 브라우저로만** 접속합니다.
개별 계정은 두지 않고, **관리자가 공유한 비밀번호를 아는 사람만** 들어올 수 있습니다.

```bash
# 서버 컴퓨터에서 — 공유할 비밀번호를 직접 정해서 실행
RHOBENCH_ACCESS_PASSWORD='연구실에_공유할_비밀번호' RHOBENCH_WORKERS=2 uvicorn server.main:app --host 0.0.0.0 --port 8000
```

접속 주소는 `http://<서버 IP>:8000` 입니다 (서버 IP는 `hostname -I`로 확인).
접속할 사람에게는 **이 주소와 비밀번호만** 알려주면 됩니다.

- 비밀번호를 지정하지 않고 실행하면 최초 1회 무작위로 발급해 콘솔에 출력합니다.
- **비밀번호 변경**: `RHOBENCH_ACCESS_PASSWORD`를 새 값으로 주고 서버를 다시 실행하면
  됩니다. 변경 즉시 기존 접속자는 모두 로그아웃되고 새 비밀번호로만 들어올 수 있습니다.
- 비밀번호는 PBKDF2-HMAC-SHA256(솔트 + 20만 회) 해시로만 `data/access.json`(0600)에
  보관되며 평문은 저장되지 않습니다.

| 환경변수 | 기본값 | 의미 |
|---|---|---|
| `RHOBENCH_ACCESS_PASSWORD` | (최초 실행 시 무작위 발급) | 공유 접속 비밀번호 |
| `RHOBENCH_WORKERS` | 1 | 동시 계산 워커 수 (코어 수에 맞춰 조정) |
| `RHOBENCH_MAX_ATOMS` | 60 | 분자 + 명시적 주변 분자의 원자 수 상한 |
| `RHOBENCH_MAX_ACTIVE_JOBS` | 4 | 서버 전체 동시 대기·실행 작업 수 |

**동작 방식**

- 모든 API는 접속 필수 — 주소를 알아도 비밀번호 없이는 아무것도 조회·제출할 수 없습니다
- 세션은 12시간 유효한 토큰(HttpOnly 쿠키)이며 서버를 재시작하면 전원 로그아웃됩니다
- 접속한 사람들은 **하나의 공유 작업 공간**을 씁니다 — 작업 큐와 결과를 함께 보고,
  물질 보관함·용매 라이브러리는 브라우저별로 각자 보관됩니다
- 자원 보호: 분자 크기 상한과 서버 전체 동시 작업 수 상한이 걸려 있어, 한 사람이
  거대 분자나 대량 제출로 서버를 묶는 상황을 막습니다

> ⚠️ 사내망 밖(인터넷)에 공개하려면 HTTPS(리버스 프록시)를 반드시 앞에 두세요.
> 현재 세션 쿠키는 평문 HTTP에서도 전송되므로 사내망 전용을 권장합니다.

## 공유용 웹앱 페이지 (HTML 한 장)

결과를 담은 **자체 완결형 웹앱 페이지**를 한 파일로 뽑을 수 있습니다.
서버도 인터넷도 없이 동작하므로 웹 호스팅에 올리거나, 구글 드라이브에 두거나,
메일에 첨부해 그대로 공유할 수 있습니다.

만드는 방법은 세 가지이고 결과물은 같습니다:

```bash
# 1) 화면에서 — 「DFT 계산 결과」의 [HTML로 공유] 버튼
# 2) 명령으로 (서버가 꺼져 있어도 됨)
python -m scripts.build_webapp                     # 완료된 결과 전체
python -m scripts.build_webapp --list              # 무엇이 담길지 확인
python -m scripts.build_webapp --ids JOB-A,JOB-B --out 공유.html
# 3) API로
curl -b cookie.txt "http://localhost:8000/api/export?format=html" -o results.html
```

정적 파일 한 개이므로 어디에 올려도 링크가 됩니다:

```bash
python -m http.server 8080 -d build     # 사내 서버에서 바로 링크 공유
# GitHub Pages · Netlify · S3 등 정적 호스팅에 그대로 업로드해도 동작
```

| 페이지에서 되는 것 | 페이지에서 안 되는 것 |
|---|---|
| 결과 상세 · 3D 구조 · 전자구름 · MEP | 새 계산 제출 (PySCF 서버 필요) |
| 물성 지문 레이더 (축 변경 포함) | 화학물질 조회 (인터넷·RDKit 필요) |
| 물질 비교 · 지표 선택 · 그래프 종류 변경 | 작업 재시도 · 취소 · 삭제 |
| 전기화학 안정성(ESW) 판정 | |
| CSV · JSON 내려받기 (페이지 안 데이터로) | |

공유 전에는 시험 삼아 돌린 작업을 정리하세요 — 완료된 결과가 **전부** 담깁니다:

```bash
python -m scripts.prune_jobs --list                  # 현재 작업 확인
python -m scripts.prune_jobs --match 테스트 --failed   # 지울 대상 미리보기
python -m scripts.prune_jobs --match 테스트 --failed --yes
```

동작 방식: `web/index.html`과 `web/app.js`를 그대로 담고, 그 앞에 `fetch` 가로채기
계층을 넣어 API 호출을 파일에 심어 둔 결과로 되돌려 줍니다. 화면 코드가 하나뿐이라
서버에서 보던 것과 **똑같은** 차트·표가 나옵니다. 파일 크기는 결과 14건 기준 약 1 MB.

외부 요청이 0건이라 폐쇄망·오프라인에서도 동작하고, `<!doctype>`·`<head>`·`<body>`
래퍼가 없는 조각이라 다른 페이지 안에 그대로 넣거나 아티팩트로 발행해도 깨지지 않습니다.

> ⚠️ **사본에는 접속 비밀번호가 걸리지 않습니다.** 파일을 받은 사람은 누구나
> 그 안의 결과를 볼 수 있으니, 공유 범위를 정한 뒤 보내세요.

## 중단 없는 운영 — 백그라운드 실행과 단계별 체크포인트

터미널 창을 닫으면 서버가 죽고 계산도 사라지던 문제를 두 층으로 막는다.

```bash
./scripts/start.sh --background   # 창을 닫아도 서버가 남는다 (로그 data/server.log, PID data/server.pid)
./scripts/start.sh --status       # 실행 중인지
./scripts/start.sh --stop         # 끄기 — 계산 중이던 작업은 다음 실행 때 체크포인트에서 재개
```

`RhoBench-start.bat`은 백그라운드 모드로 켜고 브라우저만 연다. 끄려면 `RhoBench-stop.bat`.

**단계별 체크포인트** (기획서 v2.1 10.2): 엔진이 «구조 생성·최적화 → 진동수 → 용매화 → 전위 →
conformer 민감도 → MEP → Li⁺ → 이량체 → 흡착 → BDE → TDDFT» 단계를 끝낼 때마다 상태를
`data/checkpoints/<JOB>.json`에 저장한다. 서버가 꺼졌다 켜지면

- 중단된 작업은 실패가 아니라 **재개 대기(QUEUED)** 로 바뀌고 워커가 자동으로 다시 집어 간다
  (`worker.resubmit_pending`). 캠페인 작업은 배치 우선순위를 유지한다.
- 엔진은 지문(분자 + 설정 전체 해시)이 같으면 끝난 단계를 건너뛰고, 저장된 구조에서 단일점만
  다시 계산한 뒤 다음 단계부터 잇는다. 설정이 하나라도 다르면 처음부터 계산한다.
- «재시도»로 만든 새 작업도 원본 작업의 체크포인트를 물려받는다.
- 작업이 끝나면 체크포인트를 지운다. 작업 목록에는 «체크포인트 n단계» 배지가 보인다.

이어 붙이는 단위는 단계다 — 단계 도중(예: 최적화 30스텝째)에 끊기면 그 단계는 처음부터 다시 한다.

## 클라우드 서버 운영 (네이버 클라우드 등)

같은 프로그램을 리눅스 서버에 **systemd 서비스**로 올려 어디서나 접속하고, GitHub 의 새
코드를 한 줄로 업데이트합니다. 자세한 절차는 `docs/08_네이버클라우드_배포_업데이트_가이드.md`.

```bash
# 서버에서 최초 한 번 — apt · .venv · /etc/rhobench.env(비밀번호) · systemd · nginx(80→8000)
git clone https://github.com/clsrn0319-ui/DFT-Workbench && cd DFT-Workbench && ./scripts/ncp_setup.sh

# 업데이트 — 새 커밋 확인 → pull → (계산이 끝날 때까지 대기) → 재시작 → 응답 없으면 롤백
./scripts/update.sh            # --check · --now · --test · --ref main · --no-restart

# 백업 — data/ 를 tar.gz 로, Object Storage(S3 호환) 업로드까지
./scripts/backup_data.sh --upload rhobench-backup --keep 14
```

`deploy/ncp/` 에 systemd 유닛·환경 파일 예시·nginx 설정이 있습니다. `update.sh` 는 WSL 에서도
같은 명령으로 동작합니다(systemd 가 없으면 기존 uvicorn 을 찾아 환경변수를 물려받아 재시작).

## 원격 공유 (사내망 밖에서 보여주기)

**구글 드라이브는 프로그램을 실행하지 못합니다** — 파일 보관소이므로 코드를
올려 둘 수는 있어도 그 자리에서 돌릴 수는 없습니다(구글은 2016년에 드라이브
웹 호스팅을 종료했습니다). 실행하려면 파이썬이 도는 컴퓨터가 필요합니다.
단, **결과만 보여주면 된다면 위의 HTML 사본을 드라이브에 올리는 것으로 충분합니다.**

| 방법 | 준비 | 접속 주소 | 적합한 경우 |
|---|---|---|---|
| **웹앱 페이지 (HTML 한 장)** | `scripts/build_webapp.py` | 정적 호스팅에 올리면 고정 주소 | **결과만 보여주면 될 때 — 가장 간단** |
| **내 PC + 같은 네트워크** | `./scripts/start.sh` | `http://<내 IP>:8000` (HTTP) | 같은 공간에서의 시연 — 가장 안정적 |
| **내 PC + Cloudflare 터널** | `cloudflared tunnel --url http://localhost:8000` | 임시 `https://...trycloudflare.com` | 원격 참석자에게 잠깐 보여줄 때 |
| **Google Colab** | `notebooks/RhoBench_Colab.ipynb` 실행 | 임시 `https://...trycloudflare.com` | 내 PC를 켜 두지 않고 무료로 공개 |
| **클라우드 VM** | Ubuntu VM에 위 설치 절차 | 고정 주소 (HTTPS 설정 필요) | 상시 운영 |

Colab은 CPU 2코어이므로 정확도 «빠름» 기준으로만 쓰고, 세션이 끊기면 결과가
사라지므로 노트북 4번 셀에서 드라이브 저장을 켜 두세요.

구글 드라이브에 올려서 유용한 것은 **결과와 문서**입니다 — 결과 화면의
`CSV/JSON 내보내기`와 `docs/` 폴더의 Word 문서는 드라이브에서 그대로 열람·공유됩니다.

## 스크리닝 워크플로우 (화학물질 라이브러리)

사이드바 순서 그대로 단계적 스크리닝이 가능합니다:

1. **화학물질 조회** — 이름·CAS·SMILES 입력 → RDKit 로컬 기술자 + PubChem(무료)
   등록 정보(CAS·IUPAC명·설명·실험 물성). `MP_API_KEY` 설정 시 Materials Project
   분자 DB도 조회. 버튼 한 번으로 물질 보관함 등록·DFT 계산 연계.
2. **물질 보관함 / 용매 라이브러리** — 후보 소재·용매 관리
3. **DFT 계산** — SMD 용매화·명시적 주변 분자·열보정·전위 포함 실계산
4. **전기화학 안정성** — 계산된 산화/환원 전위로 ESW 차트를 그리고 배터리
   활물질 작동 전위(Graphite 0.1 V·Si 0.4 V·LFP 3.45 V·NCM811 4.3 V vs Li/Li⁺)와
   비교 판정 (열역학적 스크리닝 — SEI/CEI 동역학 미포함, 화면에 명시)
5. **물질 비교** — PUBLISHED 결과를 나란히 비교해 바인더/전해액 적합성 검토

## 배치 스크리닝 (수백 개 후보 자동 판정)

사이드바 **계산 → 배치 스크리닝**. 바인더 후보 목록을 한 번에 등록하면 깔때기
방식으로 자동 계산하고, 활물질 구동 전위 대비 **적합 / 조건부 / 부적합 /
판정 불가**를 매겨 순위표로 돌려줍니다 (기획서 05 구현).

1. **후보 업로드** — CSV(`이름,SMILES`) 또는 한 줄 SMILES 목록, 파일(.csv/.txt/.smi)
   지원. 업로드 즉시 RDKit 검증(문법·중복·원자 수 상한)과 제외 사유 표시.
2. **캠페인 설정** — 대상 활물질(복수 선택 가능), 안정성 마진(기본 0.3 V),
   용매·온도·기준 전극·범함수, 깔때기 단계(빠름 → 표준 → 정밀)와 단계별 통과 수.
3. **자동 실행** — 제출 후 무인 진행. 실패는 1회 자동 재시도, 서버가 재시작돼도
   `data/campaigns.json` 체크포인트에서 이어서 진행. 같은 구조·같은 조건의 기존
   결과는 재계산 없이 재사용. 실패율이 30%를 넘으면 자동 일시정지.
4. **판정** — 전극 구동 «범위 전체»가 후보의 ESW 안에 들어오는지(포함 관계,
   `esw.containment`과 동일 원리)를 여유 전압으로 환산해 마진과 비교. 적합군은
   안정성 여유 내림차순으로 순위화.
5. **내보내기** — 판정표 CSV/JSON (계산 조건 포함 — 재현 가능).

### 3D 구조 파일 입력 (SDF/MOL 우선 · XYZ 보조)

SMILES 대신 3D 구조 파일을 올릴 수 있습니다 — 단건(DFT 계산 화면)과 배치
스크리닝 양쪽 지원.

- **SDF/MOL** (권장) — 결합 정보가 파일에 있어 그대로 신뢰. `$$$$` 로 구분된
  다중 분자 SDF 지원(배치용). 수소 생략 파일은 `AddHs(addCoords)` 로 보완,
  2D 좌표 파일은 결합 정보만 취하고 구조는 conformer 탐색으로 생성.
- **XYZ** — 결합 정보가 없어 `rdDetermineBonds` 로 추정. 중성이 아니면
  «XYZ 전하»를 지정해야 추정이 맞음. 다중 프레임 지원.
- **동작** — 업로드 좌표를 **초기 구조**로 쓰고 conformer 탐색을 건너뜀
  (프리셋에 DFT 최적화가 있으면 그 좌표에서 최적화 시작). «구조 재탐색»을
  켜면 좌표를 버리고 기존 SMILES 경로로 계산.
- **제약** — 2량체·3량체 전개, 명시적 주변 분자 클러스터와는 함께 쓸 수 없음
  (좌표를 이어받을 수 없어 자동으로 기존 경로 사용 또는 안내 후 차단).
  업로드 좌표 후보는 결과 캐시 재사용 대상에서 제외.

### 5대 DFT Score (기획서 v0.1 — 7·8장)

캠페인 설정에서 «5대 Score 산출»을 켜면 마지막 단계에서 물성 지문까지 계산해
**접착 · 전기화학 안정성 · 전해액 친화도 · 이온 상호작용 · 화학적 안정성**을
0~100점으로 정규화하고 가중 총점 순위를 만든다.

- **가중치 preset**: 균등 · Si 음극 · 흑연 음극 · 하이니켈 양극 — 복사 후 직접 조정 가능
- **Hard Filter / Penalty 분리**: 작동 전위 창 위반은 점수와 별개로 «탈락» 표시,
  취약 BDE(<250 kJ/mol)는 총점 감점 + 사유 명시 — 치명적 약점이 평균에 가려지지 않음
- **Target-window 채점**: 전해액 친화도·Li⁺ 결합은 목표 범위식 — 과해도 감점
  (swelling·이온 이동성 저하 위험). 앵커는 `RHOBENCH_SCORE_ANCHORS`(JSON)로 조정
- **Confidence**: ΔG 기반=High · 단열=Medium · 수직/허수 진동수=Low
- **결측 축 처리**: 데이터 없는 축은 제외하고 가중치 재정규화 + 사유 표시
- **Pareto 뷰**: 두 축 선택 산점도에서 Pareto 전선 후보 강조
- **작용기 태그**: –COOH·–OH·–CN·–SO₃H 등 자동 태깅 (표·CSV 표시)
- **프로토콜 버전**: 캠페인마다 `DFT-BINDER-v1.0` 기록 — 조건 표준이 바뀌면
  버전을 올려 서로 다른 프로토콜 결과의 직접 비교를 방지

운영 메모:

- 배치 작업은 단건 제출보다 **낮은 우선순위**로 큐에 들어가 일상 사용을 막지 않음
- `RHOBENCH_BATCH_PARALLEL` (기본 1) — 배치가 동시에 점유할 워커 수
- `RHOBENCH_MAX_BATCH` (기본 500) — 캠페인당 후보 수 상한
- `RHOBENCH_BATCH_FAIL_RATIO` (기본 0.3) — 자동 일시정지 실패율 임계
- 판정은 열역학적 스크리닝 — SEI/CEI 동역학 미포함 (화면에 명시)

### 전위 conformer 민감도 (v2.0 개정 기획서 P0-5 · 3.6)

표준·정밀 정확도는 지배 conformer 한 값으로 전위를 내지 않는다. DFT 재순위
상위 conformer(표준 3 · 정밀 5, 지배 conformer 대비 5 kcal/mol 창 안) 각각에서
**같은 경로(수직 → 단열)로 IP/EA 를 다시 계산**해 전위 편차 σ 를 낸다.

| 편차 σ | 처리 |
|---|---|
| < 0.10 V | 단일값 판정 유지 |
| 0.10 ~ 0.20 V | 5축 신뢰도의 Molecular Model 축을 Medium 으로 하향 |
| ≥ 0.20 V | 단일값 대신 **범위**로 판정 — 범위 전체가 여유를 넘어야 적합, 전체가 침범해야 부적합, 걸치면 조건부. 깔때기 컷 순위도 보수적인 끝값 사용 |

- 결과의 `descriptors.conformer_sensitivity` 에 conformer 별 ΔE·분포·전위, σ, 규칙을 기록하고
  `conformer_spread_v` 를 단독 키로도 둔다. 화면에서는 «전위 conformer 민감도» 표로 보인다
- 불확실성 Hard Gate(`/api/esw/gate`)는 σ 를 잠정 폭 0.25 V 와 제곱합으로 합성해 구간을 넓힌다
- 열보정(ΔG)은 지배 conformer 에서만 — 다른 conformer 의 차이는 전자 IP/EA 오프셋으로 옮겨 붙인다
- 이온 구조는 각 중성 conformer 에서 재최적화한 것이며, 이온 상태 자체의 독립 conformer 탐색은 아직 없다
- 전문가 설정 «전위 conformer 민감도»로 끄거나(지배 conformer 한 값) 빠름에서도 켤 수 있다.
  켜져 있을 때만 protocol_card 에 `conformer_sensitivity` 가 들어가 해시가 달라진다
- 0.10 / 0.20 V 는 기획서 3.6 의 초기 운영값 — 벤치마크 후 조정 대상

### Li⁺ 용매 경쟁 (v2.0 개정 기획서 P0-6 · 5.2)

고립 Li⁺ 결합 에너지는 Li⁺ 탈용매화 비용을 무시해 trapping 을 과대평가한다.
정밀 정확도(또는 전문가 설정 «Li⁺ 상호작용 모델 = 용매 경쟁»)에서는 경쟁 반응을 계산한다.

```
Binder + Li(solv)n⁺  ⇌  Binder·Li⁺ + n·solv
ΔE_exchange = [E(Binder·Li⁺) + n·E(solv)] − [E(Binder) + E(Li(solv)n⁺)]
```

| 항목 | 동작 |
|---|---|
| 결합 site | MEP 최소점 + 헤테로원자(카보닐·에테르·하이드록실 O, 나이트릴·아민 N, S, F) 부위를 정밀 3곳(표준 1곳)까지 자동 탐색. site 마다 Li⁺ 착물을 DFT 재최적화하고 CP 보정 결합 에너지와 Boltzmann 분포를 낸다 |
| 참조 클러스터 | Li(solv)n⁺(기본 n=4)를 배위 원자가 Li 를 향하도록 다면체로 놓고 DFT 최적화 → SMD 단일점. 용매 분자·고립 Li⁺ 도 같은 프로토콜. **용매·n·범함수·기저·SMD 별로 `data/li_reference.json` 에 캐시** — 후보마다 다시 계산하지 않음 |
| 혼합 용매 | 성분마다 참조를 만들고, 용매화가 가장 강한 성분(EC/DMC 면 EC)을 기준으로 판정 |
| 판정 (잠정) | ΔE_exchange < −40 kJ/mol → **Li⁺ trapping 위험** · −40~+60 → 용매와 경쟁 · > +60 → 용매 우세(이동성 유지) |
| Score | «이온 상호작용» 축의 주 지표를 ΔE_exchange 로 전환(창 −40~+60), 고립 결합은 보조. 프로토콜 카드에 `li_model` 기록 |

결과: `descriptors.li_interaction`(site 표·참조·판정), `li_exchange_kj`(가장 강한 site), `li_exchange_boltzmann_kj`.
한계: 전자에너지 + SMD 기준으로 열보정(ΔG)은 없고(41원자 유한차분 Hessian 비용), 배위수는 고정, 배위수 앙상블·명시적 용매 microstate 는 미구현.
`GET /api/li-references` 로 캐시된 참조 목록을 본다.

## 계산 모니터링 (Raw Log · Structured Log · PASS/REVIEW/FAIL)

「DFT 계산 모니터링 및 Raw Log 설계 가이드」를 따라 **원본 로그는 그대로 보존**하고,
프로그램이 읽는 **구조화 로그**를 따로 만들어 상태를 자동 판정한다. 단건 계산과
배치 스크리닝의 작업이 같은 저장소를 쓰므로 «계산 모니터» 화면 하나에서 모두 본다.

| 계층 | 파일 · 위치 | 내용 |
|---|---|---|
| Raw Log (원본) | `data/logs/<JOB>.log` | PySCF 원본 출력. 기본 «상세»(verbose 4)로 **항상** 남기고 40 MB 에서 멈춤. 완료 후 SHA-256 기록. 단계 구분선·attempt 구분선 포함 |
| Structured Log | `data/logs/<JOB>.events.jsonl` | STAGE · INPUT · SCF(cycle·E·ΔE·|g|·|ddm|) · OPT(step·grad·disp) · FREQ · RECOVERY · ANOMALY · END. 각 이벤트에 원본 로그 byte offset — 화면에서 «원본에서 보기» |
| Trajectory | `data/logs/<JOB>.trajectory.xyz` | 구조 최적화 스텝별 좌표 (20 MB 상한) |
| 요약 | 작업 `monitor` 필드 | 현재 단계·SCF/OPT/FREQ 상태·이상 징후·attempt 이력·heartbeat. 콜백 갱신은 1초에 한 번만 메모리에, 단계 전환 때 저장 |
| 검증 보고서 | 작업·결과 `validation` | PASS / REVIEW / FAIL (+ CRASHED · CANCELLED) 과 근거 checks |

**자동 감지하는 이상 징후** (§6): SCF max cycle 근접 · 진동(ΔE 부호 교대) · 느린 수렴(10 cycle 에 |g| 절반 미만 감소) ·
발산(|g| 5회 연속 증가, 에너지 1 Ha 튐) · 최적화 정체(8 스텝 기울기 정체) · 구조 붕괴(원자 접근 < 0.6 Å, 지름 1.6배) ·
허수 진동수 · heartbeat 정지(`RHOBENCH_HEARTBEAT_WARN_S`, 기본 180 s).

**검증 등급** (§5) — 프로세스 정상 종료와 계산의 과학적 완결성을 분리한다:

- SCF: 기본 설정으로 모두 수렴 → pass · 자동 복구(damping/level shift/SOSCF)로 살림 → **REVIEW** (attempt 이력 확인) · 끝내 미수렴 → FAIL
- 구조 최적화: 최대 스텝(100)에서 수렴 기준 미달이면 결과는 남기되 **FAIL** (예전에는 조용히 성공처럼 보였다)
- 진동수: 허수 0 → pass · |ν| < 50 cm⁻¹ → REVIEW(수치 노이즈 가능) · 그 이상 → REVIEW(안장점)
- 구조 sanity: 원자 간 비정상 접근, SMILES 결합 대비 늘어난 결합(절단 의심) → REVIEW
- 전자 상태: UKS ⟨S²⟩ 편차 > 0.1 (스핀 오염) → REVIEW · HOMO > 0 또는 gap ≤ 0 → REVIEW
- 설정 반영: 최종 SCF 객체의 실제 범함수·분산·용매가 요청과 다르면 REVIEW
- 실행 오류는 FAILED(계산 목적 미달)와 CRASHED(메모리·OS)로 구분

**화면**: 사이드바 «계산 모니터» — 실행/대기/PASS/REVIEW/FAIL 타일, 작업 표(단계·SCF cycle·|g|·OPT step·허수·복구·heartbeat·판정·징후),
작업 상세(검증 보고서, 이상 징후 → 원본 줄로 이동, attempt 표, SCF |g|·OPT |grad| 로그 차트, 입력값/실제 실행값 대조),
Raw Log Viewer(tail 실시간 따라가기 · 300줄 range · 검색 · 단계 이동 · severity 강조 · 내려받기).
캠페인 상세 표의 «검증» 열과 결과 상세의 «계산 검증» 카드에서도 같은 등급을 본다.

**API**: `GET /api/monitor?campaign=` · `GET /api/jobs/{id}/monitor` · `GET /api/jobs/{id}/events?after=&kinds=` ·
`GET /api/jobs/{id}/log?tail=|start=&count=|offset=|search=|download=true` · `GET /api/jobs/{id}/trajectory`.
전문가 설정 «SCF 최대 반복»(`scfMaxCycle`)으로 실패 시나리오를 재현할 수 있다.

아직 없는 것: 체크포인트/재시작(중단 시 부분 재개), 자원(RSS·디스크) 모니터, 로그 기반 이상 탐지 확장 — 가이드의 2차 범위.

## 물성 지문 (확장 기술자)

목적을 "물성 지문 (확장 기술자 전체)"으로 두면 아래가 추가로 계산되고, 결과
상세에서 레이더·막대·공통 축 차트로 시각화됩니다.

| 기술자 | 계산 방식 | 근사·한계 |
|---|---|---|
| 화학적 경도 η · 퍼텐셜 μ · 친전자성 ω · 연성 S | 수직 IP/EA에서 유도 (개념 DFT) | 추가 비용 없음 |
| MEP 최대·최소 전위와 위치 | vdW 표면(1.4배) 격자에서 V(r) 직접 적분 | 격자 밀도 유한 |
| Li⁺ 결합 에너지 | MEP 최소점(전자 풍부 부위)에 Li⁺ 배치 후 ΔE, **BSSE counterpoise 보정** | 착물 재최적화 없음 |
| 이량체 결합 에너지 | 같은 분자 2개 접촉 이완 후 ΔE (바인더–바인더 응집), BSSE 보정 | 상동 |
| 활물질 표면 흡착 에너지 | 대용 클러스터(흑연 π=나프탈렌, Si–Si, Li₂O, Li₃PO₄)에 접촉 이완 후 ΔE | **슬랩 아님** — 같은 모델끼리의 상대 경향만 유효 |
| UV-Vis λmax · 진동자 세기 | TDDFT 수직 여기 (가장 밝은 전이) | 진동 구조·용매 재조직화 미포함, 최소 basis에서 부정확 |

접촉 기하는 여러 방향으로 게스트를 놓고 **호스트 원자를 고정한 역장 이완**을
거쳐 가장 안정한 배치를 고릅니다.

## 신뢰성·재현성 장치

| 장치 | 동작 |
|---|---|
| **안장점 자동 교정** | 진동수 계산에서 허수 모드가 나오면 그 모드를 따라 변위시켜 재최적화(최대 2회)하고, 구조가 바뀌면 최종 단일점·전자 기술자를 다시 계산 |
| **BSSE counterpoise 보정** | 모든 결합·흡착·상호작용 에너지의 조각 에너지를 고스트 원자를 포함한 복합체 basis에서 평가 |
| **SCF 수렴 자동 복구** | 미수렴 시 damping+level shift → 완화 → 2차 수렴(SOSCF) 순으로 재시도한 뒤에도 실패해야 작업 실패 처리 |
| **재현성 기록** | 결과마다 PySCF·RDKit·Python 버전, 최적화기, basis, 수렴 임계값, 용매 모델, 스케일 인자 등 전체 설정을 `provenance`로 저장 |
| **결과 내보내기** | `GET /api/export?format=csv` (Excel 호환 BOM, 모든 수치 기술자를 열로 전개) · `?format=json` (원본 전체) |
| **용매 내 최적화** | 전문가 설정에서 켜면 구조 최적화를 기체상이 아닌 SMD 용매장 안에서 수행 |
| **범함수 비교 실행** | 여러 범함수를 골라 제출하면 범함수마다 작업이 생성되어 물질 비교 화면에서 나란히 대조 |
| **결합 해리에너지(BDE)** | 고리 밖 단일 결합을 균일 분해하고 **각 라디칼 조각을 재최적화**해 BDE 산출. 열보정이 켜져 있으면 라디칼 진동수 계산으로 **ZPE·298 K 엔탈피 보정**까지 적용하며, 문헌 BDE와 직접 비교할 값은 298 K 열. 결합별로 298 K·0 K·ZPE 보정·고정 구조·완화 에너지를 모두 표시 |

## 계산 파이프라인

| 단계 | 내용 |
|---|---|
| 1. 구조 생성 | RDKit ETKDGv3 conformer 앙상블 → MMFF94(폴백 UFF) → 상위 후보 **DFT 단일점 재순위화** |
| 2. 구조 최적화 | (정확도 '표준'↑) DFT 기체상 최적화 — geomeTRIC, 미설치 시 pyberny |
| 3. 단일점 SCF | 밀도 피팅 RKS/UKS + D3(BJ) 분산 + **SMD implicit 용매화** |
| 4. 기술자 | 전자 에너지, HOMO/LUMO/갭, 쌍극자, Mulliken 전하 |
| 5. 열역학 보정 | (정확도 '표준'↑) 해석적 Hessian → 진동수·ZPE·엔탈피·엔트로피·**깁스 자유에너지 (설정 온도 반영)**, 허수 진동수 검출 |
| 6. 용매화 에너지 | 동일 구조 기체상 SCF 대비 ΔE (SMD CDS 항 별도 보고) |
| 7. 산화/환원 전위 | 수직 IP/EA(**비평형 용매화** — 중성 밀도로 동결한 용매장, 기본 활성) + (구조 최적화 시) **단열 IP/EA — 이온 상태 구조 재최적화**, 열보정 활성 시 **ΔG 기반 전위** 추가 → 기준 전극 절대 전위(Li/Li⁺ 1.44 V, SHE 4.44 V) 차감. 기준 전극 "없음" 선택 시 IP/EA만 보고 |

추가 보정·앙상블:

- **비평형 용매화(수직 전위)**: 순간 이온화 동안 용매 핵이 재배향하지 못하는 효과를
  동결 용매장 근사로 반영 (광학 유전 완화 미포함 — 상한 추정, 결과 노트 명시)
- **1 atm→1 M 표준 상태 보정**: 열보정+용매 계산 시 용액상 깁스 자유에너지에
  RT ln(24.46) (+1.89 kcal/mol @298 K) 합산 보고
- **Boltzmann conformer 앙상블**('정밀' 기본, 전문가 설정으로 토글): DFT 재순위
  에너지로 분포를 항상 보고하고, 활성 시 유의(≥5%) conformer 각각을
  최적화·단일점 후 전자 기술자를 가중 평균 (최대 4개) |

## 환경 설정이 계산에 반영되는 방식

- **용매**: SMD 파라미터(유전상수, 굴절률, 표면장력, Abraham H-결합 파라미터)로
  해밀토니안에 직접 반영됩니다. EC/DMC/EMC/NMP는 Minnesota SMD DB에 없어 문헌
  물성으로 구성한 커스텀 항목이며, `server/presets.py`에 정의되어 있습니다.
- **EC/DMC 1:1 혼합**: 부피분율 가중 평균 유전상수(ε≈46.4)의 단일 유효 매질로
  근사합니다(관례적 근사 — 결과 노트에 명시됨).
- **온도**: 열역학 보정이 켜진 프리셋('표준'↑)에서는 엔탈피·엔트로피·깁스
  자유에너지 산출에 실제 반영됩니다(기체상 조화진동자·강체회전·이상기체 근사).
  열보정을 끄면 기록용 조건으로만 남습니다.
- **명시적 주변 분자 (cluster-continuum)**: 환경 설정에서 용질 주위에 배치할
  분자(EC·DMC·EMC·H₂O·NMP 또는 임의 SMILES)와 개수를 지정하면, 겹치지 않게
  배치·역장 이완한 클러스터 전체를 DFT 계산하고 조각 분해 상호작용 에너지를
  보고합니다 (총 10분자 한도). 클러스터에서는 열보정·단열 전위 대신 수직
  전위가 사용되고, 35원자 초과 시 DFT 최적화는 자동 생략됩니다.
- **분위기**: 결과 메타데이터로 기록됩니다. 대기 반응성 계산은 명시적 주변
  분자에 O₂ 등을 배치하는 방식으로 근사할 수 있습니다.
- **기준 전극**: IP/EA에서 절대 전위를 차감해 전위로 환산합니다. 구조 최적화가
  켜진 경우 이온 상태를 재최적화한 **단열(adiabatic) 전위**가 기본이고, 열보정
  활성 시 ΔG 기반 전위도 함께 보고됩니다. 용매 재조직화(비평형 용매화)는
  포함되지 않습니다.

## 정확도 프리셋

| 프리셋 | conformer (DFT 재순위) | 구조 최적화 | 열보정 | 최종 basis | 전위 conformer 민감도 | 용도 |
|---|---|---|---|---|---|---|
| 빠름 | 5 (1) | MMFF만 | — | def2-SVP | — | 사전 스크리닝 (분자당 수십 초) |
| 표준 | 15 (3) | DFT(def2-SVP) | ✓ | def2-TZVP | 3 | 권장 연구용 (분자당 수 분~수십 분, 민감도로 전위 부분이 최대 3배) |
| 정밀 | 30 (5) | DFT(def2-TZVP) | ✓ | def2-TZVP | 5 | 최종 확인 |

범함수는 PBE0-D3(BJ) 기본, B3LYP-D3(BJ)/PBE-D3(BJ)/M06-2X/HF 선택 가능.
전문가 설정에서 전하·스핀 다중도·basis·conformer 수·구조 최적화·열보정·
전위 방식(수직/단열)을 직접 제어할 수 있습니다.

## 검증 결과 예시

아크릴로나이트릴(AN) '빠름' 프리셋, EC/DMC SMD: HOMO −8.10 eV — Materials Project
MPcules 진공 참조값(ωB97X-V/def2-TZVPPD) −8.19 eV와 부합.
