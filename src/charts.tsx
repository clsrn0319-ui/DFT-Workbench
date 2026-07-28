import { useState, type ReactNode } from 'react'
import type { DftResult, Molecule, Surface } from './types'

// 팔레트 슬롯 1–3 (전 조합 검증 통과 범위) — CSS 변수로 라이트/다크 자동 전환
export const SERIES_VARS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)']

interface TipState {
  x: number
  y: number
  content: ReactNode
}

function useTip() {
  const [tip, setTip] = useState<TipState | null>(null)
  const show = (e: React.MouseEvent, content: ReactNode) => {
    const box = (e.currentTarget as Element).closest('.chart-box')?.getBoundingClientRect()
    if (!box) return
    setTip({ x: e.clientX - box.left, y: e.clientY - box.top, content })
  }
  const hide = () => setTip(null)
  const node = tip ? (
    <div className="chart-tip" style={{ left: tip.x + 12, top: tip.y - 8 }}>
      {tip.content}
    </div>
  ) : null
  return { show, hide, node }
}

export function Legend({ names }: { names: string[] }) {
  if (names.length < 2) return null
  return (
    <div className="legend">
      {names.map((n, i) => (
        <span key={n} className="legend-item">
          <span className="legend-swatch" style={{ background: SERIES_VARS[i] }} />
          {n}
        </span>
      ))}
    </div>
  )
}

// ── HOMO/LUMO 에너지 준위 다이어그램 ─────────────────────────────
export function EnergyLevelChart({
  entries,
}: {
  entries: { molecule: Molecule; result: DftResult }[]
}) {
  const tip = useTip()
  const W = 560
  const H = 300
  const padL = 46
  const padT = 26
  const padB = 28
  const plotW = W - padL - 12
  const plotH = H - padT - padB

  const values = entries.flatMap((e) => [e.result.homo, e.result.lumo])
  const maxV = Math.ceil(Math.max(...values, 1) + 0.5)
  const minV = Math.floor(Math.min(...values, -1) - 0.5)
  const y = (v: number) => padT + ((maxV - v) / (maxV - minV)) * plotH

  const colW = plotW / entries.length
  const levelW = Math.min(90, colW * 0.55)

  const ticks: number[] = []
  for (let t = minV; t <= maxV; t += 2) ticks.push(t)

  return (
    <div className="chart-box">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="HOMO LUMO 에너지 준위 다이어그램">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - 12} y1={y(t)} y2={y(t)} className="gridline" />
            <text x={padL - 8} y={y(t) + 4} className="axis-label" textAnchor="end">
              {t}
            </text>
          </g>
        ))}
        <text x={12} y={13} className="axis-label">
          eV
        </text>
        {entries.map((e, i) => {
          const cx = padL + colW * i + colW / 2
          const x1 = cx - levelW / 2
          const gapMid = (y(e.result.homo) + y(e.result.lumo)) / 2
          return (
            <g key={e.molecule.id}>
              {/* HOMO */}
              <line
                x1={x1}
                x2={x1 + levelW}
                y1={y(e.result.homo)}
                y2={y(e.result.homo)}
                stroke={SERIES_VARS[i]}
                strokeWidth={3}
                strokeLinecap="round"
                onMouseMove={(ev) =>
                  tip.show(ev, `${e.molecule.abbreviation} HOMO ${e.result.homo.toFixed(2)} eV`)
                }
                onMouseLeave={tip.hide}
              />
              {/* LUMO */}
              <line
                x1={x1}
                x2={x1 + levelW}
                y1={y(e.result.lumo)}
                y2={y(e.result.lumo)}
                stroke={SERIES_VARS[i]}
                strokeWidth={3}
                strokeLinecap="round"
                strokeDasharray="6 4"
                onMouseMove={(ev) =>
                  tip.show(ev, `${e.molecule.abbreviation} LUMO ${e.result.lumo.toFixed(2)} eV`)
                }
                onMouseLeave={tip.hide}
              />
              <line
                x1={cx}
                x2={cx}
                y1={y(e.result.lumo) + 3}
                y2={y(e.result.homo) - 3}
                className="gap-line"
              />
              <text x={cx + 6} y={gapMid + 4} className="value-label">
                {e.result.gap.toFixed(2)} eV
              </text>
              <text x={cx} y={H - 8} className="axis-label" textAnchor="middle">
                {e.molecule.abbreviation}
              </text>
            </g>
          )
        })}
      </svg>
      {tip.node}
      <div className="chart-note">실선 HOMO · 점선 LUMO · 세로선 = 밴드갭</div>
    </div>
  )
}

// ── 표면별 흡착에너지 묶음 막대 ─────────────────────────────────
const SURFACES: Surface[] = ['Graphite', 'Si', 'NMC811', 'LFP']

