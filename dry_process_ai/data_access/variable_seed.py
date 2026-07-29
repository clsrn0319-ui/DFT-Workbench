"""변수 사전 초기 시드 (FD-03).

변수명은 REF-03 (KETI 건식 전극 실험 Lot 데이터 정의서)을 따르며,
코드 전반에서 임의 축약 없이 이 이름을 그대로 사용한다 (코딩 컨벤션).

mixing_max_torque / kneader_torque 는 현재 미확보이나 사전 등록해 두고,
확보 시 PTFE 피브릴화의 직접 지표로 활용한다 (제약 상황 13장).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from dry_process_ai.config import NCM811_SPECIFIC_CAPACITY_MAH_G
from dry_process_ai.data_access.db import VariableDict

# (name, unit, min, max, grade, process_group, active, is_constant, constant_value, description)
_SEED: list[tuple] = [
    # --- 상수 ---
    ("ncm811_specific_capacity", "mAh/g", None, None, "const", None, True, True,
     NCM811_SPECIFIC_CAPACITY_MAH_G, "NCM811 비용량. 실측 확보 시 갱신"),
    # --- 조성 (입력) ---
    ("active_material_content", "wt%", 80.0, 99.0, "input", "formulation", True, False, None, "NCM811 함량"),
    ("binder_content", "wt%", 0.5, 10.0, "input", "formulation", True, False, None, "PTFE 함량"),
    ("conductive_content", "wt%", 0.5, 10.0, "input", "formulation", True, False, None, "Super C 함량"),
    # --- Mixing ---
    ("mixing_mass", "g", 0.0, 5000.0, "input", "mixing", True, False, None, None),
    ("mixing_rpm", "rpm", 0.0, 20000.0, "input", "mixing", True, False, None, None),
    ("mixing_temp", "°C", 0.0, 120.0, "input", "mixing", True, False, None, None),
    ("mixing_time", "min", 0.0, 600.0, "input", "mixing", True, False, None, None),
    ("mixing_repeat", "count", 0.0, 20.0, "input", "mixing", True, False, None, None),
    ("mixing_max_torque", "N·m", 0.0, 500.0, "input", "mixing", False, False, None,
     "설비 로그 — 현재 미확보. 확보 시 PTFE 피브릴화 직접 지표"),
    # --- Kneading ---
    ("kneader_screw_speed", "rpm", 0.0, 500.0, "input", "kneading", True, False, None, None),
    ("kneader_barrel_temp", "°C", 0.0, 200.0, "input", "kneading", True, False, None, None),
    ("kneader_time", "min", 0.0, 300.0, "input", "kneading", True, False, None, None),
    ("kneader_torque", "N·m", 0.0, 500.0, "input", "kneading", False, False, None,
     "설비 로그 — 현재 미확보. 확보 시 PTFE 피브릴화 직접 지표"),
    # --- Cutting ---
    ("cutting_mass", "g", 0.0, 5000.0, "input", "cutting", True, False, None, None),
    ("cutting_speed", "rpm", 0.0, 10000.0, "input", "cutting", True, False, None, None),
    ("cutting_temp", "°C", 0.0, 120.0, "input", "cutting", True, False, None, None),
    ("cutting_time", "min", 0.0, 300.0, "input", "cutting", True, False, None, None),
    ("cutting_repeat", "count", 0.0, 20.0, "input", "cutting", True, False, None, None),
    # --- Milling / Rolling / Laminating 공통 (단계별, long) ---
    ("gap_um", "μm", 0.0, 2000.0, "input", "stage", True, False, None, "단계별 롤 갭"),
    ("stage_speed", "m/min", 0.0, 50.0, "input", "stage", True, False, None, None),
    ("stage_temp", "°C", 0.0, 200.0, "input", "stage", True, False, None, None),
    ("rolling_line_pressure", "kN", 0.0, 500.0, "input", "rolling", True, False, None, None),
    ("laminating_pressure", "MPa", 0.0, 100.0, "input", "laminating", True, False, None, None),
    # --- 집전체 (Lot 속성 → 플래그는 모델 입력) ---
    ("foil_thickness_um", "μm", 5.0, 50.0, "input", "collector", True, False, None, "Al foil 두께"),
    ("collector_attached", "flag", 0.0, 1.0, "input", "collector", True, False, None,
     "집전체 부착 여부 — 압축 거동 구간 구분 학습용 필수 입력 (FP-03)"),
    ("coating_side", "flag", 0.0, 1.0, "input", "collector", True, False, None, "0=single, 1=double"),
    # --- Lot 속성 (모델 입력 아님 — 규칙 R4) ---
    ("electrode_area_cm2", "cm²", 0.0, 10000.0, "input", "lot_meta", True, False, None,
     "전극 유효 면적. 모델 입력 벡터에서 제외 — 절대량 환산에만 사용"),
    # --- A등급 목표: 단계별 (stage_measure, long) ---
    ("areal_capacity_mah_cm2", "mAh/cm²", 0.0, 50.0, "A", "stage", True, False, None, "단계별 면적당 용량"),
    ("composite_thickness_um", "μm", 0.0, 2000.0, "A", "stage", True, False, None, "단계별 합제층 두께"),
    ("composite_density_gcc", "g/cc", 0.5, 5.0, "A", "stage", True, False, None, "단계별 합제밀도"),
    ("loading_mg_cm2", "mg/cm²", 0.0, 200.0, "A", "stage", True, False, None, "로딩 L/L (두께×밀도×0.1 종속)"),
    # --- A등급 목표: 최종 전극 물성 ---
    ("electrode_thickness_um", "μm", 0.0, 2000.0, "A", "electrode", True, False, None, None),
    ("electrode_density_gcc", "g/cc", 0.5, 5.0, "A", "electrode", True, False, None, None),
    ("sheet_resistance_ohm_sq", "Ω/sq", 0.0, 1e6, "A", "electrode", True, False, None, None),
    # --- B등급 목표: 간헐 측정 ---
    ("tensile_strength_mpa", "MPa", 0.0, 100.0, "B", "electrode", True, False, None, "UTM 선택 수행"),
    ("electrode_adhesion_n_cm", "N/cm", 0.0, 50.0, "B", "electrode", True, False, None, "90° peel test 선택 수행"),
    # --- C등급 목표: 지연 측정 ---
    ("initial_discharge_capacity_mah_g", "mAh/g", 0.0, 250.0, "C", "electrochem", True, False, None, None),
    ("initial_coulombic_efficiency_pct", "%", 80.0, 100.0, "C", "electrochem", True, False, None, None),
    ("interface_resistance_ohm", "Ω", 0.0, 1e6, "C", "electrochem", True, False, None, None),
    ("cell_discharge_retention_pct", "%", 0.0, 100.0, "C", "electrochem", True, False, None, None),
    ("dcir_ohm", "Ω", 0.0, 1e6, "C", "electrochem", True, False, None, None),
    ("rate_capability_pct", "%", 0.0, 100.0, "C", "electrochem", True, False, None, None),
    # --- 제외 대상 (자리만 유지 — 규칙 R2) ---
    ("electrode_porosity", "%", 0.0, 100.0, "excluded", "electrode", False, False, None,
     "예측·제약·알람 사용 금지. 실측 체계 확보 시 활성화"),
]


def seed_variable_dict(session: Session) -> None:
    """미등록 변수만 삽입한다 (기존 레코드 보존)."""
    existing = {name for (name,) in session.query(VariableDict.variable_name).all()}
    for (name, unit, lo, hi, grade, group, active, is_const, const_val, desc) in _SEED:
        if name in existing:
            continue
        session.add(VariableDict(
            variable_name=name, unit=unit, min_value=lo, max_value=hi, grade=grade,
            process_group=group, active=active, is_constant=is_const,
            constant_value=const_val, description=desc,
        ))
