// 분자 백과 — 구조 그래프에서 자동 계산되는 화학적 특징
// (업로드 문서 '분자의 화학적 특징' 분류 체계 기반: 조성·구조 / 결합 성질 /
//  물리 특성 / 반응성 / 기타 / 유기·무기화학 관점)
import { buildMolGraph, type MolGraph } from './molGraph'

const ATOMIC_WEIGHT: Record<string, number> = {
  H: 1.008, C: 12.011, N: 14.007, O: 15.999, F: 18.998, Cl: 35.45, Br: 79.904,
  I: 126.9, S: 32.06, P: 30.974, B: 10.81, Li: 6.94, Na: 22.99, K: 39.098,
}

const EN: Record<string, number> = {
  H: 2.2, C: 2.55, N: 3.04, O: 3.44, F: 3.98, Cl: 3.16, Br: 2.96, I: 2.66,
  S: 2.58, P: 2.19, B: 2.04, Li: 0.98, Na: 0.93, K: 0.82,
}

export interface MolProfile {
  formula: string
  mw: number
  elementCounts: Record<string, number>
  bondCounts: { single: number; double: number; triple: number }
  ringClosures: number
  aromaticAtoms: number
  dbe: number // 불포화도
  hybridization: { sp3: number; sp2: number; sp: number }
  polarBonds: { label: string; dEN: number; count: number }[]
  hbd: number
  hba: number
  dipoleApprox: number // Σq·r 크기 (근사, 상대 지표)
  polarityClass: '무극성' | '약한 극성' | '극성' | '강한 극성/이온성'
  conjugated: boolean
  aromatic: boolean
  hasStereoNotation: boolean
  isIonic: boolean
  donorAtoms: { element: string; hsab: string }[]
}

const cache = new Map<string, MolProfile | null>()

export function analyzeMolecule(smiles: string): MolProfile | null {
  if (cache.has(smiles)) return cache.get(smiles)!
  const g = buildMolGraph(smiles)
  const profile = g ? build(smiles, g) : null
  cache.set(smiles, profile)
  return profile
}

