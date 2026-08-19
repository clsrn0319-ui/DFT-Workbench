"""메인 화면 — 시스템 개요와 현황."""

import streamlit as st

st.set_page_config(page_title="AI 건식 공정 최적화", page_icon="🔋", layout="wide")

from dry_process_ai.app.common import data_status_footer, load_predictor, load_train_df  # noqa: E402

st.title("🔋 AI 기반 건식 전극 공정 최적화 예측 프로그램")
st.markdown(
    """
**NCM811 / PTFE / Super C** 3성분 고정 소재계 ·
`Mixing → Kneading → Cutting → Milling(M1~M4) → Rolling(R1~R2) → Laminating(L1~L2)`

| 화면 | 기능 |
|---|---|
| **SC-01 순방향 예측** | 조성비 + 목표 사양 → 공정 조건표 + 단계별 예측표 (F1) |
| **SC-02 역방향 설계** | 목표 성능 → Pareto front + 추천 레시피 (F2) |
| **SC-03 변수 중요도** | 목표별 기여도, 조성-공정 상호작용 (F4) |
| **SC-04 실험 추천** | 능동학습 기반 다음 실험 조건 Top-K (F5) |
| **SC-05 모델 관리** | 학습 실행, 버전·평가 지표, 폐루프 (F6) |
| **SC-06 데이터 관리** | Lot 등록, CSV 가져오기, 변수 사전, 이상치 검토 |
"""
)

col1, col2, col3 = st.columns(3)
df = load_train_df()
loaded = load_predictor()
with col1:
    st.metric("적재 Lot 수", len(df))
with col2:
    measured = int((df["source_flag"] == "measured").sum()) if len(df) else 0
    st.metric("실측 Lot 수", measured)
with col3:
    st.metric("모델 버전", loaded[0].model_version if loaded else "미학습")

if len(df) == 0:
    st.info("데이터가 없습니다. **SC-06 데이터 관리**에서 Lot 을 등록하거나 CSV 를 가져오세요. "
            "데모용 합성 데이터는 SC-06 의 '합성 데이터 생성' 버튼으로 적재할 수 있습니다 "
            "(생성 데이터는 평가·해석에서 자동 제외됩니다).")

data_status_footer()
