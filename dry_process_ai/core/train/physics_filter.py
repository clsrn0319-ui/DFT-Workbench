"""FT-04 — 의사 라벨 물리 정합성 필터.

Teacher 가 생성한 의사 라벨 중 물리 제약을 통과한 것만 채택하고
통과율을 로그로 기록한다. 통과율이 임계값 미만이면 Student 학습을
진행하지 않고 Teacher 재검토를 요청한다 (기획서 4.4 예외).

검사 항목:
    ① 질량 보존 (해당 행의 단계별 예측 두께·밀도·용량)
    ② 합제밀도가 실측 이력 범위 + 여유폭 이내
    ③ 용량-로딩 정합성
    ④ 성능 변수 물리 범위 (ICE 80~100 %, 유지율 0~100 %, 저항 > 0)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from dry_process_ai.config import PSEUDO_FILTER_TOLERANCE, STAGES
from dry_process_ai.rules import constraints


@dataclass
class FilterResult:
    accepted_index: list = field(default_factory=list)
    rejected: dict[str, int] = field(default_factory=dict)   # 탈락 사유별 집계
    pass_rate: float = 0.0


def filter_pseudo_labels(
    stage_pred_phys: pd.DataFrame,
    perf_pred_phys: pd.DataFrame,
    active_material_fraction: pd.Series,
    density_ceiling_gcc: float | None = None,
    tolerance: float = PSEUDO_FILTER_TOLERANCE,
) -> FilterResult:
    """의사 라벨 행 단위 물리 정합성 검사.

    stage_pred_phys: 물리 단위 단계별 예측 (컬럼 {stage}_{target}), 행 = 후보 Lot
    perf_pred_phys:  물리 단위 성능 의사 라벨 (PERF_OUTPUT_COLUMNS)
    """
    result = FilterResult()
    for idx in perf_pred_phys.index:
        stage_values = {}
        for stage in STAGES:
            row = {}
            for target in ("areal_capacity_mah_cm2", "composite_thickness_um", "composite_density_gcc"):
                col = f"{stage}_{target}"
                if col in stage_pred_phys.columns:
                    row[target] = float(stage_pred_phys.loc[idx, col])
            if row:
                stage_values[stage] = row

        report = constraints.check_stage_sequence(
            stage_values,
            density_ceiling_gcc=density_ceiling_gcc,
            active_material_fraction=float(active_material_fraction.loc[idx]),
            tolerance=tolerance,
        )
        perf_report = constraints.check_performance_ranges({
            "initial_discharge_capacity": perf_pred_phys.loc[idx].get("initial_discharge_capacity_mah_g"),
            "initial_coulombic_efficiency": perf_pred_phys.loc[idx].get("initial_coulombic_efficiency_pct"),
            "interface_resistance": perf_pred_phys.loc[idx].get("interface_resistance_ohm"),
            "cell_discharge_retention": perf_pred_phys.loc[idx].get("cell_discharge_retention_pct"),
        })

        errors = [v for v in report.violations + perf_report.violations if v.severity == "error"]
        if errors:
            for v in errors:
                result.rejected[v.rule] = result.rejected.get(v.rule, 0) + 1
        else:
            result.accepted_index.append(idx)

    total = len(perf_pred_phys.index)
    result.pass_rate = len(result.accepted_index) / total if total else 0.0
    return result
