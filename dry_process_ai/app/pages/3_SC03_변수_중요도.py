"""SC-03 — 변수 중요도 화면 (STEP 5, F4)."""

import plotly.express as px
import streamlit as st

st.set_page_config(page_title="SC-03 변수 중요도", page_icon="📊", layout="wide")

from dry_process_ai.app.common import data_status_footer, load_train_df, require_model  # noqa: E402
from dry_process_ai.core.analyze.importance import (  # noqa: E402
    composition_process_interaction, permutation_importance,
)

st.title("SC-03 변수 중요도 — Permutation Importance")

predictor, train_lot_count = require_model()
train_df = load_train_df()
measured_n = int((train_df["source_flag"] == "measured").sum()) if len(train_df) else 0

if measured_n == 0:
    st.warning("실측 Lot 이 없습니다. 생성 데이터는 중요도 해석에 사용하지 않습니다 (규칙 R3).")
    st.stop()

TARGETS = ["sheet_resistance_ohm_sq", "electrode_density_gcc", "electrode_thickness_um",
           "tensile_strength_mpa", "electrode_adhesion_n_cm"]
target = st.selectbox("목표 변수 (FA-02 목표별 분리 산출)", TARGETS)
n_repeats = st.slider("반복 수", 2, 10, 3)

if st.button("중요도 산출", type="primary"):
    with st.spinner("변수별 치환 평가 중..."):
        result = permutation_importance(predictor, train_df, [target], n_repeats=n_repeats)
    st.session_state["importance_result"] = (target, result)

stored = st.session_state.get("importance_result")
if stored is not None:
    target, result = stored
    st.caption(f"⚠️ {result.confidence_note} · 모델 {result.model_version}")

    imp = result.per_feature[target].sort_values(ascending=False).head(15)
    fig = px.bar(x=imp.values, y=imp.index, orientation="h",
                 labels={"x": "오차 증가량 (중요도)", "y": "변수"})
    fig.update_layout(height=420, yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("공정군별 기여도 (FA-04)")
    grp = result.per_group[target].sort_values(ascending=False)
    st.plotly_chart(px.bar(x=grp.index, y=grp.values,
                           labels={"x": "공정군", "y": "기여도"}), use_container_width=True)

    st.subheader("조성-공정 상호작용 히트맵 (FA-05)")
    if st.button("상호작용 산출 (수 분 소요 가능)"):
        with st.spinner("동시 치환 평가 중..."):
            matrix = composition_process_interaction(predictor, train_df, target_column=target)
        st.plotly_chart(px.imshow(matrix.astype(float), text_auto=".3f", aspect="auto",
                                  labels=dict(color="상호작용")), use_container_width=True)
        st.caption("양수 = 개별 치환 합보다 동시 치환의 오차 증가가 큼 → 조성 변경 시 해당 공정 재조정 필요")

data_status_footer()
