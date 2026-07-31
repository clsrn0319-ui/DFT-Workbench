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

```bash
# 재부팅 후 시작 메뉴 → "Ubuntu" 실행, 이하 우분투 터미널
sudo apt update && sudo apt install -y python3-pip python3-venv git
git clone https://github.com/clsrn0319-ui/DFT-Workbench
cd DFT-Workbench
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

메모리가 부족해 계산이 느리면 `C:\Users\<이름>\.wslconfig`에 `[wsl2]` /
`memory=12GB` 식으로 상향한 뒤 `wsl --shutdown`으로 재시작합니다.

### 리눅스 · 맥

```bash
pip install -r requirements.txt
uvicorn server.main:app --host 0.0.0.0 --port 8000
# → http://localhost:8000
```

빠른 검증:

```bash
python -m scripts.smoke_test   # 아크릴로나이트릴 1건 실계산 (~1분)
python -m pytest tests/ -v     # 단위 테스트 (실 SCF 포함, ~30초)
```

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

| 프리셋 | conformer (DFT 재순위) | 구조 최적화 | 열보정 | 최종 basis | 용도 |
|---|---|---|---|---|---|
| 빠름 | 5 (1) | MMFF만 | — | def2-SVP | 사전 스크리닝 (분자당 수십 초) |
| 표준 | 15 (3) | DFT(def2-SVP) | ✓ | def2-TZVP | 권장 연구용 (분자당 수 분~수십 분) |
| 정밀 | 30 (5) | DFT(def2-TZVP) | ✓ | def2-TZVP | 최종 확인 |

범함수는 PBE0-D3(BJ) 기본, B3LYP-D3(BJ)/PBE-D3(BJ)/M06-2X/HF 선택 가능.
전문가 설정에서 전하·스핀 다중도·basis·conformer 수·구조 최적화·열보정·
전위 방식(수직/단열)을 직접 제어할 수 있습니다.

## 검증 결과 예시

아크릴로나이트릴(AN) '빠름' 프리셋, EC/DMC SMD: HOMO −8.10 eV — Materials Project
MPcules 진공 참조값(ωB97X-V/def2-TZVPPD) −8.19 eV와 부합.
