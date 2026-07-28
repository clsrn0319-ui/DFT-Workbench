# 바인더 분자물성 DFT 워크벤치

이차전지 전극 **바인더 후보 고분자**의 단량체(반복단위) 수준 DFT 물성을 관리·계산·비교하는 웹 애플리케이션입니다.

## 주요 기능

| 화면 | 기능 |
|---|---|
| **대시보드** | 등록 분자·계산 현황 요약, 최근 완료 분자의 HOMO/LUMO 에너지 준위 |
| **분자 라이브러리** | 기본 바인더 11종(PVDF·PTFE·SBR·CMC·PAA·LiPAA·PVA·PAN·PEO·PVP·Alginate) + SMILES 기반 신규 등록, 계열/검색 필터 |
| **새 계산** | 분자 다중 선택 → 범함수(B3LYP·PBE0·M06-2X·ωB97X-D·PBE) · 기저함수(6-31G(d)·6-311+G(d,p)·def2-SVP·def2-TZVP) · 용매모델(기체상·PCM·SMD) · D3 분산보정 · 전하/다중도 설정 후 작업 제출 |
| **작업 현황** | 계산 큐(동시 실행 2건), 단계별 진행률 실시간 표시, 취소/삭제 |
| **결과 분석** | 최대 3건 비교 — 에너지 준위 다이어그램, 다물성 레이더, 표면(Graphite·Si·NMC811·LFP) 흡착에너지 막대, 물성 상세 표, CSV 내보내기 |

계산 물성: HOMO/LUMO/gap, 쌍극자 모멘트, 분극률, ESP 극값, 산화/환원 전위(vs Li/Li⁺), 용매화 에너지, 활물질 표면별 흡착에너지, 전자 에너지.

> **참고:** 현재는 결정론적 **모의(mock) DFT 엔진**(`src/engine/mockDft.ts`)이 결과를 생성합니다. 동일 (분자, 계산조건)은 항상 동일한 값을 반환하며, 실계산 엔진(Gaussian/ORCA 등) 백엔드 연동 시 이 모듈만 교체하면 됩니다. 표시 값은 데모용 근사치입니다.

## 실행

```bash
npm install
npm run dev      # 개발 서버
npm run build    # 프로덕션 빌드 (dist/)
npm run preview  # 빌드 미리보기
```

## 기술 스택

- Vite + React 18 + TypeScript (외부 차트 라이브러리 없이 SVG 차트 직접 구현)
- 상태: React reducer + `localStorage` 영속화 (`src/store.tsx`)
- 라이트/다크 테마 지원
