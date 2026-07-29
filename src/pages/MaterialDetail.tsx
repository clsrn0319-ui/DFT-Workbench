import { useEffect, useState } from 'react'
import { useStore } from '../store'
import type { Nav, PageId } from '../App'
import { DICTIONARY } from '../data/dictionary'
import { EXTERNAL_REFS } from '../data/externalRefs'
import { DESCRIPTOR_GROUPS, DESCRIPTORS } from '../data/descriptors'
import { ReadyBadge, StatusBadge, Tabs, fmtDate } from '../ui'
import { Molecule2D } from '../structure/Molecule2D'
import { Molecule3D, type ColorMode } from '../structure/Molecule3D'

// 기획서 4.3 + 12장 — 개인 화학 물성 페이지
export function MaterialDetail({ go, materialId }: { go: (p: PageId, mid?: string) => void; materialId: string | null } & Partial<Nav>) {
  const store = useStore()
  const { materials, jobs, pins, dispatch, latestPublished } = store
  const [selectedId, setSelectedId] = useState(materialId ?? materials[0]?.id ?? '')
  const [tab, setTab] = useState('구조 · 특징')
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d')
  const [colorMode, setColorMode] = useState<ColorMode>('cpk')

  useEffect(() => {
    if (materialId) setSelectedId(materialId)
  }, [materialId])

  const material = materials.find((m) => m.id === selectedId)

  useEffect(() => {
    if (material) dispatch({ type: 'viewMaterial', id: material.id })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [material?.id])

  if (!material) {
    return (
      <div>
        <header className="page-head">
          <h1>분자 물성</h1>
        </header>
        <div className="empty card">
          등록된 물질이 없습니다.
          <button className="btn primary" onClick={() => go('library')}>
            물질 보관함으로 이동
          </button>
        </div>
      </div>
    )
  }

  const dict = material.dictId ? DICTIONARY.find((d) => d.dictId === material.dictId) : undefined
  const pub = latestPublished(material.id)
  const refs = material.dictId ? EXTERNAL_REFS.filter((r) => r.dictId === material.dictId) : []
  const materialJobs = jobs.filter((j) => j.materialId === material.id).sort((a, b) => b.createdAt - a.createdAt)

  return (
    <div>
      <header className="page-head">
        <h1>분자 물성</h1>
        <p className="page-desc">분자 고유 특징과 계산·외부·실험 정보를 출처와 함께 한 페이지에서 탐색합니다</p>
      </header>

      <div className="toolbar">
        <select className="input grow" value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
          {materials.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
        <button className="btn" onClick={() => go('calc', material.id)}>
          이 물질 계산 →
        </button>
        <button className="btn" onClick={() => go('results', material.id)}>
          DFT 결과 →
        </button>
      </div>

      {/* 상단 식별 영역 (기획서 12.5) */}
      <section className="card ident-card">
        <div className="ident-main">
          <h2>{material.name}</h2>
          <div className="ident-row">
            <span className="chip">{material.type}</span>
            <span className="chip">{material.originType}</span>
            <ReadyBadge state={material.readyState} />
            {material.tags.map((t) => (
              <span key={t} className="chip soft">
                {t}
              </span>
            ))}
          </div>
          <table className="kv-table">
            <tbody>
              <tr>
                <th>CAS No.</th>
                <td className="mono">{material.casNo || '미부여'}</td>
                <th>분자식</th>
                <td className="mono">{material.formula || '—'}</td>
              </tr>
              <tr>
                <th>SMILES</th>
                <td className="mono" colSpan={3}>
                  {material.smiles}
                </td>
              </tr>
              <tr>
                <th>분자량</th>
                <td>{material.mw ? `${material.mw} g/mol` : '—'}</td>
                <th>구조 버전</th>
                <td>
                  v{material.structureVersion} · 외부 DB {refs.length ? `매칭 ${refs.length}건` : '매칭 없음'}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="structure-thumb">
          <div className="structure-toolbar">
            <div className="seg">
              <button className={viewMode === '2d' ? 'on' : ''} onClick={() => setViewMode('2d')}>
                2D
              </button>
              <button className={viewMode === '3d' ? 'on' : ''} onClick={() => setViewMode('3d')}>
                3D
              </button>
            </div>
            {viewMode === '3d' && (
              <div className="seg">
                <button className={colorMode === 'cpk' ? 'on' : ''} onClick={() => setColorMode('cpk')}>
                  원소
                </button>
                <button className={colorMode === 'charge' ? 'on' : ''} onClick={() => setColorMode('charge')}>
                  전하
                </button>
              </div>
            )}
          </div>
          {viewMode === '2d' ? (
            <Molecule2D smiles={material.smiles} height={190} />
          ) : (
            <Molecule3D smiles={material.smiles} colorMode={colorMode} height={220} />
          )}
        </div>
      </section>

      <Tabs
        tabs={['구조 · 특징', 'Descriptor', '외부 참고', '이력']}
        active={tab}
        onChange={setTab}
      />

      {tab === '구조 · 특징' && (
        <div className="grid-2">
          <section className="card">
            <div className="card-head">
              <h2>관찰 — 구조에서 직접 확인되는 사실</h2>
            </div>
            {dict ? (
              <ul className="fact-list">
                {dict.functionalGroups.map((g) => (
                  <li key={g}>
                    <span className="chip soft">{g}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="empty small">
                내장 사전에 없는 구조입니다. 작용기 자동 인식(SMARTS)은 상용 버전의 RDKit 서버에서 수행됩니다.
              </div>
            )}
            <div className="card-head" style={{ marginTop: 14 }}>
              <h2>해석 — 화학 규칙 기반 경향 (가설)</h2>
            </div>
            {dict?.trends.length ? (
              <ul className="fact-list plain">
                {dict.trends.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            ) : (
              <div className="empty small">해석 근거가 준비되지 않았습니다.</div>
            )}
          </section>
          <section className="card">
            <div className="card-head">
              <h2>계산 권고 — 불확실성을 줄일 계산</h2>
            </div>
            <ul className="fact-list plain">
              <li>MEP/부분전하 분석으로 전하 집중 부위 확인</li>
              <li>중성/양이온/음이온 상태 계산으로 산화·환원 한계 산출</li>
              {dict && dict.base.hba > 0 && <li>Li⁺ 배위 conformer 탐색 (배위 후보 {dict.base.hba}곳)</li>}
              {dict && dict.base.hbd > 0 && <li>binder-binder dimer 수소결합 에너지 계산</li>}
            </ul>
            <div className="card-head" style={{ marginTop: 14 }}>
              <h2>주의 — 구조만으로 확정 불가</h2>
            </div>
            <ul className="fact-list plain caution">
              <li>제타 전위·표면 전하 밀도 (계면 모델·실험 조건 필요)</li>
              <li>실제 점도·장기 전기화학 분해 경로</li>
              {dict?.cautions.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </section>
        </div>
      )}

      {tab === 'Descriptor' && (
        <section className="card">
          <div className="card-head">
            <h2>DFT descriptor — 7개 그룹</h2>
            <span className="muted small">
              ★ = 물성 고정 (결과 상단·비교 표·레이더 동기화) · 값은 PUBLISHED 결과에서만 표시
            </span>
          </div>
          {DESCRIPTOR_GROUPS.map((group) => {
            const list = DESCRIPTORS.filter((d) => d.group === group)
            return (
              <div key={group} className="desc-group">
                <h3>{group}</h3>
                <table className="table">
                  <tbody>
                    {list.map((d) => {
                      const dv = pub?.result?.descriptors[d.key]
                      return (
                        <tr key={d.key}>
                          <td style={{ width: 30 }}>
                            <button
                              className={`pin-btn ${pins.includes(d.key) ? 'on' : ''}`}
                              title="물성 고정"
                              onClick={() => dispatch({ type: 'togglePin', key: d.key })}
                            >
                              ★
                            </button>
                          </td>
                          <td>
                            {d.label}
                            <div className="small muted">{d.definition}</div>
                          </td>
                          <td className="num mono">
                            {d.interfacial ? (
                              <span className="badge queued">실험·계면 조건 필요</span>
                            ) : dv ? (
                              `${dv.value} ${dv.unit}`
                            ) : (
                              <span className="badge queued">미계산</span>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )
          })}
          {!pub && (
            <div className="banner warn">
              이 물질의 PUBLISHED 계산 결과가 없어 수치를 표시하지 않습니다.{' '}
              <button className="btn ghost" onClick={() => go('calc', material.id)}>
                서버 계산 요청 →
              </button>
            </div>
          )}
        </section>
      )}

      {tab === '외부 참고' && (
        <section className="card">
          <div className="card-head">
            <h2>외부 데이터 — 참고 계층</h2>
            <span className="muted small">내부 서버 계산값을 대체하지 않습니다 (기획서 12.7)</span>
          </div>
          {refs.length ? (
            refs.map((r) => (
              <div key={r.sourceId} className="ref-block">
                <div className="ref-head">
                  <span className="badge overlay-badge">{r.source}</span>
                  <span className="mono small">{r.sourceId}</span>
                  <span className="small muted">
                    {r.method} · {r.solvent} · 조회 {r.retrievedAt}
                  </span>
                </div>
                <table className="table">
                  <tbody>
                    {Object.entries(r.values).map(([k, v]) => {
                      const def = DESCRIPTORS.find((d) => d.key === k)
                      return (
                        <tr key={k}>
                          <td>{def?.label ?? k}</td>
                          <td className="num mono">
                            {v.value} {v.unit}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ))
          ) : (
            <div className="empty small">
              외부 계산값 없음 — MPcules/PubChem에서 일치 구조를 찾지 못했습니다. 내부 서버 계산을 요청하세요.
            </div>
          )}
        </section>
      )}

      {tab === '이력' && (
        <section className="card">
          <div className="card-head">
            <h2>편집 · 계산 이력</h2>
          </div>
          {materialJobs.length ? (
            <table className="table">
              <thead>
                <tr>
                  <th>작업 ID</th>
                  <th>구조</th>
                  <th>조건</th>
                  <th>상태</th>
                  <th>시각</th>
                </tr>
              </thead>
              <tbody>
                {materialJobs.map((j) => (
                  <tr key={j.id}>
                    <td className="mono small">{j.id}</td>
                    <td className="small">
                      v{j.structureVersion}
                      {j.structureVersion !== material.structureVersion && (
                        <span className="badge queued" style={{ marginLeft: 6 }}>
                          이전 구조
                        </span>
                      )}
                    </td>
                    <td className="small muted">
                      {j.settings.envType} · {j.settings.expert.functional}/{j.settings.expert.basis}
                    </td>
                    <td>
                      <StatusBadge status={j.status} progress={j.progress} />
                    </td>
                    <td className="small muted">{fmtDate(j.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty small">계산 이력이 없습니다.</div>
          )}
          {material.note && (
            <>
              <div className="card-head" style={{ marginTop: 12 }}>
                <h2>사용자 메모</h2>
              </div>
              <p>{material.note}</p>
            </>
          )}
        </section>
      )}
    </div>
  )
}
