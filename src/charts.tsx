import { useState, type ReactNode } from 'react'
import type { DescriptorValue } from './types'
import { descriptorByKey } from './data/descriptors'

// 시리즈 색은 테마 CSS 변수(--series-N)를 사용 — 사용자 설정에 즉시 반영 (기획서 14)
export const seriesColor = (i: number) => `var(--series-${(i % 8) + 1})`

export interface SeriesEntry {
  label: string
  color: string
  values: Record<string, DescriptorValue>
  overlay?: boolean // 참고 오버레이 (점선·출처 배지)
  badge?: string
}

const trunc = (s: string, n = 15) => (s.length > n ? s.slice(0, n - 1) + '…' : s)

function useTip() {
  const [tip, setTip] = useState<{ x: number; y: number; content: ReactNode } | null>(null)
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

export function Legend({ entries }: { entries: SeriesEntry[] }) {
  if (entries.length < 2) return null
  return (
    <div className="legend">
      {entries.map((e) => (
        <span key={e.label + (e.badge ?? '')} className="legend-item">
          <span
            className="legend-swatch"
            style={{ background: e.overlay ? 'transparent' : e.color, border: e.overlay ? `2px dashed ${e.color}` : 'none' }}
          />
          {e.label}
          {e.badge && <span className="badge overlay-badge">{e.badge}</span>}
        </span>
      ))}
    </div>
  )
}

// ── 전기화학 안정 전압 범위 (기획서 6.3: 기본 축 0~6 V 수평 막대) ──
export function VoltageWindowChart({ entries }: { entries: SeriesEntry[] }) {
  const tip = useTip()
  const rows = entries.filter(
    (e) => e.values.binder_reduction_potential || e.values.binder_oxidation_potential,
  )
  if (!rows.length) return null

  const allV = rows.flatMap((e) => [
    e.values.binder_reduction_potential?.value ?? 0,
    e.values.binder_oxidation_potential?.value ?? 6,
  ])
  const min = Math.min(0, Math.floor(Math.min(...allV)))
  const max = Math.max(6, Math.ceil(Math.max(...allV)))

  const W = 640
  const rowH = 40
  const padL = 110
  const padT = 26
  const H = padT + rows.length * rowH + 28
  const plotW = W - padL - 20
  const x = (v: number) => padL + ((v - min) / (max - min)) * plotW

  const ticks: number[] = []
  for (let t = min; t <= max; t++) ticks.push(t)

  return (
    <div className="chart-box">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="전기화학 안정 전압 범위 비교">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={padT} y2={H - 26} className={t === 0 ? 'baseline' : 'gridline'} />
            <text x={x(t)} y={H - 12} className="axis-label" textAnchor="middle">
              {t}
            </text>
          </g>
        ))}
        <text x={W - 20} y={14} className="axis-label" textAnchor="end">
          V vs 기준전극
        </text>
        {rows.map((e, i) => {
          const red = e.values.binder_reduction_potential?.value
          const ox = e.values.binder_oxidation_potential?.value
          const y = padT + i * rowH + rowH / 2
          const window = red !== undefined && ox !== undefined ? (ox - red).toFixed(2) : null
          return (
            <g
              key={e.label + (e.overlay ? '-ov' : '')}
              onMouseMove={(ev) =>
                tip.show(
                  ev,
                  `${e.label}: 환원 ${red?.toFixed(2) ?? '—'} V · 산화 ${ox?.toFixed(2) ?? '—'} V${window ? ` · window ${window} V` : ''}`,
                )
              }
              onMouseLeave={tip.hide}
            >
              <text x={padL - 8} y={y + 4} className="axis-label" textAnchor="end">
                {trunc(e.label)}
              </text>
              {red !== undefined && ox !== undefined && (
                <line
                  x1={x(red)}
                  x2={x(ox)}
                  y1={y}
                  y2={y}
                  stroke={e.color}
                  strokeWidth={e.overlay ? 3 : 8}
                  strokeLinecap="round"
                  strokeDasharray={e.overlay ? '5 5' : undefined}
                  opacity={e.overlay ? 0.85 : 1}
                />
              )}
              {red !== undefined && (
                <>
                  <line x1={x(red)} x2={x(red)} y1={y - 9} y2={y + 9} stroke={e.color} strokeWidth={2.5} />
                  <text x={x(red)} y={y - 13} className="value-label" textAnchor="middle">
                    {red.toFixed(2)}
                  </text>
                </>
              )}
              {ox !== undefined && (
                <>
                  <line x1={x(ox)} x2={x(ox)} y1={y - 9} y2={y + 9} stroke={e.color} strokeWidth={2.5} />
                  <text x={x(ox)} y={y - 13} className="value-label" textAnchor="middle">
                    {ox.toFixed(2)}
                  </text>
                </>
              )}
            </g>
          )
        })}
      </svg>
      {tip.node}
      <div className="chart-note">왼쪽 = 환원 한계, 오른쪽 = 산화 한계, 막대 = 안정 구간 (동일 기준 전극)</div>
    </div>
  )
}