function build(smiles: string, g: MolGraph): MolProfile {
  const elementCounts: Record<string, number> = {}
  for (const a of g.atoms) elementCounts[a.element] = (elementCounts[a.element] ?? 0) + 1

  const order = ['C', 'H', 'N', 'O', 'F', 'Cl', 'S', 'P', 'Li', 'Na', 'K']
  const formula = [...order.filter((e) => elementCounts[e]), ...Object.keys(elementCounts).filter((e) => !order.includes(e))]
    .map((e) => `${e}${elementCounts[e] > 1 ? elementCounts[e] : ''}`)
    .join('')

  const mw = +g.atoms.reduce((s, a) => s + (ATOMIC_WEIGHT[a.element] ?? 0), 0).toFixed(2)

  const heavyBonds = g.bonds.filter((b) => !g.atoms[b.a].isH && !g.atoms[b.b].isH)
  const bondCounts = {
    single: heavyBonds.filter((b) => b.order === 1).length,
    double: heavyBonds.filter((b) => b.order === 2).length,
    triple: heavyBonds.filter((b) => b.order === 3).length,
  }

  // 고리 수: SMILES ring closure 숫자 쌍
  const ringClosures = ((smiles.match(/\d/g) ?? []).length / 2) | 0
  const aromaticAtoms = (smiles.match(/[cnosp]/g) ?? []).length

  const C = elementCounts.C ?? 0
  const H = elementCounts.H ?? 0
  const N = elementCounts.N ?? 0
  const X = (elementCounts.F ?? 0) + (elementCounts.Cl ?? 0) + (elementCounts.Br ?? 0) + (elementCounts.I ?? 0)
  const dbe = Math.max(0, (2 * C + 2 + N - H - X) / 2)

  // 혼성화 (중원자 기준): 삼중결합 또는 이중결합 2개 = sp, 이중/방향족 = sp², 나머지 = sp³
  const hybridization = { sp3: 0, sp2: 0, sp: 0 }
  const sp2Set = new Set<number>()
  g.atoms.forEach((a, i) => {
    if (a.isH || !['C', 'N', 'O', 'S', 'P', 'B'].includes(a.element)) return
    const orders = g.bonds.filter((b) => b.a === i || b.b === i).map((b) => b.order)
    const nDouble = orders.filter((o) => o === 2).length
    if (orders.includes(3) || nDouble >= 2) hybridization.sp++
    else if (nDouble === 1 || aromaticAtoms > 0) {
      if (nDouble === 1) {
        hybridization.sp2++
        sp2Set.add(i)
      } else hybridization.sp3++
    } else hybridization.sp3++
  })

  // 극성 결합: ΔEN ≥ 0.5
  const polarMap = new Map<string, { dEN: number; count: number }>()
  for (const b of g.bonds) {
    const A = g.atoms[b.a]
    const B = g.atoms[b.b]
    const dEN = Math.abs((EN[A.element] ?? 2.5) - (EN[B.element] ?? 2.5))
    if (dEN < 0.5) continue
    const [e1, e2] = [A.element, B.element].sort()
    const sym = b.order === 2 ? '=' : b.order === 3 ? '≡' : '–'
    const label = `${e1}${sym}${e2}`
    const cur = polarMap.get(label)
    polarMap.set(label, { dEN: +dEN.toFixed(2), count: (cur?.count ?? 0) + 1 })
  }
  const polarBonds = [...polarMap.entries()]
    .map(([label, v]) => ({ label, ...v }))
    .sort((a, b) => b.dEN - a.dEN)

  const hbd = g.bonds.filter(
    (b) =>
      (g.atoms[b.a].isH && ['O', 'N'].includes(g.atoms[b.b].element)) ||
      (g.atoms[b.b].isH && ['O', 'N'].includes(g.atoms[b.a].element)),
  ).length
  const hba = g.atoms.filter((a) => !a.isH && ['O', 'N', 'F'].includes(a.element)).length

  // 근사 쌍극자: Σ q·r (부분전하 × 좌표, 상대 지표)
  const dx = g.atoms.reduce((s, a) => s + a.charge * a.x, 0)
  const dy = g.atoms.reduce((s, a) => s + a.charge * a.y, 0)
  const dz = g.atoms.reduce((s, a) => s + a.charge * a.z, 0)
  const dipoleApprox = +Math.hypot(dx, dy, dz).toFixed(2)

  const isIonic = smiles.includes('.') || g.atoms.some((a) => a.formalCharge !== 0)
  const polarityClass = isIonic
    ? '강한 극성/이온성'
    : polarBonds.length === 0 || dipoleApprox < 0.05
      ? '무극성'
      : dipoleApprox < 0.35
        ? '약한 극성'
        : '극성'

  // 공액: sp² 중원자 연결 성분 크기 ≥ 3 또는 방향족
  let conjugated = aromaticAtoms > 0
  if (!conjugated && sp2Set.size >= 3) {
    const adj = new Map<number, number[]>()
    for (const b of heavyBonds) {
      if (sp2Set.has(b.a) && sp2Set.has(b.b)) {
        adj.set(b.a, [...(adj.get(b.a) ?? []), b.b])
        adj.set(b.b, [...(adj.get(b.b) ?? []), b.a])
      }
    }
    const seen = new Set<number>()
    for (const start of sp2Set) {
      if (seen.has(start)) continue
      let size = 0
      const stack = [start]
      while (stack.length) {
        const v = stack.pop()!
        if (seen.has(v)) continue
        seen.add(v)
        size++
        stack.push(...(adj.get(v) ?? []))
      }
      if (size >= 3) {
        conjugated = true
        break
      }
    }
  }

  const donorAtoms = g.atoms
    .filter((a) => !a.isH && ['O', 'N', 'F', 'S'].includes(a.element))
    .reduce<{ element: string; hsab: string }[]>((acc, a) => {
      if (acc.some((d) => d.element === a.element)) return acc
      const hsab =
        a.element === 'O' || a.element === 'F'
          ? '경질(hard) 염기 — Li⁺(경질 산)와 친화'
          : a.element === 'N'
            ? '경계(borderline) 염기'
            : '연질(soft) 염기'
      return [...acc, { element: a.element, hsab }]
    }, [])

  return {
    formula,
    mw,
    elementCounts,
    bondCounts,
    ringClosures,
    aromaticAtoms,
    dbe,
    hybridization,
    polarBonds,
    hbd,
    hba,
    dipoleApprox,
    polarityClass,
    conjugated,
    aromatic: aromaticAtoms > 0,
    hasStereoNotation: smiles.includes('@') || smiles.includes('/') || smiles.includes('\\'),
    isIonic,
    donorAtoms,
  }
}

