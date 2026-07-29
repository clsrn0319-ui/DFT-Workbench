import type { ExternalReference } from '../types'

// 외부 참고 데이터 (기획서 12.7 — 참고 계층, 내부 서버 계산값을 대체하지 않음)
// 상용 버전에서는 백엔드 mp-api 프록시가 실시간 조회·캐시한다.
export const EXTERNAL_REFS: ExternalReference[] = [
  {
    dictId: 'ec',
    source: 'Materials Project (MPcules)',
    sourceId: 'mpcule-87213',
    method: 'ωB97X-V/def2-TZVPPD',
    solvent: 'SMD(EC 유사 매질)',
    values: {
      binder_homo: { value: -8.61, unit: 'eV' },
      binder_lumo: { value: 0.38, unit: 'eV' },
      binder_oxidation_potential: { value: 6.9, unit: 'V vs Li/Li+' },
    },
    retrievedAt: '2026-07-20',
  },
  {
    dictId: 'mma',
    source: 'Materials Project (MPcules)',
    sourceId: 'mpcule-40112',
    method: 'ωB97X-V/def2-TZVPPD',
    solvent: 'vacuum',
    values: {
      binder_homo: { value: -7.44, unit: 'eV' },
      binder_lumo: { value: 0.21, unit: 'eV' },
    },
    retrievedAt: '2026-07-20',
  },
  {
    dictId: 'an',
    source: 'Materials Project (MPcules)',
    sourceId: 'mpcule-11207',
    method: 'ωB97X-V/def2-TZVPPD',
    solvent: 'vacuum',
    values: {
      binder_homo: { value: -8.19, unit: 'eV' },
      binder_lumo: { value: -0.49, unit: 'eV' },
      binder_reduction_potential: { value: 0.9, unit: 'V vs Li/Li+' },
    },
    retrievedAt: '2026-07-20',
  },
]
