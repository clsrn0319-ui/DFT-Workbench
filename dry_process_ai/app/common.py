"""화면 공통 유틸 — 모델·데이터 로드, 등급 배지(FS-01), 현황 표기(FS-02)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dry_process_ai.config import ensure_directories
from dry_process_ai.data_access.db import SOURCE_MEASURED, get_session, init_db
from dry_process_ai.data_access.repository import fetch_dataset

GRADE_BADGE = {"A": "🟢 A 상시측정", "B": "🟡 B 간헐측정", "C": "🔵 C 지연측정"}
ALARM_BADGE = {"info": "✅ 정보", "caution": "🟡 주의", "warning": "🔴 경고"}


@st.cache_resource
def bootstrap():
    ensure_directories()
    init_db()
    return True


def db_session():
    bootstrap()
    return get_session()


@st.cache_resource
def load_predictor():
    """최신 모델 로드 (기동 시 1회 상주 — NFR-01)."""
    from dry_process_ai.services.training_service import load_latest_predictor

    with db_session() as session:
        return load_latest_predictor(session)


def load_train_df() -> pd.DataFrame:
    with db_session() as session:
        return fetch_dataset(session)


def data_status_footer():
    """FS-02 — 학습 Lot 수와 실측/생성 구성비를 모든 화면에 표기."""
    df = load_train_df()
    loaded = load_predictor()
    n = len(df)
    measured = int((df["source_flag"] == SOURCE_MEASURED).sum()) if n else 0
    version = loaded[0].model_version if loaded else "미학습"
    st.caption(
        f"모델 버전: **{version}** · 적재 Lot: **{n}건** "
        f"(실측 {measured} / 생성 {n - measured}) · "
        f"실측 30건 미만 구간에서는 정확도 지표 대신 물리 제약 준수가 판정 기준입니다"
    )


def require_model():
    loaded = load_predictor()
    if loaded is None:
        st.warning("학습된 모델이 없습니다. **SC-05 모델 관리**에서 학습을 먼저 실행하세요.")
        st.stop()
    return loaded
