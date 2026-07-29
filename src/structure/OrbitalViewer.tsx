import { useEffect, useMemo, useRef, useState } from 'react'
import { CPK, buildMolGraph, type MolGraph } from './molGraph'
import { useStore } from '../store'

// Spartan 스타일 양자화학 3D 시각화 (DFT 계산 후 결과 표면)
// - HOMO/LUMO: 원자별 LCAO 계수 근사 → p형 위상 로브 (+/− 색), 결합성/반결합성 위상 패턴
// - ESP 표면: vdW 합집합 표면 점군에 정전기 퍼텐셜 V(p)=Σq/r 매핑
// - 전자밀도: 동일 표면의 단색 등가면
// 실제 cube 파일(격자 등가면)은 백엔드 연동 시 이 렌더러에 그대로 매핑된다.

export type QCMode = 'HOMO' | 'LUMO' | 'ESP' | 'DENSITY'

const VDW_REAL: Record<string, number> = {
  H: 1.1, C: 1.7, N: 1.55, O: 1.52, F: 1.47, Cl: 1.75, S: 1.8, P: 1.8, Li: 1.8, Na: 2.2, K: 2.7, Si: 2.1,
}

interface SurfPoint {
  x: number
  y: number
  z: number
  esp: number
}

interface Lobe {
  x: number
  y: number
  z: number
  r: number
  sign: 1 | -1
  ptype: boolean // true = p형(위/아래 쌍), false = 고립전자쌍 s형 블롭
}

function fibSphere(n: number): [number, number, number][] {
  const pts: [number, number, number][] = []
  const phi = Math.PI * (3 - Math.sqrt(5))
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2
    const r = Math.sqrt(1 - y * y)
    const th = phi * i
    pts.push([Math.cos(th) * r, y, Math.sin(th) * r])
  }
  return pts
}

function buildSurface(mol: MolGraph, scale: number): SurfPoint[] {
  const pts: SurfPoint[] = []
  const dirsHeavy = fibSphere(120)
  const dirsH = fibSphere(45)
  mol.atoms.forEach((a, i) => {
    const R = (VDW_REAL[a.element] ?? 1.6) * scale
    const dirs = a.isH ? dirsH : dirsHeavy
    for (const [dx, dy, dz] of dirs) {
      const px = a.x + dx * R
      const py = a.y + dy * R
      const pz = a.z + dz * R
      let inside = false
      for (let j = 0; j < mol.atoms.length; j++) {
        if (j === i) continue
        const b = mol.atoms[j]
        const Rj = (VDW_REAL[b.element] ?? 1.6) * scale
        if ((px - b.x) ** 2 + (py - b.y) ** 2 + (pz - b.z) ** 2 < (Rj - 0.06) ** 2) {
          inside = true
          break
        }
      }
      if (inside) continue
      // ESP: 부분전하 쿨롱 합
      let v = 0
      for (const b of mol.atoms) {
        const dist = Math.max(Math.hypot(px - b.x, py - b.y, pz - b.z), 0.6)
        v += b.charge / dist
      }
      pts.push({ x: px, y: py, z: pz, esp: v })
    }
  })
  return pts
}

