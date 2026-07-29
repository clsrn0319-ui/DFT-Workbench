import { useEffect, useRef } from 'react'
import SmilesDrawer from 'smiles-drawer'
import { useStore } from '../store'

// SMILES 2D 골격식 렌더링 (smiles-drawer)
export function Molecule2D({
  smiles,
  height = 170,
  compact = false,
}: {
  smiles: string
  height?: number
  compact?: boolean
}) {
  const ref = useRef<SVGSVGElement>(null)
  const { theme } = useStore()
  const dark = theme.mode === 'dark'

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.innerHTML = ''
    try {
      const drawer = new SmilesDrawer.SvgDrawer({
        width: compact ? 210 : 380,
        height,
        bondThickness: 1,
        padding: compact ? 8 : 16,
        compactDrawing: false,
        terminalCarbons: !compact,
        explicitHydrogens: false,
      })
      SmilesDrawer.parse(
        smiles,
        (tree: unknown) => {
          drawer.draw(tree, el, dark ? 'dark' : 'light')
        },
        () => {
          el.innerHTML = `<text x="10" y="24" fill="var(--muted)" font-size="12">구조 파싱 실패: ${smiles.slice(0, 30)}</text>`
        },
      )
    } catch {
      // 렌더링 실패 시 SMILES 문자열 폴백은 부모에서 처리
    }
  }, [smiles, height, compact, dark])

  return (
    <svg
      ref={ref}
      style={{ width: '100%', height }}
      role="img"
      aria-label={`2D 분자 구조: ${smiles}`}
      data-smiles={smiles}
    />
  )
}
