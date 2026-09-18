"""확장 물성 기술자 — 개념 DFT 지표, MEP, 결합/흡착 에너지, TDDFT.

모두 PySCF 실계산이며, 근사 수준은 각 함수 docstring과 결과 노트에 명시한다.
"""

import base64

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
        "uvvis_states": tddft_states(td, e, f),
    }


def tddft_states(td, e, f):
    """여기상태 목록 — 오비탈 비교 화면 «전이 분석» 표용.

    각 상태의 ΔE(eV)·파장(nm)·진동자 세기와 주 기여 궤도쌍(HOMO−i → LUMO+a, 가중치 %)을 남긴다.
    가중치는 X 진폭 제곱 기준(닫힌 껍질: Σ|X|² = ½ 정규화 → ×2).
    """
    out = []
    try:
        occ = np.asarray(td._scf.mo_occ)
        if occ.ndim == 2:
            occ = occ[0]
        nocc = int(np.sum(occ > 0))
    except Exception:  # noqa: BLE001
        nocc = None
    for k in range(len(e)):
        ev = float(e[k]) * HARTREE2EV
        row = {"state": k + 1, "energy_ev": round(ev, 3),
               "wavelength_nm": round(1239.841984 / ev, 1) if ev > 0 else None,
               "osc_strength": round(float(f[k]), 4), "transition": None, "weight_pct": None}
        try:
            x = td.xy[k][0]
            if isinstance(x, (tuple, list)):          # UKS: (α, β) — α 진폭만
                x = x[0]
            x = np.asarray(x)
            i, a = np.unravel_index(int(np.argmax(np.abs(x))), x.shape)
            no = x.shape[0] if nocc is None else nocc
            hi, la = no - 1 - int(i), int(a)
            row["transition"] = (("HOMO" if hi == 0 else f"HOMO−{hi}") + " → " + ("LUMO" if la == 0 else f"LUMO+{la}"))
            norm = float(np.sum(x ** 2)) or 1.0
            row["weight_pct"] = round(float(x[i, a] ** 2) / norm * 100.0, 1)
        except Exception:  # noqa: BLE001 — 진폭 해석 실패 시 에너지만
            pass
        out.append(row)
    return out


GRID_MAX_POINTS = 80000     # 저장 격자 상한 — float16 으로 약 160 KB, 등가면 삼각형 수도 이 안에서 결정된다


def _grid_axes(coords, spacing, margin=2.4, max_points=GRID_MAX_POINTS):
    """분자 주변 상자를 덮는 규칙 격자 축 — 점 수가 상한을 넘으면 간격을 키운다."""
    lo, hi = coords.min(0) - margin, coords.max(0) + margin
    axes = [np.arange(lo[i], hi[i] + spacing, spacing) for i in range(3)]
    n_grid = int(np.prod([len(a) for a in axes]))
    if n_grid > max_points:
        spacing *= (n_grid / float(max_points)) ** (1 / 3)
        axes = [np.arange(lo[i], hi[i] + spacing, spacing) for i in range(3)]
    return axes, float(spacing)


def encode_grid(axes, values):
    """격자 값(C 순서, shape = len(axes[0])×…)을 float16 base64 로 — 뷰어의 marching tetrahedra 입력.

    origin·spacing 단위 Å, 값은 ψ(a.u.^-3/2) 또는 ρ(e/bohr³). dtype 'f16' little-endian.
    """
    arr = np.asarray(values, dtype=np.float32).reshape([len(a) for a in axes])
    return {"origin": [round(float(a[0]), 4) for a in axes],
            "spacing": [round(float(a[1] - a[0]), 5) if len(a) > 1 else 0.0 for a in axes],
            "shape": [int(len(a)) for a in axes], "dtype": "f16",
            "abs_max": round(float(np.abs(arr).max()), 5),
            "data": base64.b64encode(arr.astype("<f2").tobytes()).decode("ascii")}


def decode_grid(g):
    """encode_grid 의 역 — 테스트·검증용."""
    raw = base64.b64decode(g["data"])
    return np.frombuffer(raw, dtype="<f2").astype(np.float32).reshape(g["shape"])


