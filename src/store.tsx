import {
  createContext,
  useContext,
  useEffect,
  useReducer,
  type ReactNode,
} from 'react'
import type {
  CalcJob,
  CalcSettings,
  Material,
  SolventPreset,
  ThemeTokens,
} from './types'
import { DICTIONARY, type DictEntry } from './data/dictionary'
import { BUILTIN_SOLVENTS, bumpVersion } from './data/solvents'
import { buildResult, progressStep, stageFor } from './engine/mockDft'
import { DEFAULT_THEME, applyTheme } from './theme'

interface State {
  materials: Material[]
  solvents: SolventPreset[]
  jobs: CalcJob[]
  pins: string[] // 고정(★) descriptor key, 순서 유지
  theme: ThemeTokens
  recent: string[] // 최근 본 물질 id
  compareIds: string[] // 비교 세트 (최대 8)
  showOverlay: boolean // 참고 오버레이 표시
}

type Action =
  | { type: 'addMaterial'; material: Material }
  | { type: 'updateMaterial'; id: string; patch: Partial<Material>; structureChanged: boolean }
  | { type: 'deleteMaterial'; id: string }
  | { type: 'viewMaterial'; id: string }
  | { type: 'addSolvent'; solvent: SolventPreset }
  | { type: 'updateSolvent'; id: string; patch: Partial<SolventPreset> }
  | { type: 'deleteSolvent'; id: string }
  | { type: 'submitJobs'; jobs: CalcJob[] }
  | { type: 'tick' }
  | { type: 'cancelJob'; id: string }
  | { type: 'deleteJob'; id: string }
  | { type: 'togglePin'; key: string }
  | { type: 'setPins'; keys: string[] }
  | { type: 'setTheme'; theme: ThemeTokens }
  | { type: 'toggleCompare'; id: string }
  | { type: 'setCompare'; ids: string[] }
  | { type: 'setOverlay'; show: boolean }

const STORAGE_KEY = 'dft-workbench-v4'

export function materialFromDict(e: DictEntry): Material {
  return {
    id: `mat-${e.dictId}`,
    name: e.name,
    casNo: e.casNo,
    smiles: e.smiles,
    formula: e.formula,
    mw: e.mw,
    type: e.type,
    originType: '상용',
    tags: e.synonyms.slice(0, 2),
    note: '',
    precursorCas: [],
    structureVersion: 1,
    readyState: 'Ready',
    createdAt: Date.now(),
    updatedAt: Date.now(),
    builtin: true,
    dictId: e.dictId,
  }
}

const SEED_IDS = ['vdf', 'aa', 'styrene', 'an', 'mma']

function initialState(): State {
  return {
    materials: DICTIONARY.filter((d) => SEED_IDS.includes(d.dictId)).map(materialFromDict),
    solvents: BUILTIN_SOLVENTS,
    jobs: [],
    pins: ['binder_homo', 'binder_oxidation_potential', 'binder_li_binding_energy'],
    theme: DEFAULT_THEME,
    recent: [],
    compareIds: [],
    showOverlay: false,
  }
}

function load(): State {
  const init = initialState()
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const p = JSON.parse(raw) as Partial<State>
      return {
        ...init,
        ...p,
        theme: { ...DEFAULT_THEME, ...(p.theme ?? {}) },
        solvents: p.solvents?.length ? p.solvents : init.solvents,
        materials: p.materials?.length ? p.materials : init.materials,
      }
    }
  } catch {
    // 손상된 저장소는 초기화
  }
  return init
}

const MAX_RUNNING = 2

