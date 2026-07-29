import { useMemo, useState } from 'react'
import { Molecule3D } from './Molecule3D'
import { buildMolGraph, type Atom3D, type MolGraph } from './molGraph'
import type { DescriptorValue } from '../types'

// 거리-에너지 상호작용 탐색기 (dft_information 2장 — 반응/결합 에너지의 시각화)
// 파트너(Li⁺/PF₆⁻/바인더 dimer/활물질 표면)와의 거리를 슬라이더로 바꾸면
// 모스 퍼텐셜 근사 에너지 곡선과 함께 구조 변형(인력/반발)을 3D로 보여준다.

type Partner = 'Li⁺' | 'PF₆⁻' | '바인더 dimer' | 'Si 표면'

const PARTNERS: { id: Partner; re: number; deKey: string; deFallback: number; desc: string }[] = [
  { id: 'Li⁺', re: 1.95, deKey: 'binder_li_binding_energy', deFallback: 100, desc: 'Li–O/N 배위 (평형 ≈ 2.0 Å)' },
  { id: 'PF₆⁻', re: 3.0, deKey: 'binder_pf6_binding_energy', deFallback: 25, desc: '음이온-분자 정전기 (평형 ≈ 3.0 Å)' },
  { id: '바인더 dimer', re: 2.9, deKey: 'binder_binder_hbond_energy', deFallback: 20, desc: '수소결합/쌍극자 dimer (평형 ≈ 2.9 Å)' },
  { id: 'Si 표면', re: 3.3, deKey: 'binder_adhesion_si', deFallback: 60, desc: '표면 흡착 (평형 ≈ 3.3 Å)' },
]

const A_MORSE = 1.5 // 모스 퍼텐셜 폭 파라미터 (Å⁻¹)

function morse(de: number, re: number, d: number): number {
  const t = 1 - Math.exp(-A_MORSE * (d - re))
  return de * (t * t - 1) // d=re에서 -De, d→∞에서 0
}

