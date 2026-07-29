"""FP-01 이상치 판정 규칙 — 위반 케이스 주입 시험 (전 규칙 정상 검출)."""

import pandas as pd

from dry_process_ai.rules import outliers


def _base_stage_df():
    rows = []
    for lot in ("A", "B", "C", "D"):
        for stage, gap, t, d in (
            ("M1", 180, 289, 2.60), ("M2", 130, 182, 2.65),
            ("M3", 105, 120, 2.71), ("M4", 80, 101, 2.81),
        ):
            rows.append({
                "lot_id": lot, "stage_index": stage, "gap_um": gap,
                "composite_thickness_um": t, "composite_density_gcc": d,
                "loading_mg_cm2": t * d * 0.1,
                "areal_capacity_mah_cm2": t * d * 0.1 * 0.96 * 210 / 1000,
            })
    return pd.DataFrame(rows)


def test_mass_balance_rule_detected():
    df = _base_stage_df()
    df.loc[0, "loading_mg_cm2"] = df.loc[0, "loading_mg_cm2"] * 1.2  # 20% 불일치 주입
    report = outliers.detect_stage_outliers(df)
    assert any(f.rule == "mass_balance" and f.lot_id == "A" for f in report.flags)


def test_thickness_spike_rule_detected():
    df = _base_stage_df()
    idx = df[(df.lot_id == "B") & (df.stage_index == "M2")].index[0]
    df.loc[idx, "composite_thickness_um"] = 900.0  # 분체 부착 spike
    report = outliers.detect_stage_outliers(df)
    assert any(f.rule == "thickness_spike" and f.lot_id == "B" for f in report.flags)


def test_monotonicity_rule_detected():
    df = _base_stage_df()
    idx = df[(df.lot_id == "C") & (df.stage_index == "M3")].index[0]
    df.loc[idx, "composite_thickness_um"] = 200.0  # 갭 감소인데 두께 증가
    df.loc[idx, "loading_mg_cm2"] = 200.0 * 2.71 * 0.1  # 질량 보존은 유지
    report = outliers.detect_stage_outliers(df)
    assert any(f.rule == "monotonicity" and f.lot_id == "C" for f in report.flags)


def test_density_range_rule_detected():
    df = _base_stage_df()
    idx = df[(df.lot_id == "D") & (df.stage_index == "M4")].index[0]
    df.loc[idx, "composite_density_gcc"] = 4.5
    df.loc[idx, "loading_mg_cm2"] = df.loc[idx, "composite_thickness_um"] * 4.5 * 0.1
    report = outliers.detect_stage_outliers(df, density_history_range=(2.5, 3.3))
    assert any(f.rule == "density_range" and f.lot_id == "D" for f in report.flags)


def test_composition_sum_rule():
    form = pd.DataFrame([
        {"lot_id": "A", "active_material_content": 96, "binder_content": 2, "conductive_content": 2},
        {"lot_id": "B", "active_material_content": 95, "binder_content": 2, "conductive_content": 2},  # 99
    ])
    report = outliers.check_composition_sum(form)
    assert [f.lot_id for f in report.flags] == ["B"]
    assert report.flags[0].action == "exclude"


def test_median_replacement_records_history():
    df = _base_stage_df()
    idx = df[(df.lot_id == "B") & (df.stage_index == "M2")].index[0]
    df.loc[idx, "composite_thickness_um"] = 900.0
    report = outliers.detect_stage_outliers(df)
    fixed = outliers.replace_with_median(df, report)
    # 단순 삭제가 아닌 중앙값 정밀 대체 + 대체 이력 기록
    assert fixed.loc[idx, "composite_thickness_um"] != 900.0
    assert len(fixed) == len(df)
    thickness_repl = [r for r in report.replacements if r["column"] == "composite_thickness_um"]
    assert thickness_repl and thickness_repl[0]["old_value"] == 900.0
