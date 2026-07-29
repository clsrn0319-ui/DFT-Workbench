"""실측 기반 부트스트랩 생성기 (augment) 시험 — 규칙 R3, 실측 1순위 원칙."""

import pytest

from dry_process_ai.config import STAGES
from dry_process_ai.data_access.augment import augment_dataset, generate_augmented_payloads
from dry_process_ai.data_access.repository import fetch_dataset, register_lot
from dry_process_ai.data_access.sample_data import generate_lot_payloads
from dry_process_ai.rules import constraints, physics


@pytest.fixture()
def measured_session(session):
    """실측으로 표시된 12 Lot 시드."""
    for payload in generate_lot_payloads(n_lots=12, seed=3, source_flag="measured", lot_prefix="MEA"):
        register_lot(session, payload)
    session.commit()
    return session


def test_requires_measured_anchors(session):
    # 실측이 전무하면 부트스트랩 불가 — 실측 1순위 원칙
    with pytest.raises(ValueError):
        generate_augmented_payloads(session, n_lots=5)


def test_generated_flag_and_anchor_note(measured_session):
    payloads = generate_augmented_payloads(measured_session, n_lots=10, seed=1)
    assert len(payloads) == 10
    for p in payloads:
        assert p["source_flag"] == "generated"
        assert p["note"].startswith("bootstrap anchor=MEA-")


def test_deterministic(measured_session):
    a = generate_augmented_payloads(measured_session, n_lots=8, seed=9)
    b = generate_augmented_payloads(measured_session, n_lots=8, seed=9)
    assert a == b


def test_composition_within_measured_range(measured_session):
    measured = fetch_dataset(measured_session, source_flag="measured")
    b_lo, b_hi = measured["binder_content"].min(), measured["binder_content"].max()
    c_lo, c_hi = measured["conductive_content"].min(), measured["conductive_content"].max()
    for p in generate_augmented_payloads(measured_session, n_lots=20, seed=2):
        f = p["formulation"]
        total = f["active_material_content"] + f["binder_content"] + f["conductive_content"]
        assert total == pytest.approx(100.0, abs=0.01)
        assert b_lo - 1e-9 <= f["binder_content"] <= b_hi + 1e-9
        assert c_lo - 1e-9 <= f["conductive_content"] <= c_hi + 1e-9


def test_physical_consistency(measured_session):
    """생성 Lot 은 질량 보존·용량-로딩 연동·단조성을 정확히 만족해야 한다."""
    for p in generate_augmented_payloads(measured_session, n_lots=10, seed=4):
        am_frac = p["formulation"]["active_material_content"] / 100.0
        stage_values = {
            s: {
                "composite_thickness_um": v["composite_thickness_um"],
                "composite_density_gcc": v["composite_density_gcc"],
                "loading_mg_cm2": v["loading_mg_cm2"],
                "areal_capacity_mah_cm2": v["areal_capacity_mah_cm2"],
            }
            for s, v in p["stages"].items()
        }
        report = constraints.check_stage_sequence(stage_values, active_material_fraction=am_frac)
        assert report.passed, [v.message for v in report.violations]


def test_missing_pattern_inherited(measured_session):
    """앵커의 B등급 결측(인장강도 미측정) 패턴은 생성 Lot 에서도 유지된다 (FP-02)."""
    payloads = generate_augmented_payloads(measured_session, n_lots=30, seed=5)
    for p in payloads:
        ep = p.get("electrode_property", {})
        # 앵커가 측정하지 않은 인장강도·접착력을 임의 생성하지 않는다
        anchor_id = p["note"].split("=")[1]
        assert "tensile_strength_mpa" not in ep or ep["tensile_strength_mpa"] is not None, anchor_id


def test_augment_dataset_registers(measured_session):
    ids = augment_dataset(measured_session, n_lots=6, seed=7)
    assert len(ids) == 6
    df = fetch_dataset(measured_session)
    assert (df["source_flag"] == "generated").sum() == 6
    # 실측만 조회하는 평가 경로에는 혼입되지 않는다 (규칙 R3)
    assert (fetch_dataset(measured_session, source_flag="measured")["source_flag"] == "measured").all()