// ── 작용기 자동 인식 (그래프 규칙 기반 — 임의 SMILES 지원) ───────
// 상용 버전의 RDKit SMARTS 검출을 대체하는 클라이언트 규칙 엔진.

export function detectFunctionalGroups(smiles: string): string[] {
  const g = buildMolGraph(smiles)
  if (!g) return []
  const groups = new Map<string, number>()
  const add = (name: string) => groups.set(name, (groups.get(name) ?? 0) + 1)

  const nbrs = (i: number) => g.bonds.filter((b) => b.a === i || b.b === i).map((b) => (b.a === i ? b.b : b.a))
  const bondOrder = (i: number, j: number) => g.bonds.find((b) => (b.a === i && b.b === j) || (b.a === j && b.b === i))?.order ?? 0

  g.atoms.forEach((a, i) => {
    if (a.isH) return
    const nb = nbrs(i)
    if (a.element === 'C') {
      const dblO = nb.find((n) => g.atoms[n].element === 'O' && bondOrder(i, n) === 2)
      if (dblO !== undefined) {
        const singleO = nb.filter((n) => n !== dblO && g.atoms[n].element === 'O' && bondOrder(i, n) === 1)
        const nNb = nb.find((n) => g.atoms[n].element === 'N')
        if (singleO.length) {
          const o = singleO[0]
          const oNb = nbrs(o)
          if (g.atoms[o].formalCharge < 0) add('카복실레이트 –COO⁻')
          else if (oNb.some((n) => g.atoms[n].isH)) add('카복실산 –COOH')
          else add('에스터 –C(=O)O–')
        } else if (nNb !== undefined) {
          const inRing = smiles.match(/\d/) && nb.length >= 2
          add(inRing ? '아마이드/락탐 C(=O)N' : '아마이드 C(=O)N')
        } else if (nb.some((n) => g.atoms[n].isH)) add('알데하이드 –CHO')
        else add('케톤/카보닐 C=O')
      }
      if (nb.some((n) => g.atoms[n].element === 'N' && bondOrder(i, n) === 3)) add('니트릴 –C≡N')
      const fCount = nb.filter((n) => g.atoms[n].element === 'F').length
      if (fCount) for (let k = 0; k < fCount; k++) add('C–F 결합')
      const clCount = nb.filter((n) => g.atoms[n].element === 'Cl').length
      if (clCount) for (let k = 0; k < clCount; k++) add('C–Cl 결합')
    }
    if (a.element === 'O') {
      const heavyNb = nb.filter((n) => !g.atoms[n].isH)
      const hasH = nb.some((n) => g.atoms[n].isH)
      const nextToCarbonyl = heavyNb.some((n) =>
        nbrs(n).some((m) => g.atoms[m].element === 'O' && bondOrder(n, m) === 2),
      )
      if (hasH && heavyNb.length === 1 && !nextToCarbonyl) add('하이드록실 –OH')
      if (!hasH && heavyNb.length === 2 && !nextToCarbonyl && bondOrder(heavyNb[0], i) === 1) add('에테르 C–O–C')
    }
    if (a.element === 'N') {
      const triple = nb.some((n) => bondOrder(i, n) === 3)
      const nextToCarbonyl = nb.some((n) => nbrs(n).some((m) => g.atoms[m].element === 'O' && bondOrder(n, m) === 2))
      if (!triple && !nextToCarbonyl && nb.every((n) => ['C'].includes(g.atoms[n].element) || g.atoms[n].isH))
        add('아민 N')
    }
    if (a.element === 'S') add('황 함유기 (S)')
    if (a.element === 'P') add('인 함유기 (P)')
  })

  // 비닐 C=C (비방향족)
  const aromaticIdx = new Set<number>()
  // smiles-drawer는 케쿨레화하므로 방향족 판정은 smiles 소문자 존재 여부로 근사
  const isAromaticMol = /[cnos]/.test(smiles.replace(/\[.*?\]/g, ''))
  g.bonds.forEach((b) => {
    if (b.order === 2 && g.atoms[b.a].element === 'C' && g.atoms[b.b].element === 'C') {
      if (!isAromaticMol || !(aromaticIdx.has(b.a) && aromaticIdx.has(b.b))) add('C=C (비닐/알켄)')
    }
  })
  if (isAromaticMol) add('방향족 고리')
  if (smiles.includes('.')) add('이온쌍/다중 fragment')
  if (/\[Li\+\]|\[Na\+\]|\[K\+\]/.test(smiles)) add('알칼리 금속 양이온')

  return [...groups.entries()].map(([name, n]) => (n > 1 ? `${name} ×${n}` : name))
}

