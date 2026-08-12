"""사슬 길이 수렴 (Step 1 · L3) — 값이 «고분자를 대표하는가»를 판정한다.

모노머 하나를 계산해 «이 고분자의 성질»이라 부르면, 그 값이 사슬이 길어져도
유지되는지 알 수 없다. 반복 단위 수 n을 늘려가며 같은 물성을 계산하고

  1. 연속 두 점의 차이가 임계값 아래로 내려갔는가 (수렴)
  2. 1/n 에 대한 선형 외삽으로 무한 사슬 극한값은 얼마인가

를 판정한다. 미수렴이면 그렇다고 밝히고, 대표값을 주장하지 않는다.

물성이 짧은 사슬에서 아예 정의되지 않는 경우도 있다. 예: 에틸렌(C=C)은
끊을 주사슬 단일결합이 없어 BDE가 산출되지 않는다. 그래서 수렴을 따지기 전에
«물성이 정의되는 최소 사슬 길이»를 먼저 알려준다.
"""

from rdkit import Chem

from . import descriptors as desc_mod
from .geometry import GeometryError, oligomerize

# 기본 사슬 길이 계열 — 1/n 외삽에 필요한 넓은 간격을 갖도록 골랐다
DEFAULT_LENGTHS = (1, 2, 3, 5)

# 물성별 수렴 임계값 (절대 단위). 없는 물성은 값 범위의 2 %를 쓴다.
THRESHOLDS = {
    "homo_ev": 0.05, "lumo_ev": 0.05, "gap_ev": 0.05,
    "dipole_debye": 0.2,
    "ip_vertical_ev": 0.05, "ea_vertical_ev": 0.05,
    "ip_adiabatic_ev": 0.05, "ea_adiabatic_ev": 0.05,
    "oxidation_potential_v": 0.05, "reduction_potential_v": 0.05,
    "oxidation_potential_gibbs_v": 0.05, "reduction_potential_gibbs_v": 0.05,
    "solvation_energy_kcal": 0.5,
    "bde_min_kj": 5.0, "bde_min_298_kj": 5.0,
    "dimer_binding_kj": 3.0, "li_binding_kj": 5.0,
    "chemical_hardness_ev": 0.05, "chemical_potential_ev": 0.05,
    "electrophilicity_ev": 0.05,
}
RELATIVE_FALLBACK = 0.02

# 사슬이 길어질수록 크기에 비례해 커지는 값 — 수렴을 따지는 것이 무의미하다
EXTENSIVE = {"total_energy_hartree", "gibbs_energy_hartree", "zpe_kcal",
             "gibbs_correction_kcal", "entropy_cal_mol_k",
             "gibbs_energy_solution_hartree", "n_imaginary_freqs"}


def threshold_for(key: str, values: list[float]) -> float:
    if key in THRESHOLDS:
        return THRESHOLDS[key]
    span = max(values) - min(values) if values else 0.0
    scale = max(abs(v) for v in values) if values else 1.0
    return max(span, scale) * RELATIVE_FALLBACK or 1e-6


