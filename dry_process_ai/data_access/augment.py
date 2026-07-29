"""실측 기반 학습 보강 데이터 생성기 (FD-04, 규칙 R3).

실측(measured) Lot 을 앵커로 부트스트랩한다 — 임의 분포가 아니라
실제 계측된 공정 경로(단계 구성·스프링백·압하 패턴·결측 패턴)를 그대로
계승하고 조성·목표를 소폭 섭동해 물리 정합한 이웃 Lot 을 만든다.

우선순위 원칙: 실측이 1순위다. 생성 Lot 은 source_flag='generated' 로
격리되어 학습에서 낮은 샘플 가중치(GENERATED_SAMPLE_WEIGHT)를 받고,
평가(FE)·중요도 해석(FA)에서는 코드 수준에서 자동 제외된다.
"""

from __future__ import annotations

import numpy as np
from sqlalchemy.orm import Session

from dry_process_ai.config import COMPOSITION_TOTAL_WT, DEFAULT_SEED, STAGES
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

# 성능 변수 물리 범위 (생성값 clipping)
_PERF_CLIP = {
    "initial_coulombic_efficiency_pct": (80.0, 100.0),
    "cell_discharge_retention_pct": (0.0, 100.0),
}


def _measured_anchors(session: Session) -> list[dict]:
    """실측 Lot 전체를 앵커 구조체로 로드한다."""
    anchors = []
    for lot in session.query(Lot).filter(Lot.source_flag == SOURCE_MEASURED).all():
        form = session.get(Formulation, lot.lot_id)
        if form is None:
            continue
        stages = {
            r.stage_index: r for r in
            session.query(StageMeasure).filter_by(lot_id=lot.lot_id).all()
        }
        anchors.append({
            "lot": lot,
            "form": form,
            "stages": stages,
            "collector": session.get(CollectorInfo, lot.lot_id),
            "ep": session.get(ElectrodeProperty, lot.lot_id),
            "ec": session.get(Electrochem, lot.lot_id),
            "proc": session.query(ProcessCondition).filter_by(lot_id=lot.lot_id).all(),
        })
    return anchors


