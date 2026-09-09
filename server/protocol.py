"""계산 프로토콜 카드와 전위 기준 규약 — v2.0 개정 기획서 P0-2 · P0-4 · P0-8 · 10.2.

v1.0 에서는 「E_red = EA − 1.44 V」를 항등식으로 표현했다. 엔진 내부 산식으로는
일관되지만, 연구 보고에서는 위험한 표현이다. 1.44 V 는 자연상수가 아니라
**채택한 기준 변환 규약**이고, 문헌·convention 에 따라 1.40~1.46 V 사이에서
달라진다. 어떤 값을 왜 썼는지 추적할 수 없으면 다른 그룹의 값과 비교할 수 없다.

그래서 이 모듈은 세 가지를 한다.

  1. 전위 기준 규약(REFERENCE_CONVENTIONS)을 출처와 함께 명시하고, 결과마다
     어떤 규약을 썼는지 저장한다.
  2. 프로토콜 카드 — functional·basis·용매·열보정·전하상태 처리를 한 벌로 묶고
     해시를 만든다. 같은 해시면 같은 조건에서 계산된 값이라 비교할 수 있다.
  3. 5축 신뢰도 — 「계산이 정밀한가」와 「예측이 정확한가」를 분리한다.

**중요.** 이 모듈은 신뢰도를 «계산할» 뿐 예측 정확도를 «보증하지» 않는다.
Calibration 축은 참조 데이터셋으로 검증하기 전까지 항상 미검증으로 남는다.
"""

import hashlib
import json

PROTOCOL_VERSION = "DFT-BINDER-v2.0"

# ── 전위 기준 규약 (P0-2) ────────────────────────────────────────────
# absolute_v: 기준 전극의 절대 전위 [V]. E_red(vs ref) = EA(eV) − absolute_v
# 이 값은 항등식의 상수가 아니라 «채택한 규약»이다.
REFERENCE_CONVENTIONS = {
    "Li/Li+ (1.44 V)": {
        "electrode": "Li/Li+",
        "absolute_v": 1.44,
        "electron_convention": "vacuum electron (computational chemistry convention)",
        "source": "SHE 절대전위 4.44 V(Isse·Gennaro 2010)에서 Li/Li⁺ −3.04 V vs SHE 로 환산",
        "note": "v1.0 과 값이 같아 기존 결과와 그대로 비교된다 — 기본값",
    },
    "Li/Li+ (1.40 V)": {
        "electrode": "Li/Li+",
        "absolute_v": 1.40,
        "electron_convention": "vacuum electron (computational chemistry convention)",
        "source": "배터리 반응망 연구에서 널리 쓰이는 값 (J. Am. Chem. Soc. 2021)",
        "note": "1.44 V 규약 대비 모든 전위가 +0.04 V 이동한다",
    },
    "SHE (4.44 V)": {
        "electrode": "SHE",
        "absolute_v": 4.44,
        "electron_convention": "vacuum electron (computational chemistry convention)",
        "source": "Isse·Gennaro, J. Phys. Chem. B 2010, 114, 7894",
        "note": "수용액 전기화학 문헌과 비교할 때 사용",
    },
}
DEFAULT_CONVENTION = "Li/Li+ (1.44 V)"

# 규약 간 차이 — 「기준을 바꾸면 판정이 바뀌는가」를 사용자가 볼 수 있게 한다
CONVENTION_SPREAD_V = round(
    max(c["absolute_v"] for c in REFERENCE_CONVENTIONS.values() if c["electrode"] == "Li/Li+")
    - min(c["absolute_v"] for c in REFERENCE_CONVENTIONS.values() if c["electrode"] == "Li/Li+"), 3)


def convention(name: str | None = None) -> dict:
    """전위 기준 규약을 이름으로 가져온다. 없으면 기본 규약."""
    return dict(REFERENCE_CONVENTIONS.get(name or DEFAULT_CONVENTION,
                                          REFERENCE_CONVENTIONS[DEFAULT_CONVENTION]))


