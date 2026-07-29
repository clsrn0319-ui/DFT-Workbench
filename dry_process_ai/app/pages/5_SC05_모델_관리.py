"""SC-05 — 모델 관리 화면 (STEP 3/8, F6)."""

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="SC-05 모델 관리", page_icon="🤖", layout="wide")

from dry_process_ai.app.common import data_status_footer, db_session, load_predictor  # noqa: E402
from dry_process_ai.core.train.trainer import TeacherRejected  # noqa: E402
from dry_process_ai.data_access.db import Evaluation, ModelVersion  # noqa: E402
from dry_process_ai.services.evaluation_service import run_evaluation  # noqa: E402
from dry_process_ai.services.training_service import run_training_pipeline  # noqa: E402

st.title("SC-05 모델 관리 — 학습·버전·평가")

c1, c2 = st.columns(2)
with c1:
    st.subheader("재학습 실행 (FT, F6)")
    epochs = st.slider("Epochs", 50, 1000, 300)
    seed = st.number_input("난수 seed (재현성 — 규칙 R8)", value=42)
    if st.button("학습 파이프라인 실행", type="primary"):
        with st.spinner("전처리 → Teacher/Student 준지도 학습 → 버전 저장 중..."):
            try:
                with db_session() as session:
                    result = run_training_pipeline(session, seed=int(seed), epochs=epochs)
                st.success(
                    f"학습 완료: **{result.version_id}** · 학습 Lot {result.train_lot_count}건 · "
                    f"이상치 플래그 {result.outlier_flags}건 · "
                    f"의사 라벨 통과율 {result.pseudo_label_pass_rate:.1%}"
                    if result.pseudo_label_pass_rate is not None else
                    f"학습 완료: **{result.version_id}** · 학습 Lot {result.train_lot_count}건"
                )
                st.cache_resource.clear()
            except TeacherRejected as exc:
                st.error(f"Student 학습 중단 (FT-04): {exc}")
            except RuntimeError as exc:
                st.error(str(exc))

with c2:
    st.subheader("종합 평가 실행 (FE)")
    write_docx = st.checkbox("DOCX 리포트 생성")
    if st.button("평가 실행"):
        loaded = load_predictor()
        if loaded is None:
            st.error("학습된 모델이 없습니다.")
        else:
            predictor, lot_count = loaded
            with st.spinner("정확도·정합성 지표 산출 중 (실측 데이터만 사용 — 규칙 R3)..."):
                with db_session() as session:
                    report, feedback = run_evaluation(session, predictor, lot_count, write_docx=write_docx)
            st.json(report.to_dict(), expanded=False)
            if feedback["raise_recommendation_priority"]:
                st.info("폐루프 (FE-07): 추천 우선순위 상향 대상 — "
                        + ", ".join(feedback["raise_recommendation_priority"]))

st.divider()
st.subheader("모델 버전 이력 (FT-08)")
with db_session() as session:
    versions = session.query(ModelVersion).order_by(ModelVersion.trained_at.desc()).all()
    evals = session.query(Evaluation).all()

if versions:
    vdf = pd.DataFrame([{
        "버전": v.version_id, "학습 일시": v.trained_at, "학습 Lot": v.train_lot_count,
        "실측 구성비": f"{v.measured_ratio:.0%}" if v.measured_ratio is not None else "-",
        "seed": v.seed, "registry": v.registry_version, "데이터셋": v.dataset_tag,
        "의사 라벨 통과율": f"{v.pseudo_label_pass_rate:.1%}" if v.pseudo_label_pass_rate else "-",
    } for v in versions])
    st.dataframe(vdf, use_container_width=True, hide_index=True)
else:
    st.info("학습 이력이 없습니다.")

if evals:
    st.subheader("버전별 평가 지표 추이")
    edf = pd.DataFrame([{
        "버전": e.version_id, "지표": e.metric_name, "값": e.metric_value,
        "학습 Lot": e.train_lot_count,
    } for e in evals])
    st.plotly_chart(px.line(edf, x="버전", y="값", color="지표", markers=True),
                    use_container_width=True)

data_status_footer()
