"""SC-04 — 실험 추천 화면 (STEP 6, F5)."""

import pandas as pd
import streamlit as st

st.set_page_config(page_title="4. AI 강화 실험 추천", page_icon="🧪", layout="wide")

from dry_process_ai.app.common import data_status_footer, db_session, require_model  # noqa: E402
from dry_process_ai.services.recommend_service import (  # noqa: E402
    build_unlabeled_pool, register_experiment_result, run_recommend,
)
from dry_process_ai.services.schemas import RecommendRequest  # noqa: E402

st.title("4. AI 강화 실험 추천 — 능동학습 기반 다음 실험 조건")

predictor, train_lot_count = require_model()

c1, c2, c3 = st.columns(3)
with c1:
    mode = st.selectbox("추천 모드 (FR-02)", ["balanced", "exploration", "exploitation"],
                        format_func=lambda m: {"balanced": "균형 (기본)", "exploration": "탐색 — 불확실성 우선",
                                               "exploitation": "활용 — 목표 달성 우선"}[m])
with c2:
    k = st.slider("Top-K", 1, 20, 5)
with c3:
    pool_size = st.slider("Pool 크기", 50, 1000, 300)

target_col = st.selectbox("목표 변수 (활용 모드용, 선택)", ["없음", "sheet_resistance_ohm_sq",
                                                     "initial_discharge_capacity_mah_g"])
target_val = st.number_input("목표값", value=5.0) if target_col != "없음" else None

if st.button("추천 실행", type="primary"):
    with st.spinner("unlabeled pool 생성 및 MC Dropout 불확실성 추정 중..."):
        with db_session() as session:
            pool = build_unlabeled_pool(session, n_candidates=pool_size)
            request = RecommendRequest(
                mode=mode, k=k,
                targets=({target_col: target_val} if target_val is not None else {}),
            )
            recs = run_recommend(session, predictor, pool, request, train_lot_count)
    st.session_state["recommendations"] = recs

recs = st.session_state.get("recommendations")
if recs:
    st.subheader(f"추천 조건 Top-{len(recs)}")
    rows = []
    for r in recs:
        rows.append({
            "순위": r.rank,
            "조성 (AM/PTFE/SC)": f"{r.features['active_material_content']:.2f} / "
                               f"{r.features['binder_content']:.2f} / {r.features['conductive_content']:.2f}",
            "불확실성": round(r.uncertainty, 3),
            "목표 근접도": round(r.goal_proximity, 3),
            "결합 점수": round(r.combined_score, 3),
            "추천 사유 (FR-05)": r.reason,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.divider()
st.subheader("실험 결과 입력 (FR-06) — 입력 시 train set 이동 + 재학습 트리거")
with st.form("experiment_result"):
    lot_id = st.text_input("Lot ID", "EXP-0001")
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        am = st.number_input("NCM811 (wt%)", value=96.0)
    with fc2:
        binder = st.number_input("PTFE (wt%)", value=2.0)
    with fc3:
        conductive = st.number_input("Super C (wt%)", value=2.0)
    thickness = st.number_input("최종 전극 두께 (μm)", value=80.0)
    density = st.number_input("최종 합제밀도 (g/cc)", value=3.1)
    resistance = st.number_input("시트 저항 (Ω/sq)", value=5.0)
    submitted = st.form_submit_button("등록")
    if submitted:
        payload = {
            "lot_id": lot_id,
            "formulation": {"active_material_content": am, "binder_content": binder,
                            "conductive_content": conductive},
            "collector": {"foil_thickness_um": 15.0},
            "electrode_property": {"electrode_thickness_um": thickness,
                                   "electrode_density_gcc": density,
                                   "sheet_resistance_ohm_sq": resistance},
        }
        with db_session() as session:
            lot, retrain = register_experiment_result(session, payload)
        st.success(f"Lot {lot} 등록 완료 — 재학습이 필요합니다 (「5. 모델 관리」에서 실행). 캐시를 새로고침하세요.")
        st.cache_resource.clear()

data_status_footer()