function promoteQueue(jobs: CalcJob[]): CalcJob[] {
  let running = jobs.filter((j) => j.status === 'RUNNING').length
  return jobs.map((j) => {
    if (running < MAX_RUNNING && j.status === 'QUEUED') {
      running++
      return { ...j, status: 'RUNNING' as const, stage: stageFor(0), logs: [...j.logs, '워커 할당 — 계산 시작'] }
    }
    return j
  })
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'addMaterial':
      return { ...state, materials: [action.material, ...state.materials] }
    case 'updateMaterial': {
      const materials = state.materials.map((m) =>
        m.id === action.id
          ? {
              ...m,
              ...action.patch,
              structureVersion: action.structureChanged ? m.structureVersion + 1 : m.structureVersion,
              updatedAt: Date.now(),
            }
          : m,
      )
      // 구조 변경 시 기존 결과는 "이전 구조 결과"로 보존 (기획서 5.3) — 작업의
      // structureVersion이 물질의 현재 버전과 다르면 화면에서 구분 표시한다.
      return { ...state, materials }
    }
    case 'deleteMaterial':
      return {
        ...state,
        materials: state.materials.filter((m) => m.id !== action.id),
        jobs: state.jobs.filter((j) => j.materialId !== action.id),
        compareIds: state.compareIds.filter((id) => id !== action.id),
        recent: state.recent.filter((id) => id !== action.id),
      }
    case 'viewMaterial':
      return {
        ...state,
        recent: [action.id, ...state.recent.filter((id) => id !== action.id)].slice(0, 6),
      }
    case 'addSolvent':
      return { ...state, solvents: [...state.solvents, action.solvent] }
    case 'updateSolvent': {
      const prev = state.solvents.find((s) => s.id === action.id)
      if (!prev) return state
      let solvents = state.solvents.map((s) =>
        s.id === action.id ? { ...s, ...action.patch, version: bumpVersion(s.version) } : s,
      )
      // 단일 용매 약어 변경 시 혼합 프리셋 동기화 (SOLV-05)
      if (prev.kind === 'single' && action.patch.abbr && action.patch.abbr !== prev.abbr) {
        solvents = solvents.map((s) =>
          s.kind === 'mixed' && s.components?.some((c) => c.abbr === prev.abbr)
            ? {
                ...s,
                components: s.components!.map((c) =>
                  c.abbr === prev.abbr ? { ...c, abbr: action.patch.abbr! } : c,
                ),
                name: s.name.replace(prev.abbr, action.patch.abbr!),
                abbr: s.abbr.replace(prev.abbr, action.patch.abbr!),
                version: bumpVersion(s.version),
              }
            : s,
        )
      }
      return { ...state, solvents }
    }
    case 'deleteSolvent': {
      const target = state.solvents.find((s) => s.id === action.id)
      if (!target) return state
      // 연결 혼합 프리셋 함께 정리 (SOLV-06)
      const solvents = state.solvents.filter(
        (s) =>
          s.id !== action.id &&
          !(target.kind === 'single' && s.kind === 'mixed' && s.components?.some((c) => c.abbr === target.abbr)),
      )
      return { ...state, solvents }
    }
    case 'submitJobs':
      return { ...state, jobs: promoteQueue([...state.jobs, ...action.jobs]) }
    case 'cancelJob':
      return {
        ...state,
        jobs: state.jobs.map((j) =>
          j.id === action.id && ['QUEUED', 'RUNNING', 'VALIDATING', 'COMPUTED'].includes(j.status)
            ? { ...j, status: 'FAILED' as const, error: '사용자 취소', finishedAt: Date.now() }
            : j,
        ),
      }
    case 'deleteJob':
      return { ...state, jobs: state.jobs.filter((j) => j.id !== action.id) }
    case 'togglePin': {
      const pins = state.pins.includes(action.key)
        ? state.pins.filter((k) => k !== action.key)
        : [...state.pins, action.key]
      return { ...state, pins }
    }
    case 'setPins':
      return { ...state, pins: action.keys }
    case 'setTheme':
      return { ...state, theme: action.theme }
    case 'toggleCompare': {
      const has = state.compareIds.includes(action.id)
      if (!has && state.compareIds.length >= 8) return state // 최대 8개 (기획서 4.7)
      return {
        ...state,
        compareIds: has
          ? state.compareIds.filter((id) => id !== action.id)
          : [...state.compareIds, action.id],
      }
    }
    case 'setCompare':
      return { ...state, compareIds: action.ids.slice(0, 8) }
    case 'setOverlay':
      return { ...state, showOverlay: action.show }
    case 'tick': {
      let changed = false
      let jobs = state.jobs.map((j) => {
        if (j.status === 'RUNNING') {
          changed = true
          const next = Math.min(100, j.progress + progressStep(j.settings.accuracy, j.settings.structure) * (0.7 + Math.random() * 0.6))
          const stage = stageFor(next)
          const logs = stage !== j.stage ? [...j.logs, stage] : j.logs
          if (next >= 100) {
            return {
              ...j,
              progress: 100,
              status: 'VALIDATING' as const,
              stage: '품질 검증 (Validator) — SCF·구조·진동수·상태 일치 검사',
              logs: [...logs, '계산 완료 — 품질 검증 시작'],
            }
          }
          return { ...j, progress: next, stage, logs }
        }
        if (j.status === 'VALIDATING') {
          changed = true
          const ticks = (j as CalcJob & { vt?: number }).vt ?? 0
          if (ticks >= 3) {
            const mat = state.materials.find((m) => m.id === j.materialId)
            const solvent = state.solvents.find((s) => s.id === j.settings.solventId)
            const result = buildResult(
              j.materialId,
              mat?.dictId,
              mat?.smiles ?? '',
              j.structureVersion,
              j.settings,
              solvent?.modelKey ?? null,
            )
            const published = result.validationStatus === 'PASSED'
            return {
              ...j,
              status: published ? ('PUBLISHED' as const) : ('NEEDS_REVIEW' as const),
              stage: published ? '검증 통과 — PUBLISHED' : '검증 보류 — NEEDS_REVIEW',
              finishedAt: Date.now(),
              result: published ? { ...result, publishedAt: Date.now() } : result,
              logs: [...j.logs, ...result.validationNotes],
            }
          }
          return { ...j, vt: ticks + 1 } as CalcJob
        }
        return j
      })
      if (!changed) return state
      jobs = promoteQueue(jobs)
      return { ...state, jobs }
    }
  }
}