def orbital_cloud(mf, mol, which="homo", max_points=2500, spacing=0.3, threshold=0.02, seed=0):
    """분자 궤도 ψ(r)를 격자에서 계산해 |ψ|² 가중 표본점(위상 부호 포함)으로 반환한다 — 결과 화면의
    HOMO/LUMO 3D 표현용. 좌표 단위 Å, value 는 ψ 값(부호가 lobe 색).

    등가면(marching cubes) 대신 확률 구름 표현을 쓰는 이유는 density_cloud 와 같다 — 저장 용량이
    작고(점 2,500개) 뷰어가 이미 점 구름을 그리기 때문이다. 열린 껍질(UKS)은 α 궤도를 쓴다.
    """
    coeff, occ, energy = _alpha_mos(mf)
    occ_idx = np.where(occ > 0)[0]
    if not len(occ_idx):
        return None
    homo = int(occ_idx.max())
    idx = homo + ORBITAL_OFFSETS[which]
    if idx < 0 or idx >= coeff.shape[1]:
        return None
    c = coeff[:, idx]
    coords = mol.atom_coords(unit="Angstrom")
    axes, spacing = _grid_axes(coords, spacing)
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)
    parts = []
    for start in range(0, len(grid), 20000):
        chunk = grid[start:start + 20000] / 0.52917721092
        parts.append(mol.eval_gto("GTOval", chunk) @ c)
    psi = np.concatenate(parts)
    mask = np.abs(psi) > threshold
    if not mask.any():
        return None
    pts, val = grid[mask], psi[mask]
    w = val ** 2
    rng = np.random.default_rng(seed)
    n = min(max_points, len(pts))
    sel = rng.choice(len(pts), size=n, replace=False, p=w / w.sum())
    return {
        "points": [[round(float(x), 2) for x in p] for p in pts[sel]],
        "value": [round(float(v), 4) for v in val[sel]],
        "abs_max": round(float(np.abs(val).max()), 4),
        "index": idx, "which": which, "label": ORBITAL_LABELS[which],
        "energy_ev": round(float(energy[idx]) * 27.211386, 3),
        "occ": round(float(occ[idx]), 3),
        "spacing": round(float(spacing), 3),
        "contributions": orbital_contributions(mf, mol, idx),
        # 등가면용 전체 격자 — 엔진이 떼어내 data/grids/<job>.json 에 따로 저장한다
        "grid": encode_grid(axes, psi),
    }


# 궤도 키 → HOMO 기준 오프셋 · 표시 이름 (결과 화면 Geometry 탭 · 오비탈 비교 화면)
ORBITAL_OFFSETS = {"homo-1": -1, "homo": 0, "lumo": 1, "lumo+1": 2}
ORBITAL_LABELS = {"homo-1": "HOMO−1", "homo": "HOMO", "lumo": "LUMO", "lumo+1": "LUMO+1"}


def _alpha_mos(mf):
    """(coeff, occ, energy) — 열린 껍질(UKS)은 α 궤도."""
    coeff, occ, energy = mf.mo_coeff, mf.mo_occ, mf.mo_energy
    if getattr(coeff, "ndim", 2) == 3:          # UKS: (alpha, beta)
        coeff, occ, energy = coeff[0], occ[0], energy[0]
    return np.asarray(coeff), np.asarray(occ), np.asarray(energy)


def orbital_contributions(mf, mol, idx, top=5):
    """궤도 idx 의 원자별 기여도(%) — Löwdin population (S^½ C)_μ² 을 원자별로 합산.

    기획서(오비탈 비교 3.3)가 요구하는 «기여도의 population 정의 명시»에 맞춰 method 를 함께 남긴다.
    """
    try:
        coeff, _, _ = _alpha_mos(mf)
        c = coeff[:, idx]
        S = np.asarray(mf.get_ovlp())
        w, v = np.linalg.eigh(S)
        s_half = (v * np.sqrt(np.clip(w, 1e-12, None))) @ v.T
        pop = (s_half @ c) ** 2
        pop = pop / max(float(pop.sum()), 1e-12) * 100.0
        slices = mol.aoslice_by_atom()
        per_atom = []
        for ia in range(mol.natm):
            p0, p1 = int(slices[ia][2]), int(slices[ia][3])
            per_atom.append((f"{mol.atom_symbol(ia)}{ia + 1}", float(pop[p0:p1].sum())))
        per_atom.sort(key=lambda t: -t[1])
        return {"method": "Löwdin", "atoms": [{"atom": a, "pct": round(p, 1)} for a, p in per_atom[:top]]}
    except Exception:  # noqa: BLE001 — 시각화용 부가 데이터
        return None


