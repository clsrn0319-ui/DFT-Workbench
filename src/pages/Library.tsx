import { useState } from 'react'
import { useStore } from '../store'
import type { Nav } from '../App'
import type { Material, MaterialType, OriginType } from '../types'
import { searchDictionary, validateCas, type DictEntry } from '../data/dictionary'
import { COMPUTED_KEYS } from '../data/descriptors'
import { Field, InitialBadge, ReadyBadge, StatusBadge } from '../ui'

type SortKey = '최근 수정' | '이름' | '최근 사용'

// 기획서 4.2 물질 보관함 — LIB-01~07, 검색→SMILES(4.2.2), 입력 방식(4.2.3), 편집 규칙(4.2.4)
export function Library({ go }: Nav) {
  const store = useStore()
  const { materials, jobs, compareIds, dispatch, latestPublished } = store
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SortKey>('최근 수정')
  const [view, setView] = useState<'card' | 'table'>('card')
  const [showRegister, setShowRegister] = useState(false)
  const [editing, setEditing] = useState<Material | null>(null)

  const q = query.trim().toLowerCase()
  const filtered = materials
    .filter(
      (m) =>
        !q ||
        m.name.toLowerCase().includes(q) ||
        m.casNo.includes(q) ||
        m.smiles.toLowerCase().includes(q) ||
        m.tags.some((t) => t.toLowerCase().includes(q)) ||
        m.precursorCas.some((c) => c.includes(q)),
    )
    .sort((a, b) => {
      if (sort === '이름') return a.name.localeCompare(b.name)
      if (sort === '최근 사용') {
        const ja = Math.max(0, ...jobs.filter((j) => j.materialId === a.id).map((j) => j.createdAt))
        const jb = Math.max(0, ...jobs.filter((j) => j.materialId === b.id).map((j) => j.createdAt))
        return jb - ja
      }
      return b.updatedAt - a.updatedAt
    })

  const calcStatus = (id: string) => {
    const js = jobs.filter((j) => j.materialId === id)
    if (!js.length) return null
    const latest = [...js].sort((a, b) => b.createdAt - a.createdAt)[0]
    return latest
  }

  const descriptorDone = (id: string) => {
    const pub = latestPublished(id)
    return pub ? Object.keys(pub.result!.descriptors).length : 0
  }

  const removeMaterial = (m: Material) => {
    const linked = jobs.filter((j) => j.materialId === m.id).length
    const inCompare = compareIds.includes(m.id)
    const msg =
      `'${m.name}' 삭제 시 연결 데이터에 영향이 있습니다.\n` +
      `· 계산 작업/결과 ${linked}건 삭제\n` +
      `· 비교 세트 ${inCompare ? '1건에서 제외' : '영향 없음'}\n\n삭제하시겠습니까?`
    if (window.confirm(msg)) dispatch({ type: 'deleteMaterial', id: m.id })
  }

  return (
    <div>
      <header className="page-head">
        <h1>물질 보관함</h1>
        <p className="page-desc">바인더·용매·첨가제 후보 등록과 관리 — 새 물질 등록은 이 화면에서 수행합니다</p>
      </header>

      <div className="toolbar">
        <input
          className="input grow"
          placeholder="이름 · CAS No. · 태그 · SMILES · 원료 CAS 검색 (부분 일치)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select className="input" value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
          <option>최근 수정</option>
          <option>이름</option>
          <option>최근 사용</option>
        </select>
        <div className="seg">
          <button className={view === 'card' ? 'on' : ''} onClick={() => setView('card')}>
            카드
          </button>
          <button className={view === 'table' ? 'on' : ''} onClick={() => setView('table')}>
            표
          </button>
        </div>
        <button className="btn primary" onClick={() => setShowRegister(!showRegister)}>
          {showRegister ? '등록 닫기' : '＋ 새 물질 등록'}
        </button>
      </div>

      {showRegister && <RegisterPanel onDone={() => setShowRegister(false)} />}
      {editing && <EditPanel material={editing} onDone={() => setEditing(null)} />}

      {view === 'card' ? (
        <div className="mat-grid">
          {filtered.map((m) => {
            const latest = calcStatus(m.id)
            return (
              <div key={m.id} className="mat-card">
                <div className="mat-card-top">
                  <InitialBadge material={m} />
                  <label className="compare-check" title="비교 선택 (최대 8개)">
                    <input
                      type="checkbox"
                      checked={compareIds.includes(m.id)}
                      onChange={() => dispatch({ type: 'toggleCompare', id: m.id })}
                    />
                    비교
                  </label>
                </div>
                <button className="mat-name" onClick={() => go('detail', m.id)}>
                  {m.name}
                </button>
                <div className="mono small muted ellipsis">{m.smiles}</div>
                <div className="small muted">
                  {m.casNo || 'CAS 미부여'} · 구조 v{m.structureVersion}
                </div>
                <div className="mat-meter" title="16개 descriptor 계산 완료도">
                  <div
                    className="mat-meter-fill"
                    style={{ width: `${(descriptorDone(m.id) / COMPUTED_KEYS.length) * 100}%` }}
                  />
                </div>
                <div className="small muted">
                  descriptor {descriptorDone(m.id)}/{COMPUTED_KEYS.length}
                </div>
                <div className="mat-card-badges">
                  <ReadyBadge state={m.readyState} />
                  {latest ? <StatusBadge status={latest.status} progress={latest.progress} /> : <span className="badge queued">계산 미요청</span>}
                </div>
                <div className="row-actions">
                  <button className="btn ghost" onClick={() => setEditing(m)}>
                    편집
                  </button>
                  <button className="btn ghost danger" onClick={() => removeMaterial(m)}>
                    삭제
                  </button>
                  <button className="btn ghost" onClick={() => go('calc', m.id)}>
                    계산 →
                  </button>
                </div>
              </div>
            )
          })}
          {!filtered.length && <div className="empty">조건에 맞는 물질이 없습니다.</div>}
        </div>
      ) : (
        <section className="card">
          <table className="table">
            <thead>
              <tr>
                <th>비교</th>
                <th>물질</th>
                <th>CAS</th>
                <th>SMILES</th>
                <th>구조</th>
                <th>준비 상태</th>
                <th>계산 상태</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((m) => {
                const latest = calcStatus(m.id)
                return (
                  <tr key={m.id}>
                    <td>
                      <input
                        type="checkbox"
                        checked={compareIds.includes(m.id)}
                        onChange={() => dispatch({ type: 'toggleCompare', id: m.id })}
                      />
                    </td>
                    <td className="clickable" onClick={() => go('detail', m.id)}>
                      <b>{m.name}</b>
                      <div className="small muted">{m.tags.join(' · ')}</div>
                    </td>
                    <td className="mono small">{m.casNo || '미부여'}</td>
                    <td className="mono small ellipsis" style={{ maxWidth: 180 }}>
                      {m.smiles}
                    </td>
                    <td className="small">v{m.structureVersion}</td>
                    <td>
                      <ReadyBadge state={m.readyState} />
                    </td>
                    <td>{latest ? <StatusBadge status={latest.status} progress={latest.progress} /> : <span className="badge queued">미요청</span>}</td>
                    <td className="row-actions">
                      <button className="btn ghost" onClick={() => setEditing(m)}>
                        편집
                      </button>
                      <button className="btn ghost danger" onClick={() => removeMaterial(m)}>
                        삭제
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>
      )}
    </div>
  )
}

// ── 새 물질 등록 (기획서 4.2.2 / 4.2.3) ─────────────────────────
function RegisterPanel({ onDone }: { onDone: () => void }) {
  const { dispatch, materials } = useStore()
  const [mode, setMode] = useState<'search' | 'smiles' | 'batch'>('search')
  const [term, setTerm] = useState('')
  const [candidates, setCandidates] = useState<DictEntry[] | null>(null)
  const [form, setForm] = useState({
    name: '',
    casNo: '',
    smiles: '',
    formula: '',
    mw: '',
    type: '바인더 모노머' as MaterialType,
    originType: '상용' as OriginType,
    tags: '',
    precursorCas: '',
    note: '',
    dictId: undefined as string | undefined,
  })
  const [batch, setBatch] = useState('')
  const [error, setError] = useState('')

  const runSearch = () => {
    if (!term.trim()) {
      setError('검색어를 입력하세요.')
      return
    }
    if (/^\d{2,7}-\d{2}-\d$/.test(term.trim()) && !validateCas(term.trim())) {
      setError('CAS No. 확인 숫자가 올바르지 않습니다.')
      return
    }
    setError('')
    const found = searchDictionary(term)
    setCandidates(found)
  }

  const applyCandidate = (e: DictEntry) => {
    setForm({
      ...form,
      name: e.name,
      casNo: e.casNo,
      smiles: e.smiles,
      formula: e.formula,
      mw: String(e.mw),
      type: e.type,
      tags: e.synonyms.slice(0, 2).join(', '),
      dictId: e.dictId,
    })
  }

  const register = () => {
    if (!form.name.trim() || !form.smiles.trim()) {
      setError('대표명과 SMILES는 필수입니다.')
      return
    }
    if (form.casNo && !validateCas(form.casNo)) {
      setError('CAS No. 형식 또는 확인 숫자가 올바르지 않습니다. 신규 합성물은 비워 두세요.')
      return
    }
    if (form.originType !== '상용' && form.originType !== '미상' && !form.precursorCas.trim()) {
      setError('합성/개질 물질은 원료 CAS No.를 한 개 이상 입력해야 합니다.')
      return
    }
    const mat: Material = {
      id: `mat-${Date.now()}`,
      name: form.name.trim(),
      casNo: form.casNo.trim(),
      smiles: form.smiles.trim(),
      formula: form.formula.trim(),
      mw: parseFloat(form.mw) || 0,
      type: form.type,
      originType: form.originType,
      tags: form.tags.split(',').map((t) => t.trim()).filter(Boolean),
      note: form.note,
      precursorCas: form.precursorCas.split(',').map((t) => t.trim()).filter(Boolean),
      structureVersion: 1,
      readyState: form.dictId ? 'Ready' : 'Ready with warning',
      createdAt: Date.now(),
      updatedAt: Date.now(),
      builtin: false,
      dictId: form.dictId,
    }
    dispatch({ type: 'addMaterial', material: mat })
    onDone()
  }

  const registerBatch = () => {
    const lines = batch.split('\n').map((l) => l.trim()).filter(Boolean)
    if (!lines.length) {
      setError('한 줄에 하나의 SMILES를 입력하세요.')
      return
    }
    lines.forEach((smiles, i) => {
      dispatch({
        type: 'addMaterial',
        material: {
          id: `mat-${Date.now()}-${i}`,
          name: `일괄 등록 물질 ${materials.length + i + 1}`,
          casNo: '',
          smiles,
          formula: '',
          mw: 0,
          type: '기타',
          originType: '미상',
          tags: ['일괄'],
          note: '',
          precursorCas: [],
          structureVersion: 1,
          readyState: 'Needs decision',
          createdAt: Date.now(),
          updatedAt: Date.now(),
          builtin: false,
        },
      })
    })
    onDone()
  }

  return (
    <section className="card form-card">
      <div className="card-head">
        <h2>새 물질 등록</h2>
        <div className="seg">
          <button className={mode === 'search' ? 'on' : ''} onClick={() => setMode('search')}>
            이름/CAS 검색
          </button>
          <button className={mode === 'smiles' ? 'on' : ''} onClick={() => setMode('smiles')}>
            SMILES 직접 입력
          </button>
          <button className={mode === 'batch' ? 'on' : ''} onClick={() => setMode('batch')}>
            일괄 등록
          </button>
        </div>
      </div>

      {mode === 'search' && (
        <>
          <div className="toolbar">
            <input
              className="input grow"
              placeholder="영문명 또는 CAS No. (예: Methyl methacrylate / 96-49-1)"
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && runSearch()}
            />
            <button className="btn primary" onClick={runSearch}>
              SMILES 후보 검색
            </button>
          </div>
          {candidates !== null &&
            (candidates.length ? (
              <table className="table">
                <thead>
                  <tr>
                    <th>대표명</th>
                    <th>CAS No.</th>
                    <th>SMILES</th>
                    <th>분자식</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((c) => (
                    <tr key={c.dictId}>
                      <td>
                        {c.name}
                        <div className="small muted">{c.korName}</div>
                      </td>
                      <td className="mono small">{c.casNo || '—'}</td>
                      <td className="mono small">{c.smiles}</td>
                      <td className="mono small">{c.formula}</td>
                      <td>
                        <button className="btn ghost" onClick={() => applyCandidate(c)}>
                          적용
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="banner warn">
                내장 사전에서 후보를 찾지 못했습니다 (상용 버전은 PubChem 프록시로 온라인 조회를 계속합니다).
                SMILES 직접 입력 또는 일괄 등록 경로를 사용하세요.
              </div>
            ))}
        </>
      )}

      {mode === 'batch' ? (
        <>
          <textarea
            className="input"
            rows={5}
            placeholder={'한 줄에 하나의 SMILES\n예)\nC=CC(=O)OCC\nC=C(C)C(=O)O'}
            value={batch}
            onChange={(e) => setBatch(e.target.value)}
          />
          {error && <div className="form-error">{error}</div>}
          <div className="form-actions">
            <button className="btn primary" onClick={registerBatch}>
              일괄 등록
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="form-grid">
            <Field label="대표 물질명 *">
              <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </Field>
            <Field label="CAS No. (미부여 허용)">
              <input className="input mono" value={form.casNo} onChange={(e) => setForm({ ...form, casNo: e.target.value })} placeholder="예: 80-62-6" />
            </Field>
            <Field label="SMILES *">
              <input className="input mono" value={form.smiles} onChange={(e) => setForm({ ...form, smiles: e.target.value, dictId: undefined })} />
            </Field>
            <Field label="분자식">
              <input className="input mono" value={form.formula} onChange={(e) => setForm({ ...form, formula: e.target.value })} />
            </Field>
            <Field label="분자량 (g/mol)">
              <input className="input" type="number" value={form.mw} onChange={(e) => setForm({ ...form, mw: e.target.value })} />
            </Field>
            <Field label="물질 유형">
              <select className="input" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as MaterialType })}>
                <option>바인더 모노머</option>
                <option>용매</option>
                <option>첨가제</option>
                <option>염</option>
                <option>기타</option>
              </select>
            </Field>
            <Field label="생성 유형">
              <select className="input" value={form.originType} onChange={(e) => setForm({ ...form, originType: e.target.value as OriginType })}>
                <option>상용</option>
                <option>합성</option>
                <option>개질</option>
                <option>미상</option>
              </select>
            </Field>
            <Field label="태그 (쉼표 구분)">
              <input className="input" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
            </Field>
            <Field label="원료 CAS (합성/개질 시 필수, 쉼표 구분)">
              <input className="input mono" value={form.precursorCas} onChange={(e) => setForm({ ...form, precursorCas: e.target.value })} />
            </Field>
            <Field label="메모">
              <input className="input" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
            </Field>
          </div>
          {error && <div className="form-error">{error}</div>}
          <div className="form-actions">
            <button className="btn primary" onClick={register}>
              등록
            </button>
          </div>
        </>
      )}
    </section>
  )
}

// ── 편집 (기획서 4.2.4 — 구조 변경 시 새 구조 버전·결과 무효화 안내) ─
function EditPanel({ material, onDone }: { material: Material; onDone: () => void }) {
  const { dispatch, jobs } = useStore()
  const [form, setForm] = useState({
    name: material.name,
    casNo: material.casNo,
    smiles: material.smiles,
    tags: material.tags.join(', '),
    note: material.note,
    precursorCas: material.precursorCas.join(', '),
  })
  const [error, setError] = useState('')

  const save = () => {
    if (form.casNo && !validateCas(form.casNo)) {
      setError('CAS No. 형식 또는 확인 숫자가 올바르지 않습니다.')
      return
    }
    const structureChanged = form.smiles.trim() !== material.smiles
    if (structureChanged) {
      const linked = jobs.filter((j) => j.materialId === material.id).length
      if (
        !window.confirm(
          `SMILES가 변경되어 새 구조 버전 v${material.structureVersion + 1}이 생성됩니다.\n` +
            `기존 계산 결과 ${linked}건은 "이전 구조 결과"로 보존되며 기본 결과·비교에서 제외됩니다.\n계속하시겠습니까?`,
        )
      )
        return
    }
    dispatch({
      type: 'updateMaterial',
      id: material.id,
      structureChanged,
      patch: {
        name: form.name.trim(),
        casNo: form.casNo.trim(),
        smiles: form.smiles.trim(),
        tags: form.tags.split(',').map((t) => t.trim()).filter(Boolean),
        note: form.note,
        precursorCas: form.precursorCas.split(',').map((t) => t.trim()).filter(Boolean),
      },
    })
    onDone()
  }

  return (
    <section className="card form-card">
      <div className="card-head">
        <h2>물질 편집 — {material.name}</h2>
        <span className="muted small">현재 구조 v{material.structureVersion}</span>
      </div>
      <div className="form-grid">
        <Field label="대표 물질명">
          <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label="CAS No.">
          <input className="input mono" value={form.casNo} onChange={(e) => setForm({ ...form, casNo: e.target.value })} />
        </Field>
        <Field label="SMILES (변경 시 새 구조 버전)">
          <input className="input mono" value={form.smiles} onChange={(e) => setForm({ ...form, smiles: e.target.value })} />
        </Field>
        <Field label="태그">
          <input className="input" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
        </Field>
        <Field label="원료 CAS">
          <input className="input mono" value={form.precursorCas} onChange={(e) => setForm({ ...form, precursorCas: e.target.value })} />
        </Field>
        <Field label="메모">
          <input className="input" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
        </Field>
      </div>
      {error && <div className="form-error">{error}</div>}
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