interface Store extends State {
  dispatch: (a: Action) => void
  materialById: (id: string) => Material | undefined
  solventById: (id: string | null) => SolventPreset | undefined
  publishedJobs: (materialId: string) => CalcJob[]
  latestPublished: (materialId: string) => CalcJob | undefined
}

const Ctx = createContext<Store | null>(null)

export function StoreProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, undefined, load)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  }, [state])

  useEffect(() => {
    applyTheme(state.theme)
  }, [state.theme])

  useEffect(() => {
    const t = setInterval(() => dispatch({ type: 'tick' }), 1000)
    return () => clearInterval(t)
  }, [])

  const publishedJobs = (materialId: string) =>
    state.jobs
      .filter((j) => j.materialId === materialId && j.status === 'PUBLISHED' && j.result)
      .sort((a, b) => (b.finishedAt ?? 0) - (a.finishedAt ?? 0))

  const store: Store = {
    ...state,
    dispatch,
    materialById: (id) => state.materials.find((m) => m.id === id),
    solventById: (id) => (id ? state.solvents.find((s) => s.id === id) : undefined),
    publishedJobs,
    latestPublished: (materialId) => publishedJobs(materialId)[0],
  }
  return <Ctx.Provider value={store}>{children}</Ctx.Provider>
}

export function useStore(): Store {
  const s = useContext(Ctx)
  if (!s) throw new Error('StoreProvider missing')
  return s
}

export function makeJob(material: Material, settings: CalcSettings): CalcJob {
  return {
    id: `JOB-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}-${Math.random().toString(36).slice(2, 6).toUpperCase()}`,
    materialId: material.id,
    structureVersion: material.structureVersion,
    settings,
    status: 'QUEUED',
    progress: 0,
    stage: '큐 대기',
    logs: [`작업 생성 — 구조 v${material.structureVersion}, ${settings.envType}`],
    createdAt: Date.now(),
  }
}

export const DEFAULT_SETTINGS: CalcSettings = {
  envType: '배터리 전해액',
  solventId: 'sol-ecdmc',
  temperature: 298.15,
  atmosphere: '불활성',
  structure: '모노머',
  accuracy: '표준',
  purpose: '전기화학 안정성',
  referenceElectrode: 'Li/Li+',
  expert: {
    charge: 0,
    multiplicity: 1,
    nConformers: 30,
    rmsdThreshold: 0.75,
    energyWindow: 5,
    engine: 'PySCF',
    functional: 'PBE0-D3(BJ)',
    basis: 'def2-TZVP',
    dispersion: true,
    scfTol: '1e-8',
    grid: 4,
  },
}
