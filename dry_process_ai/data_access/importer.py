"""FD-02 — CSV / Excel 일괄 가져오기.

변수 사전 기준으로 컬럼을 자동 매핑하고 단위를 통일한다.
매핑 실패 컬럼과 단위 불일치 항목은 적재 전 사용자에게 보고한다.
원본은 data/reference/ 에 무변경 보존한다 (FD-04 reference set).
"""

from __future__ import annotations

import datetime
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from dry_process_ai.config import DATA_REFERENCE_DIR, STAGES
from dry_process_ai.data_access.db import VariableDict
from dry_process_ai.data_access.repository import register_lot

# 흔한 별칭 → 변수 사전 정식 명칭 (임의 축약 금지 원칙에 따라 적재 시 정규화)
_ALIASES = {
    "am_content": "active_material_content",
    "ncm_content": "active_material_content",
    "ptfe_content": "binder_content",
    "superc_content": "conductive_content",
    "carbon_content": "conductive_content",
    "foil_thickness": "foil_thickness_um",
    "area": "electrode_area_cm2",
    "area_cm2": "electrode_area_cm2",
}

# 단위 변환: {컬럼 접미사: (원 단위 표기, 배율)} — mm 표기 두께를 μm 로 통일
_UNIT_FACTORS = {
    "_mm": ("mm→μm", 1000.0),
}


@dataclass
class ImportReport:
    """적재 결과 리포트 (FD-02 출력)."""

    imported_lots: list[str] = field(default_factory=list)
    unmapped_columns: list[str] = field(default_factory=list)
    unit_conversions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _normalize_columns(df: pd.DataFrame, known: set[str], report: ImportReport) -> pd.DataFrame:
    renames: dict[str, str] = {}
    for col in df.columns:
        canonical = _ALIASES.get(col.strip().lower())
        if canonical:
            renames[col] = canonical
            continue
        for suffix, (label, factor) in _UNIT_FACTORS.items():
            if col.endswith(suffix):
                base = col[: -len(suffix)] + "_um"
                df[col] = df[col] * factor
                renames[col] = base
                report.unit_conversions.append(f"{col}: {label}")
                break
    df = df.rename(columns=renames)
    structural = {"lot_id", "stage_index", "experiment_date", "operator", "source_flag",
                  "coating_side", "measured_thickness_um", "note"}
    stage_prefixed = {c for c in df.columns if any(c.startswith(f"{s}_") or c == f"gap_{s}" for s in STAGES)}
    for col in df.columns:
        base = col.split("_", 1)[-1] if col in stage_prefixed else col
        if col not in known and base not in known and col not in structural and col not in stage_prefixed:
            report.unmapped_columns.append(col)
    return df


def import_lot_file(session: Session, path: str | Path, preserve_reference: bool = True) -> ImportReport:
    """Lot 단위 wide CSV/Excel 파일을 적재한다.

    기대 형식: 1행 = 1 Lot. 컬럼은 변수 사전 명칭. 단계별 값은
    `{stage}_composite_thickness_um`, `{stage}_measured_thickness_um`,
    `gap_{stage}` 형식 (stage ∈ M1..L2).
    """
    path = Path(path)
    report = ImportReport()
    df = pd.read_excel(path) if path.suffix.lower() in (".xlsx", ".xls") else pd.read_csv(path)

    known = {name for (name,) in session.query(VariableDict.variable_name).all()}
    df = _normalize_columns(df, known, report)

    if "lot_id" not in df.columns:
        report.errors.append("lot_id 컬럼이 없어 적재를 중단합니다")
        return report

    if preserve_reference:
        DATA_REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.date.today().strftime("%Y%m%d")
        shutil.copy2(path, DATA_REFERENCE_DIR / f"reference_{stamp}_{path.name}")

    for _, row in df.iterrows():
        try:
            payload = _row_to_payload(row)
            register_lot(session, payload)
            report.imported_lots.append(str(row["lot_id"]))
        except Exception as exc:  # 한 Lot 실패가 전체 적재를 막지 않게 한다
            report.errors.append(f"{row.get('lot_id')}: {exc}")
    session.commit()
    return report


def _value(row: pd.Series, key: str):
    v = row.get(key)
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else v


def _row_to_payload(row: pd.Series) -> dict:
    payload: dict = {
        "lot_id": row["lot_id"],
        "experiment_date": _value(row, "experiment_date"),
        "operator": _value(row, "operator"),
        "electrode_area_cm2": _value(row, "electrode_area_cm2"),
        "source_flag": _value(row, "source_flag") or "measured",
        "formulation": {
            "active_material_content": _value(row, "active_material_content"),
            "binder_content": _value(row, "binder_content"),
            "conductive_content": _value(row, "conductive_content"),
        },
        "collector": {
            "foil_thickness_um": _value(row, "foil_thickness_um") or 0.0,
            "coating_side": _value(row, "coating_side") or "single",
        },
        "process_conditions": {},
        "stages": {},
        "electrode_property": {},
        "electrochem": {},
    }

    groups = {
        "mixing": ("mixing_mass", "mixing_rpm", "mixing_temp", "mixing_time", "mixing_repeat"),
        "kneading": ("kneader_screw_speed", "kneader_barrel_temp", "kneader_time"),
        "cutting": ("cutting_mass", "cutting_speed", "cutting_temp", "cutting_time", "cutting_repeat"),
        "rolling": ("rolling_line_pressure",),
        "laminating": ("laminating_pressure",),
    }
    for group, names in groups.items():
        vals = {n: _value(row, n) for n in names if _value(row, n) is not None}
        if vals:
            payload["process_conditions"][group] = vals

    for stage in STAGES:
        stage_row = {}
        for suffix, key in (
            ("gap_um", f"gap_{stage}"),
            ("measured_thickness_um", f"{stage}_measured_thickness_um"),
            ("composite_thickness_um", f"{stage}_composite_thickness_um"),
            ("composite_density_gcc", f"{stage}_composite_density_gcc"),
            ("loading_mg_cm2", f"{stage}_loading_mg_cm2"),
            ("areal_capacity_mah_cm2", f"{stage}_areal_capacity_mah_cm2"),
        ):
            v = _value(row, key)
            if v is not None:
                stage_row[suffix] = float(v)
        if stage_row:
            payload["stages"][stage] = stage_row

    for col in ("electrode_thickness_um", "electrode_density_gcc", "sheet_resistance_ohm_sq",
                "tensile_strength_mpa", "electrode_adhesion_n_cm"):
        v = _value(row, col)
        if v is not None:
            payload["electrode_property"][col] = float(v)

    for col in ("initial_discharge_capacity_mah_g", "initial_coulombic_efficiency_pct",
                "interface_resistance_ohm", "cell_discharge_retention_pct",
                "dcir_ohm", "rate_capability_pct"):
        v = _value(row, col)
        if v is not None:
            payload["electrochem"][col] = float(v)

    payload["formulation"] = {k: float(v) for k, v in payload["formulation"].items() if v is not None}
    if not payload["electrode_property"]:
        payload.pop("electrode_property")
    if not payload["electrochem"]:
        payload.pop("electrochem")
    return payload
