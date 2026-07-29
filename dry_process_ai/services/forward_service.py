"""FF — 순방향 예측 서비스 (F1).

조성비 + 목표 사양 → 공정 조건표 + 단계별(M1~L2) 예측표.
연계: FF-02 → FF-03 → FF-04 → FF-08 → FV-01~03, FS-01/02/03/04.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy.orm import Session

from dry_process_ai.config import COLLECTOR_ATTACHED_STAGES, PREDICTIONS_DIR, STAGES
from dry_process_ai.core.infer.gap_schedule import (
    GapSchedule,
    ScheduleInfeasible,
    adjust_kneading_time,
    search_gap_schedule,
)
from dry_process_ai.core.infer.predictor import PredictionResult, Predictor
from dry_process_ai.data_access.capability import build_capability
from dry_process_ai.data_access.db import PredictionLog
from dry_process_ai.data_access.repository import INPUT_FEATURES
from dry_process_ai.rules import physics
from dry_process_ai.rules.constraints import density_ceiling_from_history
from dry_process_ai.rules.spec_validation import (
    ProcessCapability,
    SpecValidationResult,
    propose_alternatives,
    validate_spec,
)
from dry_process_ai.services.schemas import ForwardRequest


@dataclass
class ForwardResponse:
    request: ForwardRequest
    validation: SpecValidationResult
    schedule: GapSchedule | None
    prediction: PredictionResult | None
    condition_table: dict                     # 공정 조건표 (Mixing~Laminating)
    stage_table: pd.DataFrame | None          # 단계별 예측표 (합제층 + 전체 두께 병기)
    absolute_quantities: dict | None          # 총 합제 질량·총 용량 (면적 입력 시)
    auto_filled: dict[str, float]             # FF-06 보완 항목 이력
    train_lot_count: int                      # FS-02
    model_version: str
    infeasible_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


def _auto_fill_conditions(
    train_df: pd.DataFrame,
    composition: dict[str, float],
    fixed: dict[str, float],
    window_wt: float = 1.0,
) -> tuple[dict[str, float], dict[str, float]]:
    """FF-06 — 미지정 조건을 해당 조성 근방 실측 중앙값으로 보완.

    반환: (전체 조건, 보완된 항목만의 이력)
    """
    near = train_df
    if not train_df.empty:
        near = train_df[
            ((train_df["binder_content"] - composition["binder_content"]).abs() <= window_wt)
            & ((train_df["conductive_content"] - composition["conductive_content"]).abs() <= window_wt)
        ]
        if near.empty:
            near = train_df

    conditions: dict[str, float] = {}
    auto_filled: dict[str, float] = {}
    for col in INPUT_FEATURES:
        if col in composition:
            conditions[col] = composition[col]
        elif col in fixed:
            conditions[col] = fixed[col]
        elif col in near.columns and near[col].notna().any():
            value = float(near[col].median())
            conditions[col] = value
            if not col.startswith("gap_"):  # 갭은 FF-03 스케줄이 결정
                auto_filled[col] = value
    return conditions, auto_filled


def run_forward(
    session: Session,
    predictor: Predictor,
    train_df: pd.DataFrame,
    request: ForwardRequest,
    train_lot_count: int,
    capability: ProcessCapability | None = None,
    log_prediction: bool = True,
) -> ForwardResponse:
    comp = request.composition
    capability = capability or build_capability(
        session, conductive_wt=comp.conductive_content, binder_wt=comp.binder_content,
    )

    # ---- FV: 스펙 타당성 검증 — 요청 조건은 그대로 진행하되 알람·대안 병기 ----
    validation = validate_spec(
        active_material_wt=comp.active_material_content,
        binder_wt=comp.binder_content,
        conductive_wt=comp.conductive_content,
        target_areal_capacity=request.target_areal_capacity_mah_cm2,
        target_density_gcc=request.target_density_gcc,
        capability=capability,
        target_thickness_um=request.target_thickness_um,
    )
    if validation.grade == "warning":
        propose_alternatives(
            validation, comp.active_material_content, comp.binder_content, comp.conductive_content,
            request.target_areal_capacity_mah_cm2, request.target_density_gcc, capability,
        )

    composition = {
        "active_material_content": comp.active_material_content,
        "binder_content": comp.binder_content,
        "conductive_content": comp.conductive_content,
    }

    # ---- FF-03: 갭 스케줄 탐색 ----
    schedule = None
    infeasible_reason = None
    try:
        schedule = search_gap_schedule(
            active_material_fraction=comp.active_material_fraction,
            target_areal_capacity=request.target_areal_capacity_mah_cm2,
            target_density_gcc=request.target_density_gcc,
            capability=capability,
            target_thickness_um=request.target_thickness_um,
        )
    except ScheduleInfeasible as exc:
        infeasible_reason = str(exc)

    # ---- FF-06: 미지정 조건 자동 보완 ----
    conditions, auto_filled = _auto_fill_conditions(
        train_df, composition, request.fixed_process_conditions,
    )
    conditions["foil_thickness_um"] = request.collector.foil_thickness_um
    conditions["coating_side_flag"] = 1.0 if request.collector.coating_side == "double" else 0.0
    if schedule:
        for stage in STAGES:
            conditions[f"gap_{stage}"] = schedule.gaps_um[stage]

    # ⑤ 피브릴화 보상 — Kneading 시간을 조성에 맞춰 조정
    if "kneader_time" in conditions and capability.lot_count > 0 and "kneader_time" in auto_filled:
        ref_binder = float(train_df["binder_content"].median()) if not train_df.empty else comp.binder_content
        adjusted = adjust_kneading_time(conditions["kneader_time"], comp.binder_content, ref_binder)
        if adjusted != conditions["kneader_time"]:
            conditions["kneader_time"] = adjusted
            auto_filled["kneader_time"] = adjusted

    # ---- FF-04/05/07/08: 단계별 예측 + 신뢰 구간 + 정합성 검사 ----
    prediction = None
    stage_table = None
    if schedule is not None:
        features = pd.Series({c: conditions.get(c) for c in INPUT_FEATURES}, dtype=float)
        prediction = predictor.predict_one(
            features,
            active_material_fraction=comp.active_material_fraction,
            gaps_um=schedule.gaps_um,
            density_ceiling_gcc=density_ceiling_from_history(capability.max_density_gcc),
            n_samples=request.mc_samples,
        )
        stage_table = prediction.stage_table.copy()
        # Laminating 단계: 합제층 두께와 집전체 포함 전체 두께 병기 (출력 표기 규칙)
        stage_table["total_thickness_um"] = [
            row.composite_thickness_um + request.collector.foil_thickness_um
            if row.stage_index in COLLECTOR_ATTACHED_STAGES else None
            for row in stage_table.itertuples()
        ]

    # ---- FD-08: 절대량 환산 (면적 입력 시) ----
    absolute = None
    if request.electrode_area_cm2 and prediction is not None:
        final = prediction.stage_table.iloc[-1]
        faces = request.collector.coated_face_count
        absolute = {
            "electrode_area_cm2": request.electrode_area_cm2,
            "coated_face_count": faces,
            "total_composite_mass_g": physics.total_composite_mass_g(
                final["loading_mg_cm2"], request.electrode_area_cm2, faces),
            "total_capacity_mah": physics.total_capacity_mah(
                final["areal_capacity_mah_cm2"], request.electrode_area_cm2, faces),
        }

    condition_table = {
        "mixing": {k: conditions.get(k) for k in
                   ("mixing_mass", "mixing_rpm", "mixing_temp", "mixing_time", "mixing_repeat")},
        "kneading": {k: conditions.get(k) for k in
                     ("kneader_screw_speed", "kneader_barrel_temp", "kneader_time")},
        "cutting": {k: conditions.get(k) for k in
                    ("cutting_mass", "cutting_speed", "cutting_temp", "cutting_time", "cutting_repeat")},
        "milling_rolling_laminating_gaps_um": schedule.gaps_um if schedule else None,
        "rolling": {"rolling_line_pressure": conditions.get("rolling_line_pressure")},
        "laminating": {"laminating_pressure": conditions.get("laminating_pressure")},
    }

    response = ForwardResponse(
        request=request,
        validation=validation,
        schedule=schedule,
        prediction=prediction,
        condition_table=condition_table,
        stage_table=stage_table,
        absolute_quantities=absolute,
        auto_filled=auto_filled,
        train_lot_count=train_lot_count,
        model_version=predictor.model_version,
        infeasible_reason=infeasible_reason,
    )
    if prediction is not None and not prediction.consistency.passed:
        response.warnings.extend(v.message for v in prediction.consistency.violations)

    # ---- FS-03: 예측 이력 로깅 ----
    if log_prediction:
        session.add(PredictionLog(
            input_snapshot=request.model_dump_json(),
            model_version_id=predictor.model_version,
            alarm_grade=validation.grade,
        ))
        session.commit()
    return response


def export_prediction_json(response: ForwardResponse, directory=PREDICTIONS_DIR) -> str:
    """FS-04 — pred_{YYYYMMDD_HHMM}_{model_version}.json 규약 (12.2)."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    path = directory / f"pred_{stamp}_{response.model_version}.json"
    payload = {
        "model_version": response.model_version,       # NFR-08
        "train_lot_count": response.train_lot_count,   # NFR-08
        "request": json.loads(response.request.model_dump_json()),
        "alarm_grade": response.validation.grade,
        "alarm_messages": response.validation.messages,
        "alternatives": response.validation.alternatives,
        "condition_table": response.condition_table,
        "auto_filled_conditions": response.auto_filled,
        "stage_table": (
            response.stage_table.to_dict(orient="records") if response.stage_table is not None else None
        ),
        "predictions": (
            {
                col: {"mean": iv.mean, "lower": iv.lower, "upper": iv.upper, "grade": iv.grade}
                for col, iv in response.prediction.values.items()
            } if response.prediction else None
        ),
        "absolute_quantities": response.absolute_quantities,
        "infeasible_reason": response.infeasible_reason,
        "warnings": response.warnings,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    return str(path)
