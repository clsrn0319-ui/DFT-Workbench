export type Category =
  | '불소계'
  | '고무계'
  | '셀룰로오스계'
  | '아크릴계'
  | '수용성'
  | '니트릴계'
  | '에테르계'
  | '기타'

export interface Molecule {
  id: string
  name: string
  abbreviation: string
  smiles: string
  category: Category
  monomer: string
  mw: number // 단량체 분자량 (g/mol)
  note?: string
  builtin: boolean
}

export type Functional = 'B3LYP' | 'PBE0' | 'M06-2X' | 'ωB97X-D' | 'PBE'
export type BasisSet = '6-31G(d)' | '6-311+G(d,p)' | 'def2-SVP' | 'def2-TZVP'
export type SolventModel = 'none' | 'PCM(H2O)' | 'SMD(H2O)' | 'SMD(NMP)'

export interface CalcSettings {
  functional: Functional
  basis: BasisSet
  solvent: SolventModel
  dispersion: boolean // D3(BJ) 분산 보정
  charge: number
  multiplicity: number
}

export type Surface = 'Graphite' | 'Si' | 'NMC811' | 'LFP'

export interface DftResult {
  homo: number // eV
  lumo: number // eV
  gap: number // eV
  dipole: number // Debye
  polarizability: number // a.u.
  espMin: number // kcal/mol
  espMax: number // kcal/mol
  oxidationPotential: number // V vs Li/Li+
  reductionPotential: number // V vs Li/Li+
  solvationEnergy: number // kcal/mol
  adhesion: Record<Surface, number> // eV (음수 = 흡착 안정)
  totalEnergy: number // Hartree
  scfCycles: number
  wallTimeSec: number
}

export type JobStatus = 'queued' | 'running' | 'done' | 'failed'

export interface Job {
  id: string
  moleculeId: string
  settings: CalcSettings
  status: JobStatus
  progress: number // 0–100
  stage: string
  createdAt: number
  startedAt?: number
  finishedAt?: number
  result?: DftResult
  error?: string
}
