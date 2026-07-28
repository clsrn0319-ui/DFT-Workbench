import { useState } from 'react'
import { useStore } from '../store'
import type { Category, Molecule } from '../types'
import type { PageId } from '../App'

const CATEGORIES: Category[] = [
  '불소계',
  '고무계',
  '셀룰로오스계',
  '아크릴계',
  '수용성',
  '니트릴계',
  '에테르계',
  '기타',
]

export function Library({ go }: { go: (p: PageId) => void }) {
  const { molecules, jobs, dispatch } = useStore()
  const [query, setQuery] = useState('')
  const [cat, setCat] = useState<'전체' | Category>('전체')
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ name: '', abbr: '', smiles: '', category: '기타' as Category, mw: '' })
  const [formError, setFormError] = useState('')

  const filtered = molecules.filter(
    (m) =>
      (cat === '전체' || m.category === cat) &&
      (query === '' ||
        m.name.toLowerCase().includes(query.toLowerCase()) ||
        m.abbreviation.toLowerCase().includes(query.toLowerCase()) ||
        m.smiles.includes(query)),
  )

  const doneCount = (id: string) =>
    jobs.filter((j) => j.moleculeId === id && j.status === 'done').length

  const submit = () => {
    if (!form.name.trim() || !form.abbr.trim() || !form.smiles.trim()) {
      setFormError('이름·약어·SMILES는 필수입니다.')
      return
    }
    // 간단한 SMILES 문자 검증
    if (!/^[A-Za-z0-9@+\-[\]()=#$/\\%.*]+$/.test(form.smiles.trim())) {
      setFormError('SMILES에 허용되지 않는 문자가 있습니다.')
      return
    }
    const mol: Molecule = {
      id: `custom-${Date.now()}`,
      name: form.name.trim(),
      abbreviation: form.abbr.trim(),
      smiles: form.smiles.trim(),
      category: form.category,
      monomer: '사용자 정의',
      mw: parseFloat(form.mw) || 0,
      builtin: false,
    }
    dispatch({ type: 'addMolecule', molecule: mol })
    setForm({ name: '', abbr: '', smiles: '', category: '기타', mw: '' })
    setFormError('')
    setShowForm(false)
  }

  return (
    <div>
      <header className="page-head">
        <h1>분자 라이브러리</h1>
        <p className="page-desc">바인더 후보 단량체(반복단위) 관리 및 신규 등록</p>
      </header>

      <div className="toolbar">
        <input
          className="input"
          placeholder="이름·약어·SMILES 검색"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select className="input" value={cat} onChange={(e) => setCat(e.target.value as typeof cat)}>
          <option>전체</option>
          {CATEGORIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
        <button className="btn primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? '닫기' : '＋ 분자 등록'}
        </button>
      </div>

      {showForm && (
        <section className="card form-card">
          <div className="card-head">
            <h2>신규 분자 등록</h2>
          </div>
          <div className="form-grid">
            <label>
              화합물명
              <input
                className="input"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="예: Poly(methyl methacrylate)"
              />
            </label>
            <label>
              약어
              <input
                className="input"
                value={form.abbr}
                onChange={(e) => setForm({ ...form, abbr: e.target.value })}
                placeholder="예: PMMA"
              />
            </label>
            <label>
              SMILES (단량체 기준)
              <input
                className="input mono"
                value={form.smiles}
                onChange={(e) => setForm({ ...form, smiles: e.target.value })}
                placeholder="예: C=C(C)C(=O)OC"
              />
            </label>
            <label>
              계열
              <select
                className="input"
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value as Category })}
              >
                {CATEGORIES.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            <label>
              단량체 분자량 (g/mol)
              <input
                className="input"
                type="number"
                value={form.mw}
                onChange={(e) => setForm({ ...form, mw: e.target.value })}
                placeholder="선택 입력"
              />
            </label>
          </div>
          {formError && <div className="form-error">{formError}</div>}
          <div className="form-actions">
            <button className="btn primary" onClick={submit}>
              등록
            </button>
          </div>
        </section>
      )}

      <section className="card">
        <table className="table">
          <thead>
            <tr>
              <th>약어</th>
              <th>화합물명</th>
              <th>계열</th>
              <th>SMILES</th>
              <th className="num">MW</th>
              <th className="num">완료 계산</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((m) => (
              <tr key={m.id}>
                <td>
                  <b>{m.abbreviation}</b>
                </td>
                <td>
                  {m.name}
                  {m.note && <div className="small muted">{m.note}</div>}
                </td>
                <td>
                  <span className="chip">{m.category}</span>
                </td>
                <td className="mono small">{m.smiles}</td>
                <td className="num">{m.mw ? m.mw.toFixed(1) : '—'}</td>
                <td className="num">{doneCount(m.id)}</td>
                <td className="row-actions">
                  <button className="btn ghost" onClick={() => go('new')}>
                    계산
                  </button>
                  {!m.builtin && (
                    <button
                      className="btn ghost danger"
                      onClick={() => dispatch({ type: 'removeMolecule', id: m.id })}
                    >
                      삭제
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {!filtered.length && (
              <tr>
                <td colSpan={7} className="empty">
                  조건에 맞는 분자가 없습니다.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  )
}
