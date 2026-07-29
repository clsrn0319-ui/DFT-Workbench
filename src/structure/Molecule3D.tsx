import { useEffect, useRef, useState } from 'react'
import { CPK, VDW, buildMolGraph } from './molGraph'
import { useStore } from '../store'

export type ColorMode = 'cpk' | 'charge'

// 프로토타입 3D ball-and-stick 뷰어 (canvas 직접 렌더링, 드래그 회전·휠 줌)
// 부분전하 모드: 근사 부분전하를 MEP 색상(음전위~양전위)으로 표시
export function Molecule3D({
  smiles,
  colorMode,
  height = 260,
}: {
  smiles: string
  colorMode: ColorMode
  height?: number
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const { theme } = useStore()
  const [failed, setFailed] = useState(false)
  const rotation = useRef({ yaw: 0.6, pitch: -0.45 })
  const zoom = useRef(1)
  const dragging = useRef(false)
  const auto = useRef(true)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const mol = buildMolGraph(smiles)
    if (!mol) {
      setFailed(true)
      return
    }
    setFailed(false)

    const ctx = canvas.getContext('2d')!
    const dpr = window.devicePixelRatio || 1
    let raf = 0

    const mix = (hex1: string, hex2: string, t: number) => {
      const p = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16))
      const [a, b] = [p(hex1), p(hex2)]
      return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * t)).join(',')})`
    }

    const chargeColor = (q: number) => {
      const neutral = theme.mode === 'dark' ? '#8a8a86' : '#b9b8b2'
      if (q < 0) return mix(neutral, theme.mepNegative, Math.min(1, -q / 0.45))
      return mix(neutral, theme.mepPositive, Math.min(1, q / 0.45))
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

      // 회전 + 화면 좌표
      const pts = mol.atoms.map((a) => {
        const x1 = a.x * cy + a.z * sy
        const z1 = -a.x * sy + a.z * cy
        const y2 = a.y * cp - z1 * sp
        const z2 = a.y * sp + z1 * cp
        return { x: x1, y: y2, z: z2 }
      })
      const span = Math.max(...mol.atoms.map((a) => Math.hypot(a.x, a.y, a.z)), 1.6)
      const scale = (Math.min(w, h) / (span * 2.55)) * zoom.current
      const px = (i: number) => w / 2 + pts[i].x * scale
      const py = (i: number) => h / 2 + pts[i].y * scale

      // 결합 (뒤→앞)
      const bondsSorted = [...mol.bonds].sort(
        (b1, b2) => (pts[b1.a].z + pts[b1.b].z) / 2 - (pts[b2.a].z + pts[b2.b].z) / 2,
      )
      for (const b of bondsSorted) {
        const midX = (px(b.a) + px(b.b)) / 2
        const midY = (py(b.a) + py(b.b)) / 2
        const colA = colorMode === 'cpk' ? (CPK[mol.atoms[b.a].element] ?? '#777') : chargeColor(mol.atoms[b.a].charge)
        const colB = colorMode === 'cpk' ? (CPK[mol.atoms[b.b].element] ?? '#777') : chargeColor(mol.atoms[b.b].charge)
        ctx.lineCap = 'round'
        ctx.lineWidth = b.order === 1 ? Math.max(2.5, scale * 0.11) : Math.max(2, scale * 0.08)
        const offsets = b.order === 1 ? [0] : b.order === 2 ? [-0.09, 0.09] : [-0.13, 0, 0.13]
        const dx = py(b.b) - py(b.a)
        const dy = -(px(b.b) - px(b.a))
        const dl = Math.hypot(dx, dy) || 1
        for (const off of offsets) {
          const ox = (dx / dl) * off * scale
          const oy = (dy / dl) * off * scale
          ctx.strokeStyle = colA
          ctx.beginPath()
          ctx.moveTo(px(b.a) + ox, py(b.a) + oy)
          ctx.lineTo(midX + ox, midY + oy)
          ctx.stroke()
          ctx.strokeStyle = colB
          ctx.beginPath()
          ctx.moveTo(midX + ox, midY + oy)
          ctx.lineTo(px(b.b) + ox, py(b.b) + oy)
          ctx.stroke()
        }
      }

      // 원자 (뒤→앞)
      const order = mol.atoms.map((_, i) => i).sort((i, j) => pts[i].z - pts[j].z)
      for (const i of order) {
        const a = mol.atoms[i]
        const r = (VDW[a.element] ?? 0.4) * scale * (a.isH ? 0.85 : 1)
        const depth = 0.85 + 0.15 * (pts[i].z / (span + 0.001))
        const base = colorMode === 'cpk' ? (CPK[a.element] ?? '#777') : chargeColor(a.charge)
        ctx.beginPath()
        ctx.arc(px(i), py(i), Math.max(2.5, r), 0, Math.PI * 2)
        ctx.fillStyle = base
        ctx.globalAlpha = depth
        ctx.fill()
        ctx.globalAlpha = 1
        ctx.lineWidth = 1
        ctx.strokeStyle = theme.mode === 'dark' ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.28)'
        ctx.stroke()
        if (!a.isH && a.element !== 'C' && scale > 18) {
          ctx.fillStyle = theme.mode === 'dark' ? '#fff' : '#fff'
          ctx.font = `bold ${Math.max(9, r * 0.9)}px system-ui`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(a.element, px(i), py(i))
        }
      }
    }

    const tick = () => {
      if (auto.current && !dragging.current) rotation.current.yaw += 0.006
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
  }, [smiles, colorMode, theme])

  if (failed) {
    return <div className="empty small">3D 구조를 생성할 수 없는 SMILES입니다: {smiles}</div>
  }

  return (
    <div>
      <canvas ref={canvasRef} style={{ width: '100%', height, cursor: 'grab', touchAction: 'none' }} />
      {colorMode === 'charge' ? (
        <div className="mep-legend">
          <span className="small muted">음전위(δ⁻)</span>
          <span
            className="mep-bar"
            style={{
              background: `linear-gradient(90deg, ${theme.mepNegative}, ${theme.mode === 'dark' ? '#8a8a86' : '#b9b8b2'}, ${theme.mepPositive})`,
            }}
          />
          <span className="small muted">양전위(δ⁺)</span>
        </div>
      ) : (
        <div className="legend">
          {['C', 'H', 'O', 'N', 'F'].map((el) => (
            <span key={el} className="legend-item">
              <span className="legend-swatch" style={{ background: CPK[el], borderRadius: '50%' }} />
              {el}
            </span>
          ))}
        </div>
      )}
      <div className="chart-note">
        드래그 = 회전 · 휠 = 확대/축소. 표시 구조는 프로토타입 근사 3D이며, 실제 xTB/DFT 최적화 좌표는 백엔드
        연동 시 표시됩니다.
      </div>
    </div>
  )
}
