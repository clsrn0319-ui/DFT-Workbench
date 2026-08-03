"""SC-01 — 순방향 예측 화면 (STEP 4, F1).

좌측: 조성 심플렉스 + 목표 사양 폼 / 중앙: 공정 캐스케이드 뷰 + 추이 그래프 /
우측: 예측 결과 패널 (등급 배지) / 상단: 알람 영역.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="SC-01 순방향 예측", page_icon="➡️", layout="wide")

from dry_process_ai.app.common import (  # noqa: E402
    ALARM_BADGE, GRADE_BADGE, data_status_footer, db_session, load_train_df, require_model,
)
from dry_process_ai.config import STAGES  # noqa: E402
from dry_process_ai.services.forward_service import export_prediction_json, run_forward  # noqa: E402
from dry_process_ai.services.schemas import CollectorInput, CompositionInput, ForwardRequest  # noqa: E402

st.title("SC-01 순방향 예측 — 조성 → 공정 조건 + 단계별 예측")

predictor, train_lot_count = require_model()
train_df = load_train_df()

left, main = st.columns([1, 2])

with left:
    st.subheader("조성 (합계 100 wt%)")
    am = st.number_input("NCM811 (wt%)", 80.0, 99.0, 96.0, 0.1)
    binder = st.number_input("PTFE (wt%)", 0.5, 10.0, 2.0, 0.1)
    conductive = st.number_input("Super C (wt%)", 0.5, 10.0, round(100.0 - am - binder, 2), 0.1)
    total = am + binder + conductive
    if abs(total - 100.0) > 0.01:
        st.error(f"조성 합계 {total:.2f} wt% ≠ 100 — 자동 보정하려면 Super C 를 {100.0 - am - binder:.2f} 로 설정")

    # 심플렉스 다이어그램 — 기존 실험 분포 중첩
    fig = go.Figure()
    if len(train_df):
        fig.add_trace(go.Scatterternary(
            a=train_df["active_material_content"], b=train_df["binder_content"],
            c=train_df["conductive_content"], mode="markers",
            marker=dict(size=6, color="lightgray"), name="기존 실험",
        ))
    fig.add_trace(go.Scatterternary(
        a=[am], b=[binder], c=[conductive], mode="markers",
        marker=dict(size=12, color="red"), name="현재 조성",
    ))
    fig.update_layout(
        ternary=dict(aaxis_title="NCM811", baxis_title="PTFE", caxis_title="Super C",
                     aaxis=dict(min=0.8), sum=100),
        height=320, margin=dict(l=30, r=30, t=20, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("목표 사양")
    st.caption("용량·밀도·두께 중 둘을 지정하면 나머지는 자동 결정됩니다")
    cap = st.number_input("목표 면적당 용량 (mAh/cm²)", 0.5, 20.0, 5.0, 0.1)
    den = st.number_input("목표 합제밀도 (g/cc)", 1.0, 4.5, 3.2, 0.05)
    foil = st.number_input("집전체 두께 (μm)", 5.0, 50.0, 16.0, 0.5)
    side = st.selectbox("도포", ["single", "double"])
    area = st.number_input("전극 면적 (cm², 절대량 환산용 — 선택)", 0.0, 10000.0, 0.0, 1.0)
    mc = st.slider("MC Dropout 반복", 10, 100, 30)
    run = st.button("예측 실행", type="primary", use_container_width=True)

if run and abs(total - 100.0) <= 0.01:
    request = ForwardRequest(
        composition=CompositionInput(
            active_material_content=am, binder_content=binder, conductive_content=conductive),
        target_areal_capacity_mah_cm2=cap,
        target_density_gcc=den,
        collector=CollectorInput(foil_thickness_um=foil, coating_side=side),
        electrode_area_cm2=area or None,
        mc_samples=mc,
    )
    with st.spinner("갭 스케줄 탐색 및 단계별 예측 중..."):
        with db_session() as session:
            response = run_forward(session, predictor, train_df, request, train_lot_count)
    st.session_state["forward_response"] = response

response = st.session_state.get("forward_response")
if response is not None:
    with main:
        # ---- 상단 알람 영역 (FV) ----
        grade = response.validation.grade
        st.markdown(f"### 스펙 타당성: {ALARM_BADGE[grade]}")
        if grade != "info":
            for msg in response.validation.messages:
                st.warning(msg)
        if response.validation.alternatives:
            with st.expander("💡 대안 스펙 제안 (FV-03)", expanded=(grade == "warning")):
                for alt in response.validation.alternatives:
                    st.markdown(f"- {alt['description']}")
        if response.infeasible_reason:
            st.error(f"갭 스케줄 실현 불가: {response.infeasible_reason}")

        # ---- 공정 캐스케이드 뷰 ----
        if response.stage_table is not None:
            st.markdown("### 공정 캐스케이드 (M1 → L2)")
            table = response.stage_table.copy()
            pretty = table.rename(columns={
                "stage_index": "단계",
                "gap_front_um": "전단 갭 M12 (μm)", "gap_um": "후단 갭 M23·롤 갭 (μm)",
                "areal_capacity_mah_cm2": "면적당 용량 (mAh/cm²)",
                "composite_density_gcc": "합제밀도 (g/cc)",
                "loading_mg_cm2": "L/L (mg/cm²)",
                "composite_thickness_um": "합제층 두께 (μm)",
                "total_thickness_um": "전체 두께·집전체 포함 (μm)",
            })
            st.dataframe(pretty.round(3), use_container_width=True, hide_index=True)

            # 단계별 추이 그래프 — 면적당 용량(감소)·합제밀도(증가) 두 곡선 (값 병기)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=table["stage_index"], y=table["areal_capacity_mah_cm2"],
                name="면적당 용량 (mAh/cm²)", mode="lines+markers+text",
                text=[f"{v:.2f}" for v in table["areal_capacity_mah_cm2"]],
                textposition="top center"))
            fig.add_trace(go.Scatter(
                x=table["stage_index"], y=table["composite_density_gcc"],
                name="합제밀도 (g/cc)", mode="lines+markers+text", yaxis="y2",
                text=[f"{v:.2f}" for v in table["composite_density_gcc"]],
                textposition="bottom center", line=dict(dash="dash")))
            fig.update_layout(
                yaxis=dict(title="면적당 용량 (mAh/cm²)"),
                yaxis2=dict(title="합제밀도 (g/cc)", overlaying="y", side="right"),
                height=360, margin=dict(l=40, r=50, t=20, b=30),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig, use_container_width=True)

        # ---- 공정 조건표 ----
        st.markdown("### 공정 조건표")
        st.json(response.condition_table, expanded=False)
        if response.auto_filled:
            st.caption("⚙️ 자동 보완 조건 (FF-06): " + ", ".join(
                f"{k}={v:.4g}" for k, v in response.auto_filled.items()))

        # ---- 예측 결과 패널 (등급 배지 — FS-01) ----
        if response.prediction is not None:
            st.markdown("### 최종 물성 · 성능 예측")
            rows = []
            for col, iv in response.prediction.values.items():
                if col.split("_")[0] in STAGES:
                    continue
                rows.append({
                    "항목": col, "예측": round(iv.mean, 4),
                    "95% 신뢰구간": f"[{iv.lower:.4g}, {iv.upper:.4g}]",
                    "확보 등급": GRADE_BADGE[iv.grade],
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            if not response.prediction.consistency.passed:
                st.error("정합성 검사 위반 항목 존재 (FF-08): " + "; ".join(
                    v.message for v in response.prediction.consistency.violations))

        if response.absolute_quantities:
            st.markdown("### 절대량 환산 (FD-08)")
            aq = response.absolute_quantities
            st.markdown(
                f"- 총 합제 질량: **{aq['total_composite_mass_g']:.2f} g** · "
                f"총 용량: **{aq['total_capacity_mah']:.1f} mAh** "
                f"(면적 {aq['electrode_area_cm2']} cm² × {aq['coated_face_count']}면)"
            )

        if st.button("📄 조건표 내보내기 (JSON)"):
            path = export_prediction_json(response)
            st.success(f"저장됨: {path}")

data_status_footer()