def generate_augmented_payloads(
    session: Session,
    n_lots: int = 40,
    seed: int = DEFAULT_SEED,
    composition_jitter_wt: float = 0.4,
    lot_prefix: str = "AUG",
) -> list[dict]:
    """실측 앵커 부트스트랩 → register_lot payload 목록 (source_flag='generated').

    각 생성 Lot 은:
    - 앵커의 결측 패턴(존재 단계·미측정 항목)을 그대로 유지한다
    - 조성은 실측 분포 범위 안에서 ± composition_jitter_wt 섭동
    - 두께·밀도·로딩·용량은 질량 보존·용량-로딩 연동·단조성을 정확히 만족
    - 갭은 앵커의 단계별 실측 스프링백 비율을 계승
    """
    anchors = _measured_anchors(session)
    if not anchors:
        raise ValueError("실측 Lot 이 없어 부트스트랩 생성이 불가하다 — 실측 1순위 원칙")

    rng = np.random.default_rng(seed)
    b_vals = [a["form"].binder_content for a in anchors]
    c_vals = [a["form"].conductive_content for a in anchors]
    b_lo, b_hi = min(b_vals), max(b_vals)
    c_lo, c_hi = min(c_vals), max(c_vals)

    payloads = []
    for i in range(n_lots):
        a = anchors[int(rng.integers(len(anchors)))]
        form = a["form"]

        b = float(np.clip(form.binder_content + rng.uniform(-1, 1) * composition_jitter_wt, b_lo, b_hi))
        c = float(np.clip(form.conductive_content + rng.uniform(-1, 1) * composition_jitter_wt, c_lo, c_hi))
        am = COMPOSITION_TOTAL_WT - b - c
        am_frac = am / 100.0
        anchor_am_frac = form.active_material_content / 100.0

        capacity_scale = float(rng.uniform(0.92, 1.08))  # 목표 로딩 스케일 섭동

        ordered = [s for s in STAGES if s in a["stages"]]
        stages = {}
        prev_t, prev_d = np.inf, -np.inf
        for s in ordered:
            src = a["stages"][s]
            if src.composite_thickness_um is None or src.composite_density_gcc is None:
                continue
            # 로딩 스케일 조정 + 밀도 소폭 섭동 → 두께는 질량 보존으로 종속
            loading = (src.loading_mg_cm2 or physics.loading_mg_cm2(
                src.composite_thickness_um, src.composite_density_gcc)) * capacity_scale
            d = src.composite_density_gcc * float(rng.uniform(0.99, 1.01))
            d = max(d, prev_d)                       # 밀도 단조 증가
            t = physics.final_composite_thickness_um(loading, d)
            if t > prev_t:                            # 두께 단조 감소
                t = prev_t * 0.999
                d = physics.composite_density_gcc(loading, t)
            prev_t, prev_d = t, d

            springback = None
            if src.gap_um and src.composite_thickness_um:
                springback = src.composite_thickness_um / src.gap_um - 1.0
            gap = t / (1.0 + springback) if springback is not None else None

            stages[s] = {
                **({"gap_um": round(gap, 1)} if gap is not None else {}),
                "composite_thickness_um": round(t, 2),
                "composite_density_gcc": round(d, 4),
                "loading_mg_cm2": round(physics.loading_mg_cm2(t, d), 3),
                "areal_capacity_mah_cm2": round(
                    physics.areal_capacity_mah_cm2(physics.loading_mg_cm2(t, d), am_frac), 4),
            }

        proc = {}
        for pc in a["proc"]:
            group = proc.setdefault(pc.process_group, {})
            value = pc.value
            if pc.variable_name == "kneader_time" and value is not None:
                # 피브릴화 보상: 바인더 감소분만큼 Kneading 시간 연장 경향 계승
                value = value * (1.0 + max(form.binder_content - b, 0.0) * 0.15)
            group[pc.variable_name] = value

        ep_src = a["ep"]
        electrode_property = {}
        if ep_src is not None:
            last = stages.get(ordered[-1]) if ordered else None
            if last:
                electrode_property["electrode_thickness_um"] = last["composite_thickness_um"]
                electrode_property["electrode_density_gcc"] = last["composite_density_gcc"]
            if ep_src.sheet_resistance_ohm_sq is not None:
                # 도전재 함량 감소 → 저항 증가 경향 (앵커 상대 스케일)
                ratio = (form.conductive_content / max(c, 1e-6)) ** 0.8
                electrode_property["sheet_resistance_ohm_sq"] = round(
                    ep_src.sheet_resistance_ohm_sq * ratio * float(rng.uniform(0.97, 1.03)), 2)
            # 인장강도·접착력은 앵커도 미측정(B등급 결측) — 결측 유지 (FP-02)

        ec_src = a["ec"]
        electrochem = {}
        if ec_src is not None:
            def _perturb(value, rel, key=None):
                if value is None:
                    return None
                v = value * float(rng.uniform(1 - rel, 1 + rel))
                if key in _PERF_CLIP:
                    lo, hi = _PERF_CLIP[key]
                    v = float(np.clip(v, lo, hi))
                return round(v, 3)

            for key, rel in (
                ("initial_discharge_capacity_mah_g", 0.01),
                ("initial_coulombic_efficiency_pct", 0.005),
                ("interface_resistance_ohm", 0.05),
                ("cell_discharge_retention_pct", 0.01),
            ):
                v = _perturb(getattr(ec_src, key), rel, key)
                if v is not None:
                    electrochem[key] = v

        payloads.append({
            "lot_id": f"{lot_prefix}-{i + 1:04d}",
            "source_flag": "generated",
            "note": f"bootstrap anchor={a['lot'].lot_id}",
            "formulation": {
                "active_material_content": round(am, 3),
                "binder_content": round(b, 3),
                "conductive_content": round(c, 3),
            },
            "collector": {
                "foil_thickness_um": a["collector"].foil_thickness_um if a["collector"] else 15.0,
                "coating_side": a["collector"].coating_side if a["collector"] else "single",
            },
            "process_conditions": proc,
            "stages": stages,
            **({"electrode_property": electrode_property} if electrode_property else {}),
            **({"electrochem": electrochem} if electrochem else {}),
        })
    return payloads


def augment_dataset(session: Session, n_lots: int = 40, seed: int = DEFAULT_SEED) -> list[str]:
    """생성 Lot 을 DB 에 적재하고 lot_id 목록을 반환한다."""
    from dry_process_ai.data_access.repository import register_lot

    ids = [register_lot(session, p) for p in generate_augmented_payloads(session, n_lots, seed)]
    session.commit()
    return ids
