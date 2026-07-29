"""FD — 적재 시점 합제층 환산(FD-05)·세로 구조·출처 격리 시험."""

import pytest

from dry_process_ai.data_access.repository import fetch_dataset, fetch_stage_long, register_lot


def _payload(lot_id="T-001", source="measured"):
    return {
        "lot_id": lot_id,
        "electrode_area_cm2": 25.0,
        "source_flag": source,
        "formulation": {"active_material_content": 96.0, "binder_content": 2.0, "conductive_content": 2.0},
        "collector": {"foil_thickness_um": 15.0, "coating_side": "single"},
        "process_conditions": {"mixing": {"mixing_rpm": 12000.0}},
        "stages": {
            "R2": {"gap_um": 75.0, "measured_thickness_um": 88.0, "loading_mg_cm2": 25.4},
            # Laminating: 설비 계측(집전체 포함) 92.5 μm → 적재 시 77.5 로 환산되어야 함
            "L2": {"gap_um": 70.0, "measured_thickness_um": 92.5, "loading_mg_cm2": 24.8},
        },
        "electrode_property": {"electrode_thickness_um": 77.5, "electrode_density_gcc": 3.2,
                               "sheet_resistance_ohm_sq": 5.0},
    }


def test_laminating_thickness_converted_at_load_time(session):
    # 규칙 R1: 적재 시점 집전체 차감. 예측 시점 차감 금지.
    register_lot(session, _payload())
    session.commit()
    stage = fetch_stage_long(session)
    l2 = stage[stage.stage_index == "L2"].iloc[0]
    assert l2["composite_thickness_um"] == pytest.approx(77.5)
    # 밀도는 합제층 기준으로 계산되어 단조 증가가 유지된다
    r2 = stage[stage.stage_index == "R2"].iloc[0]
    assert l2["composite_density_gcc"] > r2["composite_density_gcc"]
    assert l2["composite_density_gcc"] == pytest.approx(24.8 / 7.75, rel=1e-6)


def test_freestanding_stage_not_subtracted(session):
    register_lot(session, _payload())
    session.commit()
    stage = fetch_stage_long(session)
    r2 = stage[stage.stage_index == "R2"].iloc[0]
    assert r2["composite_thickness_um"] == pytest.approx(88.0)  # 프리스탠딩 — 차감 없음


def test_source_flag_isolation(session):
    # 규칙 R3: 실측/생성 분리 조회
    register_lot(session, _payload("M-001", "measured"))
    register_lot(session, _payload("G-001", "generated"))
    session.commit()
    assert len(fetch_dataset(session)) == 2
    measured = fetch_dataset(session, source_flag="measured")
    assert measured["lot_id"].tolist() == ["M-001"]


def test_electrode_area_not_in_input_features():
    # 규칙 R4: 전극 면적은 모델 입력 벡터에 포함되지 않는다
    from dry_process_ai.data_access.repository import INPUT_FEATURES

    assert "electrode_area_cm2" not in INPUT_FEATURES


def test_reregister_updates_in_place(session):
    register_lot(session, _payload())
    payload = _payload()
    payload["stages"]["L2"]["measured_thickness_um"] = 90.0
    register_lot(session, payload)  # 수정 등록 — 중복 삽입 없이 갱신
    session.commit()
    stage = fetch_stage_long(session)
    assert len(stage[stage.stage_index == "L2"]) == 1
    assert stage[stage.stage_index == "L2"].iloc[0]["composite_thickness_um"] == pytest.approx(75.0)
