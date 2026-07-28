import { useStore } from '../store'
import type { PageId } from '../App'
import { EnergyLevelChart } from '../charts'
import { StatusBadge } from './Jobs'

export function Dashboard({ go }: { go: (p: PageId) => void }) {
  const { molecules, jobs, moleculeById } = useStore()
  const done = jobs.filter((j) => j.status === 'done')
  const active = jobs.filter((j) => j.status === 'running' || j.status === 'queued')
  const avgGap = done.length
    ? done.reduce((s, j) => s + (j.result?.gap ?? 0), 0) / done.length
    : null

  // 최근 완료된 서로 다른 분자 최대 3개의 에너지 준위
  const recentEntries: { molecule: NonNullable<ReturnType<typeof moleculeById>>; result: NonNullable<(typeof done)[number]['result']> }[] = []
  for (const j of [...done].reverse()) {
    const m = moleculeById(j.moleculeId)
    if (m && j.result && !recentEntries.some((e) => e.molecule.id === m.id)) {
      recentEntries.push({ molecule: m, result: j.result })
    }
    if (recentEntries.length === 3) break
  }

  return (
    <div>
      <header className="page-head">
        <h1>대시보드</h1>
        <p className="page-desc">바인더 후보 분자의 DFT 물성 계산 현황 요약</p>
      </header>

      <div className="stat-row">
        <div className="stat-tile">
          <div className="stat-label">등록 분자</div>
          <div className="stat-value">{molecules.length}</div>
          <div className="stat-sub">기본 {molecules.filter((m) => m.builtin).length} · 사용자 {molecules.filter((m) => !m.builtin).length}</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">완료된 계산</div>
          <div className="stat-value">{done.length}</div>
          <div className="stat-sub">전체 작업 {jobs.length}건</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">진행·대기</div>
          <div className="stat-value">{active.length}</div>
          <div className="stat-sub">동시 실행 최대 2</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">평균 HOMO–LUMO gap</div>
          <div className="stat-value">
            {avgGap !== null ? avgGap.toFixed(2) : '—'}
            {avgGap !== null && <span className="stat-unit"> eV</span>}
          </div>
          <div className="stat-sub">완료 작업 기준</div>
        </div>
      </div>

      <div className="grid-2">
        <section className="card">
          <div className="card-head">
            <h2>최근 완료 분자 에너지 준위</h2>
          </div>
          {recentEntries.length ? (
            <EnergyLevelChart entries={recentEntries} />
          ) : (
            <div className="empty">
              완료된 계산이 아직 없습니다.
              <button className="btn primary" onClick={() => go('new')}>
                첫 계산 시작하기
              </button>
            </div>
          )}
        </section>

        <section className="card">
          <div className="card-head">
            <h2>최근 작업</h2>
            <button className="btn ghost" onClick={() => go('jobs')}>
              전체 보기
            </button>
          </div>
          {jobs.length ? (
            <table className="table">
              <thead>
                <tr>
                  <th>분자</th>
                  <th>조건</th>
                  <th>상태</th>
                </tr>
              </thead>
              <tbody>
                {[...jobs]
                  .sort((a, b) => b.createdAt - a.createdAt)
                  .slice(0, 6)
                  .map((j) => {
                    const m = moleculeById(j.moleculeId)
                    return (
                      <tr key={j.id}>
                        <td>{m?.abbreviation ?? j.moleculeId}</td>
                        <td className="mono small">
                          {j.settings.functional}/{j.settings.basis}
                        </td>
                        <td>
                          <StatusBadge job={j} />
                        </td>
                      </tr>
                    )
                  })}
              </tbody>
            </table>
          ) : (
            <div className="empty">아직 제출된 작업이 없습니다.</div>
          )}
        </section>
      </div>

      <section className="card">
        <div className="card-head">
          <h2>워크플로우</h2>
        </div>
        <ol className="workflow">
          <li onClick={() => go('library')}>
            <b>1. 분자 등록</b>
            <span>라이브러리에서 바인더 단량체 선택 또는 SMILES로 신규 등록</span>
          </li>
          <li onClick={() => go('new')}>
            <b>2. 계산 조건 설정</b>
            <span>범함수·기저함수·용매모델 선택 후 작업 제출</span>
          </li>
          <li onClick={() => go('jobs')}>
            <b>3. 작업 모니터링</b>
            <span>큐 상태와 수렴 단계를 실시간 확인</span>
          </li>
          <li onClick={() => go('results')}>
            <b>4. 결과 분석</b>
            <span>HOMO/LUMO·접착에너지·전위 비교로 후보 스크리닝</span>
          </li>
        </ol>
      </section>
    </div>
  )
}
