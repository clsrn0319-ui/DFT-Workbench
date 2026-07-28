import { useStore } from '../store'
import { DESCRIPTOR_GROUPS, DESCRIPTORS } from '../data/descriptors'

// 기획서 3.2 지식 영역 — 물성 사전 (부록 D: 16 descriptor / 7 그룹)
export function Dictionary() {
  const { pins, dispatch } = useStore()

  return (
    <div>
      <header className="page-head">
        <h1>물성 사전</h1>
        <p className="page-desc">
          16개 DFT descriptor를 7개 그룹으로 정의합니다. "더 음수/더 양수이면 무조건 좋다"와 같은 단일 방향
          평가는 하지 않으며, ★ 고정 시 결과 상단·비교 표·레이더 축에 동기화됩니다
        </p>
      </header>

      {DESCRIPTOR_GROUPS.map((group) => {
        const list = DESCRIPTORS.filter((d) => d.group === group)
        return (
          <section key={group} className="card">
            <div className="card-head">
              <h2>{group}</h2>
              <span className="muted small">{list.length}개 항목</span>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: 34 }}>★</th>
                  <th>표시명 / 필드 키</th>
                  <th>권장 단위</th>
                  <th>정의 · 조건 · 해석 주의</th>
                </tr>
              </thead>
              <tbody>
                {list.map((d) => (
                  <tr key={d.key}>
                    <td>
                      <button
                        className={`pin-btn ${pins.includes(d.key) ? 'on' : ''}`}
                        title="물성 고정"
                        onClick={() => dispatch({ type: 'togglePin', key: d.key })}
                      >
                        ★
                      </button>
                    </td>
                    <td>
                      <b>{d.label}</b>
                      <div className="mono small muted">{d.key}</div>
                      {d.interfacial && <span className="badge queued">계면·실험 — DFT 고유값 제공 금지</span>}
                    </td>
                    <td className="small">{d.unit}</td>
                    <td className="small">
                      {d.definition}
                      <div className="muted">{d.caution}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )
      })}
    </div>
  )
}
