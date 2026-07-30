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

## 계산 파이프라인

| 단계 | 내용 |
|---|---|
| 1. 구조 생성 | RDKit ETKDGv3 conformer 앙상블 → MMFF94(폴백 UFF) 최적화 → 최저 에너지 구조 |
| 2. 구조 최적화 | (정확도 '표준'↑) DFT 기체상 최적화 — geomeTRIC, 미설치 시 pyberny |
| 3. 단일점 SCF | 밀도 피팅 RKS/UKS + D3(BJ) 분산 + **SMD implicit 용매화** |
| 4. 기술자 | 전자 에너지, HOMO/LUMO/갭, 쌍극자, Mulliken 전하 |
| 5. 용매화 에너지 | 동일 구조 기체상 SCF 대비 ΔE (SMD CDS 항 별도 보고) |
| 6. 산화/환원 전위 | 수직 IP/EA ΔSCF → 기준 전극 절대 전위(Li/Li⁺ 1.44 V, SHE 4.44 V) 차감 |

## 환경 설정이 계산에 반영되는 방식

- **용매**: SMD 파라미터(유전상수, 굴절률, 표면장력, Abraham H-결합 파라미터)로
  해밀토니안에 직접 반영됩니다. EC/DMC/EMC/NMP는 Minnesota SMD DB에 없어 문헌
  물성으로 구성한 커스텀 항목이며, `server/presets.py`에 정의되어 있습니다.
- **EC/DMC 1:1 혼합**: 부피분율 가중 평균 유전상수(ε≈46.4)의 단일 유효 매질로
  근사합니다(관례적 근사 — 결과 노트에 명시됨).
- **온도·분위기**: 결과 메타데이터로 기록됩니다. 진동수 계산(열보정)과 명시적
  대기 분자 모델은 수행하지 않으며, 이 한계는 각 결과의 주의사항에 표기됩니다.
- **기준 전극**: 수직 IP/EA에서 절대 전위를 차감해 전위로 환산합니다. 구조 완화
  (adiabatic)·용매 재조직화가 빠진 근사값입니다.

## 정확도 프리셋

| 프리셋 | conformer | 구조 최적화 | 최종 basis | 용도 |
|---|---|---|---|---|
| 빠름 | 5 | MMFF만 | def2-SVP | 사전 스크리닝 (분자당 수십 초) |
| 표준 | 15 | DFT(def2-SVP) | def2-TZVP | 권장 (분자당 수 분) |
| 정밀 | 30 | DFT(def2-TZVP) | def2-TZVP | 최종 확인 |

범함수는 PBE0-D3(BJ) 기본, B3LYP-D3(BJ)/PBE-D3(BJ)/M06-2X/HF 선택 가능.
전문가 설정에서 전하·스핀 다중도·basis·conformer 수·최적화 여부를 직접 제어할 수 있습니다.

## 검증 결과 예시

아크릴로나이트릴(AN) '빠름' 프리셋, EC/DMC SMD: HOMO −8.10 eV — Materials Project
MPcules 진공 참조값(ωB97X-V/def2-TZVPPD) −8.19 eV와 부합.
