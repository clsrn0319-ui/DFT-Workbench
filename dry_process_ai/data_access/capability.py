"""실측 이력 → 공정 능력 판정선 동적 산출 (FV-04).

판정 기준을 상수로 박지 않는다 — 실측(measured) Lot 만으로 산출하며,
Lot 이 축적될 때마다 재산출되어 실제 공정 능력에 맞춰 자동 갱신된다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from dry_process_ai.config import (
    DEFAULT_MAX_REDUCTION_RATIO,
    DEFAULT_SPRINGBACK_RATIO,
    STAGES,
)
from dry_process_ai.data_access.db import SOURCE_MEASURED
from dry_process_ai.data_access.repository import fetch_dataset, fetch_stage_long
from dry_process_ai.rules.spec_validation import ProcessCapability


def build_capability(
    session: Session,
    conductive_wt: float | None = None,
    binder_wt: float | None = None,
    composition_window_wt: float = 1.0,
) -> ProcessCapability:
    """실측 이력에서 ProcessCapability 를 산출한다.

    conductive_wt / binder_wt 가 주어지면 해당 조성 근방(± composition_window_wt)
    Lot 으로 밀도 이력을 좁힌다 — "유사 조성에서 실측된 최대 밀도" (FV-01 ①).
    """
    df = fetch_dataset(session, source_flag=SOURCE_MEASURED)
    stage_long = fetch_stage_long(session, source_flag=SOURCE_MEASURED)
    cap = ProcessCapability(
        max_reduction_ratio=DEFAULT_MAX_REDUCTION_RATIO,
        springback_ratio=DEFAULT_SPRINGBACK_RATIO,
    )
    if df.empty:
        return cap
    cap.lot_count = len(df)

    # 조성 근방 필터
    similar = df
    if conductive_wt is not None:
        similar = similar[(similar["conductive_content"] - conductive_wt).abs() <= composition_window_wt]
    if binder_wt is not None:
        similar = similar[(similar["binder_content"] - binder_wt).abs() <= composition_window_wt]
    if similar.empty:
        similar = df  # 근방 이력이 없으면 전체 이력으로 완화 (판정 근거에 lot_count 병기)

    density_cols = [f"{s}_composite_density_gcc" for s in STAGES]
    density_values = similar[[c for c in density_cols if c in similar.columns]].to_numpy(dtype=float)
    density_values = density_values[~np.isnan(density_values)]
    final_density = similar["electrode_density_gcc"].dropna().to_numpy(dtype=float)
    all_density = np.concatenate([density_values, final_density]) if final_density.size else density_values
    if all_density.size:
        cap.max_density_gcc = float(np.max(all_density))
        cap.min_density_gcc = float(np.min(all_density))

    binder = df["binder_content"].dropna()
    if not binder.empty:
        cap.binder_range_wt = (float(binder.min()), float(binder.max()))

    conductive = df["conductive_content"].dropna()
    if not conductive.empty:
        cap.reference_conductive_wt = float(conductive.median())

    # 단계 이력에서 압하율·스프링백·최소 갭 산출
    if not stage_long.empty:
        gaps = stage_long["gap_um"].dropna()
        if not gaps.empty:
            cap.min_gap_um = float(gaps.min())

        springbacks, reductions = [], []
        for _, grp in stage_long.groupby("lot_id"):
            grp = grp.set_index("stage_index").reindex([s for s in STAGES if s in grp["stage_index"].values])
            prev_t = None
            for _, row in grp.iterrows():
                t, gap = row.get("composite_thickness_um"), row.get("gap_um")
                if pd.notna(t) and pd.notna(gap) and gap > 0:
                    springbacks.append(t / gap - 1.0)
                if prev_t is not None and pd.notna(t) and prev_t > 0:
                    reductions.append(1.0 - t / prev_t)
                if pd.notna(t):
                    prev_t = t
        if springbacks:
            cap.springback_ratio = float(max(np.median(springbacks), 0.0))
        if reductions:
            positive = [r for r in reductions if r > 0]
            if positive:
                cap.max_reduction_ratio = float(np.quantile(positive, 0.95))

    # 단계 프로파일 — 실측 이력의 단계별 로딩 배율·밀도 배율·스프링백 중앙값.
    # 갭 스케줄(FF-03)이 실제 공정 경로(초기 로딩 ~3×, 단계별 상이한 스프링백)에
    # 앵커되게 한다. 판정선 동적 산출 원칙(FV-04)의 일부다.
    if not stage_long.empty:
        acc = {s: {"lr": [], "dr": [], "sb": []} for s in STAGES}
        for _, grp in stage_long.groupby("lot_id"):
            g = grp.set_index("stage_index")
            if "L2" not in g.index:
                continue
            final_l = g.loc["L2", "loading_mg_cm2"]
            final_d = g.loc["L2", "composite_density_gcc"]
            if not (pd.notna(final_l) and final_l > 0 and pd.notna(final_d) and final_d > 0):
                continue
            for s in STAGES:
                if s not in g.index:
                    continue
                row = g.loc[s]
                l_v, d_v = row.get("loading_mg_cm2"), row.get("composite_density_gcc")
                t_v, gap_v = row.get("composite_thickness_um"), row.get("gap_um")
                if pd.notna(l_v) and l_v > 0:
                    acc[s]["lr"].append(float(l_v) / float(final_l))
                if pd.notna(d_v) and d_v > 0:
                    acc[s]["dr"].append(float(d_v) / float(final_d))
                if pd.notna(t_v) and pd.notna(gap_v) and gap_v > 0:
                    acc[s]["sb"].append(float(t_v) / float(gap_v) - 1.0)
        for s in STAGES:
            if acc[s]["lr"] and acc[s]["dr"]:
                cap.stage_profile[s] = {
                    "loading_ratio": float(np.median(acc[s]["lr"])),
                    "density_ratio": float(np.median(acc[s]["dr"])),
                    "springback": float(np.median(acc[s]["sb"])) if acc[s]["sb"] else None,
                }

    # 학습 범위 (FV-01 ⑥)
    for col in ("active_material_content", "binder_content", "conductive_content"):
        series = df[col].dropna()
        if not series.empty:
            cap.composition_ranges[col] = (float(series.min()), float(series.max()))
    l2_cap = df.get("L2_areal_capacity_mah_cm2")
    if l2_cap is not None and l2_cap.dropna().size:
        cap.target_ranges["areal_capacity_mah_cm2"] = (float(l2_cap.min()), float(l2_cap.max()))
    if all_density.size:
        cap.target_ranges["composite_density_gcc"] = (float(np.min(all_density)), float(np.max(all_density)))
    return cap
