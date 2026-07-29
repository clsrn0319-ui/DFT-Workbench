import { useEffect, useState } from 'react'
import { useStore } from '../store'
import type { Nav, PageId } from '../App'
import { DICTIONARY } from '../data/dictionary'
import { EXTERNAL_REFS } from '../data/externalRefs'
import { DESCRIPTOR_GROUPS, DESCRIPTORS } from '../data/descriptors'
import { Field, ReadyBadge, StatusBadge, Tabs, fmtDate } from '../ui'
import { Molecule2D } from '../structure/Molecule2D'
import { Molecule3D, type ColorMode } from '../structure/Molecule3D'
import { analyzeMolecule, deriveTrends, detectFunctionalGroups } from '../structure/encyclopedia'
import type { EncyData, Material } from '../types'

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
  const autoGroups = detectFunctionalGroups(material.smiles)
  const groups = autoGroups.length ? autoGroups : (dict?.functionalGroups ?? [])
  const trends = [...new Set([...deriveTrends(groups), ...(dict?.trends ?? [])])]
  const profile = analyzeMolecule(material.smiles)
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
            {groups.length ? (
              <ul className="fact-list">
                {groups.map((g) => (
                  <li key={g}>
                    <span className="chip soft">{g}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="empty small">인식된 작용기가 없습니다 (탄화수소 골격).</div>
            )}
            <div className="chart-note">
              작용기 자동 인식 — 구조 그래프 규칙 기반 (상용 버전은 RDKit SMARTS로 정밀화)
            </div>
            <div className="card-head" style={{ marginTop: 14 }}>
              <h2>해석 — 화학 규칙 기반 경향 (가설)</h2>
            </div>
            {trends.length ? (
              <ul className="fact-list plain">
                {trends.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            ) : (
              <div className="empty small">
                뚜렷한 극성·반응성 작용기가 없어 분산력 위주의 상호작용이 예상됩니다.
              </div>
            )}
          </section>
          <section className="card">
            <div className="card-head">
              <h2>계산 권고 — 불확실성을 줄일 계산</h2>
            </div>
            <ul className="fact-list plain">
              <li>MEP/부분전하 분석으로 전하 집중 부위 확인</li>
              <li>중성/양이온/음이온 상태 계산으로 산화·환원 한계 산출</li>
              {profile && profile.hba > 0 && <li>Li⁺ 배위 conformer 탐색 (O/N/F 배위 후보 {profile.hba}곳)</li>}
              {profile && profile.hbd > 0 && <li>binder-binder dimer 수소결합 에너지 계산 (공여 {profile.hbd}곳)</li>}
              {profile?.aromatic && <li>π–π 흡착 모티프 탐색 (흑연 표면)</li>}
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

      {tab === '구조 · 특징' && <Encyclopedia material={material} groups={groups} />}

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

// ── 백과 섹션 (구조·특징 탭 하단) — 조성·구조 / 결합 / 물리 / 반응성 / 기타 / 무기 관점 ──
// 출처 배지: [구조 계산] 자동 산출 · [문헌] 대표 참고값 · [사용자 입력] 직접 편집값 · [규칙] 화학 규칙 추론
type SourceKind = '구조 계산' | '문헌' | '사용자 입력' | '규칙'

function SourceChip({ kind }: { kind: SourceKind }) {
  const cls = kind === '문헌' ? 'badge overlay-badge' : kind === '사용자 입력' ? 'chip' : 'chip soft'
  return (
    <span className={cls} style={{ marginLeft: 6 }}>
      {kind}
    </span>
  )
}

function EncyRow({ label, value, source }: { label: string; value: React.ReactNode; source: SourceKind }) {
  if (value === undefined || value === null || value === '') return null
  return (
    <tr>
      <td style={{ width: 170 }}>
        {label}
        <SourceChip kind={source} />
      </td>
      <td>{value}</td>
    </tr>
  )
}

const ENCY_FIELDS: { key: keyof EncyData; label: string }[] = [
  { key: 'state', label: '상온 상태' },
  { key: 'bp', label: '끓는점' },
  { key: 'mp', label: '녹는점' },
  { key: 'density', label: '밀도' },
  { key: 'solubility', label: '용해성' },
  { key: 'acidBase', label: '산 · 염기 성질' },
  { key: 'reactivity', label: '안정성 · 중합성' },
  { key: 'isomers', label: '이성질체' },
  { key: 'optical', label: '색 · 광학' },
]

interface PubchemResult {
  status: 'loading' | 'ok' | 'error'
  message?: string
  props?: Record<string, string | number>
}

function Encyclopedia({ material, groups }: { material: Material; groups: string[] }) {
  const { dispatch } = useStore()
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<EncyData>({})
  const [pubchem, setPubchem] = useState<PubchemResult | null>(null)

  const profile = analyzeMolecule(material.smiles)
  const dict = material.dictId ? DICTIONARY.find((d) => d.dictId === material.dictId) : undefined
  const litEncy = dict?.ency
  const userEncy = material.userEncy

  // 사용자 입력 > 문헌 순으로 병합, 출처 추적
  const merged = (key: keyof EncyData): { value?: string; source: SourceKind } => {
    const u = userEncy?.[key]
    if (u && typeof u === 'string') return { value: u, source: '사용자 입력' }
    const l = litEncy?.[key]
    if (l && typeof l === 'string') return { value: l, source: '문헌' }
    return { value: undefined, source: '문헌' }
  }

  const startEdit = () => {
    const init: EncyData = {}
    for (const f of ENCY_FIELDS) {
      const v = userEncy?.[f.key] ?? litEncy?.[f.key]
      if (typeof v === 'string') (init[f.key] as string | undefined) = v
    }
    setForm(init)
    setEditing(true)
  }

  const saveEdit = () => {
    const cleaned: EncyData = {}
    for (const f of ENCY_FIELDS) {
      const v = (form[f.key] as string | undefined)?.trim()
      if (v) (cleaned[f.key] as string | undefined) = v
    }
    if (userEncy?.extra) cleaned.extra = userEncy.extra
    dispatch({ type: 'updateMaterial', id: material.id, structureChanged: false, patch: { userEncy: cleaned } })
    setEditing(false)
  }

  // PubChem PUG REST 조회 — 상용 버전은 백엔드 프록시가 캐시 (기획서 4.2.2)
  const fetchPubchem = async () => {
    setPubchem({ status: 'loading' })
    try {
      const url = `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/${encodeURIComponent(material.smiles)}/property/MolecularFormula,MolecularWeight,IUPACName,XLogP,TPSA,HBondDonorCount,HBondAcceptorCount,InChIKey/JSON`
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), 8000)
      const res = await fetch(url, { signal: controller.signal })
      clearTimeout(timer)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      const props = json?.PropertyTable?.Properties?.[0]
      if (!props) throw new Error('결과 없음')
      setPubchem({ status: 'ok', props })
    } catch (err) {
      setPubchem({
        status: 'error',
        message:
          '외부 조회 실패 (CORS·보안망 차단 또는 오프라인). 상용 버전에서는 백엔드 프록시가 PubChem을 조회·캐시하며, 조회 실패가 등록·수동 입력을 차단하지 않습니다.' +
          (err instanceof Error && err.name !== 'AbortError' ? '' : ' (시간 초과)'),
      })
    }
  }

  const applyPubchem = () => {
    if (pubchem?.status !== 'ok' || !pubchem.props) return
    const p = pubchem.props
    const lines = [
      p.IUPACName && `IUPAC명: ${p.IUPACName}`,
      p.InChIKey && `InChIKey: ${p.InChIKey}`,
      p.XLogP !== undefined && `XLogP: ${p.XLogP}`,
      p.TPSA !== undefined && `TPSA: ${p.TPSA} Å²`,
      p.HBondDonorCount !== undefined && `H-bond 공여/수용: ${p.HBondDonorCount}/${p.HBondAcceptorCount}`,
      'PubChem PUG REST 조회값',
    ].filter((x): x is string => !!x)
    dispatch({
      type: 'updateMaterial',
      id: material.id,
      structureChanged: false,
      patch: { userEncy: { ...(userEncy ?? {}), extra: lines } },
    })
  }

  if (!profile) {
    return <div className="empty card">구조를 해석할 수 없어 백과 정보를 생성하지 못했습니다: {material.smiles}</div>
  }

  const imf: string[] = []
  if (profile.isIonic) imf.push('이온성 상호작용')
  if (profile.hbd > 0) imf.push(`수소결합 (공여 ${profile.hbd} · 수용 ${profile.hba})`)
  else if (profile.hba > 0) imf.push(`수소결합 수용만 가능 (${profile.hba}곳)`)
  if (profile.polarityClass !== '무극성') imf.push('쌍극자-쌍극자 상호작용')
  imf.push('반데르발스(분산) 힘')

  const extraLines = [...(litEncy?.extra ?? []), ...(userEncy?.extra ?? [])]

  return (
    <>
      <div className="toolbar" style={{ marginTop: 4 }}>
        <span className="option-title" style={{ marginBottom: 0 }}>
          화학 백과 — 물질 상세 정보
        </span>
        <button className="btn" onClick={editing ? () => setEditing(false) : startEdit}>
          {editing ? '편집 닫기' : '문헌값 직접 입력 · 편집'}
        </button>
        <button className="btn" onClick={fetchPubchem} disabled={pubchem?.status === 'loading'}>
          {pubchem?.status === 'loading' ? 'PubChem 조회 중…' : 'PubChem 자동 조회'}
        </button>
      </div>

      {editing && (
        <section className="card form-card">
          <div className="card-head">
            <h2>문헌값 직접 입력 · 편집</h2>
            <span className="muted small">저장 시 [사용자 입력] 출처로 표시되며 문헌값보다 우선합니다</span>
          </div>
          <div className="form-grid">
            {ENCY_FIELDS.map((f) => (
              <Field key={f.key} label={f.label}>
                <input
                  className="input"
                  value={(form[f.key] as string | undefined) ?? ''}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                />
              </Field>
            ))}
          </div>
          <div className="form-actions">
            <button className="btn primary" onClick={saveEdit}>
              저장
            </button>
            <button className="btn" onClick={() => setEditing(false)}>
              취소
            </button>
          </div>
        </section>
      )}

      {pubchem?.status === 'error' && <div className="banner warn">{pubchem.message}</div>}
      {pubchem?.status === 'ok' && pubchem.props && (
        <section className="card">
          <div className="card-head">
            <h2>PubChem 조회 결과</h2>
            <div className="row-actions">
              <span className="badge overlay-badge">PubChem PUG REST</span>
              <button className="btn ghost" onClick={applyPubchem}>
                백과 참고값에 반영
              </button>
            </div>
          </div>
          <table className="kv-table">
            <tbody>
              <tr>
                <th>IUPAC명</th>
                <td>{pubchem.props.IUPACName ?? '—'}</td>
                <th>InChIKey</th>
                <td className="mono">{pubchem.props.InChIKey ?? '—'}</td>
              </tr>
              <tr>
                <th>분자식 / MW</th>
                <td>
                  {pubchem.props.MolecularFormula} · {pubchem.props.MolecularWeight} g/mol
                </td>
                <th>XLogP / TPSA</th>
                <td>
                  {pubchem.props.XLogP ?? '—'} · {pubchem.props.TPSA ?? '—'} Å²
                </td>
              </tr>
            </tbody>
          </table>
          <div className="chart-note">
            끓는점·녹는점 등 실험 물성 전문(PUG View)은 상용 버전의 서버 프록시가 조회·캐시합니다.
          </div>
        </section>
      )}

      <details className="expert" open>
        <summary>1 · 2 — 조성과 구조 / 결합의 성질</summary>
      <div className="grid-2">
        <section className="card">
          <div className="card-head">
            <h2>1. 조성과 구조</h2>
          </div>
          <table className="table">
            <tbody>
              <EncyRow label="분자식" value={<span className="mono">{profile.formula}</span>} source="구조 계산" />
              <EncyRow label="분자량" value={`${profile.mw} g/mol`} source="구조 계산" />
              <EncyRow
                label="원소 조성"
                value={Object.entries(profile.elementCounts)
                  .map(([e, n]) => `${e} ${n}개`)
                  .join(' · ')}
                source="구조 계산"
              />
              <EncyRow
                label="결합 방식"
                value={`단일 ${profile.bondCounts.single} · 이중 ${profile.bondCounts.double} · 삼중 ${profile.bondCounts.triple}${profile.aromatic ? ' · 방향족 고리 포함' : ''}`}
                source="구조 계산"
              />
              <EncyRow
                label="고리 구조"
                value={profile.ringClosures > 0 ? `고리 ${profile.ringClosures}개${profile.aromatic ? ' (방향족 포함)' : ' (지방족)'}` : '비고리(사슬형)'}
                source="구조 계산"
              />
              <EncyRow label="불포화도 (DBE)" value={profile.dbe} source="구조 계산" />
              <EncyRow label="작용기" value={groups.join(', ') || '없음 (탄화수소)'} source="구조 계산" />
              <EncyRow label="이성질체" value={merged('isomers').value} source={merged('isomers').source} />
              <EncyRow
                label="입체 표기"
                value={profile.hasStereoNotation ? 'SMILES에 입체 표기 포함 (@ / cis-trans)' : '표기된 입체중심 없음'}
                source="구조 계산"
              />
            </tbody>
          </table>
        </section>

        <section className="card">
          <div className="card-head">
            <h2>2. 결합의 성질</h2>
          </div>
          <table className="table">
            <tbody>
              <EncyRow
                label="극성 결합"
                value={
                  profile.polarBonds.length
                    ? profile.polarBonds.map((b) => `${b.label} ×${b.count} (ΔEN ${b.dEN})`).join(' · ')
                    : '유의미한 극성 결합 없음 (ΔEN < 0.5)'
                }
                source="구조 계산"
              />
              <EncyRow
                label="분자 전체 극성"
                value={`${profile.polarityClass} — 결합 극성과 기하 구조의 벡터 합 (근사 Σq·r = ${profile.dipoleApprox})`}
                source="규칙"
              />
              <EncyRow
                label="공명 · 공액"
                value={
                  profile.aromatic
                    ? '방향족 고리 — 고리형 공액 (휘켈 규칙 안정화)'
                    : profile.conjugated
                      ? '공액계 존재 (sp² 연결 ≥ 3) — 전자 비편재화'
                      : '국소화된 결합 (뚜렷한 공액 없음)'
                }
                source="구조 계산"
              />
              <EncyRow
                label="혼성화 분포"
                value={`sp³ ${profile.hybridization.sp3} · sp² ${profile.hybridization.sp2} · sp ${profile.hybridization.sp}`}
                source="구조 계산"
              />
              <EncyRow
                label="결합 유형"
                value={profile.isIonic ? '공유결합 + 이온결합 (형식전하/염 포함)' : '공유결합'}
                source="구조 계산"
              />
            </tbody>
          </table>
        </section>
      </div>

      </details>

      <details className="expert">
        <summary>3 · 4 — 물리적 특성 / 반응성</summary>
      <div className="grid-2">
        <section className="card">
          <div className="card-head">
            <h2>3. 물리적 특성</h2>
          </div>
          <table className="table">
            <tbody>
              <EncyRow label="상온 상태" value={merged('state').value} source={merged('state').source} />
              <EncyRow label="끓는점" value={merged('bp').value} source={merged('bp').source} />
              <EncyRow label="녹는점" value={merged('mp').value} source={merged('mp').source} />
              <EncyRow label="밀도" value={merged('density').value} source={merged('density').source} />
              <EncyRow label="용해성" value={merged('solubility').value} source={merged('solubility').source} />
              <EncyRow label="분자간 힘" value={imf.join(' → ')} source="규칙" />
              <EncyRow
                label="친수/소수성"
                value={
                  profile.isIonic || profile.hbd > 0
                    ? '친수성 경향 (H-bond 공여/이온성)'
                    : profile.polarityClass === '무극성'
                      ? '소수성 경향'
                      : '중간 극성 — 극성 유기용매 친화'
                }
                source="규칙"
              />
              {!merged('bp').value && !merged('state').value && (
                <tr>
                  <td colSpan={2} className="muted small">
                    문헌 참고값이 아직 없습니다 — 위의 「문헌값 직접 입력 · 편집」 또는 「PubChem 자동 조회」로
                    채울 수 있습니다.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>

        <section className="card">
          <div className="card-head">
            <h2>4. 반응성</h2>
          </div>
          <table className="table">
            <tbody>
              <EncyRow label="산 · 염기 성질" value={merged('acidBase').value} source={merged('acidBase').source} />
              <EncyRow
                label="친전자성 / 친핵성 부위"
                value={
                  profile.hba > 0 || profile.polarBonds.length
                    ? 'O/N 고립전자쌍 부근 = 친핵성(전자 공여) 후보 · 카보닐 C/전자결핍 C = 친전자성 후보 — MEP 시각화(3D 전하 모드)로 확인'
                    : '뚜렷한 극성 부위 없음 — 라디칼/π 반응 중심 위주'
                }
                source="규칙"
              />
              <EncyRow label="안정성 · 중합성" value={merged('reactivity').value} source={merged('reactivity').source} />
              <EncyRow label="라디칼 여부" value="닫힌 껍질(모든 전자 짝지음) — 라디칼 아님" source="규칙" />
            </tbody>
          </table>
        </section>
      </div>

      </details>

      <details className="expert">
        <summary>5 · 6 — 기타 특성 / 무기·배위화학 관점</summary>
      <div className="grid-2">
        <section className="card">
          <div className="card-head">
            <h2>5. 기타 특성 (광학 · 자성)</h2>
          </div>
          <table className="table">
            <tbody>
              <EncyRow label="색 · 광학" value={merged('optical').value} source={merged('optical').source} />
              <EncyRow
                label="흡광 경향"
                value={
                  profile.aromatic
                    ? '방향족 π→π* 전이 — UV 영역 흡수'
                    : profile.conjugated
                      ? '공액계 — UV 흡수 가능 (n→π*, π→π*)'
                      : '뚜렷한 발색단 없음 — 가시광 무색 예상'
                }
                source="규칙"
              />
              <EncyRow label="자성" value="반자성 (홀전자 없음 — 닫힌 껍질)" source="규칙" />
              <EncyRow
                label="카이랄성"
                value={profile.hasStereoNotation ? '입체 표기 존재 — 광학 이성질체 검토 필요' : '표기된 카이랄 중심 없음'}
                source="구조 계산"
              />
            </tbody>
          </table>
        </section>

        <section className="card">
          <div className="card-head">
            <h2>6. 무기·배위화학 관점</h2>
          </div>
          <table className="table">
            <tbody>
              <EncyRow
                label="배위 가능 원자 (Li⁺ 등)"
                value={
                  profile.donorAtoms.length
                    ? profile.donorAtoms.map((d) => `${d.element}: ${d.hsab}`).join(' · ')
                    : '고립전자쌍 도너 원자 없음 — 배위 능력 낮음'
                }
                source="규칙"
              />
              <EncyRow
                label="HSAB 관점"
                value={
                  profile.donorAtoms.some((d) => d.element === 'O' || d.element === 'F')
                    ? 'Li⁺(경질 산)와 O/F(경질 염기)의 친화 — 전해액 내 배위 경쟁에 참여'
                    : profile.donorAtoms.length
                      ? '경계~연질 염기 중심 — Li⁺ 배위는 상대적으로 약함'
                      : '해당 없음'
                }
                source="규칙"
              />
              {extraLines.map((x) => (
                <EncyRow key={x} label="추가 참고" value={x} source={userEncy?.extra?.includes(x) ? '사용자 입력' : '문헌'} />
              ))}
            </tbody>
          </table>
          <div className="chart-note">
            [구조 계산] = SMILES 그래프에서 자동 산출 · [문헌] = 대표 참고값(조건에 따라 변동) · [사용자 입력] =
            직접 편집값(문헌값보다 우선) · [규칙] = 화학 규칙 기반 추론(가설). DFT 계산과 무관한 백과 정보로,
            물성 비교·보고서에는 포함되지 않습니다.
          </div>
        </section>
      </div>
      </details>
    </>
  )
}
