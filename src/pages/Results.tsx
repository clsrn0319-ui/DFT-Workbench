import { useMemo, useState } from 'react'
import { useStore } from '../store'
import type { DftResult, Job, Molecule } from '../types'
import { AdhesionBars, EnergyLevelChart, PropertyRadar } from '../charts'

interface Entry {
  job: Job
  molecule: Molecule
  result: DftResult
}

const ROWS: { label: string; unit: string; get: (r: DftResult) => string }[] = [
  { label: 'HOMO', unit: 'eV', get: (r) => r.homo.toFixed(3) },
  { label: 'LUMO', unit: 'eV', get: (r) => r.lumo.toFixed(3) },
  { label: 'HOMO–LUMO gap', unit: 'eV', get: (r) => r.gap.toFixed(3) },
  { label: '쌍극자 모멘트 μ', unit: 'D', get: (r) => r.dipole.toFixed(2) },
  { label: '분극률 α', unit: 'a.u.', get: (r) => r.polarizability.toFixed(1) },
  { label: 'ESP 최소', unit: 'kcal/mol', get: (r) => r.espMin.toFixed(1) },
  { label: 'ESP 최대', unit: 'kcal/mol', get: (r) => r.espMax.toFixed(1) },
  { label: '산화 전위 E_ox', unit: 'V vs Li/Li⁺', get: (r) => r.oxidationPotential.toFixed(2) },
  { label: '환원 전위 E_red', unit: 'V vs Li/Li⁺', get: (r) => r.reductionPotential.toFixed(2) },
  { label: '용매화 에너지 ΔG_solv', unit: 'kcal/mol', get: (r) => (r.solvationEnergy ? r.solvationEnergy.toFixed(1) : '—') },
  { label: 'E_ad (Graphite)', unit: 'eV', get: (r) => r.adhesion.Graphite.toFixed(2) },
  { label: 'E_ad (Si)', unit: 'eV', get: (r) => r.adhesion.Si.toFixed(2) },
  { label: 'E_ad (NMC811)', unit: 'eV', get: (r) => r.adhesion.NMC811.toFixed(2) },
  { label: 'E_ad (LFP)', unit: 'eV', get: (r) => r.adhesion.LFP.toFixed(2) },
  { label: '전자 에너지', unit: 'Hartree', get: (r) => r.totalEnergy.toFixed(4) },
]

function exportCsv(entries: Entry[]) {
  const header = ['물성', '단위', ...entries.map((e) => e.molecule.abbreviation)]
  const lines = ROWS.map((row) => [row.label, row.unit, ...entries.map((e) => row.get(e.result))])
  const csv = [header, ...lines].map((l) => l.map((c) => `"${c}"`).join(',')).join('\n')
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'dft-results.csv'
  a.click()
  URL.revokeObjectURL(a.href)
}

export function Results() {
  const { jobs, moleculeById } = useStore()
  const doneJobs = useMemo(
    () => jobs.filter((j) => j.status === 'done' && j.result).sort((a, b) => b.createdAt - a.createdAt),
    [jobs],
  )
  const [selectedIds, setSelectedIds] = useState<string[]>([])

  // 선택이 없으면 최근 완료 작업 1건을 기본 표시
  const effective = selectedIds.length ? selectedIds : doneJobs.slice(0, 1).map((j) => j.id)

  const entries: Entry[] = effective
    .map((id) => doneJobs.find((j) => j.id === id))
    .filter((j): j is Job => !!j)
    .map((job) => ({
      job,
      molecule: moleculeById(job.moleculeId)!,
      result: job.result!,
    }))
    .filter((e) => e.molecule)

  const toggle = (id: string) =>
    setSelectedIds((sel) => {
      if (sel.includes(id)) return sel.filter((x) => x !== id)
      if (sel.length >= 3) return sel // 색상 팔레트 검증 범위(3계열)까지만 동시 비교
      return [...sel, id]
    })

  if (!doneJobs.length) {
    return (
      <div>
        <header className="page-head">
          <h1>결과 분석</h1>
          <p className="page-desc">완료된 계산 결과 조회 및 후보 비교</p>
        </header>
        <div className="empty card">완료된 계산이 없습니다. 작업이 끝나면 이곳에서 결과를 확인할 수 있습니다.</div>
      </div>
    )
  }

  return (
    <div>
      <header className="page-head">
        <h1>결과 분석</h1>
        <p className="page-desc">완료 작업을 최대 3건까지 선택해 비교합니다</p>
      </header>

      <section className="card">
        <div className="card-head">
          <h2>비교 대상 선택</h2>
          <span className="muted small">{entries.length} / 3</span>
        </div>
        <div className="mol-grid">
          {doneJobs.map((j) => {
            const m = moleculeById(j.moleculeId)
            const active = effective.includes(j.id)
            return (
              <button
                key={j.id}
                className={`mol-card ${active ? 'selected' : ''}`}
                onClick={() => toggle(j.id)}
              >
                <div className="mol-abbr">{m?.abbreviation}</div>
                <div className="small muted mono">
                  {j.settings.functional}/{j.settings.basis}
                </div>
                <div className="small muted">gap {j.result!.gap.toFixed(2)} eV</div>
              </button>
            )
          })}
        </div>
      </section>

      {entries.length > 0 && (
        <>
          <div className="grid-2">
            <section className="card">
              <div className="card-head">
                <h2>에너지 준위 (HOMO/LUMO)</h2>
              </div>
              <EnergyLevelChart entries={entries} />
            </section>
            <section className="card">
              <div className="card-head">
                <h2>다물성 프로파일</h2>
              </div>
              <PropertyRadar entries={entries} />
            </section>
          </div>

          <section className="card">
            <div className="card-head">
              <h2>활물질 표면 흡착에너지</h2>
            </div>
            <AdhesionBars entries={entries} />
          </section>

          <section className="card">
            <div className="card-head">
              <h2>물성 상세 표</h2>
              <button className="btn ghost" onClick={() => exportCsv(entries)}>
                CSV 내보내기
              </button>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>물성</th>
                  <th>단위</th>
                  {entries.map((e) => (
                    <th key={e.job.id} className="num">
                      {e.molecule.abbreviation}
                      <div className="small muted mono">
                        {e.job.settings.functional}/{e.job.settings.basis}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ROWS.map((row) => (
                  <tr key={row.label}>
                    <td>{row.label}</td>
                    <td className="muted small">{row.unit}</td>
                    {entries.map((e) => (
                      <td key={e.job.id} className="num mono">
                        {row.get(e.result)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="chart-note">
              ※ 현재 값은 모의 엔진 결과입니다. 실계산 엔진(Gaussian/ORCA 등) 연동 시 동일 화면으로 실제 값이
              표시됩니다.
            </div>
          </section>
        </>
      )}
    </div>
  )
}
