"""SC-06 — 데이터 관리 화면 (STEP 1/2)."""

import pandas as pd
import streamlit as st

st.set_page_config(page_title="6. 데이터 관리", page_icon="🗄️", layout="wide")

from dry_process_ai.app.common import data_status_footer, db_session, load_train_df  # noqa: E402
from dry_process_ai.data_access.db import VariableDict  # noqa: E402
from dry_process_ai.data_access.importer import import_lot_file  # noqa: E402
from dry_process_ai.data_access.repository import fetch_stage_long, register_lot  # noqa: E402
from dry_process_ai.data_access.sample_data import generate_lot_payloads  # noqa: E402
from dry_process_ai.rules.outliers import detect_stage_outliers  # noqa: E402

st.title("6. 데이터 관리 — Lot 등록·가져오기·변수 사전·이상치 검토")

tab_list, tab_import, tab_dict, tab_outlier = st.tabs(
    ["Lot 목록·합성 데이터", "CSV/Excel 가져오기 (FD-02)", "변수 사전 (FD-03)", "이상치 검토 (FP-01)"]
)

with tab_list:
    df = load_train_df()
    st.metric("적재 Lot 수", len(df))
    if len(df):
        st.dataframe(
            df[["lot_id", "source_flag", "electrode_area_cm2", "active_material_content",
                "binder_content", "conductive_content", "electrode_density_gcc",
                "sheet_resistance_ohm_sq"]].round(3),
            use_container_width=True, hide_index=True,
        )
    st.divider()
    st.subheader("학습 보강용 합성 데이터 생성")
    st.caption("생성 데이터는 회귀 시험·제약 학습 전용이며 평가·중요도 해석에서 자동 제외됩니다 (규칙 R3)")
    n = st.slider("생성 Lot 수", 10, 200, 40)
    if st.button("합성 데이터 생성·적재"):
        with db_session() as session:
            for payload in generate_lot_payloads(n_lots=n):
                register_lot(session, payload)
            session.commit()
        st.success(f"{n}건 적재 완료 (source_flag=generated)")
        st.cache_resource.clear()

with tab_import:
    st.caption("컬럼은 변수 사전 명칭을 사용합니다. 단계별 값: gap_M1, M1_composite_thickness_um, "
               "L1_measured_thickness_um(집전체 포함 — 적재 시 자동 차감·FD-05) 등")
    uploaded = st.file_uploader("CSV / Excel 파일", type=["csv", "xlsx", "xls"])
    if uploaded is not None and st.button("적재 실행"):
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded.name).suffix) as tmp:
            tmp.write(uploaded.getvalue())
            tmp_path = tmp.name
        with db_session() as session:
            report = import_lot_file(session, tmp_path)
        st.success(f"적재 {len(report.imported_lots)}건")
        if report.unmapped_columns:
            st.warning("매핑 실패 컬럼 (검토 필요): " + ", ".join(report.unmapped_columns))
        if report.unit_conversions:
            st.info("단위 변환: " + ", ".join(report.unit_conversions))
        for err in report.errors:
            st.error(err)
        st.cache_resource.clear()

with tab_dict:
    with db_session() as session:
        variables = session.query(VariableDict).all()
    vdf = pd.DataFrame([{
        "변수명": v.variable_name, "단위": v.unit, "하한": v.min_value, "상한": v.max_value,
        "등급": v.grade, "공정군": v.process_group, "활성": v.active,
        "상수": v.constant_value if v.is_constant else None, "설명": v.description,
    } for v in variables])
    st.dataframe(vdf, use_container_width=True, hide_index=True)
    st.caption("미확보 변수(mixing_max_torque, kneader_torque)는 사전 등록 상태이며 "
               "확보 시 활성화하여 재학습 대상으로 편입합니다")

with tab_outlier:
    with db_session() as session:
        stage_long = fetch_stage_long(session)
    if stage_long.empty:
        st.info("단계별 계측 데이터가 없습니다.")
    else:
        d = stage_long["composite_density_gcc"].dropna()
        density_range = (float(d.min()), float(d.max())) if len(d) >= 5 else None
        report = detect_stage_outliers(stage_long, density_history_range=density_range)
        if not report.flags:
            st.success("이상치 없음 — 전 규칙 통과")
        else:
            st.warning(f"이상치 플래그 {len(report.flags)}건 (판정선은 실측 이력에서 동적 산출)")
            st.dataframe(pd.DataFrame([{
                "Lot": f.lot_id, "단계": f.stage_index, "규칙": f.rule,
                "컬럼": f.column, "내용": f.message, "조치": f.action,
            } for f in report.flags]), use_container_width=True, hide_index=True)

data_status_footer()
