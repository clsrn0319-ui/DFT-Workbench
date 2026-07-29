// 백과 문헌/사용자 참고값 (조건에 따라 달라질 수 있는 대표값)
export interface EncyData {
  state?: string
  bp?: string
  mp?: string
  density?: string
  solubility?: string
  acidBase?: string
  reactivity?: string
  isomers?: string
  optical?: string
  extra?: string[]
}

// ── 물질 (기획서 5.1 Material) ─────────────────────────────────
export type MaterialType = '바인더 모노머' | '용매' | '첨가제' | '염' | '기타'
export type OriginType = '상용' | '합성' | '개질' | '미상'
export type ReadyState = 'Needs decision' | 'Ready with warning' | 'Ready' | 'Expert review'

export interface Material {
  id: string
  name: string
  casNo: string // 빈 문자열 = 미부여
  smiles: string
  formula: string
  mw: number
  type: MaterialType
  originType: OriginType
  tags: string[]
  note: string
  precursorCas: string[]
  structureVersion: number // SMILES 변경 시 증가
  readyState: ReadyState
  createdAt: number
  updatedAt: number
  builtin: boolean
  dictId?: string // 내장 사전 항목과 연결 (물성 기준값·작용기 참조)
  userEncy?: EncyData // 사용자가 직접 입력한 백과 참고값 (문헌값보다 우선 표시)
}

// ── 용매 프리셋 (기획서 4.4 / 5.1 SolventPreset) ────────────────
export interface SolventPreset {
  id: string
  kind: 'single' | 'mixed'
  name: string
  abbr: string
  smiles?: string
  formula?: string
  components?: { abbr: string; ratio: number }[] // 혼합
  ratioBasis?: '부피비' | '질량비' | '몰비'
  modelKey: string // xTB/DFT implicit solvent 모델 키
  version: string // "1.0" → 편집 시 "1.1"
  note?: string
  builtin: boolean
}

// ── 계산 설정 (기획서 4.5) ──────────────────────────────────────
export type EnvType = '배터리 전해액' | '진공·기체' | '고체·주기계' | '사용자 정의'
export type CalcStructure = '모노머' | '2량체' | '3량체' | '사용자 구조'
export type AccuracyLevel = '빠름' | '표준' | '정밀'
// 2단계 계산 흐름: ① 전자구조·구조 최적화 → ② 최적 구조를 불러와 전기화학 안정성
export type CalcPurpose = '전자구조(구조 최적화)' | '전기화학 안정성' | '전체 계산'

export interface ExpertSettings {
  charge: number
  multiplicity: number
  nConformers: number
  rmsdThreshold: number // Å
  energyWindow: number // kcal/mol
  engine: 'PySCF' | 'CP2K'
  functional: string
  basis: string
  dispersion: boolean
  scfTol: string
  grid: number
}

export interface CalcSettings {
  envType: EnvType
  solventId: string | null // null = 진공
  temperature: number // K
  atmosphere: '불활성' | '공기' | '사용자 정의'
  structure: CalcStructure
  accuracy: AccuracyLevel
  purpose: CalcPurpose
  referenceElectrode: 'Li/Li+' | 'SHE'
  expert: ExpertSettings
}

// ── 작업·결과 (기획서 13.2 상태 게이트) ─────────────────────────
export type JobStatus =
  | 'QUEUED'
  | 'RUNNING'
  | 'COMPUTED'
  | 'VALIDATING'
  | 'PUBLISHED'
  | 'NEEDS_REVIEW'
  | 'FAILED'

export interface DescriptorValue {
  value: number
  unit: string
}

export interface CalcResult {
  descriptors: Record<string, DescriptorValue>
  validationStatus: 'PASSED' | 'NEEDS_REVIEW'
  validationNotes: string[]
  publishedAt?: number
  protocolId: string
  structureHash: string
}

export interface CalcJob {
  id: string
  materialId: string
  structureVersion: number
  baseJobId?: string // 2단계(전기화학) 계산이 불러온 1단계 최적화 구조의 작업 ID
  settings: CalcSettings
  status: JobStatus
  progress: number
  stage: string
  logs: string[]
  createdAt: number
  finishedAt?: number
  result?: CalcResult
  error?: string
}

// ── 참고 오버레이 (외부/실험, 기획서 4.7·12.7) ──────────────────
export interface ExternalReference {
  dictId: string
  source: string // 'Materials Project (MPcules)' 등
  sourceId: string
  method: string
  solvent: string
  values: Record<string, DescriptorValue>
  retrievedAt: string
}

// ── 테마 (기획서 14) ────────────────────────────────────────────
export interface ThemeTokens {
  mode: 'light' | 'dark' | 'high-contrast'
  background: string
  card: string
  border: string
  accent: string // 딥 틸
  pin: string // 앰버
  chartSeries: string[] // 물질 series 색 8개
  mepNegative: string
  mepPositive: string
}
