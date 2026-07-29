import type { ReactNode } from 'react'
import type { CalcJob, JobStatus, Material, ReadyState } from './types'

// 데이터 상태 표시 (기획서 13.2 — 운영 UI에 simulation 배지 없음, 상태 명시)
export const STATUS_LABEL: Record<JobStatus, string> = {
  QUEUED: '대기',
  RUNNING: '실행',
  COMPUTED: '계산 완료·검증 대기',
  VALIDATING: '검증 중',
  PUBLISHED: '공개(PUBLISHED)',
  NEEDS_REVIEW: '검토 필요',
  FAILED: '실패',
}

export function StatusBadge({ status, progress }: { status: JobStatus; progress?: number }) {
  const cls: Record<JobStatus, string> = {
    QUEUED: 'queued',
    RUNNING: 'running',
    COMPUTED: 'validating',
    VALIDATING: 'validating',
    PUBLISHED: 'published',
    NEEDS_REVIEW: 'review',
    FAILED: 'failed',
  }
  return (
    <span className={`badge ${cls[status]}`}>
      {STATUS_LABEL[status]}
      {status === 'RUNNING' && progress !== undefined ? ` ${Math.floor(progress)}%` : ''}
    </span>
  )
}

export function ReadyBadge({ state }: { state: ReadyState }) {
  const cls =
    state === 'Ready' ? 'published' : state === 'Ready with warning' ? 'review' : state === 'Expert review' ? 'review' : 'queued'
  return <span className={`badge ${cls}`}>{state}</span>
}

export function InitialBadge({ material }: { material: Material }) {
  const initials = material.name
    .split(/[\s(]/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join('')
  return <span className="initial-badge">{initials}</span>
}

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: string[]
  active: string
  onChange: (t: string) => void
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t}
          role="tab"
          aria-selected={active === t}
          className={`tab ${active === t ? 'active' : ''}`}
          onClick={() => onChange(t)}
        >
          {t}
        </button>
      ))}
    </div>
  )
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
    </label>
  )
}

export function fmtDate(ts?: number) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString('ko-KR', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function jobConditionSummary(job: CalcJob, solventLabel: string) {
  const s = job.settings
  return `${s.envType} · ${solventLabel} · ${s.temperature} K · ${s.structure} · ${s.expert.functional}/${s.expert.basis} · ${s.referenceElectrode}`
}
