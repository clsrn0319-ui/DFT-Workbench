import { useMemo } from 'react'
import { detectFunctionalGroups } from './encyclopedia'

// IR/UV-Vis 스펙트럼 예측 (dft_information 문서 5장 — 분광학적 성질)
// 작용기 → 특성 진동수 규칙으로 IR을, gap → λmax(1240/gap)로 UV를 근사한다.

const IR_RULES: [RegExp, { cm: number; width: number; depth: number; label: string }][] = [
  [/하이드록실|카복실산/, { cm: 3400, width: 260, depth: 0.55, label: 'O–H 신축 (넓음)' }],
  [/아민/, { cm: 3360, width: 120, depth: 0.4, label: 'N–H 신축' }],
  [/방향족/, { cm: 3060, width: 40, depth: 0.25, label: '방향족 C–H' }],
  [/./, { cm: 2950, width: 70, depth: 0.45, label: 'C–H 신축' }],
  [/니트릴/, { cm: 2240, width: 35, depth: 0.5, label: 'C≡N 신축' }],
  [/카복실산/, { cm: 1710, width: 45, depth: 0.85, label: 'C=O 신축 (산)' }],
  [/에스터/, { cm: 1735, width: 40, depth: 0.85, label: 'C=O 신축 (에스터)' }],
  [/아마이드|락탐/, { cm: 1670, width: 45, depth: 0.8, label: 'C=O 신축 (아마이드)' }],
  [/케톤|알데하이드/, { cm: 1715, width: 40, depth: 0.8, label: 'C=O 신축' }],
  [/카복실레이트/, { cm: 1580, width: 60, depth: 0.7, label: 'COO⁻ 비대칭 신축' }],
  [/C=C \(비닐/, { cm: 1640, width: 35, depth: 0.45, label: 'C=C 신축' }],
  [/방향족/, { cm: 1600, width: 35, depth: 0.4, label: '고리 C=C' }],
  [/C–F/, { cm: 1180, width: 90, depth: 0.75, label: 'C–F 신축' }],
  [/에스터|에테르|카복실산|하이드록실/, { cm: 1150, width: 80, depth: 0.6, label: 'C–O 신축' }],
]

export function IRUVSpectra({ smiles, gap }: { smiles: string; gap?: number }) {
  const peaks = useMemo(() => {
    const groups = detectFunctionalGroups(smiles)
    const hay = groups.join(' ') || 'C–H'
    const out: { cm: number; width: number; depth: number; label: string }[] = []
    for (const [re, p] of IR_RULES) {
      if (re.source === '.' || re.test(hay)) {
        if (!out.some((o) => Math.abs(o.cm - p.cm) < 25)) out.push(p)
      }
    }
    return out
  }, [smiles])

  // IR: 투과율 곡선 (4000 → 500 cm⁻¹)
  const W = 560
  const H = 180
  const padL = 40
  const padT = 14
  const padB = 26
  const plotW = W - padL - 14
  const plotH = H - padT - padB
  const xIr = (cm: number) => padL + ((4000 - cm) / 3500) * plotW

  const irPath = useMemo(() => {
    const pts: string[] = []
    for (let cm = 4000; cm >= 500; cm -= 12) {
      let t = 0.97
      for (const p of peaks) {
        t -= p.depth * Math.exp(-((cm - p.cm) ** 2) / (2 * p.width ** 2))
      }
      t = Math.max(0.04, t)
      pts.push(`${pts.length ? 'L' : 'M'}${xIr(cm).toFixed(1)},${(padT + (1 - t) * plotH).toFixed(1)}`)
    }
    return pts.join(' ')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [peaks])

  // UV-Vis: λmax 가우시안 흡수
  const lambda = gap ? Math.round(1240 / Math.max(gap, 0.5)) : undefined
  const xUv = (nm: number) => padL + ((nm - 100) / 400) * plotW
  const uvPath = useMemo(() => {
    if (!lambda) return ''
    const pts: string[] = []
    for (let nm = 100; nm <= 500; nm += 4) {
      const a = Math.exp(-((nm - lambda) ** 2) / (2 * 28 ** 2)) * 0.92
      pts.push(`${pts.length ? 'L' : 'M'}${xUv(nm).toFixed(1)},${(padT + (1 - a) * plotH).toFixed(1)}`)
    }
    return pts.join(' ')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lambda])

  return (
    <div className="grid-2">
      <div className="chart-box">
        <div className="option-title">IR 스펙트럼 예측 (작용기 특성 진동수)</div>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="IR 스펙트럼 예측">
          {[4000, 3000, 2000, 1500, 1000, 500].map((cm) => (
            <g key={cm}>
              <line x1={xIr(cm)} x2={xIr(cm)} y1={padT} y2={H - padB} className="gridline" />
              <text x={xIr(cm)} y={H - 10} className="axis-label" textAnchor="middle">
                {cm}
              </text>
            </g>
          ))}
          <path d={irPath} fill="none" stroke="var(--series-1)" strokeWidth={1.8} />
          {peaks
            .filter((p) => p.depth >= 0.5)
            .map((p) => (
              <text key={p.label} x={xIr(p.cm)} y={padT + 8} className="axis-label" textAnchor="middle">
                {p.label.split(' ')[0]}
              </text>
            ))}
          <text x={W - 14} y={padT + 4} className="axis-label" textAnchor="end">
            cm⁻¹
          </text>
          <text x={12} y={padT + 4} className="axis-label">
            %T
          </text>
        </svg>
        <div className="chart-note">
          주요 흡수: {peaks.filter((p) => p.depth >= 0.5).map((p) => `${p.label} ~${p.cm}`).join(' · ') || '—'}
        </div>
      </div>
      <div className="chart-box">
        <div className="option-title">UV-Vis 흡수 예측 (TD-DFT 근사)</div>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="UV-Vis 스펙트럼 예측">
          {[100, 200, 300, 400, 500].map((nm) => (
            <g key={nm}>
              <line x1={xUv(nm)} x2={xUv(nm)} y1={padT} y2={H - padB} className="gridline" />
              <text x={xUv(nm)} y={H - 10} className="axis-label" textAnchor="middle">
                {nm}
              </text>
            </g>
          ))}
          {/* 가시광 영역 표시 */}
          <rect x={xUv(380)} y={padT} width={xUv(500) - xUv(380)} height={plotH} fill="var(--pin)" opacity={0.07} />
          <text x={xUv(440)} y={padT + 10} className="axis-label" textAnchor="middle">
            가시광
          </text>
          {uvPath && <path d={uvPath} fill="none" stroke="var(--series-7)" strokeWidth={1.8} />}
          {lambda && (
            <text x={xUv(Math.min(lambda, 490))} y={padT + 24} className="value-label" textAnchor="middle">
              λmax ≈ {lambda} nm
            </text>
          )}
          <text x={W - 14} y={H - padB - 6} className="axis-label" textAnchor="end">
            nm
          </text>
        </svg>
        <div className="chart-note">
          {lambda
            ? lambda < 380
              ? `λmax ${lambda} nm — 가시광 흡수 없음 → 무색 예상`
              : `λmax ${lambda} nm — 가시광 흡수 → 유색 가능`
            : 'gap 값이 있는 PUBLISHED 결과에서 표시됩니다'}
        </div>
      </div>
    </div>
  )
}