// ── HOMO/LUMO 공통 축 range bar (기획서 6.3: 기본 축 -8~1 eV) ────
export function HomoLumoChart({ entries }: { entries: SeriesEntry[] }) {
  const tip = useTip()
  const rows = entries.filter((e) => e.values.binder_homo && e.values.binder_lumo)
  if (!rows.length) return null

  const allE = rows.flatMap((e) => [e.values.binder_homo.value, e.values.binder_lumo.value])
  const min = Math.min(-8, Math.floor(Math.min(...allE)))
  const max = Math.max(1, Math.ceil(Math.max(...allE)))

  const W = 640
  const rowH = 40
  const padL = 110
  const padT = 26
  const H = padT + rows.length * rowH + 28
  const plotW = W - padL - 20
  const x = (v: number) => padL + ((v - min) / (max - min)) * plotW

  const ticks: number[] = []
  for (let t = min; t <= max; t += 1) ticks.push(t)

  return (
    <div className="chart-box">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="HOMO LUMO 공통 축 비교">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={padT} y2={H - 26} className={t === 0 ? 'baseline' : 'gridline'} />
            <text x={x(t)} y={H - 12} className="axis-label" textAnchor="middle">
              {t}
            </text>
          </g>
        ))}
        <text x={W - 20} y={14} className="axis-label" textAnchor="end">
          eV
        </text>
        {rows.map((e, i) => {
          const homo = e.values.binder_homo.value
          const lumo = e.values.binder_lumo.value
          const gap = e.values.binder_homo_lumo_gap?.value ?? lumo - homo
          const y = padT + i * rowH + rowH / 2
          return (
            <g
              key={e.label + (e.overlay ? '-ov' : '')}
              onMouseMove={(ev) =>
                tip.show(ev, `${e.label}: HOMO ${homo.toFixed(2)} · LUMO ${lumo.toFixed(2)} · gap ${gap.toFixed(2)} eV`)
              }
              onMouseLeave={tip.hide}
            >
              <text x={padL - 8} y={y + 4} className="axis-label" textAnchor="end">
                {trunc(e.label)}
              </text>
              <line
                x1={x(homo)}
                x2={x(lumo)}
                y1={y}
                y2={y}
                stroke={e.color}
                strokeWidth={e.overlay ? 3 : 8}
                strokeLinecap="round"
                strokeDasharray={e.overlay ? '5 5' : undefined}
                opacity={e.overlay ? 0.85 : 0.55}
              />
              <line x1={x(homo)} x2={x(homo)} y1={y - 9} y2={y + 9} stroke={e.color} strokeWidth={3} />
              <line x1={x(lumo)} x2={x(lumo)} y1={y - 9} y2={y + 9} stroke={e.color} strokeWidth={3} />
              <text x={x(homo)} y={y - 13} className="value-label" textAnchor="middle">
                {homo.toFixed(2)}
              </text>
              <text x={x(lumo)} y={y - 13} className="value-label" textAnchor="middle">
                {lumo.toFixed(2)}
              </text>
            </g>
          )
        })}
      </svg>
      {tip.node}
      <div className="chart-note">왼쪽 끝 = HOMO, 오른쪽 끝 = LUMO, 막대 길이 = gap (전자구조 경향 보조 지표)</div>
    </div>
  )
}

