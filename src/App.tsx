import { useEffect, useState } from 'react'
import { StoreProvider } from './store'
import { Dashboard } from './pages/Dashboard'
import { Library } from './pages/Library'
import { NewCalc } from './pages/NewCalc'
import { Jobs } from './pages/Jobs'
import { Results } from './pages/Results'

export type PageId = 'dashboard' | 'library' | 'new' | 'jobs' | 'results'

const NAV: { id: PageId; label: string; icon: string }[] = [
  { id: 'dashboard', label: '대시보드', icon: '◧' },
  { id: 'library', label: '분자 라이브러리', icon: '⬡' },
  { id: 'new', label: '새 계산', icon: '＋' },
  { id: 'jobs', label: '작업 현황', icon: '≡' },
  { id: 'results', label: '결과 분석', icon: '◔' },
]

export default function App() {
  const [page, setPage] = useState<PageId>('dashboard')
  const [theme, setTheme] = useState<'light' | 'dark'>(() =>
    window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light',
  )

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  return (
    <StoreProvider>
      <div className="layout">
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark">⚛</span>
            <div>
              <div className="brand-title">DFT 워크벤치</div>
              <div className="brand-sub">바인더 분자물성</div>
            </div>
          </div>
          <nav>
            {NAV.map((n) => (
              <button
                key={n.id}
                className={`nav-item ${page === n.id ? 'active' : ''}`}
                onClick={() => setPage(n.id)}
              >
                <span className="nav-icon">{n.icon}</span>
                {n.label}
              </button>
            ))}
          </nav>
          <div className="sidebar-foot">
            <button
              className="theme-toggle"
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            >
              {theme === 'dark' ? '☀ 라이트 모드' : '☾ 다크 모드'}
            </button>
            <div className="version">v0.1 · 모의 엔진</div>
          </div>
        </aside>
        <main className="content">
          {page === 'dashboard' && <Dashboard go={setPage} />}
          {page === 'library' && <Library go={setPage} />}
          {page === 'new' && <NewCalc go={setPage} />}
          {page === 'jobs' && <Jobs go={setPage} />}
          {page === 'results' && <Results />}
        </main>
      </div>
    </StoreProvider>
  )
}
