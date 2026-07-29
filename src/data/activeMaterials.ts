// 대표 이차전지 활물질(전극)의 작동 전위 기준 데이터 (V vs Li/Li⁺)
// 바인더 안정 창과의 비교용 참고값 — 전해질·율속·상한 설정에 따라 달라질 수 있다.
export interface ActiveMaterialRef {
  id: string
  name: string
  role: '음극' | '양극'
  vMin: number
  vMax: number
  note: string
}

export const ACTIVE_MATERIALS: ActiveMaterialRef[] = [
  {
    id: 'graphite',
    name: 'Natural Graphite',
    role: '음극',
    vMin: 0.05,
    vMax: 0.25,
    note: '천연 흑연 음극 — 리튬 삽입/탈리 평탄 전위',
  },
  {
    id: 'sigr',
    name: 'Si/Graphite',
    role: '음극',
    vMin: 0.05,
    vMax: 0.6,
    note: 'Si 블렌드 음극 — 합금화/탈합금 전위 범위',
  },
  {
    id: 'lto',
    name: 'LTO',
    role: '음극',
    vMin: 1.5,
    vMax: 1.6,
    note: 'Li₄Ti₅O₁₂ — 고전위 음극',
  },
  {
    id: 'lfp',
    name: 'LFP',
    role: '양극',
    vMin: 3.4,
    vMax: 3.5,
    note: 'LiFePO₄ — 평탄 전위',
  },
  {
    id: 'ncm811',
    name: 'NCM811',
    role: '양극',
    vMin: 3.0,
    vMax: 4.3,
    note: 'LiNi₀.₈Co₀.₁Mn₀.₁O₂ — 충전 상한 4.3 V 기준',
  },
  {
    id: 'lco',
    name: 'LCO',
    role: '양극',
    vMin: 3.0,
    vMax: 4.45,
    note: 'LiCoO₂ — 충전 상한 4.45 V 기준',
  },
]

export const DEFAULT_REF_IDS = ['graphite', 'sigr', 'lfp', 'ncm811']

// Li/Li⁺ 절대 전위 근사 (≈ -1.44 eV vs vacuum)
export const LI_ABS = 1.44

// 전극 전위(V vs Li/Li⁺) → 전자 에너지 준위 근사 (eV): μ ≈ -(1.44 + V)
export const fermiEv = (v: number) => -(LI_ABS + v)
