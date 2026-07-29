"""KETI 실험 Lot Excel 변환기 (keti_xlsx) 시험 — 실측 원본 기준."""

from pathlib import Path

import pytest

from dry_process_ai.data_access.keti_xlsx import parse_keti_workbook

XLSX = Path(__file__).resolve().parents[2] / "data" / "reference" / "keti_experiment_lots.xlsx"

pytestmark = pytest.mark.skipif(not XLSX.exists(), reason="실측 원본 파일 없음")


@pytest.fixture(scope="module")
def payloads():
    return parse_keti_workbook(XLSX)


def test_ten_lots_parsed(payloads):
    assert len(payloads) == 10
    assert all(p["source_flag"] == "measured" for p in payloads)


def test_composition_sums_to_100(payloads):
    for p in payloads:
        f = p["formulation"]
        total = f["active_material_content"] + f["binder_content"] + f["conductive_content"]
        assert total == pytest.approx(100.0, abs=0.01), p["lot_id"]


def test_experiment1_matches_source(payloads):
    p = payloads[0]
    assert p["lot_id"] == "건식 실험 1"
    # M1: 갭 180/180 → 180, 두께 289, 밀도 2.8, L/L 75.37 (원본 그대로)
    m1 = p["stages"]["M1"]
    assert m1["gap_um"] == 180.0
    assert m1["composite_thickness_um"] == 289.0
    assert m1["composite_density_gcc"] == 2.8
    # L2: 77 μm / 3.24 g/cc — 원본이 합제층 기준이므로 재차감 없음
    l2 = p["stages"]["L2"]
    assert l2["composite_thickness_um"] == 77.0
    assert l2["composite_density_gcc"] == 3.24


def test_units_normalized(payloads):
    p = payloads[0]
    # 초 → 분: mixing 180 s → 3 min, kneading 270 s → 4.5 min, cutting 30 s → 0.5 min
    assert p["process_conditions"]["mixing"]["mixing_time"] == 3.0
    assert p["process_conditions"]["kneading"]["kneader_time"] == 4.5
    assert p["process_conditions"]["cutting"]["cutting_time"] == 0.5
    # 시트 저항 ×10⁴ Ω/□ → Ω/sq
    assert p["electrode_property"]["sheet_resistance_ohm_sq"] == pytest.approx(2.8e4)
    # 유지율 분율 → %: 실험 1 은 0.8 → 80 %
    assert p["electrochem"]["cell_discharge_retention_pct"] == pytest.approx(80.0)


def test_retention_percent_passthrough(payloads):
    # 실험 8 은 백분율(81.2)로 기록 — 그대로 유지
    p8 = next(p for p in payloads if p["lot_id"] == "건식 실험 8")
    assert p8["electrochem"]["cell_discharge_retention_pct"] == pytest.approx(81.2)


def test_missing_stages_kept_missing(payloads):
    # 실험 5 는 M1~M3 만 존재 — 결측 단계는 payload 에 포함되지 않는다 (FP-02)
    p5 = next(p for p in payloads if p["lot_id"] == "건식 실험 5")
    assert sorted(p5["stages"].keys()) == ["M1", "M2", "M3"]


def test_interface_resistance_not_fabricated(payloads):
    # 원본에 계면 저항 측정이 없다 — 임의 생성 금지, 결측 유지
    for p in payloads:
        assert "interface_resistance_ohm" not in p.get("electrochem", {})
