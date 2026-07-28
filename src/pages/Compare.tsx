import { useStore } from '../store'
import type { Nav } from '../App'
import { FingerprintRadar, HomoLumoChart, Legend, VoltageWindowChart, seriesColor, type SeriesEntry } from '../charts'
import { DESCRIPTORS, descriptorByKey } from '../data/descriptors'
import { EXTERNAL_REFS } from '../data/externalRefs'

// 기획서 4.7 물질 비교 + 14.3 물성 지문 — PUBLISHED 서버 계산값만 기본 비교
export function Compare({ go }: Nav) {
  const store = useStore()
  const { materials, compareIds, pins, showOverlay, dispatch, materialById, latestPublished, solventById } = store

  const candidates = materials.filter((m) => latestPublished(m.id))

  const items = compareIds
    .map((id) => {
      const m = materialById(id)
      const job = m ? latestPublished(id) : undefined
      return m && job ? { material: m, job } : null
    })
    .filter((x): x is NonNullable<typeof x> => !!x)

  // 조건 불일치 경고 (기획서 4.7·8.1)
  const mismatch: string[] = []
  if (items.length >= 2) {
    const key = (i: (typeof items)[number]) => [
      solventById(i.job.settings.solventId)?.abbr ?? 'vacuum',
      i.job.settings.temperature,
      i.job.settings.referenceElectrode,
      `${i.job.settings.expert.functional}/${i.job.settings.expert.basis}`,
    ]
    const first = key(items[0])
    const labels = ['용매', '온도', '기준 전극', '계산 방법'] as const
    for (let f = 0; f < 4; f++) {
      if (items.some((i) => String(key(i)[f]) !== String(first[f]))) mismatch.push(labels[f])
    }
  }

  const entries: SeriesEntry[] = items.map((i, idx) => ({
    label: i.material.name.split(' ')[0],
    color: seriesColor(idx),
    values: i.job.result!.descriptors,
  }))

  // 참고 오버레이 (점선 + 출처 배지) — 기본 비교와 구분
  const overlayEntries: SeriesEntry[] = showOverlay
    ? items
        .map((i, idx) => {
          const ref = i.material.dictId ? EXTERNAL_REFS.find((r) => r.dictId === i.material.dictId) : undefined
          if (!ref) return null
          return {
            label: `${i.material.name.split(' ')[0]} (외부)`,
            color: seriesColor(idx),
            values: ref.values,
            overlay: true,
            badge: ref.source,
          } as SeriesEntry
        })
        .filter((x): x is SeriesEntry => !!x)
    : []

  const allEntries = [...entries, ...overlayEntries]

  const pinnedKeys = pins.filter((k) => descriptorByKey(k))
  const otherKeys = DESCRIPTORS.filter((d) => !pins.includes(d.key) && !d.interfacial).map((d) => d.key)
  const rowKeys = [...pinnedKeys, ...otherKeys]

  return (
    <div>
      <header className="page-head">
        <h1>물질 비교</h1>
        <p className="page-desc">
          등록 물질의 PUBLISHED 서버 계산 결과를 최대 8개까지 동일 축에서 비교합니다. 외부·실험값은 참고
          오버레이로만 표시됩니다
        </p>
      </header>

      <section className="card">
        <div className="card-head">
          <h2>비교 대상 선택 ({items.length}/8)</h2>
          <div className="row-actions">
            <button className="btn ghost" onClick={() => dispatch({ type: 'setCompare', ids: candidates.map((c) => c.id) })}>
              전체 선택
            </button>
            <button className="btn ghost" onClick={() => dispatch({ type: 'setCompare', ids: [] })}>
              전체 해제
            </button>
            <label className="radio-row" style={{ display: 'inline-flex' }}>
              <input type="checkbox" checked={showOverlay} onChange={(e) => dispatch({ type: 'setOverlay', show: e.target.checked })} />
              참고 오버레이 표시
            </label>
          </div>
        </div>
        {candidates.length ? (
          <div className="mol-grid">
            {candidates.map((m) => {
              const active = compareIds.includes(m.id)
              const job = latestPublished(m.id)!
              return (
                <button key={m.id} className={`mol-card ${active ? 'selected' : ''}`} onClick={() => dispatch({ type: 'toggleCompare', id: m.id })}>
                  <b>{m.name}</b>
                  <span className="small muted">
                    {solventById(job.settings.solventId)?.abbr ?? 'vacuum'} · {job.settings.expert.functional}
                  </span>
                  <span className="mono small muted">{job.id}</span>
                </button>
              )
            })}
          </div>
        ) : (
          <div className="empty small">
            PUBLISHED 결과가 있는 물질이 없습니다. 계산값이 없는 물질은 임의 값 대신 서버 계산을 요청하세요.
            <button className="btn primary" onClick={() => go('calc')}>
              서버 계산 요청 →
            </button>
          </div>
        )}
      </section>

      {items.length > 0 && (
        <>
          {mismatch.length > 0 && (
            <div className="banner warn">
              비교 조건 불일치: {mismatch.join(', ')}이(가) 서로 다릅니다 — 정량 비교에 주의하세요.
            </div>
          )}

          <section className="card">
            <div className="card-head">
              <h2>전기화학 안정 전압 범위 (공통 축)</h2>
            </div>
            <VoltageWindowChart entries={allEntries} />
            <Legend entries={allEntries} />
          </section>

          <div className="grid-2">
            <section className="card">
              <div className="card-head">
                <h2>HOMO / LUMO (공통 축)</h2>
              </div>
              <HomoLumoChart entries={allEntries} />
              <Legend entries={allEntries} />
            </section>

            <section className="card">
              <div className="card-head">
                <h2>물성 지문 (고정 ★ 기준)</h2>
              </div>
              <FingerprintRadar entries={entries} pinKeys={pins} />
              <Legend entries={entries} />
            </section>
          </div>

          <section className="card">
            <div className="card-head">
              <h2>비교 표 — 고정(★) 물성 최상단</h2>
            </div>
            <div className="scroll-x">
              <table className="table">
                <thead>
                  <tr>
                    <th>물성</th>
                    <th>단위</th>
                    {items.map((i) => (
                      <th key={i.material.id} className="num">
                        {i.material.name.split(' ')[0]}
                        <div className="small muted mono">{i.job.id}</div>
                        <div className="small muted">
                          {solventById(i.job.settings.solventId)?.abbr ?? 'vacuum'} · v{i.job.structureVersion} ·{' '}
                          {i.job.result!.protocolId}
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rowKeys.map((key) => {
                    const def = descriptorByKey(key)!
                    const pinned = pins.includes(key)
                    return (
                      <tr key={key} className={pinned ? 'row-pinned' : ''}>
                        <td>
                          <button className={`pin-btn ${pinned ? 'on' : ''}`} onClick={() => dispatch({ type: 'togglePin', key })}>
                            ★
                          </button>{' '}
                          {def.label}
                        </td>
                        <td className="small muted">{def.unit}</td>
                        {items.map((i) => {
                          const dv = i.job.result!.descriptors[key]
                          return (
                            <td key={i.material.id} className="num mono">
                              {def.interfacial ? '—' : dv ? dv.value : '—'}
                            </td>
                          )
                        })}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <div className="chart-note">
              기본 비교는 validation PASSED + PUBLISHED 서버 계산값만 사용합니다. 검증 상태·프로토콜·작업 ID가
              각 열에 표시됩니다.
            </div>
          </section>
        </>
      )}
    </div>
  )
}