// ── 물성 지문 레이더 (기획서 14.3: 고정 descriptor만 축으로 사용) ──
export function FingerprintRadar({
  entries,
  pinKeys,
}: {
  entries: SeriesEntry[]
  pinKeys: string[]
}) {
  const tip = useTip()
  const axes = pinKeys.map((k) => descriptorByKey(k)).filter((d): d is NonNullable<typeof d> => !!d && !d.interfacial)
  if (axes.length < 3) {
    return (
      <div className="empty small">
        레이더 표시에는 고정(★) 물성이 3개 이상 필요합니다. 물성 사전 또는 결과 화면에서 ★를 추가하세요.
      </div>
    )
  }

  const W = 520
  const H = 400
  const cx = W / 2
  const cy = H / 2 + 4
  const R = 128
  const n = axes.length
  const angle = (i: number) => -Math.PI / 2 + (2 * Math.PI * i) / n
  const pt = (i: number, r: number) => [cx + Math.cos(angle(i)) * r, cy + Math.sin(angle(i)) * r]

  // 방향성 정규화: direction=lower 는 더 작은(더 음수) 값이 바깥 (기획서 14.3)
  const norm = (d: (typeof axes)[number], v: number) => {
    const f = (v - d.radarMin) / (d.radarMax - d.radarMin)
    const clamped = Math.max(0.04, Math.min(1, f))
    return d.direction === 'lower' ? 1.04 - clamped : clamped
  }

  const ringPath = (r: number) =>
    axes.map((_, i) => pt(i, r)).map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ') + ' Z'

  return (
    <div className="chart-box">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="물성 지문 레이더">
        {[0.33, 0.66, 1].map((f) => (
          <path key={f} d={ringPath(R * f)} className="gridline" fill="none" />
        ))}
        {axes.map((a, i) => {
          const [x, y] = pt(i, R)
          const [lx, ly] = pt(i, R + 30)
          return (
            <g key={a.key}>
              <line x1={cx} y1={cy} x2={x} y2={y} className="gridline" />
              <text x={lx} y={ly} className="axis-label" textAnchor="middle">
                {a.label.length > 14 ? a.label.slice(0, 13) + '…' : a.label}
              </text>
              <text x={lx} y={ly + 12} className="axis-label" textAnchor="middle">
                ({a.unit.split(' ')[0]}{a.direction === 'lower' ? ', ↓바깥' : ''})
              </text>
            </g>
          )
        })}
        {entries.map((e) => {
          const pts = axes.map((a, i) => {
            const dv = e.values[a.key]
            const f = dv ? norm(a, dv.value) : 0.04
            return pt(i, R * f)
          })
          const path = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ') + ' Z'
          return (
            <g key={e.label}>
              <path d={path} fill={e.color} opacity={0.08} />
              <path d={path} fill="none" stroke={e.color} strokeWidth={2} strokeDasharray={e.overlay ? '5 5' : undefined} />
              {pts.map(([x, y], i) => {
                const dv = e.values[axes[i].key]
                return (
                  <circle
                    key={axes[i].key}
                    cx={x}
                    cy={y}
                    r={4.5}
                    fill={e.color}
                    className="ring-mark"
                    onMouseMove={(ev) =>
                      tip.show(
                        ev,
                        dv
                          ? `${e.label} · ${axes[i].label}: ${dv.value} ${dv.unit}`
                          : `${e.label} · ${axes[i].label}: 값 없음`,
                      )
                    }
                    onMouseLeave={tip.hide}
                  />
                )
              })}
            </g>
          )
        })}
      </svg>
      {tip.node}
      <div className="chart-note">
        고정(★) 물성만 축으로 사용. min-max 정규화이며 점에 마우스를 올리면 원값·단위를 표시합니다.
      </div>
    </div>
  )
}

// ── 에너지 준위 다이어그램 (세로형: 실선 HOMO · 점선 LUMO · 밴드갭) ──
export function EnergyLevelDiagram({ entries }: { entries: SeriesEntry[] }) {
  const tip = useTip()
  const rows = entries.filter((e) => e.values.binder_homo && e.values.binder_lumo && !e.overlay)
  if (!rows.length) return null

  const W = 640
  const H = 320
  const padL = 46
  const padT = 26
  const padB = 30
  const plotW = W - padL - 14
  const plotH = H - padT - padB

  const all = rows.flatMap((e) => [e.values.binder_homo.value, e.values.binder_lumo.value])
  const maxV = Math.ceil(Math.max(...all, 1) + 0.5)
  const minV = Math.floor(Math.min(...all, -1) - 0.5)
  const y = (v: number) => padT + ((maxV - v) / (maxV - minV)) * plotH

  const colW = plotW / rows.length
  const levelW = Math.min(90, colW * 0.55)
  const ticks: number[] = []
  for (let t = minV; t <= maxV; t += 2) ticks.push(t)

  return (
    <div className="chart-box">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="HOMO LUMO 에너지 준위 다이어그램">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - 14} y1={y(t)} y2={y(t)} className="gridline" />
            <text x={padL - 8} y={y(t) + 4} className="axis-label" textAnchor="end">
              {t}
            </text>
          </g>
        ))}
        <text x={14} y={14} className="axis-label">
          eV
        </text>
        {rows.map((e, i) => {
          const homo = e.values.binder_homo.value
          const lumo = e.values.binder_lumo.value
          const gap = e.values.binder_homo_lumo_gap?.value ?? lumo - homo
          const cx = padL + colW * i + colW / 2
          const x1 = cx - levelW / 2
          const mid = (y(homo) + y(lumo)) / 2
          return (
            <g key={e.label}>
              <line
                x1={x1}
                x2={x1 + levelW}
                y1={y(homo)}
                y2={y(homo)}
                stroke={e.color}
                strokeWidth={3}
                strokeLinecap="round"
                onMouseMove={(ev) => tip.show(ev, `${e.label} HOMO ${homo.toFixed(2)} eV`)}
                onMouseLeave={tip.hide}
              />
              <line
                x1={x1}
                x2={x1 + levelW}
                y1={y(lumo)}
                y2={y(lumo)}
                stroke={e.color}
                strokeWidth={3}
                strokeLinecap="round"
                strokeDasharray="6 4"
                onMouseMove={(ev) => tip.show(ev, `${e.label} LUMO ${lumo.toFixed(2)} eV`)}
                onMouseLeave={tip.hide}
              />
              <line x1={cx} x2={cx} y1={y(lumo) + 3} y2={y(homo) - 3} className="gridline" strokeDasharray="2 3" />
              <text x={cx + 6} y={mid + 4} className="value-label">
                {gap.toFixed(2)} eV
              </text>
              <text x={cx} y={H - 10} className="axis-label" textAnchor="middle">
                {trunc(e.label, 12)}
              </text>
            </g>
          )
        })}
      </svg>
      {tip.node}
      <div className="chart-note">실선 = HOMO · 점선 = LUMO · 세로 점선 = 밴드갭 (전자구조 경향 보조 지표)</div>
    </div>
  )
}

