import { useEffect, useState } from 'react'
import { useStore } from '../store'
import type { PageId } from '../App'
import type { CalcJob } from '../types'
import {
  ActiveMaterialPicker,
  EnergyLevelDiagram,
  HomoLumoChart,
  SurfaceAdhesionBars,
  VoltageWindowChart,
  refsByIds,
  seriesColor,
} from '../charts'
import { DEFAULT_REF_IDS } from '../data/activeMaterials'
import { descriptorByKey } from '../data/descriptors'
import { StatusBadge, fmtDate } from '../ui'
import { Molecule3D, type ColorMode } from '../structure/Molecule3D'
import { ConformerExplorer } from '../structure/ConformerExplorer'
import { InteractionExplorer } from '../structure/InteractionExplorer'
import { OrbitalViewer } from '../structure/OrbitalViewer'
import { IRUVSpectra } from '../structure/spectra'
import { representativeBonds } from '../structure/encyclopedia'
import { calcHint } from './Calc'

// 기획서 4.6 — 물질별 DFT 계산 결과 (우선순위 1~13 중 프론트 범위)
export function Results({ go, materialId }: { go: (p: PageId, mid?: string) => void; materialId: string | null }) {
  const store = useStore()
  const { materials, jobs, pins, compareIds, dispatch, materialById, solventById, publishedJobs } = store
  const [selectedId, setSelectedId] = useState(materialId ?? materials[0]?.id ?? '')
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [orbitalView, setOrbitalView] = useState<'range' | 'diagram'>('range')
  const [colorMode, setColorMode] = useState<ColorMode>('cpk')
  const [refIds, setRefIds] = useState<string[]>(DEFAULT_REF_IDS)
  const [structView, setStructView] = useState<'opt' | 'orbital' | 'conformer' | 'interaction'>('opt')

  useEffect(() => {
    if (materialId) setSelectedId(materialId)
  }, [materialId])

  const material = materialById(selectedId)
  const pubs = material ? publishedJobs(material.id) : []
  const currentPubs = pubs.filter((j) => j.structureVersion === material?.structureVersion)
  const job: CalcJob | undefined =
    (selectedJobId && pubs.find((j) => j.id === selectedJobId)) || currentPubs[0] || pubs[0]

  const otherJobs = material
    ? jobs
        .filter((j) => j.materialId === material.id && j.status !== 'PUBLISHED')
        .sort((a, b) => b.createdAt - a.createdAt)
    : []

  const downloadJson = () => {
    if (!material || !job?.result) return
    const solvent = solventById(job.settings.solventId)
    // 부록 B 결과 패키지 형식
    const pkg = {
      material: {
        id: material.id,
        name: material.name,
        structure_version: `v${job.structureVersion}`,
        structure_hash: job.result.structureHash,
        smiles: material.smiles,
      },
      job: { id: job.id, status: job.status, protocol_id: job.result.protocolId },
      provenance: {
        result_origin: 'SERVER_CALCULATION(모의 프로토타입)',
        validation_status: job.result.validationStatus,
        publication_status: 'PUBLISHED',
        created_at: new Date(job.finishedAt ?? job.createdAt).toISOString(),
      },
      conditions: {
        environment: job.settings.envType,
        solvent: solvent ? `${solvent.abbr} v${solvent.version}` : 'vacuum',
        temperature_k: job.settings.temperature,
        reference_electrode: job.settings.referenceElectrode,
        engine: job.settings.expert.engine,
        method: `${job.settings.expert.functional}/${job.settings.expert.basis}`,
      },
      descriptors: job.result.descriptors,
      validation_notes: job.result.validationNotes,
    }
    const blob = new Blob([JSON.stringify(pkg, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${job.id}.json`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  if (!material) {
    return (
      <div>
        <header className="page-head">
          <h1>DFT 계산 결과</h1>
        </header>
        <div className="empty card">등록된 물질이 없습니다.</div>
      </div>
    )
  }

  const d = job?.result?.descriptors
  const pinnedDefs = pins.map((k) => descriptorByKey(k)).filter((x): x is NonNullable<typeof x> => !!x)

  return (
    <div>
      <header className="page-head">
        <h1>DFT 계산 결과</h1>
        <p className="page-desc">검증을 통과해 공개(PUBLISHED)된 서버 계산값만 수치로 표시합니다</p>
      </header>

      <div className="toolbar">
        <select
          className="input grow"
          value={selectedId}
          onChange={(e) => {
            setSelectedId(e.target.value)
            setSelectedJobId(null)
          }}
        >
          {materials.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name} {publishedJobs(m.id).length ? `(공개 결과 ${publishedJobs(m.id).length})` : '(결과 없음)'}
            </option>
          ))}
        </select>
        <button
          className={`btn ${compareIds.includes(material.id) ? '' : 'primary'}`}
          onClick={() => dispatch({ type: 'toggleCompare', id: material.id })}
        >
          {compareIds.includes(material.id) ? '비교에서 제외' : '비교에 추가'}
        </button>
        <button className="btn" onClick={() => go('compare')}>
          물질 비교 →
        </button>
      </div>

      {!job && (
        <div className="empty card">
          이 물질의 PUBLISHED 결과가 없습니다. 미계산·실패·검증 보류 상태에서는 수치를 표시하지 않습니다.
          <button className="btn primary" onClick={() => go('calc', material.id)}>
            서버 계산 요청 →
          </button>
          {otherJobs.length > 0 && (
            <table className="table" style={{ marginTop: 10 }}>
              <tbody>
                {otherJobs.map((j) => (
                  <tr key={j.id}>
                    <td className="mono small">{j.id}</td>
                    <td>
                      <StatusBadge status={j.status} progress={j.progress} />
                    </td>
                    <td className="small muted">{j.status === 'NEEDS_REVIEW' ? j.result?.validationNotes.join(' / ') : j.stage}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {job && d && (
        <>
          {job.structureVersion !== material.structureVersion && (
            <div className="banner warn">
              이 결과는 이전 구조 v{job.structureVersion}에서 계산되었습니다 (현재 구조 v
              {material.structureVersion}). 현재 구조로 재계산을 권장합니다.
            </div>
          )}

          {/* 물성 고정 ★ — 결과 상단 (기획서 4.6 우선순위 12) */}
          {pinnedDefs.length > 0 && (
            <div className="stat-row">
              {pinnedDefs.map((def) => {
                const dv = d[def.key]
                return (
                  <div key={def.key} className="stat-tile pinned">
                    <div className="stat-label">
                      <span className="pin-star">★</span> {def.label}
                    </div>
                    <div className="stat-value">
                      {def.interfacial ? '—' : dv ? dv.value : '—'}
                      {dv && !def.interfacial && <span className="stat-unit"> {dv.unit}</span>}
                    </div>
                    <div className="stat-sub">{def.interfacial ? '실험·계면 조건 필요' : def.group}</div>
                  </div>
                )
              })}
            </div>
          )}

          <div className="grid-2">
            <section className="card">
              <div className="card-head">
                <h2>1. 전기화학 안정 전압 범위</h2>
                {job.baseJobId && <span className="muted small mono">기준 구조 {job.baseJobId}</span>}
              </div>
              {d.binder_oxidation_potential && d.binder_reduction_potential ? (
                <>
                  <ActiveMaterialPicker selected={refIds} onChange={setRefIds} />
                  <VoltageWindowChart
                    entries={[{ label: material.name.split(' ')[0], color: seriesColor(0), values: d }]}
                    refs={refsByIds(refIds)}
                  />
                  <div className="mini-cards">
                    <div className="mini-card">
                      <div className="stat-label">환원 한계</div>
                      <b>{d.binder_reduction_potential.value} {d.binder_reduction_potential.unit}</b>
                    </div>
                    <div className="mini-card">
                      <div className="stat-label">산화 한계</div>
                      <b>{d.binder_oxidation_potential.value} {d.binder_oxidation_potential.unit}</b>
                    </div>
                    <div className="mini-card">
                      <div className="stat-label">안정 window</div>
                      <b>{(d.binder_oxidation_potential.value - d.binder_reduction_potential.value).toFixed(2)} V</b>
                    </div>
                  </div>
                </>
              ) : (
                <div className="empty small">
                  이 결과는 1단계(전자구조·구조 최적화)까지만 계산되었습니다. 저장된 최적화 구조를 불러와
                  전기화학 안정성을 계산하세요.
                  <button
                    className="btn primary"
                    onClick={() => {
                      calcHint.purpose = '전기화학 안정성'
                      go('calc', material.id)
                    }}
                  >
                    이 구조로 2단계(전기화학 안정성) 계산 →
                  </button>
                </div>
              )}
            </section>

            <section className="card">
              <div className="card-head">
                <h2>2. HOMO / LUMO / gap</h2>
                <div className="seg">
                  <button className={orbitalView === 'range' ? 'on' : ''} onClick={() => setOrbitalView('range')}>
                    수평 축
                  </button>
                  <button className={orbitalView === 'diagram' ? 'on' : ''} onClick={() => setOrbitalView('diagram')}>
                    에너지 준위
                  </button>
                </div>
              </div>
              {orbitalView === 'range' ? (
                <HomoLumoChart
                  entries={[{ label: material.name.split(' ')[0], color: seriesColor(0), values: d }]}
                  refs={refsByIds(refIds)}
                />
              ) : (
                <EnergyLevelDiagram
                  entries={[{ label: material.name.split(' ')[0], color: seriesColor(0), values: d }]}
                  refs={refsByIds(refIds)}
                />
              )}
              <div className="chart-note">
                전자구조 경향의 보조 지표 — 전압 범위와 불일치할 수 있습니다 (기획서 6.1).
              </div>
            </section>
          </div>

          {d.binder_adhesion_si && (
            <section className="card">
              <div className="card-head">
                <h2>활물질 표면 흡착에너지</h2>
                <span className="muted small">표면 모델 고정(cluster) 전제의 보기용 값 — 부록 D 비교 규칙 적용</span>
              </div>
              <SurfaceAdhesionBars
                entries={[{ label: material.name.split(' ')[0], color: seriesColor(0), values: d }]}
              />
            </section>
          )}

          <section className="card">
            <div className="card-head">
              <h2>시각 요약 — 최적화 3D 구조</h2>
              <div className="row-actions">
                <div className="seg">
                  <button className={structView === 'opt' ? 'on' : ''} onClick={() => setStructView('opt')}>
                    최적 구조
                  </button>
                  <button className={structView === 'orbital' ? 'on' : ''} onClick={() => setStructView('orbital')}>
                    오비탈 · ESP 표면
                  </button>
                  <button className={structView === 'conformer' ? 'on' : ''} onClick={() => setStructView('conformer')}>
                    Conformer 탐색
                  </button>
                  <button className={structView === 'interaction' ? 'on' : ''} onClick={() => setStructView('interaction')}>
                    상호작용 · 거리
                  </button>
                </div>
                {structView === 'opt' && (
                  <div className="seg">
                    <button className={colorMode === 'cpk' ? 'on' : ''} onClick={() => setColorMode('cpk')}>
                      원소 (CPK)
                    </button>
                    <button className={colorMode === 'charge' ? 'on' : ''} onClick={() => setColorMode('charge')}>
                      부분전하 · MEP
                    </button>
                  </div>
                )}
              </div>
            </div>
            {structView === 'opt' && (
              <div className="visual-hero">
                <aside className="side-panel">
                  <div className="option-title">구조 · 에너지</div>
                  {representativeBonds(material.smiles).map((b) => (
                    <div key={b.label} className="fact-kv">
                      <span>
                        {b.label} ×{b.n}
                      </span>
                      <b>{b.len ? `${b.len} Å` : '—'}</b>
                    </div>
                  ))}
                  {(
                    [
                      ['binder_total_energy', 'E_elec'],
                      ['binder_zpe', 'ZPE'],
                      ['binder_gibbs_correction', 'G_corr(298K)'],
                      ['binder_entropy', 'S°(298K)'],
                      ['binder_lowest_frequency', '최저 진동수'],
                      ['binder_bde_weakest', '최약 BDE'],
                    ] as const
                  )
                    .filter(([k]) => d[k])
                    .map(([k, label]) => (
                      <div key={k} className="fact-kv">
                        <span>{label}</span>
                        <b>
                          {d[k].value} {d[k].unit}
                        </b>
                      </div>
                    ))}
                  <div className="chart-note">결합 길이 = 표준 문헌값 (실측 좌표는 백엔드 연동 시)</div>
                </aside>
                <div>
                  <Molecule3D smiles={material.smiles} colorMode={colorMode} height={380} />
                  <div className="chart-note">
                    구조 출처:{' '}
                    {job.baseJobId
                      ? `1단계 최적화 결과 ${job.baseJobId}에서 로드`
                      : `이 작업(${job.id})의 구조 최적화 결과`}
                    {colorMode === 'charge' &&
                      d.binder_meps_min_negative &&
                      ` · MEP 극값: ${d.binder_meps_min_negative.value} ~ ${d.binder_meps_max_positive?.value} kcal/mol`}
                  </div>
                </div>
                <aside className="side-panel">
                  <div className="option-title">전자구조 · 반응성</div>
                  {(
                    [
                      ['binder_homo', 'HOMO'],
                      ['binder_lumo', 'LUMO'],
                      ['binder_homo_lumo_gap', 'gap'],
                      ['binder_uv_lambda_max', 'UV λmax'],
                      ['binder_electrophilicity', '친전자성 ω'],
                      ['binder_chemical_hardness', '경도 η'],
                      ['binder_nbo_charge_cationic_site', 'NBO(+site)'],
                      ['binder_magnetic_susceptibility', '자화율 χm'],
                    ] as const
                  )
                    .filter(([k]) => d[k])
                    .map(([k, label]) => (
                      <div key={k} className="fact-kv">
                        <span>{label}</span>
                        <b>
                          {d[k].value} {d[k].unit}
                        </b>
                      </div>
                    ))}
                  {d.binder_uv_lambda_max && (
                    <div className="chart-note">
                      {d.binder_uv_lambda_max.value < 380 ? 'λmax < 380 nm → 무색 예상' : '가시광 흡수 → 유색 가능'}
                      {' · 반자성 (닫힌 껍질)'}
                    </div>
                  )}
                </aside>
              </div>
            )}
            {structView === 'orbital' && (
              <OrbitalViewer
                smiles={material.smiles}
                homo={d.binder_homo?.value}
                lumo={d.binder_lumo?.value}
                espRange={[d.binder_meps_min_negative?.value, d.binder_meps_max_positive?.value]}
              />
            )}
            {structView === 'conformer' && <ConformerExplorer smiles={material.smiles} />}
            {structView === 'interaction' && <InteractionExplorer smiles={material.smiles} descriptors={d} />}
          </section>

          <section className="card">
            <div className="card-head">
              <h2>분광 예측 (IR · UV-Vis)</h2>
              <span className="muted small">작용기 특성 진동수 · TD-DFT 근사 — 예측값</span>
            </div>
            <IRUVSpectra smiles={material.smiles} gap={d.binder_homo_lumo_gap?.value} />
          </section>

          <section className="card">
            <div className="card-head">
              <h2>3~4. 핵심 요약 카드</h2>
            </div>
            <div className="mini-cards wide">
              {(
                [
                  ['binder_ionization_energy', 'VIP'],
                  ['binder_electron_affinity', 'VEA'],
                  ['binder_dipole_moment', '쌍극자 모멘트'],
                  ['binder_meps_max_positive', 'MEP 최대 양전위'],
                  ['binder_meps_min_negative', 'MEP 최소 음전위'],
                  ['binder_li_binding_energy', 'Li⁺ 결합'],
                  ['binder_pf6_binding_energy', 'PF₆⁻ 결합'],
                  ['binder_si_binding_energy', 'Si 결합'],
                ] as const
              )
                .filter(([key]) => d[key])
                .map(([key, label]) => {
                  const dv = d[key]
                  return (
                    <div key={key} className="mini-card">
                      <div className="stat-label">{label}</div>
                      <b>
                        {dv.value} {dv.unit}
                      </b>
                    </div>
                  )
                })}
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>6. 계산 조건과 결과 상태</h2>
              <button className="btn ghost" onClick={downloadJson}>
                결과 패키지 JSON ↓
              </button>
            </div>
            <table className="kv-table">
              <tbody>
                <tr>
                  <th>작업 ID</th>
                  <td className="mono">{job.id}</td>
                  <th>validation_status</th>
                  <td>
                    <span className="badge published">{job.result!.validationStatus}</span>
                  </td>
                </tr>
                <tr>
                  <th>환경 / 용매</th>
                  <td>
                    {job.settings.envType} · {solventById(job.settings.solventId)?.abbr ?? 'vacuum'}
                  </td>
                  <th>온도 / 기준 전극</th>
                  <td>
                    {job.settings.temperature} K · {job.settings.referenceElectrode}
                  </td>
                </tr>
                <tr>
                  <th>엔진 / 방법</th>
                  <td>
                    {job.settings.expert.engine} · {job.settings.expert.functional}/{job.settings.expert.basis}
                  </td>
                  <th>프로토콜 / 구조</th>
                  <td className="mono">
                    {job.result!.protocolId} · v{job.structureVersion} · {job.result!.structureHash.slice(0, 18)}…
                  </td>
                </tr>
                <tr>
                  <th>계산 목적</th>
                  <td>{job.settings.purpose}</td>
                  <th>기준 구조</th>
                  <td className="mono">{job.baseJobId ?? '— (이 작업에서 최적화)'}</td>
                </tr>
              </tbody>
            </table>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>7. 이전 계산 이력</h2>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>작업 ID</th>
                  <th>구조</th>
                  <th>조건</th>
                  <th>상태</th>
                  <th>완료</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {[...pubs, ...otherJobs].map((j) => (
                  <tr key={j.id} className={j.id === job.id ? 'row-active' : ''}>
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
                      {solventById(j.settings.solventId)?.abbr ?? 'vacuum'} · {j.settings.expert.functional}/
                      {j.settings.expert.basis}
                    </td>
                    <td>
                      <StatusBadge status={j.status} progress={j.progress} />
                    </td>
                    <td className="small muted">{fmtDate(j.finishedAt)}</td>
                    <td>
                      {j.status === 'PUBLISHED' && j.id !== job.id && (
                        <button className="btn ghost" onClick={() => setSelectedJobId(j.id)}>
                          이 결과 보기
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  )
}
