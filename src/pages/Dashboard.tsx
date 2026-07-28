import { useStore } from '../store'
import type { Nav } from '../App'
import { StatusBadge, fmtDate } from '../ui'
import { COMPUTED_KEYS } from '../data/descriptors'

// 기획서 4.1 — DASH-01~04
export function Dashboard({ go }: Nav) {
  const { materials, jobs, recent, materialById, latestPublished } = useStore()

  const published = jobs.filter((j) => j.status === 'PUBLISHED')
  const active = jobs.filter((j) => ['QUEUED', 'RUNNING', 'VALIDATING', 'COMPUTED'].includes(j.status))
  const readyCount = materials.filter((m) => m.readyState === 'Ready').length

  return (
    <div>
      <header className="page-head">
        <h1>대시보드</h1>
        <p className="page-desc">물질 관리와 계산 상태를 파악하고 3단계 흐름의 다음 작업으로 이동합니다</p>
      </header>

      <div className="stat-row">
        <div className="stat-tile">
          <div className="stat-label">등록 물질</div>
          <div className="stat-value">{materials.length}</div>
          <div className="stat-sub">준비 완료(Ready) {readyCount}</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">공개(PUBLISHED) 계산</div>
          <div className="stat-value">{published.length}</div>
          <div className="stat-sub">검증 통과 결과만 집계</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">진행 중 작업</div>
          <div className="stat-value">{active.length}</div>
          <div className="stat-sub">대기·실행·검증 포함</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">검토 필요 · 실패</div>
          <div className="stat-value">
            {jobs.filter((j) => j.status === 'NEEDS_REVIEW' || j.status === 'FAILED').length}
          </div>
          <div className="stat-sub">숫자 미공개 상태</div>
        </div>
      </div>

      <div className="grid-2">
        <section className="card">
          <div className="card-head">
            <h2>빠른 실행</h2>
          </div>
          <div className="quick-actions">
            <button className="btn primary" onClick={() => go('library')}>
              새 물질 등록
            </button>
            <button className="btn" onClick={() => go('calc')}>
              구조 최적화 · DFT
            </button>
            <button className="btn" onClick={() => go('results')}>
              결과 보기
            </button>
          </div>
          <ol className="workflow">
            <li onClick={() => go('library')}>
              <b>① 물질 입력 · 특징 정리</b>
              <span>이름/CAS 검색으로 SMILES를 찾아 등록하고 고유 특징을 확인</span>
            </li>
            <li onClick={() => go('calc')}>
              <b>② 환경 · 구조 최적화</b>
              <span>환경·용매·온도를 선택하면 검증·conformer·xTB·DFT 프리셋 자동 적용</span>
            </li>
            <li onClick={() => go('results')}>
              <b>③ DFT 결과 · 물질 비교</b>
              <span>검증 통과(PUBLISHED) 결과를 확인하고 공통 축에서 비교</span>
            </li>
          </ol>
        </section>

        <section className="card">
          <div className="card-head">
            <h2>최근 본 물질</h2>
          </div>
          {recent.length ? (
            <table className="table">
              <tbody>
                {recent.map((id) => {
                  const m = materialById(id)
                  if (!m) return null
                  const pub = latestPublished(id)
                  const done = pub ? Object.keys(pub.result!.descriptors).length : 0
                  return (
                    <tr key={id} className="clickable" onClick={() => go('detail', id)}>
                      <td>
                        <b>{m.name}</b>
                        <div className="small muted mono">{m.smiles}</div>
                      </td>
                      <td className="num small muted">
                        descriptor {done}/{COMPUTED_KEYS.length}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : (
            <div className="empty small">아직 조회한 물질이 없습니다. 물질 보관함에서 시작하세요.</div>
          )}

          <div className="card-head" style={{ marginTop: 18 }}>
            <h2>최근 활동</h2>
          </div>
          {jobs.length ? (
            <table className="table">
              <tbody>
                {[...jobs]
                  .sort((a, b) => b.createdAt - a.createdAt)
                  .slice(0, 5)
                  .map((j) => (
                    <tr key={j.id} className="clickable" onClick={() => go('results', j.materialId)}>
                      <td>
                        {materialById(j.materialId)?.name ?? j.materialId}
                        <div className="small muted mono">{j.id}</div>
                      </td>
                      <td className="num">
                        <StatusBadge status={j.status} progress={j.progress} />
                        <div className="small muted">{fmtDate(j.createdAt)}</div>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          ) : (
            <div className="empty small">아직 계산 요청이 없습니다.</div>
          )}
        </section>
      </div>

      <section className="card">
        <div className="card-head">
          <h2>서버 상태</h2>
          <span className="muted small">프로토타입 — 브라우저 내 모의 파이프라인</span>
        </div>
        <div className="server-row">
          <div className="server-chip">
            <span className="dot ok" /> Web/API (FastAPI)
          </div>
          <div className="server-chip">
            <span className="dot ok" /> 작업 큐 (Redis/Celery)
          </div>
          <div className="server-chip">
            <span className="dot ok" /> 계산 워커 (RDKit·xTB·PySCF)
          </div>
          <div className="server-chip">
            <span className="dot ok" /> 저장소 (PostgreSQL·MinIO)
          </div>
        </div>
        <div className="chart-note">
          ※ 본 화면은 통합 기획서 v4.0의 흐름 확인용 프로토타입입니다. 결과 수치는 브라우저 내 모의 엔진이
          생성하며, 상용 배포 시 Python 백엔드의 실제 계산·검증(PUBLISHED 게이트)으로 대체됩니다.
        </div>
      </section>
    </div>
  )
}
