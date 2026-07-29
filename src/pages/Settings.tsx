import { useRef } from 'react'
import { useStore } from '../store'
import type { ThemeTokens } from '../types'
import { COLORBLIND_PRESET, DARK_PRESET, DEFAULT_THEME, contrastRatio } from '../theme'
import { Field } from '../ui'

// 기획서 14 — 사용자 정의 시각화·색상 시스템
export function Settings() {
  const { theme, appName, appSubtitle, dispatch } = useStore()
  const fileRef = useRef<HTMLInputElement>(null)

  const set = (patch: Partial<ThemeTokens>) => dispatch({ type: 'setTheme', theme: { ...theme, ...patch } })

  const setSeries = (i: number, color: string) => {
    const chartSeries = [...theme.chartSeries]
    chartSeries[i] = color
    set({ chartSeries })
  }

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(theme, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'workbench-theme.json'
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const importJson = (file: File) => {
    file.text().then((text) => {
      try {
        const t = JSON.parse(text) as ThemeTokens
        if (t.chartSeries?.length) set({ ...DEFAULT_THEME, ...t })
      } catch {
        window.alert('Theme JSON을 읽을 수 없습니다.')
      }
    })
  }

  // 대비 검사 (기획서 14.4)
  const textColor = theme.mode === 'dark' ? '#ffffff' : '#171716'
  const accentContrast = contrastRatio(theme.accent, theme.card)
  const textContrast = contrastRatio(textColor, theme.background)

  return (
    <div>
      <header className="page-head">
        <h1>시각화 · 계정 설정</h1>
        <p className="page-desc">
          워크스페이스·차트 색상을 변경하고 계정(브라우저)에 저장합니다. 색상은 데이터·단위·계산 조건을
          변경하지 않으며, 그래프는 항상 라벨·범례를 함께 유지합니다
        </p>
      </header>

      <section className="card">
        <div className="card-head">
          <h2>워크스페이스 이름</h2>
          <span className="muted small">사이드바 상단과 브라우저 탭 제목에 즉시 반영됩니다</span>
        </div>
        <div className="form-grid">
          <Field label="앱 이름">
            <input
              className="input"
              value={appName}
              onChange={(e) => dispatch({ type: 'setAppName', name: e.target.value, subtitle: appSubtitle })}
              placeholder="BINDER SCREENING"
            />
          </Field>
          <Field label="부제">
            <input
              className="input"
              value={appSubtitle}
              onChange={(e) => dispatch({ type: 'setAppName', name: appName, subtitle: e.target.value })}
              placeholder="분자 물성 · DFT 워크벤치"
            />
          </Field>
        </div>
      </section>

      <div className="grid-2">
        <section className="card">
          <div className="card-head">
            <h2>워크스페이스 색상</h2>
          </div>
          <div className="form-grid">
            <Field label="모드">
              <select
                className="input"
                value={theme.mode}
                onChange={(e) => {
                  const mode = e.target.value as ThemeTokens['mode']
                  if (mode === 'dark') set({ ...DARK_PRESET, mode })
                  else if (mode === 'light')
                    set({ mode, background: '#ffffff', card: '#ffffff', border: '#e5e5e0', chartSeries: DEFAULT_THEME.chartSeries })
                  else set({ mode })
                }}
              >
                <option value="light">라이트 (기본 — 순백)</option>
                <option value="dark">다크</option>
                <option value="high-contrast">고대비</option>
              </select>
            </Field>
            <Field label="배경">
              <input type="color" className="input color" value={theme.background} onChange={(e) => set({ background: e.target.value })} />
            </Field>
            <Field label="카드">
              <input type="color" className="input color" value={theme.card} onChange={(e) => set({ card: e.target.value })} />
            </Field>
            <Field label="테두리">
              <input type="color" className="input color" value={theme.border} onChange={(e) => set({ border: e.target.value })} />
            </Field>
            <Field label="주요색 (딥 틸 기본)">
              <input type="color" className="input color" value={theme.accent} onChange={(e) => set({ accent: e.target.value })} />
            </Field>
            <Field label="pin 강조색 (앰버 기본)">
              <input type="color" className="input color" value={theme.pin} onChange={(e) => set({ pin: e.target.value })} />
            </Field>
          </div>
          <div className={`banner ${accentContrast < 3 || textContrast < 4.5 ? 'warn' : 'success'}`}>
            대비 검사 — 본문 텍스트 {textContrast}:1 {textContrast < 4.5 ? '(4.5:1 미달 — 대체색 권장)' : '통과'} ·
            주요색 {accentContrast}:1 {accentContrast < 3 ? '(3:1 미달 — 대체색 권장)' : '통과'}
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <h2>비교 차트 물질 series 색 (8개)</h2>
          </div>
          <div className="series-grid">
            {theme.chartSeries.map((c, i) => (
              <label key={i} className="series-item">
                <input type="color" value={c} onChange={(e) => setSeries(i, e.target.value)} />
                <span className="small muted">
                  {i + 1}번 <span className="mono">{c}</span>
                </span>
              </label>
            ))}
          </div>
          <div className="form-grid" style={{ marginTop: 12 }}>
            <Field label="MEP 음전위 색">
              <input type="color" className="input color" value={theme.mepNegative} onChange={(e) => set({ mepNegative: e.target.value })} />
            </Field>
            <Field label="MEP 양전위 색">
              <input type="color" className="input color" value={theme.mepPositive} onChange={(e) => set({ mepPositive: e.target.value })} />
            </Field>
          </div>
          <div className="chart-note">
            그래프는 색 외에도 물질명·끝점 값·범례·점선(오버레이)을 병행 표기하므로 색 변경이 판독성을
            해치지 않습니다.
          </div>
        </section>
      </div>

      <section className="card">
        <div className="card-head">
          <h2>프리셋 · Theme JSON</h2>
        </div>
        <div className="quick-actions">
          <button className="btn" onClick={() => set({ ...DEFAULT_THEME })}>
            기본 테마로 초기화
          </button>
          <button className="btn" onClick={() => set({ ...COLORBLIND_PRESET })}>
            색각 친화 preset
          </button>
          <button className="btn" onClick={() => set({ ...DARK_PRESET })}>
            다크 preset
          </button>
          <button className="btn" onClick={exportJson}>
            Theme JSON 내보내기
          </button>
          <button className="btn" onClick={() => fileRef.current?.click()}>
            Theme JSON 가져오기
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json"
            hidden
            onChange={(e) => e.target.files?.[0] && importJson(e.target.files[0])}
          />
        </div>
      </section>
    </div>
  )
}
