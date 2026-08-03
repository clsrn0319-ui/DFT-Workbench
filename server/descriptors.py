"""확장 물성 기술자 — 개념 DFT 지표, MEP, 결합/흡착 에너지, TDDFT.

모두 PySCF 실계산이며, 근사 수준은 각 함수 docstring과 결과 노트에 명시한다.
"""

import numpy as np
from pyscf import gto

HARTREE2EV = 27.211386
HARTREE2KCAL = 627.5095
HARTREE2KJ = 2625.4996

# 표면 흡착 대용 클러스터 모델 — 활물질 표면의 화학적 환경을 모사하는 소형 대용체.
# 슬랩(주기) 계산이 아니므로 절대값 비교는 금지하고, 같은 모델끼리의 경향만 사용한다.
SURFACE_MODELS = [
    {"key": "graphite", "label": "Graphite",
     "smiles": "c1ccc2ccccc2c1", "desc": "흑연 π 표면 — 나프탈렌 조각 모델"},
    {"key": "si", "label": "Si",
     "smiles": "[SiH3][SiH3]", "desc": "실리콘 표면 — 수소 종단 Si–Si 사이트"},
    {"key": "ncm811", "label": "NCM811",
     "smiles": "[Li]O[Li]", "desc": "층상 산화물 양극 — 리튬 산화물 사이트 근사"},
    {"key": "lfp", "label": "LFP",
     "smiles": "[Li]OP(=O)(O[Li])O[Li]", "desc": "인산철 양극 — 인산 리튬 사이트 근사"},
]

# 원소별 반데르발스 반지름 (Å) — MEP 표면 격자 생성용
VDW = {"H": 1.20, "C": 1.70, "N": 1.55, "O": 1.52, "F": 1.47, "P": 1.80,
       "S": 1.80, "Cl": 1.75, "Br": 1.85, "I": 1.98, "Li": 1.82, "Si": 2.10}


def reactivity_indices(ip_ev, ea_ev):
    """개념 DFT 반응성 지표 (Parr–Pearson). IP·EA(eV)에서 유도되어 추가 계산 비용 없음.

    η = (IP − EA)/2 화학적 경도, μ = −(IP + EA)/2 화학적 퍼텐셜,
    ω = μ²/(2η) 친전자성 지수, S = 1/(2η) 화학적 연성.
    """
    eta = (ip_ev - ea_ev) / 2.0
    mu = -(ip_ev + ea_ev) / 2.0
    out = {"chemical_hardness_ev": round(eta, 3), "chemical_potential_ev": round(mu, 3)}
    if abs(eta) > 1e-6:
        out["electrophilicity_ev"] = round(mu * mu / (2 * eta), 3)
        out["softness_inv_ev"] = round(1.0 / (2 * eta), 3)
    return out


def _vdw_surface_points(mol, scale=1.4, density=1.6):
    """반데르발스 표면(스케일 배율) 위 격자점 생성 — MEP 극값 탐색용."""
    coords = mol.atom_coords(unit="Angstrom")
    radii = np.array([VDW.get(mol.atom_symbol(i), 1.7) * scale for i in range(mol.natm)])
    pts = []
    for i in range(mol.natm):
        n = max(24, int(density * 4 * np.pi * radii[i] ** 2))
        # 피보나치 구면 격자
        k = np.arange(n) + 0.5
        phi = np.arccos(1 - 2 * k / n)
        theta = np.pi * (1 + 5 ** 0.5) * k
        sph = np.stack([np.cos(theta) * np.sin(phi),
                        np.sin(theta) * np.sin(phi), np.cos(phi)], axis=1)
        cand = coords[i] + sph * radii[i]
        # 다른 원자 내부에 묻힌 점 제거
        d = np.linalg.norm(cand[:, None, :] - coords[None, :, :], axis=2)
        keep = np.all(d >= radii[None, :] - 1e-6, axis=1)
        pts.append(cand[keep])
    return np.vstack(pts) if pts else np.zeros((0, 3))


