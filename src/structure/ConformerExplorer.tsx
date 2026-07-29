import { useMemo, useState } from 'react'
import { Molecule3D } from './Molecule3D'
import { bestConformerAmong, buildConformerGraph, conformerEnergy } from './molGraph'

const MAX_CONF = 30

// Conformer 탐색 수에 따른 구조 안정화 시각화:
// N을 늘리면 더 낮은 에너지 conformer가 발견되고, 그 구조가 3D로 표시된다.
export function ConformerExplorer({ smiles }: { smiles: string }) {
  const [n, setN] = useState(10)
  const [showIdx, setShowIdx] = useState<number | null>(null) // null = 현재 최저 에너지 conformer

  const energies = useMemo(
    () => Array.from({ length: MAX_CONF }, (_, i) => conformerEnergy(smiles, i + 1)),
    [smiles],
  )
  const globalMin = Math.min(...energies)
  const best = bestConformerAmong(smiles, n)
  const displayed = showIdx ?? best.index
  const graph = useMemo(() => buildConformerGraph(smiles, displayed), [smiles, displayed])

  // E_min(N) 수렴 곡선 (전체 탐색 최저 대비 상대값)
  const minCurve: number[] = []
  let running = Infinity
  for (let i = 1; i <= MAX_CONF; i++) {
    running = Math.min(running, energies[i - 1])
    minCurve.push(running - globalMin)
  }

  const W = 600
  const H = 160
  const padL = 40
  const padT = 12
  const padB = 26
  const plotW = W - padL - 14
  const plotH = H - padT - padB
  const maxY = Math.max(...minCurve, 0.5)
  const cx = (i: number) => padL + ((i - 1) / (MAX_CONF - 1)) * plotW
  const cy = (e: number) => padT + (1 - e / maxY) * plotH

  const path = minCurve
    .map((e, i) => `${i === 0 ? 'M' : 'L'}${cx(i + 1).toFixed(1)},${cy(e).toFixed(1)}`)
    .join(' ')

  return (
    <div>
      <div className="conf-controls">
        <label className="small">
          탐색 conformer 수: <b>{n}</b>
          <input
            type="range"
            min={1}
            max={MAX_CONF}
            value={n}
            onChange={(e) => {
              setN(parseInt(e.target.value))
              setShowIdx(null)
            }}
          />
        </label>
        <div className="small muted">
          최저 에너지 conformer <b>#{best.index}</b> · ΔE = {(best.energy - globalMin).toFixed(2)} kcal/mol
          (전체 탐색 최저 대비)
          {best.energy - globalMin < 0.01 && ' — 수렴'}
        </div>
      </div>

      <div className="conf-grid">
        <div>
          <Molecule3D smiles={smiles} colorMode="cpk" height={240} graphOverride={graph} />
        </div>
        <div className="chart-box">
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="conformer 수에 따른 최저 에너지 수렴">
            {[0, maxY / 2, maxY].map((t) => (
              <g key={t}>
                <line x1={padL} x2={W - 14} y1={cy(t)} y2={cy(t)} className={t === 0 ? 'baseline' : 'gridline'} />
                <text x={padL - 6} y={cy(t) + 4} className="axis-label" textAnchor="end">
                  {t.toFixed(1)}
                </text>
              </g>
            ))}
            {/* 개별 conformer 에너지 (첫 N개) */}
            {energies.slice(0, n).map((e, i) => (
              <circle
                key={i}
                cx={cx(i + 1)}
                cy={cy(e - globalMin > maxY ? maxY : e - globalMin)}
                r={showIdx === i + 1 ? 5 : 3}
                fill={i + 1 === best.index ? 'var(--accent)' : 'var(--muted)'}
                opacity={i + 1 === best.index ? 1 : 0.45}
                style={{ cursor: 'pointer' }}
                onClick={() => setShowIdx(i + 1)}
              />
            ))}
            <path d={path} fill="none" stroke="var(--accent)" strokeWidth={2} />
            <line x1={cx(n)} x2={cx(n)} y1={padT} y2={H - padB} stroke="var(--pin)" strokeWidth={1.4} strokeDasharray="4 3" />
            <text x={cx(n)} y={padT - 2} fontSize={10} fill="var(--pin)" textAnchor="middle">
              N={n}
            </text>
            <text x={padL} y={H - 6} className="axis-label">
              1
            </text>
            <text x={W - 14} y={H - 6} className="axis-label" textAnchor="end">
              conformer 수 {MAX_CONF}
            </text>
          </svg>
          <div className="chart-note">
            세로축 = ΔE_min (kcal/mol). 선 = N개 탐색 시 발견된 최저 상대 에너지(안정화 수렴 곡선) · 점 = 개별
            conformer(클릭 시 해당 구조 표시, 틸 = 현재 최저) · 곡선이 평평해지면 conformer 수를 더 늘려도
            이득이 작음을 의미
          </div>
        </div>
      </div>
      <div className="chart-note">
        표시 중: conformer #{displayed} (ΔE ={' '}
        {(conformerEnergy(smiles, displayed) - globalMin).toFixed(2)} kcal/mol)
        {showIdx !== null && (
          <button className="btn ghost" onClick={() => setShowIdx(null)}>
            최저 에너지 구조로
          </button>
        )}{' '}
        — 고에너지 conformer일수록 기준 구조에서 뒤틀린 형태로 표시됩니다. 실제 RMSD 중복 제거·에너지 창
        기준은 전문 계산 설정을 따릅니다 (프로토타입 모의값).
      </div>
    </div>
  )
}