export function AdhesionBars({
  entries,
}: {
  entries: { molecule: Molecule; result: DftResult }[]
}) {
  const tip = useTip()
  const W = 560
  const H = 280
  const padL = 46
  const padT = 26
  const padB = 28
  const plotW = W - padL - 12
  const plotH = H - padT - padB

  // 흡착에너지는 음수(안정)이므로 |E_ad| 크기로 그린다
  const maxV = Math.max(...entries.flatMap((e) => SURFACES.map((s) => Math.abs(e.result.adhesion[s]))), 0.2)
  const top = Math.ceil(maxV * 10) / 10 + 0.1
  const groupW = plotW / SURFACES.length
  const barW = Math.min(26, (groupW * 0.7) / entries.length)

  const ticks = [0, top / 2, top]

  return (
    <div className="chart-box">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="표면별 흡착에너지 비교">
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={padL}
              x2={W - 12}
              y1={padT + plotH - (t / top) * plotH}
              y2={padT + plotH - (t / top) * plotH}
              className={t === 0 ? 'baseline' : 'gridline'}
            />
            <text
              x={padL - 8}
              y={padT + plotH - (t / top) * plotH + 4}
              className="axis-label"
              textAnchor="end"
            >
              {t.toFixed(1)}
            </text>
          </g>
        ))}
        <text x={12} y={13} className="axis-label">
          |E_ad| (eV)
        </text>
        {SURFACES.map((surf, gi) => {
          const gx = padL + groupW * gi + groupW / 2
          const total = entries.length * barW + (entries.length - 1) * 2
          return (
            <g key={surf}>
              {entries.map((e, i) => {
                const v = Math.abs(e.result.adhesion[surf])
                const h = (v / top) * plotH
                const x = gx - total / 2 + i * (barW + 2)
                return (
                  <path
                    key={e.molecule.id}
                    d={`M${x},${padT + plotH} v${-Math.max(h - 4, 0)} q0,-4 4,-4 h${barW - 8} q4,0 4,4 v${Math.max(h - 4, 0)} z`}
                    fill={SERIES_VARS[i]}
                    onMouseMove={(ev) =>
                      tip.show(
                        ev,
                        `${e.molecule.abbreviation} / ${surf}: ${e.result.adhesion[surf].toFixed(2)} eV`,
                      )
                    }
                    onMouseLeave={tip.hide}
                  />
                )
              })}
              <text x={gx} y={H - 8} className="axis-label" textAnchor="middle">
                {surf}
              </text>
            </g>
          )
        })}
      </svg>
      {tip.node}
      <Legend names={entries.map((e) => e.molecule.abbreviation)} />
      <div className="chart-note">막대가 길수록 표면 흡착이 강함 (E_ad 음수 방향)</div>
    </div>
  )
}

// ── 다물성 레이더 차트 ──────────────────────────────────────────
interface Axis {
  key: string
  label: string
  value: (r: DftResult) => number
  max: number
}

const AXES: Axis[] = [
  { key: 'gap', label: '전기화학 안정성\n(gap, eV)', value: (r) => r.gap, max: 12 },
  { key: 'adh', label: 'Si 접착\n(|E_ad|, eV)', value: (r) => Math.abs(r.adhesion.Si), max: 1.6 },
  { key: 'dip', label: '극성\n(μ, D)', value: (r) => r.dipole, max: 8 },
  { key: 'ox', label: '내산화성\n(E_ox, V)', value: (r) => Math.max(r.oxidationPotential, 0), max: 9 },
  { key: 'sol', label: '용매화\n(|ΔG_solv|)', value: (r) => Math.abs(r.solvationEnergy), max: 60 },
]

export function PropertyRadar({
  entries,
}: {
  entries: { molecule: Molecule; result: DftResult }[]
}) {
  const W = 460
  const H = 340
  const cx = W / 2
  const cy = H / 2 + 6
  const R = 108
  const n = AXES.length
  const angle = (i: number) => -Math.PI / 2 + (2 * Math.PI * i) / n
  const pt = (i: number, r: number) => [cx + Math.cos(angle(i)) * r, cy + Math.sin(angle(i)) * r]

  const ringPath = (r: number) =>
    AXES.map((_, i) => pt(i, r))
      .map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`)
      .join(' ') + ' Z'

  return (
    <div className="chart-box">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="다물성 레이더 비교">
        {[0.33, 0.66, 1].map((f) => (
          <path key={f} d={ringPath(R * f)} className="gridline" fill="none" />
        ))}
        {AXES.map((a, i) => {
          const [x, y] = pt(i, R)
          const [lx, ly] = pt(i, R + 26)
          return (
            <g key={a.key}>
              <line x1={cx} y1={cy} x2={x} y2={y} className="gridline" />
              {a.label.split('\n').map((line, li) => (
                <text
                  key={li}
                  x={lx}
                  y={ly + li * 13 - 4}
                  className="axis-label"
                  textAnchor="middle"
                >
                  {line}
                </text>
              ))}
            </g>
          )
        })}
        {entries.map((e, si) => {
          const path =
            AXES.map((a, i) => {
              const f = Math.min(1, a.value(e.result) / a.max)
              const [x, y] = pt(i, R * f)
              return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
            }).join(' ') + ' Z'
          return (
            <g key={e.molecule.id}>
              <path d={path} fill={SERIES_VARS[si]} opacity={0.12} />
              <path d={path} fill="none" stroke={SERIES_VARS[si]} strokeWidth={2} />
              {AXES.map((a, i) => {
                const f = Math.min(1, a.value(e.result) / a.max)
                const [x, y] = pt(i, R * f)
                return (
                  <circle key={a.key} cx={x} cy={y} r={4} fill={SERIES_VARS[si]} className="ring-mark" />
                )
              })}
            </g>
          )
        })}
      </svg>
      <Legend names={entries.map((e) => e.molecule.abbreviation)} />
      <div className="chart-note">축별 정규화 값 — 바깥쪽일수록 해당 물성이 큼</div>
    </div>
  )
}