def redox_from_ea(ea_ev: float, conv_name: str | None = None) -> dict:
    """EA(eV) → 환원 전위. 항등식이 아니라 «규약을 적용한 변환»임을 값에 남긴다."""
    c = convention(conv_name)
    return {
        "value_v": round(ea_ev - c["absolute_v"], 3),
        "convention": conv_name or DEFAULT_CONVENTION,
        "absolute_v": c["absolute_v"],
        "electrode": c["electrode"],
        "formula": f"E = EA − {c['absolute_v']} V ({c['electrode']} 기준 변환 규약)",
        "convention_spread_v": CONVENTION_SPREAD_V,
    }


# ── 용매 환경 수준 (P0-4 · 14.5) ──────────────────────────────────────
# 혼합 용매를 부피 가중 SMD 로 만드는 것은 «검증된 혼합용매»가 아니라 근사다.
# 그 사실을 등급으로 남기고, 미검증 근사에는 신뢰도 상한을 건다.
ENVIRONMENT_LEVELS = {
    "L0": {"label": "순수 용매 continuum", "confidence_cap": "High",
           "detail": "SMD 파라미터가 그 용매에 대해 직접 정의된 경우"},
    "L1": {"label": "effective SMD mixture (근사)", "confidence_cap": "Medium",
           "detail": ("성분 SMD 파라미터의 부피 가중 평균. SMD 는 본래 용매별 "
                      "파라미터와 학습 데이터에 기반하므로, 가중 평균이 실제 혼합용매의 "
                      "미시적 용매화를 정량적으로 재현한다는 보장은 없다. "
                      "특히 이온의 SMD 오차는 중성 분자보다 크다.")},
    "L2": {"label": "explicit 1차 용매껍질 + continuum", "confidence_cap": "High",
           "detail": "명시적 용매 분자와 연속체를 함께 쓰는 cluster-continuum"},
    "L3": {"label": "계면 모델 (periodic/QM-MM)", "confidence_cap": "High",
           "detail": "전극 계면을 직접 모델링 — 현재 미구현"},
}


def environment_level(settings: dict) -> dict:
    """설정에서 용매 환경 수준을 판정한다."""
    if settings.get("envType") == "진공·기체":
        return {"level": "L0", **ENVIRONMENT_LEVELS["L0"],
                "label": "기체상 (용매 없음)", "confidence_cap": "High"}
    if settings.get("customMixedSolvent"):
        return {"level": "L1", **ENVIRONMENT_LEVELS["L1"]}
    if settings.get("explicitMolecules"):
        return {"level": "L2", **ENVIRONMENT_LEVELS["L2"]}
    sol = settings.get("solventId") or ""
    # 내장 혼합 프리셋도 같은 근사다 — 단일 용매만 L0
    if "dmc" in sol and "ec" in sol:
        return {"level": "L1", **ENVIRONMENT_LEVELS["L1"]}
    return {"level": "L0", **ENVIRONMENT_LEVELS["L0"]}


# ── 5축 신뢰도 (P0-8 · 6.2) ──────────────────────────────────────────
CONFIDENCE_AXES = [
    ("numerical", "Numerical", "SCF·구조·진동수 수렴, 스핀 오염, 허수 진동수"),
    ("model", "Molecular Model", "conformer·올리고머 길이·서열 대표성"),
    ("method", "Method", "범함수·기저 민감도"),
    ("environment", "Environment", "용매 혼합·Li⁺·표면 모델의 실제 조건 근접도"),
    ("calibration", "Calibration", "참조 데이터셋 검증·적용 범위"),
]
LEVELS = ["Low", "Medium", "High"]


def _worst(levels: list[str]) -> str:
    """한 축의 심각한 약점이 평균에 가려지지 않도록 최소값을 쓴다 (6.2)."""
    if not levels:
        return "Low"
    return LEVELS[min(LEVELS.index(x) for x in levels)]


def _cap(level: str, cap: str) -> str:
    return LEVELS[min(LEVELS.index(level), LEVELS.index(cap))]


