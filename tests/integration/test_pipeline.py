"""통합 시험 — STEP 1~8 파이프라인 연결 (샘플 데이터로 전 구간 실행).

판정 기준: 오류 없이 전 산출물 생성 + 물리 제약 위반 출력 0건 (NFR-04).
"""

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("tensorflow")

from dry_process_ai.config import STAGES  # noqa: E402
from dry_process_ai.core.analyze.evaluation import evaluate_model  # noqa: E402
from dry_process_ai.core.analyze.importance import permutation_importance  # noqa: E402
from dry_process_ai.core.infer.predictor import Predictor  # noqa: E402
from dry_process_ai.core.optimize.backward import BackwardDesigner, ObjectiveSpec  # noqa: E402
from dry_process_ai.core.optimize.recommend import recommend_experiments  # noqa: E402
from dry_process_ai.core.train.trainer import train_teacher_student  # noqa: E402
from dry_process_ai.data_access.capability import build_capability  # noqa: E402
from dry_process_ai.data_access.pool import generate_pool  # noqa: E402
from dry_process_ai.data_access.preprocess import ScalingRegistry  # noqa: E402
from dry_process_ai.data_access.repository import (  # noqa: E402
    ALL_TARGET_COLUMNS, INPUT_FEATURES, fetch_dataset, register_lot,
)
from dry_process_ai.data_access.sample_data import generate_lot_payloads  # noqa: E402
from dry_process_ai.services.forward_service import run_forward  # noqa: E402
from dry_process_ai.services.schemas import CompositionInput, ForwardRequest  # noqa: E402

EPOCHS = 40  # 시험용 소규모 학습


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    """모듈 공유 픽스처: 합성 데이터 적재 → 학습 → Predictor."""
    import dry_process_ai.data_access.db as dbmod
    from dry_process_ai.data_access.db import init_db

    tmp = tmp_path_factory.mktemp("db")
    dbmod._engine = None
    dbmod._SessionLocal = None
    init_db(f"sqlite:///{tmp}/pipe.db")
    session = dbmod.get_session()

    # 일부를 실측으로 표시해 평가·중요도 경로를 검증한다
    for i, payload in enumerate(generate_lot_payloads(n_lots=30, seed=11)):
        payload["source_flag"] = "measured" if i < 15 else "generated"
        register_lot(session, payload)
    session.commit()

    df = fetch_dataset(session)
    registry = ScalingRegistry.fit(df, list(INPUT_FEATURES), list(ALL_TARGET_COLUMNS), version="v1.0")
    # 소규모 epoch 시험이므로 통과율 임계는 적용하지 않는다 (임계 동작은 단위 시험에서 검증)
    result = train_teacher_student(df, registry, seed=3, epochs=EPOCHS, verbose=0, min_pass_rate=0.0)
    predictor = Predictor(result.model, result.spec, registry, "v1.0")
    yield session, df, predictor, result
    session.close()
    dbmod._engine = None
    dbmod._SessionLocal = None


def test_training_completes(trained):
    _, df, _, result = trained
    assert result.train_lot_count == len(df)
    assert 0.0 < result.measured_ratio < 1.0
    if result.pseudo_label_result is not None:
        # FT-04: 통과율이 로그로 기록되어야 한다 (임계 판정 동작은 단위 시험에서 검증)
        assert 0.0 <= result.pseudo_label_result.pass_rate <= 1.0


def test_forward_service_end_to_end(trained):
    session, df, predictor, _ = trained
    request = ForwardRequest(
        composition=CompositionInput(active_material_content=96, binder_content=2, conductive_content=2),
        target_areal_capacity_mah_cm2=5.0,
        target_density_gcc=3.0,
        mc_samples=10,
    )
    response = run_forward(session, predictor, df, request, train_lot_count=len(df))
    assert response.validation.grade in ("info", "caution", "warning")
    assert response.schedule is not None
    assert response.stage_table is not None and len(response.stage_table) == 8

    # 물리 제약 위반 출력 0건 (NFR-04): 예측 단계열 단조성 확인
    t = response.stage_table["composite_thickness_um"].to_numpy()
    d = response.stage_table["composite_density_gcc"].to_numpy()
    assert all(a >= b - 1e-6 for a, b in zip(t, t[1:]))
    assert all(a <= b + 1e-6 for a, b in zip(d, d[1:]))

    # 모든 예측값에 신뢰 구간 + 등급 배지 동반 (NFR-05)
    for iv in response.prediction.values.values():
        assert iv.lower <= iv.mean <= iv.upper
        assert iv.grade in ("A", "B", "C")

    # Laminating 단계는 집전체 포함 전체 두께 병기
    l2 = response.stage_table[response.stage_table.stage_index == "L2"].iloc[0]
    assert l2["total_thickness_um"] == pytest.approx(
        l2["composite_thickness_um"] + request.collector.foil_thickness_um)


def test_evaluation_uses_measured_only(trained):
    session, df, predictor, _ = trained
    report = evaluate_model(predictor, df, train_lot_count=len(df))
    assert report.measured_lot_count == int((df["source_flag"] == "measured").sum())
    assert report.consistency["violation_rate_pct"] == 0.0  # 제약 위반율 0 % 목표
    # 30건 미만 실측 → 정확도 유예 명시
    assert any("30건" in note for note in report.notes)


def test_importance_excludes_generated(trained):
    _, df, predictor, _ = trained
    result = permutation_importance(predictor, df, ["sheet_resistance_ohm_sq"], n_repeats=2)
    assert result.measured_lot_count == int((df["source_flag"] == "measured").sum())
    assert not result.per_feature.empty


def test_recommend_pipeline(trained):
    session, df, predictor, _ = trained
    pool = generate_pool(df, n_candidates=30, seed=5)
    assert not pool.empty
    capability = build_capability(session)
    recs = recommend_experiments(
        predictor, pool, mode="balanced", k=3,
        targets={"sheet_resistance_ohm_sq": 4.0},
        capability=capability, mc_samples=8,
    )
    assert len(recs) == 3
    for r in recs:
        assert r.reason  # FR-05 추천 근거 필수
        total = (r.features["active_material_content"] + r.features["binder_content"]
                 + r.features["conductive_content"])
        assert total == pytest.approx(100.0, abs=0.01)  # 조성 제약


def test_backward_design(trained):
    session, df, predictor, _ = trained
    capability = build_capability(session)
    designer = BackwardDesigner(predictor, capability, df, seed=2)
    result = designer.design(
        [ObjectiveSpec("sheet_resistance_ohm_sq", "min", 3.0),
         ObjectiveSpec("initial_discharge_capacity_mah_g", "max", 2.0)],
        target_areal_capacity=5.0, n_samples=40, top_k=5,
    )
    assert result.candidates, "제약 통과 후보가 있어야 한다"
    assert result.pareto_front
    assert len(result.top) <= 5
    for cand in result.top:
        assert cand.alarm_grade in ("info", "caution", "warning")
        assert cand.rationale  # FB-06 추천 근거
        assert cand.active_material_wt + cand.binder_wt + cand.conductive_wt == pytest.approx(100.0)
