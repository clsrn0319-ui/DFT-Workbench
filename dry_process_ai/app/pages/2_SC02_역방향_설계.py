"""SC-02 — 역방향 설계 화면 (STEP 7, F2).

상단: 목표 설정 / 중앙: Pareto front 산점도 / 하단: 추천 상위 5건.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="SC-02 역방향 설계", page_icon="⬅️", layout="wide")

from dry_process_ai.app.common import (  # noqa: E402
    ALARM_BADGE, data_status_footer, db_session, load_train_df, require_model,
)
from dry_process_ai.services.backward_service import run_backward  # noqa: E402
from dry_process_ai.services.schemas import BackwardObjective, BackwardRequest  # noqa: E402

st.title("SC-02 역방향 설계 — 목표 성능 → 조성·공정 역추천")

predictor, train_lot_count = require_model()
train_df = load_train_df()

TARGETS = [
    "sheet_resistance_ohm_sq", "initial_discharge_capacity_mah_g",
    "initial_coulombic_efficiency_pct", "interface_resistance_ohm",
    "cell_discharge_retention_pct", "electrode_density_gcc",
    "tensile_strength_mpa", "electrode_adhesion_n_cm",
]

st.subheader("목표 설정 (FB-01)")
n_obj = st.number_input("목표 변수 수", 1, 4, 2)
objectives = []
cols = st.columns(int(n_obj))
for i, col in enumerate(cols):
    with col:
        target_col = st.selectbox(f"목표 {i + 1}", TARGETS, index=i % len(TARGETS), key=f"t{i}")
        direction = st.selectbox("방향", ["min", "max", "equal"], key=f"d{i}")
        weight = st.number_input("가중치", 0.1, 10.0, 1.0, 0.1, key=f"w{i}")
        target_val = None
        if direction == "equal":
            target_val = st.number_input("목표값", key=f"v{i}", value=3.0)
        objectives.append(BackwardObjective(
            column=target_col, direction=direction, weight=weight, target=target_val))

cap = st.number_input("목표 면적당 용량 (mAh/cm²)", 0.5, 20.0, 5.0, 0.1)
c1, c2, c3 = st.columns(3)
with c1:
    n_samples = st.slider("탐색 샘플 수", 30, 500, 120)
with c2:
    n_bo = st.slider("BO 정밀화 호출 수 (0=미사용)", 0, 50, 0)
with c3:
    run = st.button("역방향 탐색 실행", type="primary", use_container_width=True)

if run:
    request = BackwardRequest(
        objectives=objectives, target_areal_capacity_mah_cm2=cap,
        n_samples=n_samples, n_bo_calls=n_bo,
    )
    progress = st.progress(0, "조성-공정 공간 탐색 중... (60초 이내 목표 — NFR-02)")
    with db_session() as session:
        response = run_backward(session, predictor, train_df, request, train_lot_count)
    progress.progress(100, "완료")
    st.session_state["backward_response"] = response

response = st.session_state.get("backward_response")
if response is not None:
    result = response.result
    # FB-07 간헐 측정 제약 안내
    for col, info in response.strength_constraint_info.items():
        if not info["usable_as_constraint"]:
            st.info(f"⚠️ {col}: 실측 {info['measured_count']}건 — **제약 사용 불가**, 참고 지표로만 표시 (FB-07)")

    if not result.candidates:
        st.error("제약을 만족하는 후보가 없습니다. 목표 스펙을 완화하거나 데이터를 보강하세요.")
    else:
        st.subheader(f"Pareto front (유효 해 {len(result.candidates)}건 중 front {len(result.pareto_front)}건)")
        if len(result.candidates[0].objectives) >= 2:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=[c.objectives[0] for c in result.candidates],
                y=[c.objectives[1] for c in result.candidates],
                mode="markers", marker=dict(size=6, color="lightgray"), name="유효 해",
            ))
            fig.add_trace(go.Scatter(
                x=[c.objectives[0] for c in result.pareto_front],
                y=[c.objectives[1] for c in result.pareto_front],
                mode="markers", marker=dict(size=10, color="crimson"), name="Pareto front",
                text=[f"AM {c.active_material_wt:.1f} / PTFE {c.binder_wt:.1f} / SC {c.conductive_wt:.1f}"
                      for c in result.pareto_front],
            ))
            fig.update_layout(xaxis_title="목적 1 (작을수록 좋음)", yaxis_title="목적 2 (작을수록 좋음)",
                              height=380)
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("추천 레시피 상위 5건 (FB-06)")
        rows = []
        for rank, c in enumerate(result.top, start=1):
            rows.append({
                "순위": rank,
                "조성 (AM/PTFE/SC wt%)": f"{c.active_material_wt:.1f} / {c.binder_wt:.1f} / {c.conductive_wt:.1f}",
                "목표 밀도 (g/cc)": round(c.target_density_gcc, 3),
                "sheet_resistance": round(c.predictions.get("sheet_resistance_ohm_sq", float("nan")), 3),
                "알람": ALARM_BADGE[c.alarm_grade],
                "가중 점수": round(c.weighted_score, 4),
                "추천 근거": c.rationale,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        pick = st.selectbox("상세 확인할 후보", range(1, len(result.top) + 1))
        c = result.top[pick - 1]
        st.markdown(f"**갭 스케줄 (μm)**: {c.gaps_um}")
        st.markdown("**단계별 예측** — SC-01 과 동일 형식으로 확인하려면 이 조성을 순방향 화면에 입력하세요.")
        st.json({k: round(v, 4) for k, v in c.predictions.items() if not pd.isna(v)}, expanded=False)

data_status_footer()