// 작용기 → 물성 경향 해석 (가설 계층)
const GROUP_TRENDS: [RegExp, string][] = [
  [/카복실산/, '카복실기 — 강한 H-bond 공여/수용, O 주변 음전위 집중 (Li⁺ 배위·접착 후보), 수계 친화'],
  [/카복실레이트/, '음이온성 카복실레이트 — 매우 강한 음전위, Li⁺ 강배위, 수용성'],
  [/에스터/, '에스터 O 음전위 — Li⁺ 배위 후보, 강산·염기 조건에서 가수분해 가능'],
  [/아마이드|락탐/, '아마이드 O 음전위 — H-bond 수용·Li⁺ 배위, 높은 극성'],
  [/니트릴/, '니트릴 — 큰 쌍극자, 낮은 LUMO 경향 (환원 민감 가능성), N 고립전자쌍 배위 후보'],
  [/하이드록실/, '–OH — H-bond 공여·수용, 접착·수계 친화'],
  [/에테르/, '에테르 O — 약한 Li⁺ 배위, 유연한 사슬'],
  [/방향족/, '공액 π계 — 높은 HOMO 경향(산화 민감), π–π 상호작용으로 흑연 친화 가능성'],
  [/C–F/, '불소화 — 낮은 HOMO 경향(내산화성), 소수성·낮은 표면 에너지'],
  [/C=C \(비닐/, '비닐기 — 라디칼 중합 가능 부위'],
  [/아민/, '아민 N — 염기성·H-bond, 배위 후보'],
  [/이온쌍/, '이온성 — 강한 정전기 상호작용, 해리 상태는 용매·농도 의존'],
]

export function deriveTrends(groups: string[]): string[] {
  const out: string[] = []
  for (const [re, trend] of GROUP_TRENDS) {
    if (groups.some((gr) => re.test(gr))) out.push(trend)
  }
  return out
}

// 대표 결합 길이 (표준 문헌값, Å) — 구조 정보 표시용
const BOND_LEN: Record<string, number> = {
  'C–C': 1.54, 'C=C': 1.34, 'C≡C': 1.2, 'C–O': 1.43, 'C=O': 1.22, 'C–N': 1.47,
  'C=N': 1.28, 'C≡N': 1.16, 'C–F': 1.35, 'C–Cl': 1.77, 'C–S': 1.82, 'C–H': 1.09,
  'O–H': 0.96, 'N–H': 1.01, 'H–O': 0.96, 'H–N': 1.01, 'F–P': 1.6, 'Li–O': 1.9,
}

export function representativeBonds(smiles: string): { label: string; len?: number; n: number }[] {
  const g = buildMolGraph(smiles)
  if (!g) return []
  const map = new Map<string, number>()
  for (const b of g.bonds) {
    const A = g.atoms[b.a].element
    const B = g.atoms[b.b].element
    const [e1, e2] = [A, B].sort()
    const sym = b.order === 2 ? '=' : b.order === 3 ? '≡' : '–'
    const label = `${e1}${sym}${e2}`
    map.set(label, (map.get(label) ?? 0) + 1)
  }
  return [...map.entries()]
    .map(([label, n]) => ({ label, len: BOND_LEN[label], n }))
    .sort((a, b) => b.n - a.n)
    .slice(0, 6)
}
