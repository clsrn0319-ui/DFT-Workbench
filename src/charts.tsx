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
