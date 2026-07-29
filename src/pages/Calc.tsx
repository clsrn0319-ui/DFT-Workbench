import { useEffect, useState } from 'react'
import { DEFAULT_SETTINGS, makeJob, useStore } from '../store'
import type { PageId } from '../App'
import type { AccuracyLevel, CalcPurpose, CalcSettings, CalcStructure, EnvType } from '../types'
import { Field, StatusBadge, Tabs, fmtDate } from '../ui'

const ENV_TYPES: { id: EnvType; desc: string }[] = [
  { id: '배터리 전해액', desc: 'implicit/혼합 용매 · 298.15 K · Li/Li⁺ · 중성/양이온/음이온' },
  { id: '진공·기체', desc: 'vacuum · isolated molecule · 분자 자체 전자구조' },
  { id: '고체·주기계', desc: 'CP2K · periodic boundary · 올리고머/고체 후보' },
  { id: '사용자 정의', desc: '환경·엔진·정확도·전극 기준 직접 선택' },
]

const STRUCTURES: CalcStructure[] = ['모노머', '2량체', '3량체', '사용자 구조']
const ACCURACY: { id: AccuracyLevel; desc: string }[] = [
  { id: '빠름', desc: 'conformer 10 · 느슨한 수렴 — 사전 스크리닝' },
  { id: '표준', desc: 'conformer 30 · PBE0-D3(BJ)/def2-TZVP — 권장 기본' },
  { id: '정밀', desc: 'conformer 50 · tight 수렴 · 상위 basis 재확인' },
]

const PURPOSES: { id: CalcPurpose; step: string; desc: string }[] = [
  {
    id: '전자구조(구조 최적화)',
    step: '1단계',
    desc: 'conformer→xTB→DFT로 최적 구조를 찾고 HOMO/LUMO·MEP·쌍극자를 산출. 최적화 구조 저장',
  },
  {
    id: '전기화학 안정성',
    step: '2단계',
    desc: '1단계에서 공개된 최적화 구조를 불러와 중성/양이온/음이온 계산 — 전위·열화학·결합에너지 산출',
  },
  {
    id: '전체 계산',
    step: '일괄',
    desc: '두 단계를 한 번에 수행 (1단계 결과 재사용 없이 전체 파이프라인 실행)',
  },
]

// 결과 화면 등에서 "이 구조로 2단계 계산" 진입 시 목적을 미리 지정하는 힌트
export const calcHint: { purpose?: CalcPurpose } = {}

