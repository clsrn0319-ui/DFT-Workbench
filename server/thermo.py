"""준조화 자유에너지 보정 (qRRHO) — v2.0 개정 기획서 P0-3.

고분자 올리고머는 저진동수 비틀림(torsion) 모드가 많다. 순수 조화 진동자(RRHO)
근사는 이 모드들의 엔트로피를 크게 과대평가한다 — 진동수가 0에 가까워지면
조화 진동자의 엔트로피가 발산하기 때문이다. 실제 그 운동은 진동이 아니라
내부 회전에 가깝다.

Grimme 의 준조화 처리(Chem. Eur. J. 2012, 18, 9955)는 각 모드의 엔트로피를
조화 진동자 값과 자유 회전자 값 사이에서 damping 함수로 보간한다.

    w(ν) = 1 / (1 + (ν₀/ν)^α)        ν₀ = 100 cm⁻¹, α = 4
    S_mode = w·S_harmonic + (1 − w)·S_free-rotor

진동수가 높으면 w → 1 이라 조화 값을 그대로 쓰고, 낮으면 자유 회전자 값으로
넘어간다. 엔탈피는 건드리지 않는다 — 저진동수 문제는 엔트로피에서 생긴다.

**이 보정은 엔트로피만 바꾼다.** 강체 구조가 아닌 유연한 사슬에서 ΔG 가
얼마나 달라지는지 함께 보고해 사용자가 그 크기를 알 수 있게 한다.
"""

import math

# 물리 상수 (CODATA)
KB = 1.380649e-23            # J/K
HBAR = 1.054571817e-34       # J·s
H_PLANCK = 6.62607015e-34    # J·s
C_LIGHT = 2.99792458e10      # cm/s
R_GAS = 8.31446261815324     # J/(mol·K)
NA = 6.02214076e23
HARTREE2J = 4.3597447222071e-18

# Grimme 준조화 파라미터
CUTOFF_CM = 100.0            # ν₀ — 이 아래에서 자유 회전자로 넘어간다
ALPHA = 4
# 자유 회전자 엔트로피 발산을 막는 평균 관성모멘트 (Grimme 원 논문 값)
B_AV = 1.0e-44               # kg·m²


def _s_harmonic(nu_cm: float, temperature: float) -> float:
    """조화 진동자 한 모드의 엔트로피 [J/(mol·K)]."""
    theta = H_PLANCK * nu_cm * C_LIGHT / KB          # 특성 온도 [K]
    x = theta / temperature
    if x > 500:                                       # 언더플로 방지
        return 0.0
    ex = math.exp(-x)
    return R_GAS * (x * ex / (1.0 - ex) - math.log(1.0 - ex))


def _s_free_rotor(nu_cm: float, temperature: float) -> float:
    """자유 회전자 한 모드의 엔트로피 [J/(mol·K)] — 낮은 진동수 극한."""
    mu = HBAR / (8.0 * math.pi ** 2 * nu_cm * C_LIGHT)      # 유효 관성모멘트
    mu_eff = mu * B_AV / (mu + B_AV)                        # 발산 억제
    arg = 8.0 * math.pi ** 3 * mu_eff * KB * temperature / (H_PLANCK ** 2)
    if arg <= 0:
        return 0.0
    return R_GAS * (0.5 + 0.5 * math.log(arg))


def _weight(nu_cm: float) -> float:
    """Grimme damping — 높은 진동수는 조화, 낮은 진동수는 자유 회전자."""
    if nu_cm <= 0:
        return 0.0
    return 1.0 / (1.0 + (CUTOFF_CM / nu_cm) ** ALPHA)


def quasi_rrho_entropy(freqs_cm, temperature: float,
                       cutoff_cm: float = CUTOFF_CM) -> dict:
    """진동 엔트로피를 조화 / 준조화 두 방식으로 계산해 차이를 함께 낸다.

    freqs_cm 는 실수 진동수 목록 (허수·0 이하는 제외된다).
    반환 단위는 J/(mol·K) 와 hartree/K 를 모두 제공한다.
    """
    real = [float(f) for f in freqs_cm if float(f) > 0.0]
    s_harm = s_qrrho = 0.0
    n_low = 0
    for nu in real:
        sh = _s_harmonic(nu, temperature)
        s_harm += sh
        if nu < cutoff_cm * 5:          # damping 이 유의미한 영역만 보간
            w = _weight(nu)
            s_qrrho += w * sh + (1.0 - w) * _s_free_rotor(nu, temperature)
        else:
            s_qrrho += sh
        if nu < cutoff_cm:
            n_low += 1
    j_to_hartree_per_k = 1.0 / (HARTREE2J * NA)
    delta_s = s_qrrho - s_harm
    return {
        "s_vib_harmonic_j_mol_k": round(s_harm, 3),
        "s_vib_qrrho_j_mol_k": round(s_qrrho, 3),
        "delta_s_j_mol_k": round(delta_s, 3),
        # ΔG = −TΔS — 엔트로피가 줄면 자유에너지가 올라간다
        "delta_g_hartree": -temperature * delta_s * j_to_hartree_per_k,
        "delta_g_kcal": round(-temperature * delta_s / 4184.0, 3),
        "n_modes": len(real),
        "n_low_freq": n_low,
        "cutoff_cm": cutoff_cm,
        "lowest_freq_cm": round(min(real), 1) if real else None,
    }


def standard_state_correction(temperature: float) -> dict:
    """기체 1 atm → 용액 1 M 표준 상태 보정.

    ΔG = RT·ln(V_m / 1 L) = RT·ln(0.082057·T)
    298.15 K 에서 +1.89 kcal/mol. 용액상 반응 자유에너지를 다룰 때
    **한 번만** 적용해야 한다 — 중복 적용이 흔한 실수라 별도 함수로 분리했다.
    """
    kcal = R_GAS * temperature * math.log(0.0820573 * temperature) / 4184.0
    return {
        "delta_g_kcal": round(kcal, 3),
        "delta_g_hartree": kcal * 4184.0 / (HARTREE2J * NA),
        "formula": "ΔG = RT·ln(0.082057·T)",
        "note": "기체 1 atm 기준 열보정을 용액 1 M 기준으로 옮기는 보정 — 한 번만 적용",
    }


def apply(thermo_result: dict, temperature: float, enabled: bool = True) -> dict:
    """엔진의 열보정 결과에 준조화 보정을 얹는다.

    조화 값을 지우지 않고 나란히 남긴다 — 보정이 얼마나 바꿨는지 보여야
    사용자가 그 크기를 판단할 수 있다.
    """
    freqs = thermo_result.get("freqs_cm")
    if freqs is None or not enabled:
        return {**thermo_result, "thermo_model": "RRHO",
                "qrrho": None}
    q = quasi_rrho_entropy(freqs, temperature)
    out = dict(thermo_result)
    out["thermo_model"] = "qRRHO (Grimme 2012)"
    out["qrrho"] = q
    out["g_corr_hartree_rrho"] = thermo_result.get("g_corr_hartree")
    out["entropy_hartree_per_k_rrho"] = thermo_result.get("entropy_hartree_per_k")
    if thermo_result.get("g_corr_hartree") is not None:
        out["g_corr_hartree"] = thermo_result["g_corr_hartree"] + q["delta_g_hartree"]
    if thermo_result.get("entropy_hartree_per_k") is not None:
        j_to_hartree_per_k = 1.0 / (HARTREE2J * NA)
        out["entropy_hartree_per_k"] = (thermo_result["entropy_hartree_per_k"]
                                        + q["delta_s_j_mol_k"] * j_to_hartree_per_k)
    return out
