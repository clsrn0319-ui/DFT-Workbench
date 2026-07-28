import type { CalcSettings, DftResult, Surface } from '../types'

// 실제 DFT 코드가 연결되기 전까지 사용하는 결정론적 모의 엔진.
// 동일한 (분자, 계산조건) 조합은 항상 동일한 결과를 반환한다.

interface BaseProps {
  homo: number
  lumo: number
  dipole: number
  polarizability: number
  espMin: number
  espMax: number
  solvation: number
  adhesion: Record<Surface, number>
  energy: number
}

// B3LYP/6-311+G(d,p) 기준의 대표값 (문헌 수준의 근사치, 데모용)
const BASE: Record<string, BaseProps> = {
  pvdf: { homo: -8.72, lumo: 0.94, dipole: 1.39, polarizability: 24.1, espMin: -18.2, espMax: 21.5, solvation: -2.1, adhesion: { Graphite: -0.34, Si: -0.42, NMC811: -0.58, LFP: -0.49 }, energy: -277.35 },
  ptfe: { homo: -9.61, lumo: 0.81, dipole: 0.0, polarizability: 27.9, espMin: -9.8, espMax: 14.2, solvation: -0.8, adhesion: { Graphite: -0.28, Si: -0.31, NMC811: -0.44, LFP: -0.38 }, energy: -475.61 },
  sbr: { homo: -6.68, lumo: -0.38, dipole: 0.42, polarizability: 84.3, espMin: -14.6, espMax: 12.9, solvation: -1.4, adhesion: { Graphite: -0.61, Si: -0.37, NMC811: -0.35, LFP: -0.33 }, energy: -309.62 },
  cmc: { homo: -7.21, lumo: 0.31, dipole: 3.86, polarizability: 132.4, espMin: -46.3, espMax: 44.1, solvation: -18.9, adhesion: { Graphite: -0.41, Si: -1.08, NMC811: -0.82, LFP: -0.74 }, energy: -800.44 },
  paa: { homo: -7.43, lumo: -0.41, dipole: 1.88, polarizability: 40.6, espMin: -37.4, espMax: 41.8, solvation: -8.6, adhesion: { Graphite: -0.39, Si: -1.21, NMC811: -0.88, LFP: -0.79 }, energy: -267.21 },
  lipaa: { homo: -6.94, lumo: 0.22, dipole: 6.71, polarizability: 44.8, espMin: -58.1, espMax: 22.4, solvation: -52.3, adhesion: { Graphite: -0.36, Si: -1.34, NMC811: -0.95, LFP: -0.86 }, energy: -274.68 },
  pva: { homo: -7.08, lumo: 0.53, dipole: 1.67, polarizability: 27.3, espMin: -33.5, espMax: 35.7, solvation: -5.9, adhesion: { Graphite: -0.32, Si: -0.86, NMC811: -0.66, LFP: -0.6 }, energy: -153.83 },
  pan: { homo: -8.03, lumo: -0.62, dipole: 3.92, polarizability: 38.2, espMin: -31.8, espMax: 23.6, solvation: -6.2, adhesion: { Graphite: -0.44, Si: -0.72, NMC811: -0.69, LFP: -0.61 }, energy: -170.86 },
  peo: { homo: -7.34, lumo: 1.12, dipole: 1.89, polarizability: 26.8, espMin: -29.4, espMax: 20.1, solvation: -4.3, adhesion: { Graphite: -0.3, Si: -0.63, NMC811: -0.57, LFP: -0.52 }, energy: -153.79 },
  pvp: { homo: -6.61, lumo: 0.18, dipole: 4.12, polarizability: 74.5, espMin: -41.2, espMax: 19.8, solvation: -9.7, adhesion: { Graphite: -0.47, Si: -0.78, NMC811: -0.71, LFP: -0.64 }, energy: -363.53 },
  alginate: { homo: -7.02, lumo: 0.36, dipole: 5.94, polarizability: 118.9, espMin: -55.7, espMax: 30.2, solvation: -48.7, adhesion: { Graphite: -0.38, Si: -1.16, NMC811: -0.85, LFP: -0.77 }, energy: -763.19 },
}

