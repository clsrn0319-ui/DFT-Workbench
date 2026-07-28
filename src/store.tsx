import {
  createContext,
  useContext,
  useEffect,
  useReducer,
  type ReactNode,
} from 'react'
import type { CalcSettings, Job, Molecule } from './types'
import { BUILTIN_MOLECULES } from './data/binders'
import { computeResult, progressStep, stageFor } from './engine/mockDft'

interface State {
  molecules: Molecule[]
  jobs: Job[]
}

type Action =
  | { type: 'addMolecule'; molecule: Molecule }
  | { type: 'removeMolecule'; id: string }
  | { type: 'submitJobs'; jobs: Job[] }
  | { type: 'tick' }
  | { type: 'cancelJob'; id: string }
  | { type: 'deleteJob'; id: string }

const STORAGE_KEY = 'dft-workbench-v1'

function load(): State {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as State
      const customs = parsed.molecules.filter((m) => !m.builtin)
      return {
        molecules: [...BUILTIN_MOLECULES, ...customs],
        jobs: parsed.jobs ?? [],
      }
    }
  } catch {
    // 손상된 저장소는 초기화
  }
  return { molecules: BUILTIN_MOLECULES, jobs: [] }
}

function runQueue(state: State): State {
  // 동시 실행 2개 제한: 대기 중인 작업을 실행 상태로 승격
  const running = state.jobs.filter((j) => j.status === 'running').length
  if (running >= 2) return state
  let slots = 2 - running
  const jobs = state.jobs.map((j) => {
    if (slots > 0 && j.status === 'queued') {
      slots--
      return { ...j, status: 'running' as const, startedAt: Date.now(), stage: stageFor(0) }
    }
    return j
  })
  return { ...state, jobs }
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'addMolecule':
      return { ...state, molecules: [...state.molecules, action.molecule] }
    case 'removeMolecule':
      return {
        ...state,
        molecules: state.molecules.filter((m) => m.id !== action.id || m.builtin),
      }
    case 'submitJobs':
      return runQueue({ ...state, jobs: [...state.jobs, ...action.jobs] })
    case 'cancelJob':
      return {
        ...state,
        jobs: state.jobs.map((j) =>
          j.id === action.id && (j.status === 'queued' || j.status === 'running')
            ? { ...j, status: 'failed' as const, error: '사용자 취소', finishedAt: Date.now() }
            : j,
        ),
      }
    case 'deleteJob':
      return { ...state, jobs: state.jobs.filter((j) => j.id !== action.id) }
    case 'tick': {
      let changed = false
      const jobs = state.jobs.map((j) => {
        if (j.status !== 'running') return j
        changed = true
        const next = Math.min(100, j.progress + progressStep(j.settings.basis) * (0.6 + Math.random() * 0.8))
        if (next >= 100) {
          const mol = state.molecules.find((m) => m.id === j.moleculeId)
          return {
            ...j,
            progress: 100,
            stage: stageFor(100),
            status: 'done' as const,
            finishedAt: Date.now(),
            result: computeResult(j.moleculeId, mol?.smiles ?? '', j.settings),
          }
        }
        return { ...j, progress: next, stage: stageFor(next) }
      })
      if (!changed) return state
      return runQueue({ ...state, jobs })
    }
  }
}

interface Store extends State {
  dispatch: (a: Action) => void
  moleculeById: (id: string) => Molecule | undefined
}

const Ctx = createContext<Store | null>(null)

export function StoreProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, undefined, load)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  }, [state])

  useEffect(() => {
    const t = setInterval(() => dispatch({ type: 'tick' }), 1000)
    return () => clearInterval(t)
  }, [])

  const store: Store = {
    ...state,
    dispatch,
    moleculeById: (id) => state.molecules.find((m) => m.id === id),
  }
  return <Ctx.Provider value={store}>{children}</Ctx.Provider>
}

export function useStore(): Store {
  const s = useContext(Ctx)
  if (!s) throw new Error('StoreProvider missing')
  return s
}

export function makeJob(moleculeId: string, settings: CalcSettings): Job {
  return {
    id: `job-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    moleculeId,
    settings,
    status: 'queued',
    progress: 0,
    stage: '대기 중',
    createdAt: Date.now(),
  }
}
