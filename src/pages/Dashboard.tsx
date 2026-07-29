import { useState, type ReactNode } from 'react'
import { DASHBOARD_WIDGETS, useStore } from '../store'
import type { Nav } from '../App'
import { StatusBadge, fmtDate } from '../ui'
import { COMPUTED_KEYS } from '../data/descriptors'

// 기획서 4.1 (DASH-01~04) + 사용자 위젯 편집: 표시/숨김·순서 변경을 계정에 저장
export function Dashboard({ go }: Nav) {
  const store = useStore()
  const { materials, jobs, recent, compareIds, dashboardWidgets, dispatch, materialById, latestPublished } = store
  const [editMode, setEditMode] = useState(false)

  const published = jobs.filter((j) => j.status === 'PUBLISHED')
  const active = jobs.filter((j) => ['QUEUED', 'RUNNING', 'VALIDATING', 'COMPUTED'].includes(j.status))

  const move = (id: string, dir: -1 | 1) => {
    const ids = [...dashboardWidgets]
    const i = ids.indexOf(id)
    const j = i + dir
    if (i < 0 || j < 0 || j >= ids.length) return
    ;[ids[i], ids[j]] = [ids[j], ids[i]]
    dispatch({ type: 'setWidgets', ids })
  }

  const remove = (id: string) =>
    dispatch({ type: 'setWidgets', ids: dashboardWidgets.filter((w) => w !== id) })

  const add = (id: string) => dispatch({ type: 'setWidgets', ids: [...dashboardWidgets, id] })

  const hidden = DASHBOARD_WIDGETS.filter((w) => !dashboardWidgets.includes(w.id))

  const widgetLabel = (id: string) => DASHBOARD_WIDGETS.find((w) => w.id === id)?.label ?? id

  const renderWidget = (id: string): ReactNode => {
    switch (id) {
      case 'stats':
        return (
          <div className="stat-row">
            <div className="stat-tile">
              <div className="stat-label">등록 물질</div>
              <div className="stat-value">{materials.length}</div>
              <div className="stat-sub">준비 완료 {materials.filter((m) => m.readyState === 'Ready').length}</div>
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
        )
      case 'quick':
        return (
          <section className="card">
            <div className="card-head">
              <h2>빠른 실행 · 워크플로우</h2>
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
                <span>1단계(전자구조·구조 최적화) → 2단계(전기화학 안정성) 순서로 계산</span>
              </li>
              <li onClick={() => go('results')}>
                <b>③ DFT 결과 · 물질 비교</b>
                <span>검증 통과(PUBLISHED) 결과를 활물질 기준과 함께 비교</span>
              </li>
            </ol>
          </section>
        )
      case 'recent-materials':
        return (
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
                          descriptor {Math.min(done, COMPUTED_KEYS.length)}/{COMPUTED_KEYS.length}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            ) : (
              <div className="empty small">아직 조회한 물질이 없습니다. 물질 보관함에서 시작하세요.</div>
            )}
          </section>
        )
      case 'recent-jobs':
        return (
          <section className="card">
            <div className="card-head">
              <h2>최근 활동</h2>
            </div>
            {jobs.length ? (
              <table className="table">
                <tbody>
                  {[...jobs]
                    .sort((a, b) => b.createdAt - a.createdAt)
                    .slice(0, 6)
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
        )
      case 'compare-set':
        return (
          <section className="card">
            <div className="card-head">
              <h2>비교 세트 요약</h2>
              <button className="btn ghost" onClick={() => go('compare')}>
                물질 비교 →
              </button>
            </div>
            {compareIds.length ? (
              <div className="mat-card-badges">
                {compareIds.map((id) => (
                  <span key={id} className="chip">
                    {materialById(id)?.name.split(' ')[0] ?? id}
                  </span>
                ))}
                <span className="small muted">{compareIds.length}/8 선택됨</span>
              </div>
            ) : (
              <div className="empty small">비교 세트가 비어 있습니다. 보관함이나 결과 화면에서 추가하세요.</div>
            )}
          </section>
        )
      case 'server':
        return (
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
              ※ 결과 수치는 브라우저 내 모의 엔진이 생성하며, 상용 배포 시 Python 백엔드의 실제
              계산·검증(PUBLISHED 게이트)으로 대체됩니다.
            </div>
          </section>
        )
      default:
        return null
    }
  }

  return (
    <div>
      <header className="page-head">
        <div className="card-head" style={{ marginBottom: 0 }}>
          <h1>대시보드</h1>
          <button className={`btn ${editMode ? 'primary' : ''}`} onClick={() => setEditMode(!editMode)}>
            {editMode ? '편집 완료' : '위젯 편집'}
          </button>
        </div>
        <p className="page-desc">
          {editMode
            ? '위젯을 위/아래로 이동하거나 제거하고, 아래에서 숨긴 위젯을 다시 추가하세요. 구성은 계정에 저장됩니다.'
            : '물질 관리와 계산 상태를 파악하고 3단계 흐름의 다음 작업으로 이동합니다'}
        </p>
      </header>

      {dashboardWidgets.map((id, i) => (
        <div key={id} className={`widget ${editMode ? 'editing' : ''}`}>
          {editMode && (
            <div className="widget-controls">
              <span className="small muted">{widgetLabel(id)}</span>
              <span className="row-actions">
                <button className="btn ghost" disabled={i === 0} onClick={() => move(id, -1)}>
                  ↑
                </button>
                <button
                  className="btn ghost"
                  disabled={i === dashboardWidgets.length - 1}
                  onClick={() => move(id, 1)}
                >
                  ↓
                </button>
                <button className="btn ghost danger" onClick={() => remove(id)}>
                  제거
                </button>
              </span>
            </div>
          )}
          {renderWidget(id)}
        </div>
      ))}

      {editMode && (
        <section className="card">
          <div className="card-head">
            <h2>숨긴 위젯 추가</h2>
          </div>
          {hidden.length ? (
            <div className="quick-actions">
              {hidden.map((w) => (
                <button key={w.id} className="btn" onClick={() => add(w.id)}>
                  ＋ {w.label}
                </button>
              ))}
            </div>
          ) : (
            <div className="empty small">모든 위젯이 표시되어 있습니다.</div>
          )}
          <div className="form-actions">
            <button
              className="btn ghost"
              onClick={() =>
                dispatch({ type: 'setWidgets', ids: ['stats', 'quick', 'recent-materials', 'recent-jobs', 'server'] })
              }
            >
              기본 구성으로 초기화
            </button>
          </div>
        </section>
      )}

      {!dashboardWidgets.length && !editMode && (
        <div className="empty card">
          표시할 위젯이 없습니다.
          <button className="btn primary" onClick={() => setEditMode(true)}>
            위젯 편집
          </button>
        </div>
      )}
    </div>
  )
}