def orbital_clouds(mf, mol):
    """HOMO−1 · HOMO · LUMO · LUMO+1 네 궤도의 점 구름. 없거나 실패한 궤도는 None."""
    out = {}
    for which in ORBITAL_OFFSETS:
        try:
            out[which] = orbital_cloud(mf, mol, which)
        except Exception:  # noqa: BLE001 — 시각화용 부가 데이터
            out[which] = None
    return out


def orbital_levels(mf, mol=None, n_below=5, n_above=5):
    """에너지 준위도용 궤도 목록 — HOMO−n_below … LUMO+n_above (index · 이름 · eV · 점유수)."""
    try:
        coeff, occ, energy = _alpha_mos(mf)
        occ_idx = np.where(occ > 0)[0]
        if not len(occ_idx):
            return None
        homo = int(occ_idx.max())
        levels = []
        for idx in range(max(0, homo - n_below), min(len(energy), homo + 1 + n_above)):
            off = idx - homo
            label = ("HOMO" if off == 0 else f"HOMO−{-off}") if off <= 0 else ("LUMO" if off == 1 else f"LUMO+{off - 1}")
            levels.append({"index": idx, "label": label, "energy_ev": round(float(energy[idx]) * 27.211386, 3),
                           "occ": round(float(occ[idx]), 3)})
        spin = "alpha" if getattr(mf.mo_coeff, "ndim", 2) == 3 else "restricted"
        return {"homo_index": homo, "spin": spin, "levels": levels}
    except Exception:  # noqa: BLE001
        return None


def density_cloud(mf, mol, max_points=3000, spacing=0.25, threshold=0.004, seed=0):
    """전자 밀도 ρ(r)를 격자에서 계산해 밀도 가중 표본점(전자구름)으로 반환한다.

    점의 밀집도가 곧 전자가 존재할 확률에 비례하도록 ρ를 가중치로 표본추출한다
    (등가면이 아니라 확률 구름 표현). 반환 좌표 단위는 Å.
    """
    dm = mf.make_rdm1()
    if dm.ndim == 3:
        dm = dm[0] + dm[1]
    coords = mol.atom_coords(unit="Angstrom")
    axes, spacing = _grid_axes(coords, spacing)
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
        "grid": encode_grid(axes, rho),
    }


def split_grids(orbital_clouds, density_cloud):
    """점 구름 dict 에서 격자를 떼어낸다 — jobs.json 을 키우지 않도록 별도 파일로 보낼 몫."""
    grids = {}
    for k, v in (orbital_clouds or {}).items():
        if isinstance(v, dict) and v.get("grid"):
            grids[k] = v.pop("grid")
    if isinstance(density_cloud, dict) and density_cloud.get("grid"):
        grids["density"] = density_cloud.pop("grid")
    return grids


def breakable_bonds(smiles: str, max_bonds: int = 5):
    """균일 분해(homolysis) 대상 단일 결합 목록 — 고리 밖 무거운 원자 사이 결합.

    각 항목은 (라벨, 조각1 원자 인덱스, 조각2 원자 인덱스). 인덱스는 수소를 붙인
    (AddHs) 원자 순서를 따르며, 이는 3D 좌표 생성 순서와 동일하다.
    """
    from rdkit import Chem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return []
    mol = Chem.AddHs(mol)
    out = []
    for bond in mol.GetBonds():
        if bond.GetBondType() != Chem.BondType.SINGLE or bond.IsInRing():
            continue
        a, b = bond.GetBeginAtom(), bond.GetEndAtom()
        if a.GetSymbol() == "H" or b.GetSymbol() == "H":
            continue
        emol = Chem.RWMol(mol)
        emol.RemoveBond(a.GetIdx(), b.GetIdx())
        frags = Chem.GetMolFrags(emol.GetMol(), asMols=False)
        if len(frags) != 2:
            continue  # 고리 아님에도 분리되지 않으면 건너뜀
        out.append((f"{a.GetSymbol()}{a.GetIdx()}–{b.GetSymbol()}{b.GetIdx()}",
                    list(frags[0]), list(frags[1])))
        if len(out) >= max_bonds:
            break
    return out


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
