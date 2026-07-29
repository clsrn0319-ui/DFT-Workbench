"""학습 보강용 생성(합성) 데이터 생성기.

용도는 회귀 시험과 제약 학습으로 한정된다 (규칙 R3).
정확도 평가(FE)와 변수 중요도 해석(FA)에서는 source_flag == 'generated'
레코드가 코드 수준에서 자동 제외된다.

물리 정합성(질량 보존·단조성·스프링백)을 만족하도록 생성하여
출력 제약층·정합성 검사기의 회귀 시험 기준 데이터로 쓸 수 있게 한다.
"""

from __future__ import annotations

import numpy as np

from dry_process_ai.config import COMPOSITION_TOTAL_WT, DEFAULT_SEED, STAGES
from dry_process_ai.rules import physics


def generate_lot_payloads(
    n_lots: int = 40,
    seed: int = DEFAULT_SEED,
    source_flag: str = "generated",
    lot_prefix: str = "GEN",
) -> list[dict]:
    """물리적으로 정합한 합성 Lot payload 목록을 생성한다 (register_lot 형식)."""
    rng = np.random.default_rng(seed)
    payloads = []
    for i in range(n_lots):
        binder = float(rng.uniform(1.0, 3.5))
        conductive = float(rng.uniform(1.0, 3.5))
        active = COMPOSITION_TOTAL_WT - binder - conductive
        am_frac = active / 100.0

        # 목표 스펙을 흩뿌려 다양한 공정 경로를 만든다
        target_capacity = float(rng.uniform(3.0, 6.5))          # mAh/cm²
        final_density = float(rng.uniform(2.7, 3.3))            # g/cc
        final_density -= (conductive - 1.0) * 0.05              # 도전재↑ → 치밀화 난이도↑
        loading_final = physics.required_loading_mg_cm2(target_capacity, am_frac)
        final_thickness = physics.final_composite_thickness_um(loading_final, final_density)

        # 초기(M1) 시트: 낮은 밀도, 두꺼움. 트리밍으로 로딩은 단계마다 소폭 감소.
        density_m1 = float(rng.uniform(2.3, 2.6))
        loading_m1 = loading_final * float(rng.uniform(1.05, 1.15))
        thickness_m1 = loading_m1 / density_m1 / 0.1

        # 8단계 기하 보간 + 소량 노이즈 (단조성 유지)
        n = len(STAGES)
        t_ratio = (final_thickness / thickness_m1) ** (1.0 / (n - 1))
        loading_path = np.linspace(loading_m1, loading_final, n)
        thickness_path, density_path = [], []
        t = thickness_m1
        for k in range(n):
            noise = 1.0 + rng.uniform(-0.01, 0.01)
            tk = thickness_m1 * (t_ratio ** k) * noise
            tk = min(tk, t)  # 단조 감소 보장
            t = tk
            thickness_path.append(tk)
            density_path.append(loading_path[k] / tk / 0.1)
        # 밀도 단조 증가 보정
        for k in range(1, n):
            if density_path[k] < density_path[k - 1]:
                density_path[k] = density_path[k - 1]
                thickness_path[k] = loading_path[k] / density_path[k] / 0.1

        springback = float(rng.uniform(0.03, 0.08))
        foil = float(rng.uniform(12.0, 20.0))
        stages = {}
        for k, stage in enumerate(STAGES):
            tk = float(thickness_path[k])
            dk = float(density_path[k])
            lk = physics.loading_mg_cm2(tk, dk)
            qk = physics.areal_capacity_mah_cm2(lk, am_frac)
            gap = tk / (1.0 + springback)
            row = {
                "gap_um": round(gap, 1),
                "composite_thickness_um": round(tk, 2),
                "composite_density_gcc": round(dk, 4),
                "loading_mg_cm2": round(lk, 3),
                "areal_capacity_mah_cm2": round(qk, 4),
            }
            if stage in ("L1", "L2"):
                # 화면 병기용 원측정값 — 적재 시 재차 차감되지 않도록 composite 를 직접 준다
                row["measured_thickness_um"] = round(tk + foil, 2)
                row["composite_thickness_um"] = round(tk, 2)
            stages[stage] = row

        kneader_time = 30.0 + (3.5 - binder) * 8.0 + rng.uniform(-3, 3)  # 저바인더 → 피브릴화 보상
        sheet_resistance = float(np.exp(rng.normal(0.0, 0.08)) * 12.0 / (conductive ** 0.8) * (3.2 / final_density))
        tensile = float(2.0 + binder * 1.8 + rng.normal(0, 0.3))
        adhesion = float(1.0 + binder * 0.9 + rng.normal(0, 0.2))
        measured_aux = rng.random() < 0.5  # B등급 간헐 측정 재현
        has_cell = rng.random() < 0.6      # C등급 지연 측정 재현

        ice = float(np.clip(88.0 + (final_density - 3.0) * 4.0 + rng.normal(0, 1.0), 80.0, 100.0))
        retention = float(np.clip(92.0 + binder * 1.0 - conductive * 0.5 + rng.normal(0, 1.5), 0.0, 100.0))
        idc = float(np.clip(200.0 - (3.3 - final_density) * 20.0 + rng.normal(0, 3.0), 120.0, 215.0))
        interface_r = float(np.exp(rng.normal(0.0, 0.1)) * 8.0 / (conductive ** 0.5))

        payload = {
            "lot_id": f"{lot_prefix}-{i + 1:04d}",
            "experiment_date": "2026-07-01",
            "operator": "synthetic",
            "electrode_area_cm2": float(rng.choice([16.0, 25.0, 100.0])),
            "source_flag": source_flag,
            "formulation": {
                "active_material_content": round(active, 3),
                "binder_content": round(binder, 3),
                "conductive_content": round(conductive, 3),
            },
            "collector": {"foil_thickness_um": round(foil, 1), "coating_side": "single"},
            "process_conditions": {
                "mixing": {
                    "mixing_mass": float(rng.uniform(200, 400)),
                    "mixing_rpm": float(rng.uniform(8000, 15000)),
                    "mixing_temp": float(rng.uniform(20, 35)),
                    "mixing_time": float(rng.uniform(3, 10)),
                    "mixing_repeat": float(rng.integers(1, 4)),
                },
                "kneading": {
                    "kneader_screw_speed": float(rng.uniform(30, 80)),
                    "kneader_barrel_temp": float(rng.uniform(60, 120)),
                    "kneader_time": float(max(kneader_time, 5.0)),
                },
                "cutting": {
                    "cutting_mass": float(rng.uniform(150, 350)),
                    "cutting_speed": float(rng.uniform(1000, 4000)),
                    "cutting_temp": float(rng.uniform(20, 30)),
                    "cutting_time": float(rng.uniform(1, 5)),
                    "cutting_repeat": float(rng.integers(1, 3)),
                },
                "rolling": {"rolling_line_pressure": float(rng.uniform(50, 200))},
                "laminating": {"laminating_pressure": float(rng.uniform(5, 40))},
            },
            "stages": stages,
            "electrode_property": {
                "electrode_thickness_um": round(float(thickness_path[-1]), 2),
                "electrode_density_gcc": round(float(density_path[-1]), 4),
                "sheet_resistance_ohm_sq": round(sheet_resistance, 4),
                **({"tensile_strength_mpa": round(tensile, 3),
                    "electrode_adhesion_n_cm": round(adhesion, 3)} if measured_aux else {}),
            },
        }
        if has_cell:
            payload["electrochem"] = {
                "initial_discharge_capacity_mah_g": round(idc, 2),
                "initial_coulombic_efficiency_pct": round(ice, 2),
                "interface_resistance_ohm": round(interface_r, 3),
                "cell_discharge_retention_pct": round(retention, 2),
            }
        payloads.append(payload)
    return payloads
