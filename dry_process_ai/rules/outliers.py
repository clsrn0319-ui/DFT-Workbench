"""FP-01 물리 기반 이상치 판정 규칙.

건식 공정 특유의 계측 오류를 규칙으로 자동 판정한다.
단순 삭제 대신 정상 데이터의 중앙값으로 해당 값만 정밀 대체한다
(삭제하면 연계된 희소 성능 데이터까지 잃는다 — 기획서 3.2.1).

검사 항목:
    mass_balance    질량 보존 loading ≈ thickness × density × 0.1, 오차 3% 초과
    density_range   단계별 합제밀도가 실측 이력 범위를 크게 이탈
    thickness_spike 분체 부착에 의한 두께 센서 비정상 최대값
    monotonicity    갭을 줄였는데 두께가 증가 (측정/기입 오류)
    composition_sum 3성분 합계 ≠ 100 wt% → 학습 제외 및 알림
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from dry_process_ai.config import (
    COMPOSITION_TOTAL_WT,
    MASS_BALANCE_TOLERANCE,
    STAGES,
)
from dry_process_ai.rules import physics


@dataclass
class OutlierFlag:
    lot_id: str
    stage_index: str | None
    rule: str
    column: str | None
    message: str
    action: str  # "replace_median" | "flag_lot" | "review" | "exclude"


@dataclass
class OutlierReport:
    flags: list[OutlierFlag] = field(default_factory=list)
    replacements: list[dict] = field(default_factory=list)  # 대체 이력

    def add(self, **kwargs) -> None:
        self.flags.append(OutlierFlag(**kwargs))


def check_composition_sum(formulation: pd.DataFrame, tolerance_wt: float = 0.01) -> OutlierReport:
    """조성 합계 ≠ 100 wt% 판정 → 학습 제외 대상."""
    report = OutlierReport()
    total = (
        formulation["active_material_content"]
        + formulation["binder_content"]
        + formulation["conductive_content"]
    )
    bad = formulation.loc[(total - COMPOSITION_TOTAL_WT).abs() > tolerance_wt]
    for _, row in bad.iterrows():
        report.add(
            lot_id=str(row["lot_id"]), stage_index=None, rule="composition_sum", column=None,
            message=f"조성 합계 {total.loc[row.name]:.2f} wt% ≠ {COMPOSITION_TOTAL_WT}",
            action="exclude",
        )
    return report


def detect_stage_outliers(
    stage_df: pd.DataFrame,
    density_history_range: tuple[float, float] | None = None,
    density_margin_gcc: float = 0.3,
    thickness_spike_factor: float = 2.5,
) -> OutlierReport:
    """단계별 계측(long 포맷 stage_measure)에 대한 이상치 판정.

    stage_df 컬럼: lot_id, stage_index, gap_um, areal_capacity_mah_cm2,
                   composite_thickness_um, composite_density_gcc, loading_mg_cm2
    density_history_range: 실측 이력 (min, max). 판정선은 동적 산출 원칙(FV-04)에
        따라 호출측이 이력에서 조회해 전달하며, 없으면 해당 검사는 건너뛴다.
    """
    report = OutlierReport()

    for _, row in stage_df.iterrows():
        lot, stage = str(row["lot_id"]), str(row["stage_index"])
        t = row.get("composite_thickness_um")
        d = row.get("composite_density_gcc")
        loading = row.get("loading_mg_cm2")

        # ① 질량 보존
        if pd.notna(loading) and pd.notna(t) and pd.notna(d) and loading > 0:
            expected = physics.loading_mg_cm2(t, d)
            if abs(loading - expected) / loading > MASS_BALANCE_TOLERANCE:
                report.add(
                    lot_id=lot, stage_index=stage, rule="mass_balance", column="loading_mg_cm2",
                    message=f"로딩 {loading:.2f} vs 두께×밀도×0.1={expected:.2f} (오차 {abs(loading - expected) / loading:.1%})",
                    action="replace_median",
                )

        # ② 합제밀도 이력 범위 이탈
        if density_history_range is not None and pd.notna(d):
            lo, hi = density_history_range
            if d < lo - density_margin_gcc or d > hi + density_margin_gcc:
                report.add(
                    lot_id=lot, stage_index=stage, rule="density_range", column="composite_density_gcc",
                    message=f"합제밀도 {d:.2f} g/cc 가 실측 이력 [{lo:.2f}, {hi:.2f}] ± {density_margin_gcc} 이탈",
                    action="flag_lot",
                )

    # ③ 두께 센서 비정상 최대값 — 동일 단계 분포의 중앙값 대비 spike
    for stage, grp in stage_df.groupby("stage_index"):
        t = grp["composite_thickness_um"].dropna()
        if len(t) < 3:
            continue
        median = float(t.median())
        for idx, v in t.items():
            if median > 0 and v > median * thickness_spike_factor:
                report.add(
                    lot_id=str(stage_df.loc[idx, "lot_id"]), stage_index=str(stage),
                    rule="thickness_spike", column="composite_thickness_um",
                    message=f"두께 {v:.1f} μm > 단계 중앙값 {median:.1f} × {thickness_spike_factor} (분체 부착 의심)",
                    action="replace_median",
                )

    # ④ 단조성 위반 — 갭을 줄였는데 두께 증가
    for lot, grp in stage_df.groupby("lot_id"):
        grp = grp.set_index("stage_index").reindex([s for s in STAGES if s in grp["stage_index"].values])
        prev_gap, prev_t, prev_stage = None, None, None
        for stage, row in grp.iterrows():
            gap, t = row.get("gap_um"), row.get("composite_thickness_um")
            if prev_gap is not None and pd.notna(gap) and pd.notna(t) and pd.notna(prev_t):
                if gap < prev_gap and t > prev_t:
                    report.add(
                        lot_id=str(lot), stage_index=str(stage), rule="monotonicity",
                        column="composite_thickness_um",
                        message=f"{prev_stage}→{stage}: 갭 {prev_gap:.0f}→{gap:.0f} 감소인데 두께 {prev_t:.1f}→{t:.1f} 증가",
                        action="review",
                    )
            if pd.notna(gap):
                prev_gap, prev_stage = gap, stage
            if pd.notna(t):
                prev_t = t
    return report


def replace_with_median(stage_df: pd.DataFrame, report: OutlierReport) -> pd.DataFrame:
    """action == replace_median 플래그 값만 해당 단계 정상 데이터의 중앙값으로 대체.

    대체 이력은 report.replacements 에 기록된다 (FP-01 출력: 이상치 플래그 + 대체 이력).
    """
    df = stage_df.copy()
    flagged = {(f.lot_id, f.stage_index, f.column) for f in report.flags if f.action == "replace_median"}
    for lot_id, stage, column in flagged:
        mask = (df["lot_id"].astype(str) == lot_id) & (df["stage_index"].astype(str) == stage)
        stage_mask = df["stage_index"].astype(str) == stage
        normal = df.loc[stage_mask & ~df.index.isin(df.index[mask]), column].dropna()
        if normal.empty:
            continue
        median = float(normal.median())
        for idx in df.index[mask]:
            old = df.loc[idx, column]
            df.loc[idx, column] = median
            report.replacements.append(
                {"lot_id": lot_id, "stage_index": stage, "column": column,
                 "old_value": None if pd.isna(old) else float(old), "new_value": median}
            )
    return df