def mep_extremes(mf, mol):
    """반데르발스 표면 위 분자 정전기 퍼텐셜(MEP)의 최대·최소값과 위치.

    V(r) = Σ Z_A/|r−R_A| − ∫ρ(r')/|r−r'| — 양(+)은 친전자 부위(수소결합 주개·Li⁺ 배위 반대),
    음(−)은 친핵 부위(Li⁺ 배위 부위)를 가리킨다.
    """
    pts = _vdw_surface_points(mol)
    if len(pts) == 0:
        return None
    bohr = pts / 0.52917721092
    dm = mf.make_rdm1()
    if dm.ndim == 3:
        dm = dm[0] + dm[1]
    charges = mol.atom_charges()
    acoords = mol.atom_coords()  # Bohr
    v_nuc = np.array([np.sum(charges / np.linalg.norm(acoords - p, axis=1)) for p in bohr])
    v_ele = np.empty(len(bohr))
    for i, p in enumerate(bohr):
        with mol.with_rinv_origin(p):
            v_ele[i] = np.einsum("ij,ji->", mol.intor("int1e_rinv"), dm)
    v = v_nuc - v_ele
    imax, imin = int(np.argmax(v)), int(np.argmin(v))
    return {
        "mep_max_kcal": round(float(v[imax]) * HARTREE2KCAL, 1),
        "mep_min_kcal": round(float(v[imin]) * HARTREE2KCAL, 1),
        "mep_max_point": [round(float(c), 3) for c in pts[imax]],
        "mep_min_point": [round(float(c), 3) for c in pts[imin]],
    }


def tddft_lambda_max(mf, nstates=8):
    """TDDFT 수직 여기 → 진동자 세기가 가장 큰 전이의 λmax(nm)와 세기.

    기체상/암묵적 용매 수직 여기 근사이며 진동 구조·용매 재조직화는 미포함.
    """
    from pyscf import tddft as tddft_mod
    td = tddft_mod.TDDFT(mf)
    td.nstates = nstates
    td.kernel()
    e = np.asarray(td.e)
    f = np.asarray(td.oscillator_strength())
    if e.size == 0:
        return None
    bright = int(np.argmax(f))
    ev = float(e[bright]) * HARTREE2EV
    if ev <= 0:
        return None
    return {
        "uvvis_lambda_max_nm": round(1239.841984 / ev, 1),
        "uvvis_osc_strength": round(float(f[bright]), 4),
        "uvvis_excitation_ev": round(ev, 3),
    }


def density_cloud(mf, mol, max_points=3000, spacing=0.25, threshold=0.004, seed=0):
    """전자 밀도 ρ(r)를 격자에서 계산해 밀도 가중 표본점(전자구름)으로 반환한다.

    점의 밀집도가 곧 전자가 존재할 확률에 비례하도록 ρ를 가중치로 표본추출한다
    (등가면이 아니라 확률 구름 표현). 반환 좌표 단위는 Å.
    """
    dm = mf.make_rdm1()
    if dm.ndim == 3:
        dm = dm[0] + dm[1]
    coords = mol.atom_coords(unit="Angstrom")
    lo, hi = coords.min(0) - 2.4, coords.max(0) + 2.4
    axes = [np.arange(lo[i], hi[i] + spacing, spacing) for i in range(3)]
    n_grid = int(np.prod([len(a) for a in axes]))
    if n_grid > 400000:  # 대형 분자는 격자를 성기게
        spacing *= (n_grid / 400000.0) ** (1 / 3)
        axes = [np.arange(lo[i], hi[i] + spacing, spacing) for i in range(3)]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)

    rho_parts = []
    for start in range(0, len(grid), 20000):  # 메모리 보호를 위한 청크 처리
        chunk = grid[start:start + 20000] / 0.52917721092
        ao = mol.eval_gto("GTOval", chunk)
        rho_parts.append(np.einsum("pi,ij,pj->p", ao, dm, ao))
    rho = np.concatenate(rho_parts)

    mask = rho > threshold
    if not mask.any():
        return None
    pts, w = grid[mask], rho[mask]
    rng = np.random.default_rng(seed)
    n = min(max_points, len(pts))
    idx = rng.choice(len(pts), size=n, replace=False, p=w / w.sum())
    sel_pts, sel_rho = pts[idx], w[idx]
    return {
        "points": [[round(float(c), 2) for c in p] for p in sel_pts],
        "rho": [round(float(v), 4) for v in sel_rho],
        "rho_max": round(float(w.max()), 4),
        "spacing": round(float(spacing), 3),
    }


def li_cation_site(mol, mep):
    """MEP 최소점(가장 음전하인 부위)에서 바깥으로 Li⁺를 배치할 좌표.

    실제 Li⁺ 배위 부위는 전자가 풍부한 곳이므로 MEP 최소점이 물리적으로 타당한 시작점이다.
    """
    if not mep:
        return None
    p = np.array(mep["mep_min_point"])
    coords = mol.atom_coords(unit="Angstrom")
    d = np.linalg.norm(coords - p, axis=1)
    nearest = coords[int(np.argmin(d))]
    direction = p - nearest
    n = np.linalg.norm(direction)
    if n < 1e-6:
        direction = np.array([0.0, 0.0, 1.0])
        n = 1.0
    # 최근접 원자에서 약 2.0 Å 떨어진 지점 (전형적 Li–O/N 배위 거리)
    return nearest + direction / n * 2.0
