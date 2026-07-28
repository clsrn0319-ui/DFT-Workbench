import { useState } from 'react'
import { makeJob, useStore } from '../store'
import type { BasisSet, CalcSettings, Functional, SolventModel } from '../types'
import type { PageId } from '../App'

const FUNCTIONALS: { id: Functional; desc: string }[] = [
  { id: 'B3LYP', desc: '범용 하이브리드 — 유기분자 표준' },
  { id: 'PBE0', desc: '하이브리드 — 균형 잡힌 정확도' },
  { id: 'M06-2X', desc: '비공유 상호작용·열화학에 강점' },
  { id: 'ωB97X-D', desc: '장거리 보정+분산 — 전위·gap 신뢰도' },
  { id: 'PBE', desc: 'GGA — 빠르지만 gap 과소평가' },
]

const BASES: { id: BasisSet; desc: string }[] = [
  { id: '6-31G(d)', desc: '소형 — 빠른 사전 스크리닝' },
  { id: '6-311+G(d,p)', desc: '확산함수 포함 — 음이온·전위 계산 권장' },
  { id: 'def2-SVP', desc: '소형 def2 계열' },
  { id: 'def2-TZVP', desc: 'triple-ζ — 고정밀' },
]

const SOLVENTS: { id: SolventModel; label: string; desc: string }[] = [
  { id: 'none', label: '기체상', desc: '용매 효과 없음' },
  { id: 'PCM(H2O)', label: 'PCM · 물', desc: '수계 바인더 공정' },
  { id: 'SMD(H2O)', label: 'SMD · 물', desc: '용매화 에너지 정밀' },
  { id: 'SMD(NMP)', label: 'SMD · NMP', desc: 'PVDF 등 유기계 공정' },
]

export function NewCalc({ go }: { go: (p: PageId) => void }) {
  const { molecules, dispatch } = useStore()
  const [selected, setSelected] = useState<string[]>([])
  const [settings, setSettings] = useState<CalcSettings>({
    functional: 'B3LYP',
    basis: '6-311+G(d,p)',
    solvent: 'none',
    dispersion: true,
    charge: 0,
    multiplicity: 1,
  })
  const [submitted, setSubmitted] = useState(0)

  const toggle = (id: string) =>
    setSelected((sel) => (sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]))

  const submit = () => {
    const jobs = selected.map((id) => makeJob(id, settings))
    dispatch({ type: 'submitJobs', jobs })
    setSubmitted(jobs.length)
    setSelected([])
  }

  return (
    <div>
      <header className="page-head">
        <h1>새 계산</h1>
        <p className="page-desc">분자를 선택하고 DFT 계산 조건을 설정해 작업을 제출합니다</p>
      </header>

      {submitted > 0 && (
        <div className="banner success">
          작업 {submitted}건이 큐에 제출되었습니다.
          <button className="btn ghost" onClick={() => go('jobs')}>
            작업 현황 보기 →
          </button>
        </div>
      )}

      <section className="card">
        <div className="card-head">
          <h2>1. 대상 분자 선택</h2>
          <span className="muted small">{selected.length}개 선택됨</span>
        </div>
        <div className="mol-grid">
          {molecules.map((m) => (
            <button
              key={m.id}
              className={`mol-card ${selected.includes(m.id) ? 'selected' : ''}`}
              onClick={() => toggle(m.id)}
            >
              <div className="mol-abbr">{m.abbreviation}</div>
              <div className="mol-smiles mono">{m.smiles}</div>
              <span className="chip">{m.category}</span>
            </button>
          ))}
        </div>
      </section>

      <div className="grid-2">
        <section className="card">
          <div className="card-head">
            <h2>2. 이론 수준</h2>
          </div>
          <div className="option-group">
            <div className="option-title">교환-상관 범함수</div>
            {FUNCTIONALS.map((f) => (
              <label key={f.id} className="radio-row">
                <input
                  type="radio"
                  name="functional"
                  checked={settings.functional === f.id}
                  onChange={() => setSettings({ ...settings, functional: f.id })}
                />
                <b>{f.id}</b>
                <span className="muted small">{f.desc}</span>
              </label>
            ))}
          </div>
          <div className="option-group">
            <div className="option-title">기저함수</div>
            {BASES.map((b) => (
              <label key={b.id} className="radio-row">
                <input
                  type="radio"
                  name="basis"
                  checked={settings.basis === b.id}
                  onChange={() => setSettings({ ...settings, basis: b.id })}
                />
                <b>{b.id}</b>
                <span className="muted small">{b.desc}</span>
              </label>
            ))}
          </div>
          <label className="radio-row">
            <input
              type="checkbox"
              checked={settings.dispersion}
              onChange={(e) => setSettings({ ...settings, dispersion: e.target.checked })}
            />
            <b>D3(BJ) 분산 보정</b>
            <span className="muted small">표면 흡착에너지 계산 시 권장</span>
          </label>
        </section>

        <section className="card">
          <div className="card-head">
            <h2>3. 환경 및 시스템</h2>
          </div>
          <div className="option-group">
            <div className="option-title">용매 모델</div>
            {SOLVENTS.map((s) => (
              <label key={s.id} className="radio-row">
                <input
                  type="radio"
                  name="solvent"
                  checked={settings.solvent === s.id}
                  onChange={() => setSettings({ ...settings, solvent: s.id })}
                />
                <b>{s.label}</b>
                <span className="muted small">{s.desc}</span>
              </label>
            ))}
          </div>
          <div className="form-grid">
            <label>
              전하
              <input
                className="input"
                type="number"
                value={settings.charge}
                onChange={(e) => setSettings({ ...settings, charge: parseInt(e.target.value) || 0 })}
              />
            </label>
            <label>
              스핀 다중도
              <input
                className="input"
                type="number"
                min={1}
                value={settings.multiplicity}
                onChange={(e) =>
                  setSettings({ ...settings, multiplicity: Math.max(1, parseInt(e.target.value) || 1) })
                }
              />
            </label>
          </div>
          <div className="summary-box">
            <div className="option-title">계산 요약</div>
            <code className="mono">
              {settings.functional}
              {settings.dispersion ? '-D3(BJ)' : ''}/{settings.basis}
              {settings.solvent !== 'none' ? ` · ${settings.solvent}` : ' · 기체상'} · 전하 {settings.charge} ·
              다중도 {settings.multiplicity}
            </code>
            <div className="small muted">
              계산 항목: 구조최적화 → 진동수 → HOMO/LUMO·쌍극자·ESP·산화/환원 전위·표면 흡착에너지(4종)
            </div>
          </div>
          <button className="btn primary big" disabled={!selected.length} onClick={submit}>
            {selected.length ? `작업 ${selected.length}건 제출` : '분자를 선택하세요'}
          </button>
        </section>
      </div>
    </div>
  )
}