def confidence(desc: dict, settings: dict, redox_basis: str | None = None,
               conformer_spread_v: float | None = None,
               chain_converged: bool | None = None) -> dict:
    """5축 신뢰도. 「정밀한 계산」과 「정확한 예측」을 분리한다.

    Calibration 축은 참조 데이터셋 검증이 없으므로 항상 Low 다 — 이것이
    v1.0 의 High/Medium/Low 와 가장 크게 다른 점이다. v1.0 에서 «High» 였던
    결과도 v2.0 에서는 전체 신뢰도가 Low 로 내려간다. 계산이 나빠진 것이
    아니라, 예측 정확도가 검증되지 않았다는 사실을 이제 표시하는 것이다.
    """
    axes, reasons = {}, {}

    # ① Numerical — 수치적으로 안정한가
    n_imag = desc.get("n_imaginary_freqs")
    if isinstance(n_imag, int) and n_imag > 0:
        axes["numerical"] = "Low"
        reasons["numerical"] = f"허수 진동수 {n_imag}개 — 안장점 가능성"
    elif desc.get("zpe_kcal") is not None:
        axes["numerical"] = "High"
        reasons["numerical"] = "진동수 계산 완료 · 허수 없음"
    else:
        axes["numerical"] = "Medium"
        reasons["numerical"] = "진동수 계산 없음 — 극소점 여부 미확인"

    # ② Molecular Model — 이 구조가 물질을 대표하는가
    if chain_converged is False:
        axes["model"] = "Low"
        reasons["model"] = "올리고머 길이 미수렴 — 고분자 대표값으로 확정 금지"
    elif conformer_spread_v is not None and conformer_spread_v >= 0.20:
        axes["model"] = "Low"
        reasons["model"] = f"conformer 간 전위 편차 {conformer_spread_v:.2f} V — 단일값 부적절"
    elif conformer_spread_v is not None and conformer_spread_v >= 0.10:
        axes["model"] = "Medium"
        reasons["model"] = f"conformer 간 전위 편차 {conformer_spread_v:.2f} V"
    elif chain_converged is True:
        axes["model"] = "High"
        reasons["model"] = "올리고머 길이 수렴 확인"
    else:
        axes["model"] = "Medium"
        reasons["model"] = "단일 구조 — 올리고머 수렴·conformer 편차 미확인"

    # ③ Method — 범함수·기저 민감도
    if redox_basis and any(k in redox_basis.lower() for k in ("tzvpd", "ma-def2", "aug-")):
        axes["method"] = "Medium"
        reasons["method"] = f"음이온에 diffuse 기저({redox_basis}) 적용 — 범함수 민감도는 미평가"
    elif desc.get("reduction_potential_gibbs_v") is not None:
        axes["method"] = "Low"
        reasons["method"] = ("음이온에 diffuse 기저를 쓰지 않음 — EA·환원 전위의 "
                             "기저 의존성이 평가되지 않았습니다")
    else:
        axes["method"] = "Low"
        reasons["method"] = "범함수·기저 민감도 미평가"

    # ④ Environment — 계산 환경이 실제 조건에 얼마나 가까운가
    env = environment_level(settings)
    axes["environment"] = _cap("High", env["confidence_cap"])
    reasons["environment"] = f"{env['level']} · {env['label']}"
    if env["level"] == "L1":
        reasons["environment"] += " — 미검증 근사라 Medium 상한"

    # ⑤ Calibration — 참조 데이터셋으로 검증되었는가
    axes["calibration"] = "Low"
    reasons["calibration"] = ("참조 데이터셋 검증(benchmark)이 아직 없습니다 — "
                              "예측 오차가 정량화되지 않았습니다")

    overall = _worst(list(axes.values()))
    return {
        "axes": [{"key": k, "label": lbl, "level": axes[k],
                  "reason": reasons[k], "detail": detail}
                 for k, lbl, detail in CONFIDENCE_AXES],
        "overall": overall,
        "rule": "한 축의 약점이 가려지지 않도록 최소값을 전체 신뢰도로 쓴다",
        "note": ("Calibration 축이 검증되기 전에는 전체 신뢰도가 Low 를 넘지 못합니다. "
                 "계산이 정밀한 것과 예측이 정확한 것은 다릅니다."),
    }


