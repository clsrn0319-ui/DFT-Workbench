import { useState } from 'react'
import { StoreProvider } from './store'
import { Dashboard } from './pages/Dashboard'
import { Library } from './pages/Library'
import { MaterialDetail } from './pages/MaterialDetail'
import { Calc } from './pages/Calc'
import { Solvents } from './pages/Solvents'
import { Results } from './pages/Results'
import { Compare } from './pages/Compare'
import { Dictionary } from './pages/Dictionary'
import { Settings } from './pages/Settings'

export type PageId =
  | 'dashboard'
  | 'library'
  | 'detail'
  | 'calc'
  | 'solvents'
  | 'results'
  | 'compare'
  | 'dictionary'
  | 'settings'

export interface Nav {
  go: (p: PageId, materialId?: string) => void
}

// 기획서 3.2 정보 구조: 좌측 1차 메뉴 — "DFT 계산 결과" 바로 아래 "물질 비교"
const NAV: { group: string; items: { id: PageId; label: string }[] }[] = [
  { group: '', items: [{ id: 'dashboard', label: '대시보드' }] },
  {
    group: '분자 데이터',
    items: [
      { id: 'library', label: '물질 보관함' },
      { id: 'detail', label: '분자 물성' },
    ],
  },
  {
    group: '계산',
    items: [
      { id: 'calc', label: '구조 최적화 · DFT' },
      { id: 'solvents', label: '용매 라이브러리' },
    ],
  },
  {
    group: '결과',
    items: [
      { id: 'results', label: 'DFT 계산 결과' },
      { id: 'compare', label: '물질 비교' },
    ],
  },
  { group: '지식', items: [{ id: 'dictionary', label: '물성 사전' }] },
  { group: '설정', items: [{ id: 'settings', label: '시각화 · 계정' }] },
]

export default function App() {
  const [page, setPage] = useState<PageId>('dashboard')
  const [materialId, setMaterialId] = useState<string | null>(null)

  const go = (p: PageId, mid?: string) => {
    if (mid) setMaterialId(mid)
    setPage(p)
  }

  return (
    <StoreProvider>
      <div className="layout">
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark">⌬</span>
            <div>
              <div className="brand-title">BINDER SCREENING</div>
              <div className="brand-sub">분자 물성 · DFT 워크벤치</div>
            </div>
          </div>
          <nav>
            {NAV.map((g) => (
              <div key={g.group || 'root'} className="nav-group">
                {g.group && <div className="nav-group-label">{g.group}</div>}
                {g.items.map((n) => (
                  <button
                    key={n.id}
                    className={`nav-item ${page === n.id ? 'active' : ''}`}
                    onClick={() => setPage(n.id)}
                  >
                    {n.label}
                  </button>
                ))}
              </div>
            ))}
          </nav>
          <div className="sidebar-foot">
            <div className="server-chip">
              <span className="dot ok" /> API · 큐 · 워커 정상
            </div>
            <div className="version">통합 기획서 v4.0 기준 · 프로토타입</div>
          </div>
        </aside>
        <main className="content">
          {page === 'dashboard' && <Dashboard go={go} />}
          {page === 'library' && <Library go={go} />}
          {page === 'detail' && <MaterialDetail go={go} materialId={materialId} />}
          {page === 'calc' && <Calc go={go} materialId={materialId} />}
          {page === 'solvents' && <Solvents go={go} />}
          {page === 'results' && <Results go={go} materialId={materialId} />}
          {page === 'compare' && <Compare go={go} />}
          {page === 'dictionary' && <Dictionary />}
          {page === 'settings' && <Settings />}
        </main>
      </div>
    </StoreProvider>
  )
}