// LCAO 근사 오비탈 계수: HOMO = 전자풍부 π/고립전자쌍(결합성 — 인접 동일 위상),
// LUMO = π* (반결합성 — 인접 위상 교대)
function buildOrbital(mol: MolGraph, which: 'HOMO' | 'LUMO'): Lobe[] {
  const heavy = mol.atoms.map((a, i) => ({ a, i })).filter(({ a }) => !a.isH)
  const isPi = (i: number) => mol.bonds.some((b) => (b.a === i || b.b === i) && b.order >= 2)
  const lonePair = (i: number) => ['O', 'N', 'F'].includes(mol.atoms[i].element)

  const members: { i: number; w: number; ptype: boolean }[] = []
  for (const { a, i } of heavy) {
    if (which === 'HOMO') {
      if (lonePair(i)) members.push({ i, w: a.element === 'O' ? 1 : 0.85, ptype: isPi(i) })
      else if (isPi(i)) members.push({ i, w: 0.8, ptype: true })
    } else {
      if (isPi(i)) members.push({ i, w: a.element === 'C' ? 0.95 : 0.6, ptype: true })
      else if (a.element === 'C' && mol.bonds.some((b) => (b.a === i || b.b === i) && lonePair(b.a === i ? b.b : b.a)))
        members.push({ i, w: 0.45, ptype: false }) // σ* 성분
    }
  }
  if (!members.length) {
    // π계가 없으면 고립전자쌍/최고 |전하| 원자에 배치
    const sorted = [...heavy].sort((x, y) => Math.abs(y.a.charge) - Math.abs(x.a.charge)).slice(0, 3)
    for (const { i } of sorted) members.push({ i, w: 0.7, ptype: false })
  }

  // 위상: BFS 깊이 — HOMO는 결합성(같은 위상 유지), LUMO는 반결합성(교대)
  const memberSet = new Set(members.map((m) => m.i))
  const sign = new Map<number, 1 | -1>()
  for (const m of members) {
    if (sign.has(m.i)) continue
    const queue: { i: number; s: 1 | -1 }[] = [{ i: m.i, s: 1 }]
    while (queue.length) {
      const { i, s } = queue.shift()!
      if (sign.has(i)) continue
      sign.set(i, s)
      for (const b of mol.bonds) {
        const other = b.a === i ? b.b : b.b === i ? b.a : -1
        if (other >= 0 && memberSet.has(other) && !sign.has(other)) {
          queue.push({ i: other, s: which === 'LUMO' ? ((-s) as 1 | -1) : s })
        }
      }
    }
  }

  return members.map((m) => {
    const a = mol.atoms[m.i]
    return { x: a.x, y: a.y, z: a.z, r: 0.42 + m.w * 0.34, sign: sign.get(m.i) ?? 1, ptype: m.ptype }
  })
}

