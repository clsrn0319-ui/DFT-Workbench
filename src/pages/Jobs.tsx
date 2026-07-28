import { useStore } from '../store'
import type { Job } from '../types'
import type { PageId } from '../App'

export function StatusBadge({ job }: { job: Job }) {
  const map = {
    queued: { label: '대기', cls: 'queued' },
    running: { label: `실행 ${Math.floor(job.progress)}%`, cls: 'running' },
    done: { label: '✓ 완료', cls: 'done' },
    failed: { label: '✕ 실패', cls: 'failed' },
  }[job.status]
  return <span className={`badge ${map.cls}`}>{map.label}</span>
}

function fmtTime(ts?: number) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString('ko-KR', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function Jobs({ go }: { go: (p: PageId) => void }) {
  const { jobs, moleculeById, dispatch } = useStore()
  const sorted = [...jobs].sort((a, b) => b.createdAt - a.createdAt)

  return (
    <div>
      <header className="page-head">
        <h1>작업 현황</h1>
        <p className="page-desc">계산 큐 및 진행 상태 (동시 실행 2건, 1초 주기 갱신)</p>
      </header>

      {!jobs.length && (
        <div className="empty card">
          제출된 작업이 없습니다.
          <button className="btn primary" onClick={() => go('new')}>
            새 계산 만들기
          </button>
        </div>
      )}

      {sorted.map((j) => {
        const m = moleculeById(j.moleculeId)
        return (
          <div key={j.id} className="job-row card">
            <div className="job-main">
              <div className="job-title">
                <b>{m?.abbreviation ?? j.moleculeId}</b>
                <span className="muted small"> {m?.name}</span>
              </div>
              <div className="mono small muted">
                {j.settings.functional}
                {j.settings.dispersion ? '-D3(BJ)' : ''}/{j.settings.basis}
                {j.settings.solvent !== 'none' ? ` · ${j.settings.solvent}` : ''}
              </div>
              {j.status === 'running' && (
                <>
                  <div className="progress-track">
                    <div className="progress-fill" style={{ width: `${j.progress}%` }} />
                  </div>
                  <div className="small muted">{j.stage}</div>
                </>
              )}
              {j.status === 'done' && j.result && (
                <div className="small muted">
                  gap {j.result.gap.toFixed(2)} eV · μ {j.result.dipole.toFixed(2)} D · SCF{' '}
                  {j.result.scfCycles}회 · {j.result.wallTimeSec}s
                </div>
              )}
              {j.status === 'failed' && <div className="small form-error">{j.error}</div>}
            </div>
            <div className="job-side">
              <StatusBadge job={j} />
              <div className="small muted">제출 {fmtTime(j.createdAt)}</div>
              {j.finishedAt && <div className="small muted">종료 {fmtTime(j.finishedAt)}</div>}
              <div className="row-actions">
                {(j.status === 'queued' || j.status === 'running') && (
                  <button className="btn ghost danger" onClick={() => dispatch({ type: 'cancelJob', id: j.id })}>
                    취소
                  </button>
                )}
                {(j.status === 'done' || j.status === 'failed') && (
                  <button className="btn ghost danger" onClick={() => dispatch({ type: 'deleteJob', id: j.id })}>
                    삭제
                  </button>
                )}
                {j.status === 'done' && (
                  <button className="btn ghost" onClick={() => go('results')}>
                    결과 →
                  </button>
                )}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