# ── 검증 상태 (1.2) ──────────────────────────────────────────────────
# 「자동 테스트 119건 통과」는 소프트웨어가 의도대로 도는지에 대한 증거이지
# 예측이 실제와 맞는지에 대한 증거가 아니다. 둘을 섞어 표시하면 안 된다.
VALIDATION_STAGES = [
    {"stage": "A. Software verification", "question": "코드가 의도한 계산을 수행하는가",
     "evidence": "단위·통합·회귀 테스트", "status": "통과",
     "detail": "자동 테스트 통과 — 프로그램 오류 가능성 감소"},
    {"stage": "B. Numerical verification", "question": "같은 조건에서 수치적으로 안정한가",
     "evidence": "SCF·구조·진동수 수렴, 기저 민감도, 교차 엔진 대조", "status": "부분",
     "detail": "수렴 검사와 허수 진동수 기록은 있으나 교차 엔진 대조는 미실시"},
    {"stage": "C. Method validation", "question": "이 프로토콜이 참조 데이터를 재현하는가",
     "evidence": "MAE·RMSE·순위 상관", "status": "미실시",
     "detail": "참조 데이터셋(benchmark)이 아직 구성되지 않았습니다"},
    {"stage": "D. Application validation", "question": "실제 연구 결과와 연결되는가",
     "evidence": "blind 후보군, LSV/CV onset, 순위 적중률", "status": "미실시",
     "detail": "실험 calibration 데이터가 아직 없습니다"},
]


def validation_status() -> dict:
    return {"stages": VALIDATION_STAGES,
            "summary": ("소프트웨어 검증(A)은 통과했으나 과학적 예측 정확도 검증(C·D)은 "
                        "아직 수행되지 않았습니다. 이 프로그램의 값은 «동일 조건에서의 "
                        "상대 비교»에 쓰고, 절대값을 실험 예측으로 인용하지 마세요.")}


# ── 프로토콜 카드 · 해시 (10.2) ──────────────────────────────────────
def card(settings: dict, params: dict | None = None,
         conv_name: str | None = None) -> dict:
    """이 계산이 어떤 조건으로 수행되는가 — 한 벌로 묶어 해시까지 만든다."""
    p = params or {}
    exp = settings.get("expert") or {}
    conv = convention(conv_name)
    env = environment_level(settings)
    body = {
        "protocol_version": PROTOCOL_VERSION,
        "accuracy": settings.get("accuracy"),
        "functional": exp.get("functional"),
        "dispersion": p.get("disp"),
        "basis_geometry": p.get("basis_opt"),
        "basis_singlepoint": p.get("basis_sp"),
        "basis_anion": p.get("basis_anion") or p.get("basis_sp"),
        "solvent_model": "SMD",
        "environment_level": env["level"],
        "temperature_k": settings.get("temperature"),
        "reference_convention": conv_name or DEFAULT_CONVENTION,
        "absolute_reference_v": conv["absolute_v"],
        "electron_convention": conv["electron_convention"],
        "standard_state": "gas 1 atm → solution 1 M 보정 적용",
        "thermochemistry": p.get("thermo_model", "RRHO"),
        "geometry_optimized": p.get("do_opt"),
        "redox_adiabatic": p.get("redox_adiabatic"),
    }
    # conformer 민감도(P0-5)는 프로토콜의 일부다 — 켜져 있을 때만 키를 넣어,
    # 민감도가 없는 기존 결과의 해시는 그대로 유지한다.
    if (p.get("conf_sens") or 0) >= 2:
        body["conformer_sensitivity"] = int(p["conf_sens"])
    # Li⁺ 모델(P0-6)도 프로토콜의 일부 — 경쟁 모델일 때만 키를 넣어 기존 해시를 지킨다
    if p.get("li_model") == "competition":
        body["li_model"] = f"solvent_competition(n={p.get('li_coordination') or 4})"
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    return {**body, "protocol_hash": digest,
            "reference_source": conv["source"],
            "environment_label": env["label"],
            "environment_detail": env["detail"],
            "confidence_cap": env["confidence_cap"]}
