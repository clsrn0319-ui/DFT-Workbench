"""공용 픽스처 — in-memory SQLite + 합성 데이터셋."""

from __future__ import annotations

import pytest

import dry_process_ai.data_access.db as dbmod
from dry_process_ai.data_access.db import Base, init_db
from dry_process_ai.data_access.repository import fetch_dataset, register_lot
from dry_process_ai.data_access.sample_data import generate_lot_payloads


@pytest.fixture()
def session(tmp_path):
    """파일 기반 임시 DB 세션 (테스트 간 격리)."""
    db_url = f"sqlite:///{tmp_path}/test.db"
    # 전역 엔진 캐시를 리셋해 테스트 간 오염을 막는다
    dbmod._engine = None
    dbmod._SessionLocal = None
    init_db(db_url)
    s = dbmod.get_session()
    yield s
    s.close()
    dbmod._engine = None
    dbmod._SessionLocal = None


@pytest.fixture()
def seeded_session(session):
    """합성 40 Lot 적재된 세션."""
    for payload in generate_lot_payloads(n_lots=40, seed=7):
        register_lot(session, payload)
    session.commit()
    return session


@pytest.fixture()
def train_df(seeded_session):
    return fetch_dataset(seeded_session)