def extrapolate(points: list[tuple[int, float]]) -> dict | None:
    """value = a + b/n 선형 외삽 — a 가 무한 사슬 극한값.

    말단기 효과가 1/n 으로 감소한다는 표준 가정을 따른다. 점이 2개뿐이면
    직선이 정확히 지나가 잔차가 0이 되므로 «1/n 형태가 맞는지» 확인할 방법이
    없다. 그런 외삽은 크게 빗나가도 알 수 없어 아예 내지 않는다.
    """
    if len(points) < 3:
        return None
    xs = [1.0 / n for n, _ in points]
    ys = [v for _, v in points]
    m = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = m * sxx - sx * sx
    if abs(denom) < 1e-12:
        return None
    slope = (m * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / m
    resid = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    max_resid = max(abs(r) for r in resid)
    return {"limit": round(intercept, 4), "slope": round(slope, 4),
            "max_residual": round(max_resid, 4)}


def analyze_property(key: str, points: list[tuple[int, float]]) -> dict:
    """한 물성의 사슬 길이 의존성을 판정한다. points 는 (n, value) 목록."""
    pts = sorted(points)
    values = [v for _, v in pts]
    result = {
        "key": key,
        "points": [{"n": n, "value": round(v, 4)} for n, v in pts],
        "extensive": key in EXTENSIVE,
    }
    if key in EXTENSIVE:
        result["status"] = "extensive"
        result["note"] = ("사슬 길이에 비례하는 크기 값이라 수렴 판정 대상이 아닙니다 "
                          "— 반복 단위당 값으로 환산해 비교하세요.")
        return result
    if len(pts) < 2:
        result["status"] = "insufficient"
        result["note"] = "사슬 길이 2개 이상이 있어야 수렴을 판정할 수 있습니다."
        return result

    deltas = [{"from_n": pts[i - 1][0], "to_n": pts[i][0],
               "delta": round(values[i] - values[i - 1], 4)}
              for i in range(1, len(pts))]
    thr = threshold_for(key, values)
    last = abs(deltas[-1]["delta"])
    converged = last < thr
    extrap = extrapolate(pts)

    result.update({
        "deltas": deltas,
        "threshold": round(thr, 4),
        "last_delta": round(last, 4),
        "converged": converged,
        "status": "converged" if converged else "not_converged",
        "longest_n": pts[-1][0],
        "value_at_longest": round(values[-1], 4),
        "extrapolation": extrap,
    })
    if converged:
        result["note"] = (f"n={pts[-2][0]}→{pts[-1][0]} 변화 {last:.4g} 가 "
                          f"임계값 {thr:.4g} 미만 — 대표값으로 쓸 수 있습니다.")
    else:
        # 외삽을 내지 못한 경우(점 2개)에 «외삽값을 참고하라»고 하면 안 된다
        tail = ("더 긴 사슬을 계산하거나 외삽값을 참고하세요."
                if extrap else "더 긴 사슬을 계산하세요.")
        result["note"] = (f"n={pts[-2][0]}→{pts[-1][0]} 변화 {last:.4g} 가 "
                          f"임계값 {thr:.4g} 이상 — 아직 수렴하지 않았습니다. " + tail)
    return result


def analyze(series: list[dict], base_smiles: str | None = None) -> dict:
    """길이별 결과 묶음을 물성별 수렴 판정으로 환산한다.

    series: [{"n": int, "descriptors": {...}}, ...]
    base_smiles 를 주면 비닐 단량체 여부를 확인해 n=1을 판정에서 제외한다.
    """
    excluded, exclusion_note = [], None
    if base_smiles:
        seg = monomer_is_chain_segment(base_smiles)
        if not seg["same_species"]:
            excluded, exclusion_note = [1], seg["note"]

    used = [e for e in series if e.get("n") not in excluded]
    by_key: dict[str, list[tuple[int, float]]] = {}
    for entry in used:
        n = entry.get("n")
        for key, value in (entry.get("descriptors") or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                by_key.setdefault(key, []).append((n, float(value)))

    props = [analyze_property(k, pts) for k, pts in sorted(by_key.items())]
    judged = [p for p in props if p["status"] in ("converged", "not_converged")]
    lengths = sorted({e["n"] for e in used})
    result = {
        "lengths": lengths,
        "all_lengths": sorted({e["n"] for e in series}),
        "excluded_lengths": excluded,
        "exclusion_note": exclusion_note,
        "properties": props,
        "n_converged": sum(1 for p in judged if p["converged"]),
        "n_judged": len(judged),
        "not_converged": [p["key"] for p in judged if not p["converged"]],
        "extrapolation_available": len(lengths) >= 3,
    }
    if len(lengths) < 2:
        result["warning"] = (
            "판정에 쓸 수 있는 사슬 길이가 2개 미만입니다"
            + (f" (n={excluded} 제외됨)" if excluded else "")
            + " — 더 긴 사슬을 계산하세요.")
    elif len(lengths) < 3:
        result["warning"] = (
            "길이가 2개뿐이라 무한 사슬 외삽은 내지 않습니다 — 직선이 두 점을 "
            "정확히 지나 1/n 형태가 맞는지 확인할 수 없기 때문입니다. "
            "수렴 여부만 참고하고, 극한값이 필요하면 길이를 하나 더 계산하세요.")
    return result


def monomer_is_chain_segment(smiles: str) -> dict:
    """모노머가 사슬 단위와 같은 화학종인지 확인한다.

    비닐 단량체는 중합하면서 C=C 이중결합이 소모되어 포화 사슬이 된다.
    즉 n=1(에틸렌)과 n=2(부탄)는 다른 물질이고, 이 둘을 같은 계열로 놓고
    «수렴»을 따지면 의미가 없다. 그런 경우 n=1을 판정에서 뺀다.
    """
    alkene = Chem.MolFromSmarts("[CX3;!R]=[CX3;!R]")
    try:
        mono = Chem.MolFromSmiles(smiles)
        dimer = Chem.MolFromSmiles(oligomerize(smiles, 2))
    except (GeometryError, ValueError):
        return {"same_species": True, "note": None}
    if mono is None or dimer is None:
        return {"same_species": True, "note": None}

    per_unit_mono = len(mono.GetSubstructMatches(alkene))
    per_unit_dimer = len(dimer.GetSubstructMatches(alkene)) / 2.0
    if per_unit_mono > per_unit_dimer + 1e-9:
        return {
            "same_species": False,
            "note": ("비닐 단량체입니다 — 중합하면서 C=C가 소모되므로 n=1(단량체)과 "
                     "n≥2(포화 사슬)는 다른 화학종입니다. n=1은 수렴 판정에서 "
                     "제외합니다."),
        }
    return {"same_species": True, "note": None}


def minimum_defined_length(smiles: str, max_n: int = 4) -> dict:
    """물성이 «정의되는» 최소 사슬 길이 — DFT 없이 구조만으로 판별.

    현재는 BDE(끊을 수 있는 주사슬 단일결합)만 확인한다. 에틸렌처럼 모노머에
    단일결합이 없는 구조는 그 길이에서 BDE 자체가 산출되지 않는다.
    """
    out = {"smiles": smiles, "bde_min_n": None, "checked": []}
    for n in range(1, max_n + 1):
        try:
            oligo = oligomerize(smiles, n) if n > 1 else smiles
            bonds = len(desc_mod.breakable_bonds(oligo))
        except (GeometryError, ValueError) as exc:
            out["checked"].append({"n": n, "error": str(exc)})
            continue
        out["checked"].append({"n": n, "smiles": oligo, "breakable_bonds": bonds})
        if bonds > 0 and out["bde_min_n"] is None:
            out["bde_min_n"] = n
    if out["bde_min_n"] is None:
        out["note"] = f"n={max_n} 까지 끊을 수 있는 주사슬 결합이 없어 BDE를 낼 수 없습니다."
    elif out["bde_min_n"] > 1:
        out["note"] = (f"모노머에는 끊을 주사슬 단일결합이 없습니다 — "
                       f"BDE는 n={out['bde_min_n']} 이상에서만 산출됩니다.")
    else:
        out["note"] = "모노머부터 BDE가 산출됩니다."
    return out


def build_series(smiles: str, lengths=DEFAULT_LENGTHS) -> list[dict]:
    """길이별 올리고머 SMILES 목록 — 계산 제출용."""
    out = []
    for n in lengths:
        try:
            oligo = oligomerize(smiles, n) if n > 1 else smiles
        except (GeometryError, ValueError) as exc:
            out.append({"n": n, "error": str(exc)})
            continue
        out.append({"n": n, "smiles": oligo})
    return out
