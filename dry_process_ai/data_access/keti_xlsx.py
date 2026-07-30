"""FD-02 확장 — KETI 실험 Lot 원본 Excel(가로 양식) 변환기.

「Experiment Data」시트의 실측 양식(조성 → Mixing/Kneading/Cutting →
단계별 M1~L2 → Formation/Cycle → Sheet properties)을 register_lot payload 로
변환한다. 원본 파일은 data/reference/ 에 무변경 보존한다 (FD-04).

단위 처리:
    - 시간: 초 → 분 (변수 사전 단위 통일)
    - 시트 저항: ×10⁴ Ω/□ 표기 → Ω/sq 환산
    - 장기 유지율: 분율(0.8) 표기 → % 환산 (백분율 혼용 기록은 그대로 사용)
    - 단계별 두께는 원본이 이미 합제층 기준이므로 composite_thickness_um 으로
      직접 적재한다 (집전체 두께 미기록 — 재차감 방지)
Milling(3-roll mill)의 이중 갭은 전단(M12)·후단(M23)으로 분리 기록한다 — 후단이 출구 두께 기준.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import openpyxl

# 0-based 컬럼 매핑 (Experiment Data 시트, 데이터는 8행부터)
_COL = {
    "lot": 1, "am": 2, "binder": 3, "conductive": 4,
    "mixing_mass": 5, "mixing_rpm": 6, "mixing_temp": 7, "mixing_time_s": 8, "mixing_rest_s": 9, "mixing_repeat": 10,
    "kneader_mass": 11, "kneader_rpm": 12, "kneader_temp": 13, "kneader_time_s": 14,
    "cutting_mass": 15, "cutting_rpm": 16, "cutting_temp": 17, "cutting_time_s": 18, "cutting_rest_s": 19, "cutting_repeat": 20,
    "target_cap": 21, "target_den": 22,
    "form_ch1": 67, "form_dis1": 68, "form_eff1": 69,
    "cycle_ret_cycles": 81, "cycle_ret": 82,
    "sheet_res_e4": 83,
}
# 단계 블록: (q, d, L/L, t) + 갭 컬럼
_STAGE_BLOCKS = {
    "M1": {"gaps": (23, 24), "q": 25, "d": 26, "ll": 27, "t": 28},
    "M2": {"gaps": (29, 30), "q": 31, "d": 32, "ll": 33, "t": 34},
    "M3": {"gaps": (35, 36), "q": 37, "d": 38, "ll": 39, "t": 40},
    "M4": {"gaps": (41, 42), "q": 43, "d": 44, "ll": 45, "t": 46},
    "R1": {"gaps": (47,), "q": 48, "d": 49, "ll": 50, "t": 51},
    "R2": {"gaps": (52,), "q": 53, "d": 54, "ll": 55, "t": 56},
    "L1": {"gaps": (57,), "q": 58, "d": 59, "ll": 60, "t": 61},
    "L2": {"gaps": (62,), "q": 63, "d": 64, "ll": 65, "t": 66},
}

# 원본에 집전체 두께가 없어 상수로 가정 (Al foil 표준). 전 Lot 동일값이므로
# FP-05 저변동 제외에 의해 모델 입력에서 자동 배제된다.
ASSUMED_FOIL_THICKNESS_UM = 15.0


def _f(row: tuple, idx: int) -> float | None:
    v = row[idx] if idx < len(row) else None
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize_retention_pct(v: float | None) -> float | None:
    """분율(0.8)·백분율(81.2) 혼용 기록을 % 로 통일."""
    if v is None:
        return None
    return v * 100.0 if v <= 1.5 else v


def parse_keti_workbook(path: str | Path, sheet_name: str = "Experiment Data") -> list[dict[str, Any]]:
    """KETI 가로 양식 → register_lot payload 목록 (source_flag=measured)."""
    wb = openpyxl.load_workbook(str(path), data_only=True)
    ws = wb[sheet_name]
    payloads: list[dict[str, Any]] = []

    for row in ws.iter_rows(min_row=8, values_only=True):
        lot_name = row[_COL["lot"]] if len(row) > _COL["lot"] else None
        if lot_name is None or not str(lot_name).strip():
            continue

        stages: dict[str, dict[str, float]] = {}
        for stage, cols in _STAGE_BLOCKS.items():
            t = _f(row, cols["t"])
            d = _f(row, cols["d"])
            if t is None and d is None:
                continue
            gap_values = [_f(row, c) for c in cols["gaps"]]
            entry: dict[str, float] = {}
            if len(gap_values) == 2:
                # 3-roll mill: 전단(M12)/후단(M23 — 출구 기준) 분리 기록
                front, rear = gap_values
                if rear is not None:
                    entry["gap_um"] = rear
                elif front is not None:
                    entry["gap_um"] = front  # 후단 미기록 시 전단으로 대체
                if front is not None:
                    entry["gap_front_um"] = front
            elif gap_values and gap_values[0] is not None:
                entry["gap_um"] = gap_values[0]
            if t is not None:
                entry["composite_thickness_um"] = t  # 원본이 합제층 기준 — 재차감 금지
            if d is not None:
                entry["composite_density_gcc"] = d
            ll = _f(row, cols["ll"])
            if ll is not None:
                entry["loading_mg_cm2"] = ll
            q = _f(row, cols["q"])
            if q is not None:
                entry["areal_capacity_mah_cm2"] = q
            stages[stage] = entry

        electrode_property: dict[str, float] = {}
        if "L2" in stages:
            if "composite_thickness_um" in stages["L2"]:
                electrode_property["electrode_thickness_um"] = stages["L2"]["composite_thickness_um"]
            if "composite_density_gcc" in stages["L2"]:
                electrode_property["electrode_density_gcc"] = stages["L2"]["composite_density_gcc"]
        sheet_res = _f(row, _COL["sheet_res_e4"])
        if sheet_res is not None:
            electrode_property["sheet_resistance_ohm_sq"] = sheet_res * 1.0e4  # ×10⁴ Ω/□ → Ω/sq

        electrochem: dict[str, float] = {}
        idc = _f(row, _COL["form_dis1"])
        if idc is not None:
            electrochem["initial_discharge_capacity_mah_g"] = idc
        ice = _f(row, _COL["form_eff1"])
        if ice is not None:
            electrochem["initial_coulombic_efficiency_pct"] = ice
        ret = _normalize_retention_pct(_f(row, _COL["cycle_ret"]))
        if ret is not None:
            electrochem["cell_discharge_retention_pct"] = ret
        # interface_resistance / DCIR / rate 는 원본 미측정 — NaN 유지 (FP-02)

        def _minutes(idx_key: str) -> float | None:
            v = _f(row, _COL[idx_key])
            return v / 60.0 if v is not None else None

        payloads.append({
            "lot_id": str(lot_name).strip(),
            "source_flag": "measured",
            "formulation": {
                "active_material_content": _f(row, _COL["am"]),
                "binder_content": _f(row, _COL["binder"]),
                "conductive_content": _f(row, _COL["conductive"]),
            },
            "collector": {"foil_thickness_um": ASSUMED_FOIL_THICKNESS_UM, "coating_side": "single"},
            "process_conditions": {
                "mixing": {k: v for k, v in {
                    "mixing_mass": _f(row, _COL["mixing_mass"]),
                    "mixing_rpm": _f(row, _COL["mixing_rpm"]),
                    "mixing_temp": _f(row, _COL["mixing_temp"]),
                    "mixing_time": _minutes("mixing_time_s"),
                    "mixing_repeat": _f(row, _COL["mixing_repeat"]),
                }.items() if v is not None},
                "kneading": {k: v for k, v in {
                    "kneader_screw_speed": _f(row, _COL["kneader_rpm"]),
                    "kneader_barrel_temp": _f(row, _COL["kneader_temp"]),
                    "kneader_time": _minutes("kneader_time_s"),
                }.items() if v is not None},
                "cutting": {k: v for k, v in {
                    "cutting_mass": _f(row, _COL["cutting_mass"]),
                    "cutting_speed": _f(row, _COL["cutting_rpm"]),
                    "cutting_temp": _f(row, _COL["cutting_temp"]),
                    "cutting_time": _minutes("cutting_time_s"),
                    "cutting_repeat": _f(row, _COL["cutting_repeat"]),
                }.items() if v is not None},
            },
            "stages": stages,
            **({"electrode_property": electrode_property} if electrode_property else {}),
            **({"electrochem": electrochem} if electrochem else {}),
        })
    return payloads


def import_keti_workbook(session, path: str | Path) -> list[str]:
    """파싱 → 적재 → 원본 reference 보존. 반환: 적재된 lot_id 목록."""
    import datetime
    import shutil

    from dry_process_ai.config import DATA_REFERENCE_DIR
    from dry_process_ai.data_access.repository import register_lot

    payloads = parse_keti_workbook(path)
    imported = []
    for payload in payloads:
        imported.append(register_lot(session, payload))
    session.commit()

    DATA_REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.date.today().strftime("%Y%m%d")
    shutil.copy2(path, DATA_REFERENCE_DIR / f"reference_{stamp}_{Path(path).name}")
    return imported