export function OrbitalViewer({
  smiles,
  homo,
  lumo,
  espRange,
}: {
  smiles: string
  homo?: number
  lumo?: number
  espRange?: [number | undefined, number | undefined]
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const { theme } = useStore()
  const [mode, setMode] = useState<QCMode>('ESP')
  const [surfScale, setSurfScale] = useState(1.0)
  const rotation = useRef({ yaw: 0.6, pitch: -0.5 })
  const zoom = useRef(1)
  const dragging = useRef(false)
  const auto = useRef(true)

  const mol = useMemo(() => buildMolGraph(smiles), [smiles])
  const surface = useMemo(() => (mol ? buildSurface(mol, surfScale) : []), [mol, surfScale])
  const lobes = useMemo(
    () => (mol && (mode === 'HOMO' || mode === 'LUMO') ? buildOrbital(mol, mode) : []),
    [mol, mode],
  )

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !mol) return
    const ctx = canvas.getContext('2d')!
    const dpr = window.devicePixelRatio || 1
    let raf = 0

    const hex2rgb = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number]
    const neg = hex2rgb(theme.mepNegative)
    const pos = hex2rgb(theme.mepPositive)
    const neutral: [number, number, number] = theme.mode === 'dark' ? [150, 150, 146] : [185, 184, 178]

    const espColor = (v: number, alpha: number) => {
      const t = Math.max(-1, Math.min(1, v / 0.32))
      const c = t < 0 ? neg : pos
      const f = Math.abs(t)
      const r = Math.round(neutral[0] + (c[0] - neutral[0]) * f)
      const g = Math.round(neutral[1] + (c[1] - neutral[1]) * f)
      const b = Math.round(neutral[2] + (c[2] - neutral[2]) * f)
      return `rgba(${r},${g},${b},${alpha})`
    }

    const render = () => {
      const w = canvas.clientWidth
      const h = canvas.clientHeight
      if (canvas.width !== w * dpr) {
        canvas.width = w * dpr
        canvas.height = h * dpr
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)

      const { yaw, pitch } = rotation.current
      const cy = Math.cos(yaw)
      const sy = Math.sin(yaw)
      const cp = Math.cos(pitch)
      const sp = Math.sin(pitch)
      const tf = (x: number, y: number, z: number) => {
        const x1 = x * cy + z * sy
        const z1 = -x * sy + z * cy
        const y2 = y * cp - z1 * sp
        const z2 = y * sp + z1 * cp
        return { x: x1, y: y2, z: z2 }
      }

      const span = Math.max(...mol.atoms.map((a) => Math.hypot(a.x, a.y, a.z)), 1.6) + 1.9
      const scale = (Math.min(w, h) / (span * 2.3)) * zoom.current
      const X = (p: { x: number }) => w / 2 + p.x * scale
      const Y = (p: { y: number }) => h / 2 + p.y * scale

      // 골격 (licorice)
      const apts = mol.atoms.map((a) => tf(a.x, a.y, a.z))
      for (const b of mol.bonds) {
        const A = apts[b.a]
        const B = apts[b.b]
        ctx.strokeStyle = theme.mode === 'dark' ? 'rgba(220,220,214,0.85)' : 'rgba(90,90,86,0.85)'
        ctx.lineWidth = Math.max(1.6, scale * 0.07)
        ctx.lineCap = 'round'
        ctx.beginPath()
        ctx.moveTo(X(A), Y(A))
        ctx.lineTo(X(B), Y(B))
        ctx.stroke()
      }
      mol.atoms.forEach((a, i) => {
        const p = apts[i]
        ctx.beginPath()
        ctx.arc(X(p), Y(p), Math.max(2, scale * (a.isH ? 0.09 : 0.14)), 0, Math.PI * 2)
        ctx.fillStyle = CPK[a.element] ?? '#777'
        ctx.fill()
      })

      if (mode === 'ESP' || mode === 'DENSITY') {
        const spts = surface
          .map((s) => ({ ...tf(s.x, s.y, s.z), esp: s.esp }))
          .sort((a, b) => a.z - b.z)
        const r = Math.max(1.6, scale * 0.075)
        for (const p of spts) {
          const depth = 0.45 + 0.55 * ((p.z / span + 1) / 2)
          ctx.beginPath()
          ctx.arc(X(p), Y(p), r, 0, Math.PI * 2)
          ctx.fillStyle =
            mode === 'ESP'
              ? espColor(p.esp, 0.30 + 0.45 * depth)
              : theme.mode === 'dark'
                ? `rgba(140,160,180,${0.16 + 0.3 * depth})`
                : `rgba(120,140,165,${0.14 + 0.28 * depth})`
          ctx.fill()
        }
      } else {
        // 오비탈 로브: p형은 분자면 위/아래 쌍(±z), s형은 단일 블롭
        const draw: { z: number; sx: number; sy: number; r: number; sign: 1 | -1 }[] = []
        for (const lb of lobes) {
          if (lb.ptype) {
            const up = tf(lb.x, lb.y, lb.z + 0.62)
            const dn = tf(lb.x, lb.y, lb.z - 0.62)
            draw.push({ z: up.z, sx: X(up), sy: Y(up), r: lb.r, sign: lb.sign })
            draw.push({ z: dn.z, sx: X(dn), sy: Y(dn), r: lb.r, sign: (-lb.sign) as 1 | -1 })
          } else {
            const c = tf(lb.x, lb.y, lb.z)
            draw.push({ z: c.z, sx: X(c), sy: Y(c), r: lb.r * 1.15, sign: lb.sign })
          }
        }
        draw.sort((a, b) => a.z - b.z)
        for (const dxo of draw) {
          const col = dxo.sign > 0 ? theme.mepNegative : theme.mepPositive
          const rgb = hex2rgb(col)
          const rr = dxo.r * scale
          const grad = ctx.createRadialGradient(dxo.sx, dxo.sy, rr * 0.15, dxo.sx, dxo.sy, rr)
          grad.addColorStop(0, `rgba(${rgb[0]},${rgb[1]},${rgb[2]},0.72)`)
          grad.addColorStop(1, `rgba(${rgb[0]},${rgb[1]},${rgb[2]},0.16)`)
          ctx.beginPath()
          ctx.arc(dxo.sx, dxo.sy, rr, 0, Math.PI * 2)
          ctx.fillStyle = grad
          ctx.fill()
          ctx.lineWidth = 1
          ctx.strokeStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},0.55)`
          ctx.stroke()
        }
      }
    }

    const tick = () => {
      if (auto.current && !dragging.current) rotation.current.yaw += 0.005
      render()
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)

    let lastX = 0
    let lastY = 0
    const onDown = (e: PointerEvent) => {
      dragging.current = true
      auto.current = false
      lastX = e.clientX
      lastY = e.clientY
      canvas.setPointerCapture(e.pointerId)
    }
    const onMove = (e: PointerEvent) => {
      if (!dragging.current) return
      rotation.current.yaw += (e.clientX - lastX) * 0.011
      rotation.current.pitch += (e.clientY - lastY) * 0.011
      rotation.current.pitch = Math.max(-1.5, Math.min(1.5, rotation.current.pitch))
      lastX = e.clientX
      lastY = e.clientY
    }
    const onUp = () => {
      dragging.current = false
    }
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      zoom.current = Math.max(0.5, Math.min(2.6, zoom.current * (e.deltaY > 0 ? 0.9 : 1.1)))
    }
    canvas.addEventListener('pointerdown', onDown)
    canvas.addEventListener('pointermove', onMove)
    canvas.addEventListener('pointerup', onUp)
    canvas.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      cancelAnimationFrame(raf)
      canvas.removeEventListener('pointerdown', onDown)
      canvas.removeEventListener('pointermove', onMove)
      canvas.removeEventListener('pointerup', onUp)
      canvas.removeEventListener('wheel', onWheel)
    }
  }, [mol, surface, lobes, mode, theme])

  if (!mol) return <div className="empty small">구조를 생성할 수 없는 SMILES입니다: {smiles}</div>

  const modeDesc: Record<QCMode, string> = {
    HOMO: `HOMO${homo !== undefined ? ` (${homo} eV)` : ''} — 전자가 가장 높은 에너지로 채워진 궤도. 색 = 파동함수 위상(＋/−), 인접 로브가 같은 색이면 결합성. 산화(전자 잃음)가 일어나는 자리`,
    LUMO: `LUMO${lumo !== undefined ? ` (${lumo} eV)` : ''} — 전자가 들어갈 수 있는 가장 낮은 빈 궤도. 인접 로브의 색이 교대되면 반결합성(π*). 환원(전자 받음)이 일어나는 자리`,
    ESP: `정전기 퍼텐셜(ESP) 표면 — 전자밀도 표면 위 전위를 색으로 매핑. 음전위 부위는 Li⁺가, 양전위 부위는 음이온이 접근${espRange?.[0] !== undefined ? ` · MEP 극값 ${espRange[0]} ~ ${espRange[1]} kcal/mol` : ''}`,
    DENSITY: '전자밀도 등가면 — 분자가 실제로 차지하는 공간(반데르발스 표면). 입체 장애·접근성 판단의 기준',
  }

  return (
    <div>
      <div className="conf-controls">
        <div className="seg">
          {(['ESP', 'HOMO', 'LUMO', 'DENSITY'] as QCMode[]).map((m) => (
            <button key={m} className={mode === m ? 'on' : ''} onClick={() => setMode(m)}>
              {m === 'ESP' ? 'ESP 표면' : m === 'DENSITY' ? '전자밀도' : m}
            </button>
          ))}
        </div>
        {(mode === 'ESP' || mode === 'DENSITY') && (
          <label className="small">
            표면 크기 <b>{surfScale.toFixed(2)}×</b>
            <input
              type="range"
              min={0.85}
              max={1.25}
              step={0.05}
              value={surfScale}
              onChange={(e) => setSurfScale(parseFloat(e.target.value))}
            />
          </label>
        )}
      </div>
      <canvas ref={canvasRef} style={{ width: '100%', height: 380, cursor: 'grab', touchAction: 'none' }} />
      {mode === 'ESP' ? (
        <div className="mep-legend">
          <span className="small muted">음전위(δ⁻) — Li⁺ 배위 부위</span>
          <span
            className="mep-bar"
            style={{
              background: `linear-gradient(90deg, ${theme.mepNegative}, ${theme.mode === 'dark' ? '#969692' : '#b9b8b2'}, ${theme.mepPositive})`,
            }}
          />
          <span className="small muted">양전위(δ⁺)</span>
        </div>
      ) : mode === 'HOMO' || mode === 'LUMO' ? (
        <div className="legend">
          <span className="legend-item">
            <span className="legend-swatch" style={{ background: theme.mepNegative, borderRadius: '50%' }} />
            위상 ＋
          </span>
          <span className="legend-item">
            <span className="legend-swatch" style={{ background: theme.mepPositive, borderRadius: '50%' }} />
            위상 −
          </span>
        </div>
      ) : null}
      <div className="chart-note">
        {modeDesc[mode]}
        <br />
        드래그 = 회전 · 휠 = 확대/축소. 표면·오비탈은 부분전하/LCAO 규칙 기반 근사이며, 실제 cube 등가면은
        백엔드(PySCF) 연동 시 동일 화면에 표시됩니다.
      </div>
    </div>
  )
}
