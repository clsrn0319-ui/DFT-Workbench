import { useState } from 'react'
import { useStore } from '../store'
import type { Nav } from '../App'
import type { SolventPreset } from '../types'
import { Field } from '../ui'

// 기획서 4.4 — SOLV-01~06
export function Solvents({ go }: Nav) {
  const { solvents, dispatch } = useStore()
  const [editing, setEditing] = useState<SolventPreset | null>(null)
  const [showAdd, setShowAdd] = useState<'single' | 'mixed' | null>(null)

  const singles = solvents.filter((s) => s.kind === 'single')
  const mixed = solvents.filter((s) => s.kind === 'mixed')

  const remove = (s: SolventPreset) => {
    if (s.kind === 'single' && singles.length <= 1) {
      window.alert('마지막 단일 용매는 관리자 승인 없이 삭제할 수 없습니다. (기획서 8.3)')
      return
    }
    const linked = mixed.filter((m) => m.components?.some((c) => c.abbr === s.abbr))
    const msg =
      s.kind === 'single' && linked.length
        ? `'${s.abbr}' 삭제 시 이를 사용하는 혼합 프리셋 ${linked.length}건(${linked.map((l) => l.abbr).join(', ')})도 함께 정리됩니다.\n삭제하시겠습니까?`
        : `'${s.abbr}' v${s.version}을(를) 삭제하시겠습니까?`
    if (window.confirm(msg)) dispatch({ type: 'deleteSolvent', id: s.id })
  }

  return (
    <div>
      <header className="page-head">
        <h1>용매 라이브러리</h1>
        <p className="page-desc">
          단일·혼합 용매 프리셋 관리 — 적용 시 xTB와 DFT에 동일한 용매 조건이 사용됩니다. 수정하면 버전이
          증가합니다
        </p>
      </header>

      <div className="toolbar">
        <button className="btn primary" onClick={() => setShowAdd(showAdd === 'single' ? null : 'single')}>
          ＋ 단일 용매
        </button>
        <button className="btn primary" onClick={() => setShowAdd(showAdd === 'mixed' ? null : 'mixed')}>
          ＋ 혼합 용매
        </button>
      </div>

      {showAdd && <AddPanel kind={showAdd} onDone={() => setShowAdd(null)} />}
      {editing && <EditPanel solvent={editing} onDone={() => setEditing(null)} />}

      <section className="card">
        <div className="card-head">
          <h2>단일 용매</h2>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>약어</th>
              <th>이름</th>
              <th>SMILES</th>
              <th>모델 키</th>
              <th>버전</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {singles.map((s) => (
              <tr key={s.id}>
                <td>
                  <b>{s.abbr}</b>
                </td>
                <td>
                  {s.name}
                  {s.note && <div className="small muted">{s.note}</div>}
                </td>
                <td className="mono small">{s.smiles}</td>
                <td className="mono small">{s.modelKey}</td>
                <td className="mono small">v{s.version}</td>
                <td className="row-actions">
                  <button className="btn ghost" onClick={() => go('calc')}>
                    적용
                  </button>
                  <button className="btn ghost" onClick={() => setEditing(s)}>
                    편집
                  </button>
                  <button className="btn ghost danger" onClick={() => remove(s)}>
                    삭제
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>혼합 용매 프리셋</h2>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>약어</th>
              <th>구성</th>
              <th>기준</th>
              <th>버전</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {mixed.map((s) => (
              <tr key={s.id}>
                <td>
                  <b>{s.abbr}</b>
                </td>
                <td className="small">
                  {s.components?.map((c) => `${c.abbr} ${c.ratio}`).join(' : ')}
                </td>
                <td className="small">{s.ratioBasis}</td>
                <td className="mono small">v{s.version}</td>
                <td className="row-actions">
                  <button className="btn ghost" onClick={() => go('calc')}>
                    적용
                  </button>
                  <button className="btn ghost" onClick={() => setEditing(s)}>
                    편집
                  </button>
                  <button className="btn ghost danger" onClick={() => remove(s)}>
                    삭제
                  </button>
                </td>
              </tr>
            ))}
            {!mixed.length && (
              <tr>
                <td colSpan={5} className="empty small">
                  혼합 프리셋이 없습니다.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  )
}

function AddPanel({ kind, onDone }: { kind: 'single' | 'mixed'; onDone: () => void }) {
  const { solvents, dispatch } = useStore()
  const singles = solvents.filter((s) => s.kind === 'single')
  const [form, setForm] = useState({
    name: '',
    abbr: '',
    smiles: '',
    modelKey: '',
    compA: singles[0]?.abbr ?? '',
    compB: singles[1]?.abbr ?? '',
    ratioA: '1',
    ratioB: '1',
    basis: '부피비' as '부피비' | '질량비' | '몰비',
  })
  const [error, setError] = useState('')

  const save = () => {
    if (!form.name.trim() || !form.abbr.trim()) {
      setError('이름과 약어는 필수입니다.')
      return
    }
    if (kind === 'mixed' && form.compA === form.compB) {
      setError('혼합 용매는 서로 다른 구성 용매 2개가 필요합니다.')
      return
    }
    const preset: SolventPreset =
      kind === 'single'
        ? {
            id: `sol-${Date.now()}`,
            kind,
            name: form.name.trim(),
            abbr: form.abbr.trim(),
            smiles: form.smiles.trim(),
            modelKey: form.modelKey.trim() || `smd:${form.abbr.trim().toLowerCase()}`,
            version: '1.0',
            builtin: false,
          }
        : {
            id: `sol-${Date.now()}`,
            kind,
            name: form.name.trim(),
            abbr: form.abbr.trim(),
            components: [
              { abbr: form.compA, ratio: parseFloat(form.ratioA) || 1 },
              { abbr: form.compB, ratio: parseFloat(form.ratioB) || 1 },
            ],
            ratioBasis: form.basis,
            modelKey: form.modelKey.trim() || `smd:${form.abbr.trim().toLowerCase()}`,
            version: '1.0',
            builtin: false,
          }
    dispatch({ type: 'addSolvent', solvent: preset })
    onDone()
  }

  return (
    <section className="card form-card">
      <div className="card-head">
        <h2>{kind === 'single' ? '단일 용매 등록' : '혼합 용매 등록'}</h2>
      </div>
      <div className="form-grid">
        <Field label="이름 *">
          <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label="약어 *">
          <input className="input" value={form.abbr} onChange={(e) => setForm({ ...form, abbr: e.target.value })} />
        </Field>
        {kind === 'single' ? (
          <Field label="SMILES">
            <input className="input mono" value={form.smiles} onChange={(e) => setForm({ ...form, smiles: e.target.value })} />
          </Field>
        ) : (
          <>
            <Field label="구성 용매 A">
              <select className="input" value={form.compA} onChange={(e) => setForm({ ...form, compA: e.target.value })}>
                {singles.map((s) => (
                  <option key={s.id}>{s.abbr}</option>
                ))}
              </select>
            </Field>
            <Field label="구성 용매 B">
              <select className="input" value={form.compB} onChange={(e) => setForm({ ...form, compB: e.target.value })}>
                {singles.map((s) => (
                  <option key={s.id}>{s.abbr}</option>
                ))}
              </select>
            </Field>
            <Field label="비율 A:B">
              <div className="ratio-row">
                <input className="input" type="number" value={form.ratioA} onChange={(e) => setForm({ ...form, ratioA: e.target.value })} />
                <span>:</span>
                <input className="input" type="number" value={form.ratioB} onChange={(e) => setForm({ ...form, ratioB: e.target.value })} />
              </div>
            </Field>
            <Field label="비율 기준">
              <select className="input" value={form.basis} onChange={(e) => setForm({ ...form, basis: e.target.value as typeof form.basis })}>
                <option>부피비</option>
                <option>질량비</option>
                <option>몰비</option>
              </select>
            </Field>
          </>
        )}
        <Field label="xTB/DFT 모델 키">
          <input className="input mono" value={form.modelKey} onChange={(e) => setForm({ ...form, modelKey: e.target.value })} placeholder="비우면 자동 생성" />
        </Field>
      </div>
      {error && <div className="form-error">{error}</div>}
      <div className="form-actions">
        <button className="btn primary" onClick={save}>
          등록 (v1.0)
        </button>
        <button className="btn" onClick={onDone}>
          취소
        </button>
      </div>
    </section>
  )
}

function EditPanel({ solvent, onDone }: { solvent: SolventPreset; onDone: () => void }) {
  const { dispatch } = useStore()
  const [form, setForm] = useState({ name: solvent.name, abbr: solvent.abbr, modelKey: solvent.modelKey })

  const save = () => {
    dispatch({
      type: 'updateSolvent',
      id: solvent.id,
      patch: { name: form.name.trim(), abbr: form.abbr.trim(), modelKey: form.modelKey.trim() },
    })
    onDone()
  }

  return (
    <section className="card form-card">
      <div className="card-head">
        <h2>용매 편집 — {solvent.abbr}</h2>
        <span className="muted small">
          저장 시 v{solvent.version} → 버전 증가{solvent.kind === 'single' ? ' · 약어 변경 시 혼합 프리셋 동기화' : ''}
        </span>
      </div>
      <div className="form-grid">
        <Field label="이름">
          <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label="약어">
          <input className="input" value={form.abbr} onChange={(e) => setForm({ ...form, abbr: e.target.value })} />
        </Field>
        <Field label="xTB/DFT 모델 키">
          <input className="input mono" value={form.modelKey} onChange={(e) => setForm({ ...form, modelKey: e.target.value })} />
        </Field>
      </div>
      <div className="form-actions">
        <button className="btn primary" onClick={save}>
          저장
        </button>
        <button className="btn" onClick={onDone}>
          취소
        </button>
      </div>
    </section>
  )
}