// 기획서 4.5 — 기본 화면 / 자동 처리·경고 / 전문 계산 설정(접힘)
export function Calc({ go, materialId }: { go: (p: PageId, mid?: string) => void; materialId: string | null }) {
  const store = useStore()
  const { materials, solvents, jobs, dispatch, materialById, solventById } = store
  const [tab, setTab] = useState('간편 설정')
  const [selected, setSelected] = useState<string[]>(materialId ? [materialId] : [])
  const [settings, setSettings] = useState<CalcSettings>(() => {
    const purpose = calcHint.purpose
    calcHint.purpose = undefined
    return purpose ? { ...DEFAULT_SETTINGS, purpose } : DEFAULT_SETTINGS
  })
  const [expertOpen, setExpertOpen] = useState(false)
  const [submitted, setSubmitted] = useState(0)

  useEffect(() => {
    if (materialId && !selected.includes(materialId)) setSelected((s) => [...s, materialId])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [materialId])

  const toggle = (id: string) =>
    setSelected((sel) => (sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]))

  // 2단계 계산의 기준 구조: 현재 구조 버전에서 공개된 1단계(또는 전체) 결과 중 최신
  const baseFor = (id: string) => {
    const m = materialById(id)
    return jobs
      .filter(
        (j) =>
          j.materialId === id &&
          j.status === 'PUBLISHED' &&
          j.structureVersion === m?.structureVersion &&
          j.settings.purpose !== '전기화학 안정성',
      )
      .sort((a, b) => (b.finishedAt ?? 0) - (a.finishedAt ?? 0))[0]
  }

  const isStage2 = settings.purpose === '전기화학 안정성'

  const warnings: string[] = []
  for (const id of selected) {
    const m = materialById(id)
    if (!m) continue
    if (m.smiles.includes('.')) warnings.push(`${m.name}: 다중 fragment (이온쌍) — 계산 대상 상태 확인 필요`)
    if (m.readyState === 'Needs decision') warnings.push(`${m.name}: 준비 상태 'Needs decision' — 구조 확인 권장`)
    if (isStage2 && !baseFor(id))
      warnings.push(
        `${m.name}: 1단계(전자구조·구조 최적화) 공개 결과가 없어 제출에서 제외됩니다 — 먼저 1단계를 계산하세요.`,
      )
  }
  if (settings.envType === '배터리 전해액' && !settings.solventId)
    warnings.push('배터리 전해액 환경에는 용매 프리셋 선택이 필요합니다.')

  const submittable = isStage2 ? selected.filter((id) => baseFor(id)) : selected

  const submit = () => {
    const jobsToAdd = submittable
      .map((id) => materialById(id))
      .filter((m): m is NonNullable<typeof m> => !!m)
      .map((m) => makeJob(m, settings, isStage2 ? baseFor(m.id)?.id : undefined))
    dispatch({ type: 'submitJobs', jobs: jobsToAdd })
    setSubmitted(jobsToAdd.length)
    setSelected([])
    setTab('작업 상태')
  }

  const activeJobs = [...jobs].sort((a, b) => b.createdAt - a.createdAt)

  return (
    <div>
      <header className="page-head">
        <h1>구조 최적화 · DFT</h1>
        <p className="page-desc">
          환경을 선택하면 구조 검증 · conformer · xTB · DFT 프리셋이 자동 적용됩니다. 상세값은 전문 계산
          설정에서만 수정합니다
        </p>
      </header>

      <Tabs tabs={['간편 설정', '작업 상태']} active={tab} onChange={setTab} />

      {tab === '간편 설정' && (
        <>
          {submitted > 0 && (
            <div className="banner success">
              작업 {submitted}건이 큐에 제출되었습니다. 작업 상태 탭에서 진행을 확인하세요.
            </div>
          )}
          <section className="card">
            <div className="card-head">
              <h2>1. 대상 물질</h2>
              <span className="muted small">{selected.length}개 선택</span>
            </div>
            <div className="mol-grid">
              {materials.map((m) => (
                <button
                  key={m.id}
                  className={`mol-card ${selected.includes(m.id) ? 'selected' : ''}`}
                  onClick={() => toggle(m.id)}
                >
                  <b>{m.name}</b>
                  <span className="mono small muted ellipsis">{m.smiles}</span>
                  <span className="small muted">구조 v{m.structureVersion}</span>
                </button>
              ))}
            </div>
          </section>

          <div className="grid-2">
            <section className="card">
              <div className="card-head">
                <h2>2. 환경</h2>
              </div>
              <div className="option-group">
                <div className="option-title">환경 유형</div>
                {ENV_TYPES.map((e) => (
                  <label key={e.id} className="radio-row">
                    <input
                      type="radio"
                      name="env"
                      checked={settings.envType === e.id}
                      onChange={() => setSettings({ ...settings, envType: e.id, solventId: e.id === '진공·기체' ? null : settings.solventId ?? 'sol-ecdmc' })}
                    />
                    <b>{e.id}</b>
                    <span className="muted small">{e.desc}</span>
                  </label>
                ))}
              </div>
              <div className="form-grid">
                <Field label="용매 프리셋">
                  <select
                    className="input"
                    value={settings.solventId ?? ''}
                    disabled={settings.envType === '진공·기체'}
                    onChange={(e) => setSettings({ ...settings, solventId: e.target.value || null })}
                  >
                    <option value="">(용매 없음)</option>
                    {solvents.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.abbr} v{s.version} {s.kind === 'mixed' ? '(혼합)' : ''}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="온도 (K)">
                  <input
                    className="input"
                    type="number"
                    value={settings.temperature}
                    onChange={(e) => setSettings({ ...settings, temperature: parseFloat(e.target.value) || 298.15 })}
                  />
                </Field>
                <Field label="분위기">
                  <select
                    className="input"
                    value={settings.atmosphere}
                    onChange={(e) => setSettings({ ...settings, atmosphere: e.target.value as CalcSettings['atmosphere'] })}
                  >
                    <option>불활성</option>
                    <option>공기</option>
                    <option>사용자 정의</option>
                  </select>
                </Field>
                <Field label="기준 전극">
                  <select
                    className="input"
                    value={settings.referenceElectrode}
                    onChange={(e) => setSettings({ ...settings, referenceElectrode: e.target.value as CalcSettings['referenceElectrode'] })}
                  >
                    <option>Li/Li+</option>
                    <option>SHE</option>
                  </select>
                </Field>
              </div>
              <button className="btn ghost" onClick={() => go('solvents')}>
                용매 라이브러리 관리 →
              </button>
            </section>

            <section className="card">
              <div className="card-head">
                <h2>3. 구조 · 정확도 · 목적</h2>
              </div>
              <div className="form-grid">
                <Field label="계산 구조">
                  <select
                    className="input"
                    value={settings.structure}
                    onChange={(e) => setSettings({ ...settings, structure: e.target.value as CalcStructure })}
                  >
                    {STRUCTURES.map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </Field>
              </div>
              <div className="option-group" style={{ marginTop: 12 }}>
                <div className="option-title">계산 목적 — 2단계 흐름</div>
                {PURPOSES.map((p) => (
                  <label key={p.id} className="radio-row">
                    <input
                      type="radio"
                      name="purpose"
                      checked={settings.purpose === p.id}
                      onChange={() => setSettings({ ...settings, purpose: p.id })}
                    />
                    <span className="chip">{p.step}</span>
                    <b>{p.id}</b>
                    <span className="muted small">{p.desc}</span>
                  </label>
                ))}
              </div>
              <div className="option-group">
                <div className="option-title">최적화 수준</div>
                {ACCURACY.map((a) => (
                  <label key={a.id} className="radio-row">
                    <input
                      type="radio"
                      name="acc"
                      checked={settings.accuracy === a.id}
                      onChange={() => setSettings({ ...settings, accuracy: a.id })}
                    />
                    <b>{a.id}</b>
                    <span className="muted small">{a.desc}</span>
                  </label>
                ))}
              </div>

              <details className="expert" open={expertOpen} onToggle={(e) => setExpertOpen((e.target as HTMLDetailsElement).open)}>
                <summary>전문 계산 설정 (검증된 프리셋 기본 적용 — 필요 시에만 수정)</summary>
                <div className="form-grid" style={{ marginTop: 10 }}>
                  <Field label="전하">
                    <input
                      className="input"
                      type="number"
                      value={settings.expert.charge}
                      onChange={(e) => setSettings({ ...settings, expert: { ...settings.expert, charge: parseInt(e.target.value) || 0 } })}
                    />
                  </Field>
                  <Field label="스핀 다중도">
                    <input
                      className="input"
                      type="number"
                      min={1}
                      value={settings.expert.multiplicity}
                      onChange={(e) => setSettings({ ...settings, expert: { ...settings.expert, multiplicity: Math.max(1, parseInt(e.target.value) || 1) } })}
                    />
                  </Field>
                  <Field label="conformer 수">
                    <input
                      className="input"
                      type="number"
                      value={settings.expert.nConformers}
                      onChange={(e) => setSettings({ ...settings, expert: { ...settings.expert, nConformers: parseInt(e.target.value) || 30 } })}
                    />
                  </Field>
                  <Field label="RMSD 기준 (Å)">
                    <input
                      className="input"
                      type="number"
                      step={0.05}
                      value={settings.expert.rmsdThreshold}
                      onChange={(e) => setSettings({ ...settings, expert: { ...settings.expert, rmsdThreshold: parseFloat(e.target.value) || 0.75 } })}
                    />
                  </Field>
                  <Field label="엔진">
                    <select
                      className="input"
                      value={settings.expert.engine}
                      onChange={(e) => setSettings({ ...settings, expert: { ...settings.expert, engine: e.target.value as 'PySCF' | 'CP2K' } })}
                    >
                      <option>PySCF</option>
                      <option>CP2K</option>
                    </select>
                  </Field>
                  <Field label="함수">
                    <select
                      className="input"
                      value={settings.expert.functional}
                      onChange={(e) => setSettings({ ...settings, expert: { ...settings.expert, functional: e.target.value } })}
                    >
                      <option>PBE0-D3(BJ)</option>
                      <option>B3LYP</option>
                      <option>M06-2X</option>
                      <option>ωB97X-D</option>
                      <option>PBE</option>
                    </select>
                  </Field>
                  <Field label="기저함수">
                    <select
                      className="input"
                      value={settings.expert.basis}
                      onChange={(e) => setSettings({ ...settings, expert: { ...settings.expert, basis: e.target.value } })}
                    >
                      <option>def2-TZVP</option>
                      <option>def2-TZVPD</option>
                      <option>def2-SVP</option>
                      <option>6-311+G(d,p)</option>
                    </select>
                  </Field>
                  <Field label="SCF tolerance">
                    <select
                      className="input"
                      value={settings.expert.scfTol}
                      onChange={(e) => setSettings({ ...settings, expert: { ...settings.expert, scfTol: e.target.value } })}
                    >
                      <option>1e-8</option>
                      <option>1e-9</option>
                      <option>1e-7</option>
                    </select>
                  </Field>
                </div>
              </details>

              {warnings.length > 0 && (
                <div className="banner warn">
                  {warnings.map((w) => (
                    <div key={w}>· {w}</div>
                  ))}
                </div>
              )}

              <div className="summary-box">
                <div className="option-title">계산 요약 — {settings.purpose}</div>
                <code className="mono small">
                  {settings.envType} · {solventById(settings.solventId)?.abbr ?? '용매 없음'} ·{' '}
                  {settings.temperature} K · {settings.structure} · {settings.expert.functional}/
                  {settings.expert.basis} · 기준 {settings.referenceElectrode}
                </code>
                {isStage2 ? (
                  <>
                    <div className="small muted">
                      자동 처리: 1단계 최적화 구조 로드 → SCF → 양이온/음이온 상태 → 열보정·결합 계산 →
                      전위 변환 → 검증 게이트 (conformer·구조 최적화 생략)
                    </div>
                    {submittable.length > 0 && (
                      <div className="small">
                        {submittable.map((id) => (
                          <div key={id} className="mono small muted">
                            {materialById(id)?.name}: 기준 구조 {baseFor(id)?.id} (v
                            {baseFor(id)?.structureVersion})
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="small muted">
                    자동 처리: 구조 검증 → 수소/전하 점검 → conformer {settings.expert.nConformers}개 →
                    GFN2-xTB → DFT 구조 최적화
                    {settings.purpose === '전체 계산' ? ' → 중성/양이온/음이온 → 전위 변환' : ' → 전자구조 산출'} →
                    검증 게이트
                  </div>
                )}
              </div>
              <button className="btn primary big" disabled={!submittable.length} onClick={submit}>
                {submittable.length
                  ? `작업 ${submittable.length}건 제출${isStage2 && submittable.length < selected.length ? ` (${selected.length - submittable.length}건 제외)` : ''}`
                  : isStage2 && selected.length
                    ? '선택 물질에 1단계 공개 결과가 없습니다'
                    : '대상 물질을 선택하세요'}
              </button>
            </section>
          </div>
        </>
      )}

      {tab === '작업 상태' && (
        <>
          {!activeJobs.length && (
            <div className="empty card">
              제출된 작업이 없습니다.
              <button className="btn primary" onClick={() => setTab('간편 설정')}>
                간편 설정으로 이동
              </button>
            </div>
          )}
          {activeJobs.map((j) => {
            const m = materialById(j.materialId)
            return (
              <div key={j.id} className="job-row card">
                <div className="job-main">
                  <div>
                    <b>{m?.name ?? j.materialId}</b>
                    <span className="mono small muted"> {j.id}</span>
                  </div>
                  <div className="small muted">
                    {j.settings.purpose} · {j.settings.envType} ·{' '}
                    {solventById(j.settings.solventId)?.abbr ?? '용매 없음'} · {j.settings.structure} ·{' '}
                    {j.settings.expert.functional}/{j.settings.expert.basis}
                    {j.baseJobId && (
                      <span className="mono"> · 기준 구조 {j.baseJobId}</span>
                    )}
                  </div>
                  {(j.status === 'RUNNING' || j.status === 'VALIDATING') && (
                    <>
                      <div className="progress-track">
                        <div className="progress-fill" style={{ width: `${j.progress}%` }} />
                      </div>
                      <div className="small muted">{j.stage}</div>
                    </>
                  )}
                  {j.status === 'NEEDS_REVIEW' && (
                    <div className="small form-error">{j.result?.validationNotes.join(' / ')}</div>
                  )}
                  {j.status === 'FAILED' && <div className="small form-error">{j.error}</div>}
                  <details className="log-details">
                    <summary className="small muted">서버 로그 요약 ({j.logs.length})</summary>
                    <ul className="log-list mono small">
                      {j.logs.map((l, i) => (
                        <li key={i}>{l}</li>
                      ))}
                    </ul>
                  </details>
                </div>
                <div className="job-side">
                  <StatusBadge status={j.status} progress={j.progress} />
                  <div className="small muted">제출 {fmtDate(j.createdAt)}</div>
                  <div className="row-actions">
                    {['QUEUED', 'RUNNING', 'VALIDATING'].includes(j.status) && (
                      <button className="btn ghost danger" onClick={() => dispatch({ type: 'cancelJob', id: j.id })}>
                        취소
                      </button>
                    )}
                    {['PUBLISHED', 'NEEDS_REVIEW', 'FAILED'].includes(j.status) && (
                      <button className="btn ghost danger" onClick={() => dispatch({ type: 'deleteJob', id: j.id })}>
                        삭제
                      </button>
                    )}
                    {j.status === 'PUBLISHED' && (
                      <button className="btn ghost" onClick={() => go('results', j.materialId)}>
                        결과 →
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </>
      )}
    </div>
  )
}