// ── 활물질 표면 흡착에너지 묶음 막대 (|E_ad|, kJ/mol) ─────────────
const ADHESION_SURFACES: { key: string; label: string }[] = [
  { key: 'binder_adhesion_graphite', label: 'Graphite' },
  { key: 'binder_adhesion_si', label: 'Si' },
  { key: 'binder_adhesion_nmc811', label: 'NMC811' },
  { key: 'binder_adhesion_lfp', label: 'LFP' },
]

export function SurfaceAdhesionBars({ entries }: { entries: SeriesEntry[] }) {
  const tip = useTip()
  const rows = entries.filter((e) => !e.overlay && ADHESION_SURFACES.some((s) => e.values[s.key]))
  if (!rows.length) {
    return (
      <div className="empty small">
        표면 흡착에너지 값이 없는 결과입니다. 최신 엔진으로 재계산하면 표시됩니다.
      </div>
    )
  }

  const W = 640
  const H = 300
  const padL = 52
  const padT = 26
  const padB = 30
  const plotW = W - padL - 14
  const plotH = H - padT - padB

  const maxV = Math.max(
    ...rows.flatMap((e) => ADHESION_SURFACES.map((s) => Math.abs(e.values[s.key]?.value ?? 0))),
    10,
  )
  const top = Math.ceil(maxV / 20) * 20 + 10
  const groupW = plotW / ADHESION_SURFACES.length
  const barW = Math.min(24, (groupW * 0.72) / rows.length)
  const ticks = [0, top / 2, top]

  return (
    <div className="chart-box">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="활물질 표면 흡착에너지 비교">
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={padL}
              x2={W - 14}
              y1={padT + plotH - (t / top) * plotH}
              y2={padT + plotH - (t / top) * plotH}
              className={t === 0 ? 'baseline' : 'gridline'}
            />
            <text x={padL - 8} y={padT + plotH - (t / top) * plotH + 4} className="axis-label" textAnchor="end">
              {Math.round(t)}
            </text>
          </g>
        ))}
        <text x={14} y={14} className="axis-label">
          |E_ad| (kJ/mol)
        </text>
        {ADHESION_SURFACES.map((surf, gi) => {
          const gx = padL + groupW * gi + groupW / 2
          const total = rows.length * barW + (rows.length - 1) * 2
          return (
            <g key={surf.key}>
              {rows.map((e, i) => {
                const dv = e.values[surf.key]
                if (!dv) return null
                const v = Math.abs(dv.value)
                const h = (v / top) * plotH
                const x = gx - total / 2 + i * (barW + 2)
                return (
                  <path
                    key={e.label}
                    d={`M${x},${padT + plotH} v${-Math.max(h - 4, 0)} q0,-4 4,-4 h${barW - 8} q4,0 4,4 v${Math.max(h - 4, 0)} z`}
                    fill={e.color}
                    onMouseMove={(ev) => tip.show(ev, `${e.label} / ${surf.label}: ${dv.value} ${dv.unit}`)}
                    onMouseLeave={tip.hide}
                  />
                )
              })}
              <text x={gx} y={H - 10} className="axis-label" textAnchor="middle">
                {surf.label}
              </text>
            </g>
          )
        })}
      </svg>
      {tip.node}
      <div className="chart-note">
        막대가 길수록 해당 표면 흡착이 강함 (E_ad 음수 방향). 표면 모델이 다른 값과는 비교 금지 (부록 D).
      </div>
    </div>
  )
}
