"""Lot 리포지터리 (FD-01, FD-05, FD-06, FD-08).

핵심 원칙:
- 합제층 기준 환산은 적재 시점에 수행한다 (FD-05, 규칙 R1).
  Laminating 단계(L1, L2)의 측정 전체 두께에서 집전체 두께를 차감해 저장하고,
  원측정값은 total_thickness_um 에 보존해 화면에서 병기한다.
- 전극 면적은 Lot 속성으로만 기록한다 (FD-08, 규칙 R4).
- 학습 데이터셋 조회는 출처 플래그를 항상 동반한다 (규칙 R3).
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from dry_process_ai.config import COLLECTOR_ATTACHED_STAGES, STAGES
from dry_process_ai.data_access.db import (
    CollectorInfo,
    Electrochem,
    ElectrodeProperty,
    Formulation,
    Lot,
    ProcessCondition,
    SOURCE_MEASURED,
    StageMeasure,
)
from dry_process_ai.rules import physics

# 모델 입력 벡터를 구성하는 공정 조건 변수 (long → wide 전개 시 컬럼명)
PROCESS_FEATURES = (
    "mixing_mass", "mixing_rpm", "mixing_temp", "mixing_time", "mixing_repeat",
    "kneader_screw_speed", "kneader_barrel_temp", "kneader_time",
    "cutting_mass", "cutting_speed", "cutting_temp", "cutting_time", "cutting_repeat",
    "rolling_line_pressure", "laminating_pressure",
)

COMPOSITION_FEATURES = ("active_material_content", "binder_content", "conductive_content")
COLLECTOR_FEATURES = ("foil_thickness_um", "coating_side_flag")
GAP_FEATURES = tuple(f"gap_{s}" for s in STAGES)

# 전극 면적은 여기 포함되지 않는다 (규칙 R4)
INPUT_FEATURES = COMPOSITION_FEATURES + PROCESS_FEATURES + GAP_FEATURES + COLLECTOR_FEATURES

STAGE_TARGET_COLUMNS = tuple(
    f"{s}_{t}" for s in STAGES
    for t in ("areal_capacity_mah_cm2", "composite_thickness_um", "composite_density_gcc")
)
FINAL_PROPERTY_COLUMNS = ("electrode_thickness_um", "electrode_density_gcc", "sheet_resistance_ohm_sq")
AUX_PROPERTY_COLUMNS = ("tensile_strength_mpa", "electrode_adhesion_n_cm")
PERFORMANCE_COLUMNS = (
    "initial_discharge_capacity_mah_g", "initial_coulombic_efficiency_pct",
    "interface_resistance_ohm", "cell_discharge_retention_pct",
)
ALL_TARGET_COLUMNS = STAGE_TARGET_COLUMNS + FINAL_PROPERTY_COLUMNS + AUX_PROPERTY_COLUMNS + PERFORMANCE_COLUMNS


def register_lot(session: Session, payload: dict[str, Any]) -> str:
    """Lot 단위 등록·수정 (FD-01).

    payload 구조 예:
        {
          "lot_id": "L2026-001", "experiment_date": "2026-07-01", "operator": "...",
          "electrode_area_cm2": 25.0, "source_flag": "measured",
          "formulation": {"active_material_content": 96, "binder_content": 2, "conductive_content": 2},
          "collector": {"foil_thickness_um": 15, "coating_side": "single", "coated_face_count": 1},
          "process_conditions": {"mixing": {"mixing_rpm": 12000, ...}, ...},
          "stages": {"M1": {"gap_um": 180, "measured_thickness_um": 289, "loading_mg_cm2": 75.4,
                            "areal_capacity_mah_cm2": 15.2}, ...},
          "electrode_property": {...}, "electrochem": {...},
        }

    stages[*].measured_thickness_um 은 설비 계측 원값이다. Laminating 단계는
    적재 시점에 집전체 두께를 차감하여 composite_thickness_um 으로 환산한다 (FD-05).
    """
    lot_id = str(payload["lot_id"])
    collector = payload.get("collector", {})
    foil = float(collector.get("foil_thickness_um", 0.0))

    session.merge(Lot(
        lot_id=lot_id,
        experiment_date=payload.get("experiment_date"),
        operator=payload.get("operator"),
        electrode_area_cm2=payload.get("electrode_area_cm2"),
        source_flag=payload.get("source_flag", SOURCE_MEASURED),
        note=payload.get("note"),
    ))

    f = payload.get("formulation")
    if f:
        session.merge(Formulation(lot_id=lot_id, **f))

    if collector:
        session.merge(CollectorInfo(
            lot_id=lot_id,
            foil_thickness_um=foil,
            coating_side=collector.get("coating_side", "single"),
            collector_attached=collector.get("collector_attached", True),
            coated_face_count=collector.get("coated_face_count", 1),
        ))

    for group, variables in payload.get("process_conditions", {}).items():
        for name, value in variables.items():
            existing_pc = (
                session.query(ProcessCondition)
                .filter_by(lot_id=lot_id, process_group=group, variable_name=name)
                .one_or_none()
            )
            if existing_pc is None:
                existing_pc = ProcessCondition(lot_id=lot_id, process_group=group, variable_name=name)
                session.add(existing_pc)
            existing_pc.value = None if value is None else float(value)
    session.flush()

    for stage, row in payload.get("stages", {}).items():
        measured = row.get("measured_thickness_um")
        composite = row.get("composite_thickness_um")
        total = None
        if stage in COLLECTOR_ATTACHED_STAGES:
            # FD-05: 적재 시점 집전체 차감 (규칙 R1)
            if composite is None and measured is not None:
                total = float(measured)
                composite = physics.composite_thickness_from_total(total, foil)
            elif composite is not None:
                total = float(composite) + foil
        else:
            if composite is None and measured is not None:
                composite = float(measured)

        loading = row.get("loading_mg_cm2")
        density = row.get("composite_density_gcc")
        if density is None and loading is not None and composite:
            density = physics.composite_density_gcc(float(loading), float(composite))
        if loading is None and density is not None and composite:
            loading = physics.loading_mg_cm2(float(composite), float(density))

        existing = (
            session.query(StageMeasure)
            .filter_by(lot_id=lot_id, stage_index=stage)
            .one_or_none()
        )
        if existing is None:
            existing = StageMeasure(lot_id=lot_id, stage_index=stage)
            session.add(existing)
        existing.gap_um = row.get("gap_um")
        existing.areal_capacity_mah_cm2 = row.get("areal_capacity_mah_cm2")
        existing.composite_thickness_um = composite
        existing.composite_density_gcc = density
        existing.loading_mg_cm2 = loading
        existing.total_thickness_um = total

    ep = payload.get("electrode_property")
    if ep:
        session.merge(ElectrodeProperty(lot_id=lot_id, **ep))

    ec = payload.get("electrochem")
    if ec:
        session.merge(Electrochem(lot_id=lot_id, **ec))

    session.flush()
    return lot_id


def _process_conditions_wide(session: Session) -> pd.DataFrame:
    rows = session.query(ProcessCondition).all()
    if not rows:
        return pd.DataFrame(columns=["lot_id"])
    df = pd.DataFrame(
        [{"lot_id": r.lot_id, "variable_name": r.variable_name, "value": r.value} for r in rows]
    )
    return df.pivot_table(index="lot_id", columns="variable_name", values="value", aggfunc="first").reset_index()


def fetch_dataset(session: Session, source_flag: str | None = None) -> pd.DataFrame:
    """Lot 1건 = 1행의 wide 학습 데이터셋 (FD-06 단계 정렬 포함).

    반환 컬럼: lot_id, source_flag, electrode_area_cm2(속성), INPUT_FEATURES,
    ALL_TARGET_COLUMNS. 결측은 NaN 그대로 유지한다 (FP-02).

    source_flag="measured" 로 호출하면 실측만 반환 — 평가(FE)·중요도(FA) 는
    반드시 이 경로를 쓴다 (규칙 R3).
    """
    q = session.query(Lot)
    if source_flag:
        q = q.filter(Lot.source_flag == source_flag)
    lots = q.all()
    if not lots:
        return pd.DataFrame()

    base = pd.DataFrame([
        {"lot_id": l.lot_id, "source_flag": l.source_flag, "electrode_area_cm2": l.electrode_area_cm2}
        for l in lots
    ])
    lot_ids = set(base["lot_id"])

    form = pd.DataFrame([
        {"lot_id": r.lot_id, "active_material_content": r.active_material_content,
         "binder_content": r.binder_content, "conductive_content": r.conductive_content}
        for r in session.query(Formulation).all() if r.lot_id in lot_ids
    ])

    proc = _process_conditions_wide(session)

    coll = pd.DataFrame([
        {"lot_id": r.lot_id, "foil_thickness_um": r.foil_thickness_um,
         "coating_side_flag": 1.0 if r.coating_side == "double" else 0.0}
        for r in session.query(CollectorInfo).all() if r.lot_id in lot_ids
    ])

    stage_rows = [
        {"lot_id": r.lot_id, "stage_index": r.stage_index, "gap_um": r.gap_um,
         "areal_capacity_mah_cm2": r.areal_capacity_mah_cm2,
         "composite_thickness_um": r.composite_thickness_um,
         "composite_density_gcc": r.composite_density_gcc}
        for r in session.query(StageMeasure).all() if r.lot_id in lot_ids
    ]
    stage_wide = pd.DataFrame({"lot_id": list(lot_ids)})
    if stage_rows:
        sdf = pd.DataFrame(stage_rows)
        gaps = sdf.pivot_table(index="lot_id", columns="stage_index", values="gap_um", aggfunc="first")
        gaps.columns = [f"gap_{c}" for c in gaps.columns]
        parts = [gaps]
        for target in ("areal_capacity_mah_cm2", "composite_thickness_um", "composite_density_gcc"):
            p = sdf.pivot_table(index="lot_id", columns="stage_index", values=target, aggfunc="first")
            p.columns = [f"{c}_{target}" for c in p.columns]
            parts.append(p)
        stage_wide = pd.concat(parts, axis=1).reset_index()

    ep = pd.DataFrame([
        {"lot_id": r.lot_id, "electrode_thickness_um": r.electrode_thickness_um,
         "electrode_density_gcc": r.electrode_density_gcc,
         "sheet_resistance_ohm_sq": r.sheet_resistance_ohm_sq,
         "tensile_strength_mpa": r.tensile_strength_mpa,
         "electrode_adhesion_n_cm": r.electrode_adhesion_n_cm}
        for r in session.query(ElectrodeProperty).all() if r.lot_id in lot_ids
    ])

    ec = pd.DataFrame([
        {"lot_id": r.lot_id,
         "initial_discharge_capacity_mah_g": r.initial_discharge_capacity_mah_g,
         "initial_coulombic_efficiency_pct": r.initial_coulombic_efficiency_pct,
         "interface_resistance_ohm": r.interface_resistance_ohm,
         "cell_discharge_retention_pct": r.cell_discharge_retention_pct}
        for r in session.query(Electrochem).all() if r.lot_id in lot_ids
    ])

    df = base
    for part in (form, proc, coll, stage_wide, ep, ec):
        if not part.empty:
            df = df.merge(part, on="lot_id", how="left")

    # 누락 컬럼을 NaN 으로 보강해 스키마를 고정한다
    for col in INPUT_FEATURES + ALL_TARGET_COLUMNS:
        if col not in df.columns:
            df[col] = float("nan")
    ordered = ["lot_id", "source_flag", "electrode_area_cm2", *INPUT_FEATURES, *ALL_TARGET_COLUMNS]
    return df[ordered]


def fetch_stage_long(session: Session, source_flag: str | None = None) -> pd.DataFrame:
    """stage_measure 를 long 포맷 그대로 반환 (이상치 판정·이력 산출용)."""
    lot_flags = {l.lot_id: l.source_flag for l in session.query(Lot).all()}
    rows = []
    for r in session.query(StageMeasure).all():
        if source_flag and lot_flags.get(r.lot_id) != source_flag:
            continue
        rows.append({
            "lot_id": r.lot_id, "stage_index": r.stage_index, "gap_um": r.gap_um,
            "areal_capacity_mah_cm2": r.areal_capacity_mah_cm2,
            "composite_thickness_um": r.composite_thickness_um,
            "composite_density_gcc": r.composite_density_gcc,
            "loading_mg_cm2": r.loading_mg_cm2,
        })
    return pd.DataFrame(rows)