// 사용자 정의 분자용: id 해시 기반의 그럴듯한 기본값 생성
function hash(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

function rand01(seed: string): number {
  return (hash(seed) % 100000) / 100000
}

function fallbackBase(id: string, smiles: string): BaseProps {
  const key = id + smiles
  const r = (tag: string) => rand01(key + tag)
  const homo = -6.2 - r('h') * 3.2
  return {
    homo,
    lumo: -0.8 + r('l') * 2.0,
    dipole: r('d') * 5.5,
    polarizability: 20 + r('p') * 110,
    espMin: -(10 + r('em') * 45),
    espMax: 10 + r('ex') * 35,
    solvation: -(1 + r('s') * 30),
    adhesion: {
      Graphite: -(0.25 + r('ag') * 0.4),
      Si: -(0.3 + r('as') * 1.0),
      NMC811: -(0.3 + r('an') * 0.7),
      LFP: -(0.3 + r('af') * 0.6),
    },
    energy: -(120 + r('e') * 700),
  }
}

// 범함수별 보정 (B3LYP 기준): [HOMO 이동, LUMO 이동]
const FUNC_SHIFT: Record<string, [number, number]> = {
  B3LYP: [0, 0],
  PBE0: [-0.25, 0.21],
  'M06-2X': [-0.62, 0.48],
  'ωB97X-D': [-1.05, 0.82],
  PBE: [0.95, -0.78],
}

const BASIS_SCALE: Record<string, number> = {
  '6-31G(d)': 0.93,
  '6-311+G(d,p)': 1.0,
  'def2-SVP': 0.95,
  'def2-TZVP': 1.01,
}

const SOLV_STAB: Record<string, number> = {
  none: 0,
  'PCM(H2O)': 1.0,
  'SMD(H2O)': 1.15,
  'SMD(NMP)': 0.85,
}

export function computeResult(
  moleculeId: string,
  smiles: string,
  s: CalcSettings,
): DftResult {
  const base = BASE[moleculeId] ?? fallbackBase(moleculeId, smiles)
  const seed = `${moleculeId}|${s.functional}|${s.basis}|${s.solvent}|${s.dispersion}|${s.charge}`
  const jitter = (tag: string, amp: number) => (rand01(seed + tag) - 0.5) * amp

  const [dh, dl] = FUNC_SHIFT[s.functional]
  const bs = BASIS_SCALE[s.basis]
  const sv = SOLV_STAB[s.solvent]

  const homo = (base.homo + dh) * bs + jitter('h', 0.08) - sv * 0.05
  const lumo = (base.lumo + dl) * bs + jitter('l', 0.08) + sv * 0.03
  const gap = lumo - homo
  const dipole = base.dipole * (1 + sv * 0.18) + jitter('d', 0.1)
  const solvationEnergy = s.solvent === 'none' ? 0 : base.solvation * sv + jitter('s', 0.6)

  // 산화전위 ≈ -HOMO 기반, 환원전위 ≈ -LUMO 기반의 선형 근사 (vs Li/Li+)
  const oxidationPotential = -homo - 1.46 + jitter('op', 0.05)
  const reductionPotential = -lumo - 1.46 + jitter('rp', 0.05)

  const dispBonus = s.dispersion ? 1.12 : 1.0
  const adhesion = Object.fromEntries(
    (Object.keys(base.adhesion) as Surface[]).map((surf) => [
      surf,
      +(base.adhesion[surf] * dispBonus + jitter('a' + surf, 0.04)).toFixed(3),
    ]),
  ) as Record<Surface, number>

  const basisCost = { '6-31G(d)': 1, 'def2-SVP': 1.1, '6-311+G(d,p)': 2.2, 'def2-TZVP': 2.6 }[s.basis]

  return {
    homo: +homo.toFixed(3),
    lumo: +lumo.toFixed(3),
    gap: +gap.toFixed(3),
    dipole: +Math.abs(dipole).toFixed(3),
    polarizability: +(base.polarizability * bs * (1 + jitter('pol', 0.04))).toFixed(1),
    espMin: +(base.espMin * (1 + sv * 0.1)).toFixed(1),
    espMax: +(base.espMax * (1 + sv * 0.08)).toFixed(1),
    oxidationPotential: +oxidationPotential.toFixed(2),
    reductionPotential: +reductionPotential.toFixed(2),
    solvationEnergy: +solvationEnergy.toFixed(2),
    adhesion,
    totalEnergy: +(base.energy * bs + jitter('e', 0.01)).toFixed(5),
    scfCycles: 9 + (hash(seed) % 14),
    wallTimeSec: Math.round(40 * basisCost * (1 + rand01(seed + 'wt'))),
  }
}

export const STAGES = [
  { at: 0, label: '입력 검증 및 초기 구조 생성' },
  { at: 10, label: '기하 구조 최적화' },
  { at: 45, label: 'SCF 수렴' },
  { at: 70, label: '진동수 계산' },
  { at: 85, label: '물성 산출 (HOMO/LUMO·ESP·흡착)' },
  { at: 100, label: '완료' },
]

export function stageFor(progress: number): string {
  let label = STAGES[0].label
  for (const st of STAGES) if (progress >= st.at) label = st.label
  return label
}

// 진행 속도: 기저함수가 클수록 느리게 (데모용 15~40초 내외)
export function progressStep(basis: string): number {
  const cost = { '6-31G(d)': 1, 'def2-SVP': 1.1, '6-311+G(d,p)': 1.8, 'def2-TZVP': 2.2 }[basis] ?? 1
  return 8 / cost // 1초 틱당 % 증가량
}