export function InteractionExplorer({
  smiles,
  descriptors,
}: {
  smiles: string
  descriptors?: Record<string, DescriptorValue>
}) {
  const [partnerId, setPartnerId] = useState<Partner>('Li⁺')
  const [d, setD] = useState(4.0)

  const partner = PARTNERS.find((p) => p.id === partnerId)!
  const de = Math.abs(descriptors?.[partner.deKey]?.value ?? partner.deFallback) // kJ/mol
  const energy = morse(de, partner.re, d)

  const scene = useMemo(() => buildScene(smiles, partnerId, d, partner.re), [smiles, partnerId, d, partner.re])

  // 에너지 곡선
  const W = 560
  const H = 210
  const padL = 52
  const padT = 16
  const padB = 30
  const plotW = W - padL - 16
  const plotH = H - padT - padB
  const dMin = 1.2
  const dMax = 8
  const eMin = -de * 1.08
  const eMax = Math.min(de * 0.9, 160)
  const x = (dd: number) => padL + ((dd - dMin) / (dMax - dMin)) * plotW
  const y = (e: number) => padT + ((eMax - e) / (eMax - eMin)) * plotH

  const curve = useMemo(() => {
    const pts: string[] = []
    for (let dd = dMin; dd <= dMax; dd += 0.06) {
      const e = Math.min(morse(de, partner.re, dd), eMax)
      pts.push(`${pts.length ? 'L' : 'M'}${x(dd).toFixed(1)},${y(e).toFixed(1)}`)
    }
    return pts.join(' ')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [de, partner.re, eMax])

  const regime = d < partner.re - 0.25 ? '반발 구간 — 전자구름 겹침으로 에너지 급상승, 구조가 밀려남' : d < partner.re + 0.4 ? '평형 구간 — 가장 안정한 결합 거리, 결합 부위가 파트너 쪽으로 끌림' : d < 6 ? '인력 구간 — 정전기/분산 인력이 작용' : '분리 상태 — 상호작용 거의 없음'

  return (
    <div>
      <div className="conf-controls">
        <div className="seg">
          {PARTNERS.map((p) => (
            <button key={p.id} className={partnerId === p.id ? 'on' : ''} onClick={() => setPartnerId(p.id)}>
              {p.id}
            </button>
          ))}
        </div>
        <label className="small">
          거리 d = <b>{d.toFixed(1)} Å</b>
          <input type="range" min={dMin} max={dMax} step={0.1} value={d} onChange={(e) => setD(parseFloat(e.target.value))} />
        </label>
      </div>

      <div className="conf-grid">
        <div>
          <Molecule3D smiles={smiles} colorMode="charge" height={280} graphOverride={scene} />
        </div>
        <div className="chart-box">
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="거리에 따른 상호작용 에너지 곡선">
            {[eMax, 0, -de].map((e) => (
              <g key={e}>
                <line x1={padL} x2={W - 16} y1={y(e)} y2={y(e)} className={e === 0 ? 'baseline' : 'gridline'} />
                <text x={padL - 6} y={y(e) + 4} className="axis-label" textAnchor="end">
                  {Math.round(e)}
                </text>
              </g>
            ))}
            {[2, 4, 6, 8].map((dd) => (
              <text key={dd} x={x(dd)} y={H - 10} className="axis-label" textAnchor="middle">
                {dd}
              </text>
            ))}
            <path d={curve} fill="none" stroke="var(--accent)" strokeWidth={2} />
            {/* 평형 거리 */}
            <line x1={x(partner.re)} x2={x(partner.re)} y1={padT} y2={H - padB} stroke="var(--muted)" strokeWidth={1} strokeDasharray="3 3" />
            <text x={x(partner.re)} y={padT - 2} className="axis-label" textAnchor="middle">
              r_e
            </text>
            {/* 현재 위치 */}
            <circle cx={x(d)} cy={y(Math.min(energy, eMax))} r={6} fill="var(--pin)" className="ring-mark" />
            <text x={x(d) + 8} y={y(Math.min(energy, eMax)) - 8} className="value-label">
              {energy.toFixed(1)} kJ/mol
            </text>
            <text x={W - 16} y={H - 10} className="axis-label" textAnchor="end">
              d (Å)
            </text>
            <text x={12} y={12} className="axis-label">
              E (kJ/mol)
            </text>
          </svg>
          <div className="banner" style={{ marginTop: 8 }}>
            <b>{regime}</b>
            <div className="small muted">
              {partner.desc} · 결합 깊이 De = {de.toFixed(0)} kJ/mol
              {descriptors?.[partner.deKey] ? ' (PUBLISHED 계산값)' : ' (기본 근사값 — 계산 후 실제값 사용)'}
            </div>
          </div>
        </div>
      </div>
      <div className="chart-note">
        모스 퍼텐셜 근사 시뮬레이션 — 곡선의 우물 깊이는 결합 에너지, r_e는 평형 거리입니다. 거리를 평형보다
        줄이면 반발로 구조가 찌그러지고, 평형 부근에서 결합 부위가 파트너 쪽으로 끌립니다. 실제 relaxed scan은
        백엔드 연동 시 제공됩니다.
      </div>
    </div>
  )
}

// ── 3D 장면 구성: 분자(변형) + 파트너를 거리 d에 배치 ─────────────
function buildScene(smiles: string, partnerId: Partner, d: number, re: number): MolGraph | null {
  const base = buildMolGraph(smiles)
  if (!base) return null

  // 결합 부위 = 가장 음전하가 큰 중원자 (Li⁺/표면 기준), dimer/PF6는 양전하 부위
  const wantNegative = partnerId === 'Li⁺' || partnerId === 'Si 표면'
  let siteIdx = 0
  let best = wantNegative ? Infinity : -Infinity
  base.atoms.forEach((a, i) => {
    if (a.isH) return
    if (wantNegative ? a.charge < best : a.charge > best) {
      best = a.charge
      siteIdx = i
    }
  })
  const site = base.atoms[siteIdx]

  // 구조 변형: 평형 부근 인력(파트너 쪽 끌림) / 근접 반발(밀림)
  const s = d - re
  const k = s < 0 ? -0.5 * Math.min(1, (re - d) / re) : 0.28 * Math.exp(-s / 1.4)
  const atoms: Atom3D[] = base.atoms.map((a) => {
    const distToSite = Math.hypot(a.x - site.x, a.y - site.y, a.z - site.z)
    const w = Math.exp(-distToSite / 1.8)
    return { ...a, x: a.x + k * w }
  })
  const bonds = base.bonds.map((b) => ({ ...b }))

  // 파트너 배치 (+x 방향, site로부터 d)
  const px = site.x + k * 1 + d
  const py = site.y
  const pz = site.z
  const push = (a: Atom3D) => {
    atoms.push(a)
    return atoms.length - 1
  }

  if (partnerId === 'Li⁺') {
    push({ element: 'Li', x: px, y: py, z: pz, charge: 0.9, formalCharge: 1, isH: false })
  } else if (partnerId === 'PF₆⁻') {
    const p = push({ element: 'P', x: px + 1.6, y: py, z: pz, charge: 0.6, formalCharge: 0, isH: false })
    const dirs = [
      [-1.6, 0, 0], [1.6, 0, 0], [0, 1.6, 0], [0, -1.6, 0], [0, 0, 1.6], [0, 0, -1.6],
    ]
    dirs.forEach(([ax, ay, az]) => {
      const f = push({ element: 'F', x: px + 1.6 + ax, y: py + ay, z: pz + az, charge: -0.35, formalCharge: 0, isH: false })
      bonds.push({ a: p, b: f, order: 1 })
    })
  } else if (partnerId === '바인더 dimer') {
    // 같은 분자를 미러링해 배치
    const offset = px + (site.x - Math.min(...base.atoms.map((a) => a.x)))
    const start = atoms.length
    base.atoms.forEach((a) => {
      push({ ...a, x: offset + (site.x - a.x), y: a.y, z: -a.z })
    })
    base.bonds.forEach((b) => bonds.push({ a: start + b.a, b: start + b.b, order: b.order }))
  } else {
    // Si 표면: 3×5 슬랩
    for (let row = 0; row < 3; row++) {
      for (let col = -2; col <= 2; col++) {
        push({
          element: 'Si',
          x: px + row * 2.0,
          y: py + col * 2.2,
          z: pz + (row % 2 === 0 ? 0 : 1.1),
          charge: 0.05,
          formalCharge: 0,
          isH: false,
        })
      }
    }
  }

  return { atoms, bonds }
}
