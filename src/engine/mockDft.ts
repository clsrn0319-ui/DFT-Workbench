import type { CalcResult, CalcSettings, DescriptorValue } from '../types'
import { DICTIONARY } from '../data/dictionary'

// ── 프로토타입 모의 계산 엔진 ───────────────────────────────────
// 기획서 13장의 파이프라인(FastAPI + RDKit/xTB/PySCF/CP2K + 검증 게이트)을
// 브라우저 안에서 흐름 확인용으로 시뮬레이션한다. 동일 (물질, 조건) 입력은
// 항상 동일한 결과를 반환하며, 상용 배포 시 이 모듈이 실제 API 클라이언트로
// 교체된다. (기획서 1.2 "이전 HTML에서 흐름 확인용 시뮬레이션" 계층)

function hash(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

const rand01 = (seed: string) => (hash(seed) % 100000) / 100000

interface BaseProps {
  homo: number
  lumo: number
  dipole: number
  alpha: number
  liBind: number
  hbd: number
  hba: number
}

function baseFor(dictId: string | undefined, smiles: string): BaseProps {
  const entry = dictId ? DICTIONARY.find((d) => d.dictId === dictId) : undefined
  if (entry) return entry.base
  const r = (tag: string) => rand01(smiles + tag)
  return {
    homo: -6.3 - r('h') * 3.0,
    lumo: -0.8 + r('l') * 1.9,
    dipole: r('d') * 6,
    alpha: 25 + r('a') * 100,
    liBind: -(50 + r('li') * 110),
    hbd: Math.floor(r('hbd') * 3),
    hba: Math.floor(r('hba') * 4),
  }
}

// 함수별 궤도 보정 (B3LYP 기준)
const FUNC_SHIFT: Record<string, [number, number]> = {
  B3LYP: [0, 0],
  'PBE0-D3(BJ)': [-0.25, 0.21],
  'M06-2X': [-0.62, 0.48],
  'ωB97X-D': [-1.05, 0.82],
  PBE: [0.95, -0.78],
}

const BASIS_SCALE: Record<string, number> = {
  'def2-SVP': 0.94,
  'def2-TZVP': 1.0,
  'def2-TZVPD': 1.01,
  '6-311+G(d,p)': 0.99,
}

const SOLV_EPS: Record<string, number> = {
  // modelKey → 상대 유전 안정화 계수
  'smd:ec': 1.2,
  'smd:dmc': 0.55,
  'smd:emc': 0.5,
  'smd:water': 1.35,
  'smd:nmp': 0.9,
  'smd:ec-dmc-11': 1.0,
}

const STRUCT_SCALE: Record<string, number> = {
  모노머: 1,
  '2량체': 1.6,
  '3량체': 2.1,
  '사용자 구조': 1.3,
}

export function computeDescriptors(
  materialKey: string,
  dictId: string | undefined,
  smiles: string,
  s: CalcSettings,
  solventModelKey: string | null,
): Record<string, DescriptorValue> {
  const base = baseFor(dictId, smiles)
  const seed = `${materialKey}|${s.envType}|${solventModelKey}|${s.temperature}|${s.structure}|${s.accuracy}|${s.expert.functional}|${s.expert.basis}|${s.expert.charge}`
  const jit = (tag: string, amp: number) => (rand01(seed + tag) - 0.5) * amp

  const [dh, dl] = FUNC_SHIFT[s.expert.functional] ?? [0, 0]
  const bs = BASIS_SCALE[s.expert.basis] ?? 1
  const eps = solventModelKey ? (SOLV_EPS[solventModelKey] ?? 0.8) : 0
  const sc = STRUCT_SCALE[s.structure]

  const homo = (base.homo + dh) * bs - eps * 0.06 + jit('h', 0.06)
  const lumo = (base.lumo + dl) * bs + eps * 0.04 + jit('l', 0.06)
  const gap = lumo - homo
  const dipole = Math.abs(base.dipole * (1 + eps * 0.15) + jit('d', 0.15))

  // Koopmans 기반 근사 + 용매·이완 보정
  const vip = -homo + 1.05 + jit('vip', 0.1) - eps * 0.12
  const vea = -lumo - 0.85 + jit('vea', 0.1) + eps * 0.1
  // 전위 (V vs Li/Li+): 절대전위 스케일 근사 변환
  const shift = s.referenceElectrode === 'Li/Li+' ? 1.46 : 4.44 - 3.04
  const eox = vip - shift - eps * 0.18 + jit('eox', 0.05)
  // 환원 전위 ∝ 전자친화도: VEA가 낮을수록(음수) 환원이 어렵고 하한이 낮아진다
  const ered = vea + (s.referenceElectrode === 'Li/Li+' ? 1.74 : 0.34) + eps * 0.1 + jit('ered', 0.05)

  const mepMin = -(8 + dipole * 6.2 + base.hba * 3.5) + jit('mn', 1.5)
  const mepMax = 10 + dipole * 3.4 + base.hbd * 7 + jit('mx', 1.5)

  const liBind = base.liBind * (1 - eps * 0.22) * (1 + (sc - 1) * 0.15) + jit('li', 4)
  const pf6Bind = -(8 + mepMax * 0.55) * (1 - eps * 0.18) + jit('pf', 2)
  const siBind = -(25 + Math.abs(mepMin) * 1.4 + base.hbd * 12) + jit('si', 4)
  const hbond = base.hbd > 0 ? -(6 + base.hbd * 9 + base.hba * 2) + jit('hb', 2) : -(2 + base.hba * 1.5)

  const enthalpy = liBind * 0.92 + jit('ent', 3)
  const dgIonEx = liBind * 0.33 + 8 + jit('dg', 3)
  const nboCharge = 0.18 + rand01(seed + 'nbo') * 0.45

  const r = (v: number, digits = 2) => +v.toFixed(digits)
  return {
    binder_homo: { value: r(homo, 3), unit: 'eV' },
    binder_lumo: { value: r(lumo, 3), unit: 'eV' },
    binder_homo_lumo_gap: { value: r(gap, 3), unit: 'eV' },
    binder_ionization_energy: { value: r(vip), unit: 'eV' },
    binder_electron_affinity: { value: r(vea), unit: 'eV' },
    binder_oxidation_potential: { value: r(eox), unit: `V vs ${s.referenceElectrode}` },
    binder_reduction_potential: { value: r(ered), unit: `V vs ${s.referenceElectrode}` },
    binder_meps_max_positive: { value: r(mepMax, 1), unit: 'kcal/mol' },
    binder_meps_min_negative: { value: r(mepMin, 1), unit: 'kcal/mol' },
    binder_dipole_moment: { value: r(dipole), unit: 'D' },
    binder_nbo_charge_cationic_site: { value: r(nboCharge, 3), unit: 'e' },
    binder_enthalpy: { value: r(enthalpy, 1), unit: 'kJ/mol' },
    binder_gibbs_free_energy_ion_exchange: { value: r(dgIonEx, 1), unit: 'kJ/mol' },
    binder_li_binding_energy: { value: r(liBind, 1), unit: 'kJ/mol' },
    binder_pf6_binding_energy: { value: r(pf6Bind, 1), unit: 'kJ/mol' },
    binder_binder_hbond_energy: { value: r(hbond, 1), unit: 'kJ/mol' },
    binder_si_binding_energy: { value: r(siBind, 1), unit: 'kJ/mol' },
  }
}

export function buildResult(
  materialKey: string,
  dictId: string | undefined,
  smiles: string,
  structureVersion: number,
  s: CalcSettings,
  solventModelKey: string | null,
): CalcResult {
  const descriptors = computeDescriptors(materialKey, dictId, smiles, s, solventModelKey)
  const seed = materialKey + s.expert.functional + s.expert.basis + s.structure
  // 검증 게이트 시뮬레이션: 일부 조합은 NEEDS_REVIEW (기획서 13.2)
  const review = hash(seed + 'validate') % 11 === 0
  return {
    descriptors,
    validationStatus: review ? 'NEEDS_REVIEW' : 'PASSED',
    validationNotes: review
      ? ['진동수 계산에서 저주파 허수 모드 1개 검출 — conformer 재탐색 후 재검증 필요']
      : ['SCF·geometry·frequency·상태 일치·파일 완전성 검사 통과'],
    protocolId: `PROTO-${s.accuracy === '정밀' ? 'HIGH' : s.accuracy === '빠름' ? 'FAST' : 'STD'}-1.0`,
    structureHash: `sha256:${hash(smiles + structureVersion).toString(16).padStart(8, '0')}`,
  }
}

// ── 파이프라인 단계 (기획서 7.1) ────────────────────────────────
export const PIPELINE_STAGES = [
  { at: 0, label: '구조 해석 (RDKit 파싱·원자가 검사)' },
  { at: 8, label: '표준화·Descriptor (canonical 구조·hash)' },
  { at: 16, label: '3D conformer 생성 (ETKDG·RMSD 중복 제거)' },
  { at: 28, label: 'xTB 사전 최적화 (GFN2-xTB)' },
  { at: 45, label: 'DFT 구조 최적화·SCF 수렴' },
  { at: 68, label: '진동수·열보정 계산' },
  { at: 80, label: '중성/양이온/음이온 상태 계산' },
  { at: 92, label: '결과 집계·전위 변환' },
  { at: 100, label: '계산 완료' },
]

export function stageFor(progress: number): string {
  let label = PIPELINE_STAGES[0].label
  for (const st of PIPELINE_STAGES) if (progress >= st.at) label = st.label
  return label
}

export function progressStep(accuracy: string, structure: string): number {
  const acc = { 빠름: 1.6, 표준: 1, 정밀: 0.55 }[accuracy] ?? 1
  const str = { 모노머: 1, '2량체': 0.7, '3량체': 0.5, '사용자 구조': 0.8 }[structure] ?? 1
  return 7 * acc * str // 1초 틱당 % (표준 모노머 ≈ 15초)
}
