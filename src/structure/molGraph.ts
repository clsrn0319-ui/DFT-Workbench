// SMILES → 원자/결합 그래프 (smiles-drawer preprocessor 기반)
// 2D 좌표는 smiles-drawer 레이아웃, 3D는 프로토타입 근사(z 퍼커링 + 수소 배치).
// 실제 xTB/DFT 최적화 좌표는 백엔드 연동 시 이 모듈을 대체한다.
import SmilesDrawer from 'smiles-drawer'

export interface Atom3D {
  element: string
  x: number
  y: number
  z: number
  charge: number // 근사 부분전하 (MEP 색상용)
  formalCharge: number
  isH: boolean
}

export interface Bond3D {
  a: number
  b: number
  order: 1 | 2 | 3
}

export interface MolGraph {
  atoms: Atom3D[]
  bonds: Bond3D[]
}

const VALENCE: Record<string, number> = { C: 4, N: 3, O: 2, F: 1, Cl: 1, Br: 1, I: 1, S: 2, P: 3, B: 3, Li: 1, Na: 1, K: 1 }

function hash(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

const cache = new Map<string, MolGraph | null>()

export function buildMolGraph(smiles: string): MolGraph | null {
  if (cache.has(smiles)) return cache.get(smiles)!
  let result: MolGraph | null = null
  try {
    const drawer = new SmilesDrawer.SvgDrawer({ width: 400, height: 300 })
    let tree: unknown = null
    SmilesDrawer.parse(smiles, (t: unknown) => {
      tree = t
    })
    if (!tree) throw new Error('parse failed')
    const pre = (drawer as unknown as { preprocessor: { initDraw: (t: unknown, theme: string, info: boolean, hl: unknown[]) => void; processGraph: () => void; graph: { vertices: PreVertex[]; edges: PreEdge[] } } }).preprocessor
    pre.initDraw(tree, 'light', false, [])
    pre.processGraph()
    result = fromPreprocessor(pre.graph, smiles)
  } catch {
    result = null
  }
  cache.set(smiles, result)
  return result
}

interface PreVertex {
  position: { x: number; y: number }
  value: { element: string; bracket?: { charge?: number; hcount?: number } | null; bondType?: string; isAromatic?: boolean }
}

interface PreEdge {
  sourceId: number
  targetId: number
  bondType: string
}

function fromPreprocessor(g: { vertices: PreVertex[]; edges: PreEdge[] }, smiles: string): MolGraph {
  const SCALE = 1.5 / 26 // smiles-drawer 결합길이(≈26px) → 1.5 Å
  const heavy = g.vertices.map((v) => ({
    element: v.value.element,
    x: v.position.x * SCALE,
    y: v.position.y * SCALE,
    z: 0,
    formalCharge: v.value.bracket?.charge ?? 0,
    aromatic: !!v.value.isAromatic,
  }))
  const bonds: Bond3D[] = g.edges.map((e) => ({
    a: e.sourceId,
    b: e.targetId,
    order: e.bondType === '=' ? 2 : e.bondType === '#' ? 3 : 1,
  }))

  // 중심 정렬
  const cx = heavy.reduce((s, a) => s + a.x, 0) / heavy.length
  const cy = heavy.reduce((s, a) => s + a.y, 0) / heavy.length
  heavy.forEach((a) => {
    a.x -= cx
    a.y -= cy
  })

  // 결합 차수 합·이웃 목록
  const bondOrderSum = new Array(heavy.length).fill(0)
  const neighbors: number[][] = heavy.map(() => [])
  for (const b of bonds) {
    bondOrderSum[b.a] += b.order
    bondOrderSum[b.b] += b.order
    neighbors[b.a].push(b.b)
    neighbors[b.b].push(b.a)
  }

  // 유사 3D: sp3 원자에 결정론적 z 퍼커링 (sp2/방향족/말단 다중결합은 평면 유지)
  heavy.forEach((a, i) => {
    const sp3 = !a.aromatic && !bonds.some((b) => (b.a === i || b.b === i) && b.order > 1)
    if (sp3 && neighbors[i].length >= 2) {
      a.z = ((hash(smiles + ':' + i) % 100) / 100 - 0.5) * 0.55
    }
  })

  const atoms: Atom3D[] = heavy.map((a) => ({
    element: a.element,
    x: a.x,
    y: a.y,
    z: a.z,
    charge: 0,
    formalCharge: a.formalCharge,
    isH: false,
  }))

  // 암시적 수소 생성: 원자가 - 결합차수합 - |형식전하 방향|
  heavy.forEach((a, i) => {
    const val = VALENCE[a.element] ?? 0
    let nH = Math.max(0, val - bondOrderSum[i] + (a.element === 'N' && a.formalCharge > 0 ? 1 : 0) - (a.formalCharge < 0 ? 1 : 0))
    if (a.aromatic) nH = Math.max(0, nH - 1)
    if (nH === 0) return
    // 이웃 반대 방향으로 부채꼴 배치 + z 분산
    let dx = 0
    let dy = 0
    for (const n of neighbors[i]) {
      dx += heavy[n].x - a.x
      dy += heavy[n].y - a.y
    }
    const len = Math.hypot(dx, dy) || 1
    const baseAngle = neighbors[i].length ? Math.atan2(-dy / len, -dx / len) : 0
    for (let k = 0; k < nH; k++) {
      const spread = nH > 1 ? ((k / (nH - 1)) - 0.5) * 1.9 : 0
      const ang = baseAngle + spread
      const zH = a.z + (k % 2 === 0 ? 0.45 : -0.45) * (neighbors[i].length >= 2 ? 1 : 0.3)
      atoms.push({
        element: 'H',
        x: a.x + Math.cos(ang) * 1.0,
        y: a.y + Math.sin(ang) * 1.0,
        z: zH,
        charge: 0,
        formalCharge: 0,
        isH: true,
      })
      bonds.push({ a: i, b: atoms.length - 1, order: 1 })
    }
  })

  assignCharges(atoms, bonds)
  return { atoms, bonds }
}

// 근사 부분전하 (전기음성도 규칙 기반 — MEP/전하 색상 표시용)
function assignCharges(atoms: Atom3D[], bonds: Bond3D[]) {
  const neighborIdx: number[][] = atoms.map(() => [])
  for (const b of bonds) {
    neighborIdx[b.a].push(b.b)
    neighborIdx[b.b].push(b.a)
  }
  const isDouble = (i: number) => bonds.some((b) => (b.a === i || b.b === i) && b.order >= 2)
  atoms.forEach((a, i) => {
    let q = 0
    switch (a.element) {
      case 'O':
        q = isDouble(i) ? -0.45 : -0.35
        break
      case 'N':
        q = isDouble(i) ? -0.38 : -0.32
        break
      case 'F':
        q = -0.22
        break
      case 'Cl':
        q = -0.15
        break
      case 'S':
        q = -0.1
        break
      case 'Li':
      case 'Na':
      case 'K':
        q = 0.85
        break
      case 'H': {
        const parent = neighborIdx[i][0]
        const pe = parent !== undefined ? atoms[parent].element : 'C'
        q = pe === 'O' ? 0.35 : pe === 'N' ? 0.28 : 0.06
        break
      }
      default: {
        // C 등: 전기음성 이웃당 +
        for (const n of neighborIdx[i]) {
          if (['O', 'N', 'F', 'Cl'].includes(atoms[n].element)) q += 0.14
        }
      }
    }
    q += a.formalCharge * 0.6
    a.charge = +q.toFixed(3)
  })
}

export const CPK: Record<string, string> = {
  C: '#4a4a48',
  H: '#d8d6ce',
  O: '#d43c3c',
  N: '#2a6fd0',
  F: '#22aa66',
  Cl: '#22aa66',
  Br: '#8a4b26',
  S: '#d9a000',
  P: '#e07020',
  Li: '#8f6fe0',
  Na: '#8f6fe0',
  K: '#8f6fe0',
}

export const VDW: Record<string, number> = {
  C: 0.42,
  H: 0.26,
  O: 0.38,
  N: 0.4,
  F: 0.35,
  Cl: 0.45,
  S: 0.48,
  P: 0.48,
  Li: 0.44,
  Na: 0.5,
  K: 0.55,
}

// ── Conformer 탐색 시뮬레이션 ───────────────────────────────────
// conformer i (1..N)의 상대 에너지(kcal/mol)와 변형 구조를 결정론적으로 생성.
// 에너지가 낮을수록 기준(이완) 구조에 가까운 좌표를 갖는다.

export function conformerEnergy(smiles: string, i: number): number {
  return +(0.4 + rand01(`${smiles}|conf${i}|E`) * 7.6).toFixed(2)
}

export function bestConformerAmong(smiles: string, n: number): { index: number; energy: number } {
  let best = { index: 1, energy: conformerEnergy(smiles, 1) }
  for (let i = 2; i <= n; i++) {
    const e = conformerEnergy(smiles, i)
    if (e < best.energy) best = { index: i, energy: e }
  }
  return best
}

function rand01(seed: string): number {
  return (hash(seed) % 100000) / 100000
}

export function buildConformerGraph(smiles: string, confIdx: number): MolGraph | null {
  const base = buildMolGraph(smiles)
  if (!base) return null
  const e = conformerEnergy(smiles, confIdx)
  const amp = (e / 8) * 0.9 // 고에너지 conformer일수록 기준 구조에서 크게 벗어남
  const atoms = base.atoms.map((a, i) => {
    const r = (tag: string) => (hash(`${smiles}|c${confIdx}|${i}|${tag}`) % 100) / 100 - 0.5
    const f = a.isH ? 1.3 : 0.8
    return {
      ...a,
      x: a.x + r('x') * amp * f * 0.5,
      y: a.y + r('y') * amp * f * 0.5,
      z: a.z + r('z') * amp * f * 1.2,
    }
  })
  return { atoms, bonds: base.bonds }
}
