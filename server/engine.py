"""PySCF 기반 실제 DFT 계산 엔진.

계산 흐름 (run_job):
  1. RDKit conformer 탐색 → 역장 상위 후보 → (표준↑) DFT 단일점 재순위화
  2. (옵션) DFT 기체상 구조 최적화 — geomeTRIC 우선, 없으면 pyberny
  3. 최종 단일점 SCF — SMD implicit 용매화(환경 설정) + D3(BJ) 분산 보정
  4. 기술자(descriptor) 추출: 전자에너지, HOMO/LUMO/갭, 쌍극자, Mulliken 전하
  5. (옵션) 진동수 계산 → ZPE·엔탈피·엔트로피·깁스 보정 (설정 온도 반영)
  6. 용매 환경이면 동일 구조 기체상 SCF로 용매화 에너지 산출
  7. (옵션) 산화/환원 전위:
       - 수직: 중성 구조에서 이온 ΔSCF
       - 단열: 이온 상태 구조 재최적화 후 ΔSCF (+열보정 시 ΔG 기반 전위)

환경 설정의 실제 반영:
  - 용매: SMD 파라미터(유전상수·굴절률·표면장력·H-결합 파라미터)로 해밀토니안에 반영
  - 온도: 열역학 보정(엔탈피·엔트로피·깁스) 산출에 사용. 열보정 생략 시 기록용
  - 분위기: 기록용 메타데이터 (단일 분자 DFT는 대기를 명시적으로 모델링하지 않음)
"""

import math
import time
import traceback

import numpy as np
from pyscf import gto, dft, scf
from pyscf.hessian import thermo as pyscf_thermo
from pyscf.solvent import smd

from . import binder as binder_mod
from . import descriptors as desc_mod
from . import presets
from . import protocol as protocol_mod
from . import thermo as thermo_mod
from .geometry import (smiles_to_conformers, build_cluster,
                       build_cluster_from_atoms, atoms_to_xyz_block)

HARTREE2KJ = 2625.4996

MAX_CLUSTER_OPT_ATOMS = 35  # 이보다 큰 클러스터는 DFT 최적화를 자동 생략 (MMFF 구조 사용)
MAX_INTERACTION_FRAGMENTS = 6  # 상호작용 에너지 분해를 수행할 최대 분자 수

HARTREE2EV = presets.HARTREE2EV
HARTREE2KCAL = presets.HARTREE2KCAL


def _register_custom_solvents():
    """전해액 용매의 SMD 파라미터를 PySCF solvent DB에 등록."""
    for sol in presets.SOLVENTS:
        if sol.get("smd"):
            smd.solvent_db[sol["modelKey"]] = list(sol["smd"])


_register_custom_solvents()


class CancelledError(Exception):
    pass


def _solvent_key(settings):
    if settings["envType"] == "진공·기체":
        return None
    custom = settings.get("customMixedSolvent")
    if custom:
        # 용매 라이브러리의 사용자 혼합 용매: 성분 SMD 파라미터의 부피 가중 평균으로 등록
        by_abbr = {s["abbr"]: s for s in presets.SOLVENTS if s["kind"] == "single"}
        total = sum(c["ratio"] for c in custom["components"])
        vec = [0.0] * 8
        for c in custom["components"]:
            sol = by_abbr.get(c["abbr"])
            if sol is None:
                raise ValueError(f"혼합 성분 {c['abbr']}의 SMD 파라미터가 없습니다")
            params = sol["smd"] if sol.get("smd") else presets.WATER_SMD_FOR_MIX
            w = c["ratio"] / total
            vec = [v + w * p for v, p in zip(vec, params)]
        key = "smd:mix-" + "-".join(
            f"{c['abbr']}{c['ratio']:g}" for c in custom["components"]).lower()
        smd.solvent_db[key] = vec
        return key
    if not settings.get("solventId"):
        return None
    sol = presets.SOLVENTS_BY_ID.get(settings["solventId"])
    if sol is None:
        raise ValueError(f"알 수 없는 용매 id: {settings['solventId']}")
    return sol.get("builtin_key") or sol["modelKey"]


def _no_reference(settings):
    ref = settings.get("referenceElectrode")
    return ref in (None, "", "없음")


def _resolve_params(settings):
    acc = presets.ACCURACY[settings["accuracy"]]
    exp = settings["expert"]
    functional = exp.get("functional") or "PBE0-D3(BJ)"
    if functional not in presets.FUNCTIONALS:
        raise ValueError(f"지원하지 않는 범함수: {functional}")
    xc, disp = presets.FUNCTIONALS[functional]
    do_opt = acc["do_opt"] if exp.get("optimizeGeometry") is None else bool(exp["optimizeGeometry"])
    do_thermo = acc["do_thermo"] if exp.get("thermochemistry") is None else bool(exp["thermochemistry"])
    # 단열 전위는 구조 최적화가 켜져 있을 때 기본 활성 (이온 상태 재최적화 필요)
    redox_adiabatic = do_opt if exp.get("redoxAdiabatic") is None else bool(exp["redoxAdiabatic"])
    return {
        "n_conf": exp.get("nConformers") or acc["n_conf"],
        "n_dft_rank": acc["n_dft_rank"],
        "do_opt": do_opt,
        "do_thermo": do_thermo,
        "redox_adiabatic": redox_adiabatic,
        # 수직 전위의 비평형 용매화(동결 용매장): 용매 존재 시 기본 활성
        "noneq": True if exp.get("nonequilibriumSolvation") is None
                 else bool(exp["nonequilibriumSolvation"]),
        "ensemble": acc.get("ensemble", False) if exp.get("boltzmannEnsemble") is None
                    else bool(exp["boltzmannEnsemble"]),
        "freq_scale": (float(exp["freqScale"]) if exp.get("freqScale")
                       else presets.FREQ_SCALE.get(functional, 1.0)),
        "opt_in_solvent": bool(exp.get("optimizeInSolvent")),
        # BDE 라디칼 조각 재최적화 (기본 활성 — 고정 구조는 BDE를 크게 과대평가)
        "bde_relax": True if exp.get("bdeRelaxFragments") is None
                     else bool(exp["bdeRelaxFragments"]),
        # BDE의 ZPE·298 K 열보정 (열보정이 켜져 있을 때만 유효)
        "bde_thermal": True if exp.get("bdeThermalCorrection") is None
                       else bool(exp["bdeThermalCorrection"]),
        "basis_opt": acc["basis_opt"],
        "basis_sp": exp.get("basis") or acc["basis_sp"],
        # 음이온 전용 diffuse 기저 (v2.0 P0-1). 전문가 설정이 우선하고,
        # 없으면 정확도 프리셋의 기본값을 쓴다.
        "basis_anion": exp.get("basisAnion") or acc.get("basis_anion"),
        # 준조화 자유에너지 보정 — 열보정을 하는 프리셋에서 기본 활성
        "qrrho": True if exp.get("qrrho") is None else bool(exp["qrrho"]),
        "thermo_model": "qRRHO" if (exp.get("qrrho") is not False) else "RRHO",
        "functional": functional,
        "xc": xc,
        "disp": disp,
        "charge": int(exp.get("charge") or 0),
        "multiplicity": int(exp.get("multiplicity") or 1),
        "scf_tol": float(exp.get("scfTol") or 1e-8),
    }


def _build_mol(atoms, basis, charge, multiplicity):
    atom_spec = [(sym, (x, y, z)) for sym, x, y, z in atoms]
    return gto.M(atom=atom_spec, basis=basis, charge=charge,
                 spin=multiplicity - 1, unit="Angstrom", verbose=0)


def _make_mf(mol, xc, disp, solvent_key, scf_tol):
    if xc == "hf":
        mf = scf.RHF(mol) if mol.spin == 0 else scf.UHF(mol)
    else:
        mf = dft.RKS(mol, xc=xc) if mol.spin == 0 else dft.UKS(mol, xc=xc)
    mf = mf.density_fit()
    mf.conv_tol = scf_tol
    if disp:
        try:
            mf.disp = disp
        except Exception:
            pass  # pyscf-dispersion 미설치 시 분산 보정 없이 진행
    if solvent_key:
        mf = mf.SMD()
        mf.with_solvent.solvent = solvent_key
    return mf


def _atomic_charges(mf, mol):
    """원자 전하 — meta-Löwdin 을 주값으로, Mulliken 은 진단용으로 함께 낸다.

    Mulliken population 은 기저 집합에 민감해서 diffuse 기저를 쓰면 값이 크게
    흔들린다 (v2.0 P0-7). meta-Löwdin 은 직교화된 원자 궤도에 사영하므로
    기저 의존성이 훨씬 낮다. Hirshfeld/CM5 는 PySCF 에 내장되어 있지 않아
    이번 개정에서는 meta-Löwdin 을 대안으로 쓴다.
    """
    out = {}
    try:
        _, mulliken = mf.mulliken_pop(verbose=0)
        out["mulliken"] = [round(float(c), 3) for c in mulliken]
    except Exception:  # noqa: BLE001 — 전하 분석 실패가 계산 전체를 막지 않는다
        out["mulliken"] = None
    try:
        _, meta = mf.mulliken_meta(verbose=0)
        out["meta_lowdin"] = [round(float(c), 3) for c in meta]
    except Exception:  # noqa: BLE001
        out["meta_lowdin"] = None
    out["primary"] = "meta_lowdin" if out["meta_lowdin"] else "mulliken"
    if out["mulliken"] and out["meta_lowdin"]:
        out["max_abs_diff"] = round(
            max(abs(a - b) for a, b in zip(out["mulliken"], out["meta_lowdin"])), 3)
    return out


def _run_scf(mf, label, log, dm0=None):
    """SCF 실행. 미수렴 시 damping·level shift·2차 수렴(SOSCF)으로 단계적 복구를 시도한다."""
    t0 = time.time()
    energy = mf.kernel(dm0) if dm0 is not None else mf.kernel()
    if not mf.converged:
        dm_last = mf.make_rdm1()
        # 1) 진동 억제: damping + level shift + 사이클 증가
        log(f"{label} SCF 미수렴 — damping·level shift로 재시도")
        mf.max_cycle = max(mf.max_cycle, 200)
        mf.damp = 0.4
        mf.level_shift = 0.4
        energy = mf.kernel(dm_last)
        if not mf.converged:
            # 2) level shift를 낮춰 해에 접근
            log(f"{label} 재시도 2 — level shift 완화")
            mf.damp = 0.1
            mf.level_shift = 0.1
            energy = mf.kernel(mf.make_rdm1())
        if not mf.converged:
            # 3) 2차 수렴(뉴턴) — 초기 밀도는 직전 결과 사용
            log(f"{label} 재시도 3 — 2차 수렴(SOSCF)")
            try:
                mf_n = mf.newton()
                mf_n.max_cycle = 100
                energy = mf_n.kernel(mf.make_rdm1())
                if mf_n.converged:
                    mf.converged = True
                    mf.mo_coeff, mf.mo_energy, mf.mo_occ = (
                        mf_n.mo_coeff, mf_n.mo_energy, mf_n.mo_occ)
                    mf.e_tot = energy
            except Exception as exc:  # noqa: BLE001 — 마지막 복구 시도
                log(f"{label} SOSCF 실패: {exc}")
    if not mf.converged:
        raise RuntimeError(f"{label} SCF 미수렴 — damping·level shift·SOSCF 모두 실패")
    log(f"{label} SCF 수렴 — E = {energy:.6f} Ha ({time.time() - t0:.1f}s)")
    return float(energy)


def _counterpoise_energy(all_atoms, keep_slice, basis, charge, mult,
                         xc, disp, solvent_key, scf_tol, label, log):
    """조각 에너지를 전체 클러스터 basis(고스트 원자 포함)에서 계산 — BSSE counterpoise 보정."""
    spec = []
    for i, (sym, x, y, z) in enumerate(all_atoms):
        inside = keep_slice[0] <= i < keep_slice[1]
        spec.append((sym if inside else f"ghost:{sym}", (x, y, z)))
    mol_g = gto.M(atom=spec, basis=basis, charge=charge, spin=mult - 1,
                  unit="Angstrom", verbose=0)
    mf_g = _make_mf(mol_g, xc, disp, solvent_key, scf_tol)
    return _run_scf(mf_g, label, log)


def _provenance(params, settings, solvent_key):
    """재현성을 위한 계산 환경·설정 전체 기록."""
    import platform
    import pyscf
    import rdkit
    try:
        from pyscf.geomopt import geometric_solver  # noqa: F401
        optimizer = "geomeTRIC"
    except ImportError:
        optimizer = "pyberny"
    return {
        "engine": f"PySCF {pyscf.__version__}",
        "rdkit": rdkit.__version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "geometry_optimizer": optimizer,
        "functional": params["functional"],
        "xc_pyscf": params["xc"],
        "dispersion": params["disp"] or "없음",
        "basis_optimization": params["basis_opt"],
        "basis_singlepoint": params["basis_sp"],
        "density_fitting": "on (기본 auxbasis)",
        "scf_conv_tol": params["scf_tol"],
        "solvent_model": f"SMD({solvent_key})" if solvent_key else "vacuum",
        "optimized_in_solvent": params["opt_in_solvent"] and solvent_key is not None,
        "charge": params["charge"],
        "multiplicity": params["multiplicity"],
        "n_conformers_searched": params["n_conf"],
        "n_conformers_dft_ranked": params["n_dft_rank"],
        "boltzmann_ensemble": params["ensemble"],
        "thermochemistry": params["do_thermo"],
        "freq_scale_factor": params["freq_scale"],
        "nonequilibrium_solvation": params["noneq"],
        "bde_fragment_relaxation": params["bde_relax"],
        "bde_thermal_correction": params["bde_thermal"],
        "redox_adiabatic": params["redox_adiabatic"],
        "temperature_k": settings.get("temperature"),
        "pressure_pa": 101325,
        "accuracy_preset": settings.get("accuracy"),
        "purpose": settings.get("purpose"),
    }


def _freeze_solvent_from(mf_ion, dm_neutral):
    """이온 계산의 용매 반응장을 중성 분자 밀도로 고정 (비평형 수직 근사)."""
    sv = mf_ion.with_solvent
    sv.build()
    sv.e, sv.v = sv.kernel(dm_neutral)
    sv.frozen = True


def _optimize_geometry(mf, log, label=""):
    """DFT 기체상 구조 최적화. geomeTRIC → pyberny 순으로 시도."""
    try:
        from pyscf.geomopt.geometric_solver import optimize as geo_opt
        log(f"구조 최적화 시작{label} (geomeTRIC)")
        return geo_opt(mf, maxsteps=100)
    except ImportError:
        from pyscf.geomopt.berny_solver import optimize as berny_opt
        log(f"구조 최적화 시작{label} (pyberny)")
        return berny_opt(mf, maxsteps=100)


def _mol_to_atoms(mol):
    coords = mol.atom_coords(unit="Angstrom")
    return [(mol.atom_symbol(i), *coords[i]) for i in range(mol.natm)]


def _optimize_state(atoms, params, charge, multiplicity, log, label="", solvent_key=None):
    """구조 최적화 후 좌표를 반환. solvent_key가 있으면 용매장(SMD) 안에서 최적화한다."""
    mol = _build_mol(atoms, params["basis_opt"], charge, multiplicity)
    mf = _make_mf(mol, params["xc"], params["disp"], solvent_key, params["scf_tol"])
    mol_opt = _optimize_geometry(mf, log, label)
    return _mol_to_atoms(mol_opt)


def _thermo_correction(atoms, params, charge, multiplicity, temperature, log, label=""):
    """기체상 진동수 계산 → 열역학 보정.

    최적화 수준(basis_opt)에서 Hessian을 계산하고, 설정 온도에서
    ZPE·엔탈피·엔트로피·깁스 보정을 산출한다 (강체회전·조화진동자·이상기체 근사).
    """
    t0 = time.time()
    mol = _build_mol(atoms, params["basis_opt"], charge, multiplicity)
    mf = _make_mf(mol, params["xc"], params["disp"], None, params["scf_tol"])
    e_elec = mf.kernel()
    if not mf.converged:
        raise RuntimeError(f"열보정{label} SCF 미수렴")
    hess = mf.Hessian().kernel()
    freq_info = pyscf_thermo.harmonic_analysis(mol, hess)
    freqs = freq_info["freq_wavenumber"]
    if np.iscomplexobj(freqs):
        n_imag = int(np.sum(np.abs(freqs.imag) > 1.0))
        freqs_real = freqs.real
    else:
        n_imag = int(np.sum(freqs < 0))
        freqs_real = freqs
    scale = params.get("freq_scale", 1.0)
    th = pyscf_thermo.thermo(mf, freq_info["freq_au"] * scale,
                             temperature=temperature, pressure=101325)
    g_corr = float(th["G_tot"][0]) - float(e_elec)
    result = {
        "norm_mode": np.asarray(freq_info["norm_mode"]),
        "freqs_cm": freqs_real,
        "zpe_hartree": float(th["ZPE"][0]),
        "g_corr_hartree": g_corr,
        "h_corr_hartree": float(th["H_tot"][0]) - float(e_elec),
        "entropy_hartree_per_k": float(th["S_tot"][0]),
        "n_imaginary": n_imag,
        "lowest_freq_cm": float(np.min(freqs_real)),
    }
    # 준조화 보정 — 유연한 사슬의 저진동수 비틀림 모드에서 조화 근사가 엔트로피를
    # 크게 과대평가한다 (v2.0 P0-3). 조화 값도 나란히 남긴다.
    result = thermo_mod.apply(result, temperature,
                              enabled=params.get("qrrho", True))
    q = result.get("qrrho")
    log(f"진동수 계산{label} 완료 — 허수 진동수 {n_imag}개, "
        f"ZPE {result['zpe_hartree'] * HARTREE2KCAL:.2f} kcal/mol ({time.time() - t0:.1f}s)")
    if q:
        log(f"  qRRHO 보정{label} — 저진동수 {q['n_low_freq']}개(<{q['cutoff_cm']:.0f} cm⁻¹), "
            f"ΔG {q['delta_g_kcal']:+.2f} kcal/mol")
    return result


def _atomic_thermo():
    """단원자 조각의 열보정 — 진동 없음(ZPE=0), 병진 3/2·RT + pV(RT) = 5/2·RT."""
    R_HARTREE_PER_K = 8.31446261815324 / (HARTREE2KJ * 1000)
    return lambda temperature: {
        "zpe_hartree": 0.0,
        "h_corr_hartree": 2.5 * R_HARTREE_PER_K * temperature,
        "n_imaginary": 0,
    }


_atomic_thermo_fn = _atomic_thermo()


def _frontier_orbitals(mf):
    """HOMO/LUMO (eV). 개열각(UKS)은 알파/베타 통합 스펙트럼 기준."""
    mo_e = np.asarray(mf.mo_energy)
    mo_occ = np.asarray(mf.mo_occ)
    if mo_e.ndim == 2:  # UKS/UHF
        mo_e = np.concatenate(mo_e)
        mo_occ = np.concatenate(mo_occ)
    homo = float(mo_e[mo_occ > 0].max() * HARTREE2EV)
    virtuals = mo_e[mo_occ == 0]
    lumo = float(virtuals.min() * HARTREE2EV) if virtuals.size else None
    return homo, lumo


def run_job(job, update, is_cancelled=lambda: False):
    """job(dict)을 실제로 계산한다. update(patch)로 진행 상황을 반영한다."""
    log_lines = list(job.get("logs") or [])

    def log(msg):
        log_lines.append(msg)
        update({"logs": list(log_lines)})

    def stage(name, progress):
        if is_cancelled():
            raise CancelledError()
        update({"stage": name, "progress": progress})
        log(f"[{name}]")

    t_start = time.time()
    try:
        settings = job["settings"]
        params = _resolve_params(settings)
        solvent_key = _solvent_key(settings)
        smiles = job["material"]["smiles"]
        temperature = float(settings.get("temperature") or 298.15)
        purpose = settings.get("purpose", "")
        # 바인더 스크리닝은 지문 전체(접착·응집·BDE)와 전위를 모두 필요로 한다
        want_binder = "바인더" in purpose
        want_fingerprint = "지문" in purpose or want_binder
        want_redox = "전위" in purpose or want_fingerprint  # 반응성 지표에 IP/EA 필요
        fingerprint_structures = {}
        closed_shell = params["multiplicity"] == 1
        explicit = [(m["smiles"], m["count"]) for m in (settings.get("explicitMolecules") or [])]
        explicit_label = " + ".join(
            f"{m['count']}× {m.get('name') or m['smiles']}"
            for m in (settings.get("explicitMolecules") or []))
        fragments = None

        # 업로드된 3D 구조 — 초기 구조로 쓰고 conformer 탐색을 건너뛴다.
        # «구조 재탐색»이 켜져 있으면 좌표를 버리고 기존 경로로 돌아간다.
        user_geom = (job["material"].get("geometry") or {})
        user_atoms = [tuple(a) for a in (user_geom.get("atoms") or [])] or None
        if user_atoms and user_geom.get("rescan"):
            log("업로드 3D 구조가 있지만 «구조 재탐색»이 켜져 있어 conformer 탐색부터 다시 수행합니다")
            user_atoms = None
        if user_atoms and explicit:
            log("명시적 주변 분자 클러스터 계산은 배치 알고리즘이 좌표를 다시 만들므로 "
                "업로드 3D 구조를 사용하지 않습니다")
            user_atoms = None

        if explicit:
            # 1') 명시적 주변 분자 클러스터 생성 (cluster-continuum)
            stage("클러스터 생성 (명시적 주변 분자 배치)", 5)
            atoms, fragments, cl_info = build_cluster(
                smiles, explicit, n_conformers=params["n_conf"])
            geom_info = {"n_conformers": params["n_conf"],
                         "forcefield": cl_info["forcefield"],
                         "n_molecules": cl_info["n_molecules"]}
            log(f"클러스터 구성: 용질 + {explicit_label} — 총 {len(atoms)}원자, "
                f"{cl_info['forcefield']} 이완 완료")
            # 클러스터에서는 열보정(거대 Hessian)·단열 전위(이온 클러스터 재최적화) 미지원
            if params["do_thermo"]:
                params["do_thermo"] = False
                log("클러스터 계산에서는 열역학 보정을 생략합니다")
            if params["redox_adiabatic"]:
                params["redox_adiabatic"] = False
                if want_redox:
                    log("클러스터 전위는 수직 ΔSCF로 계산합니다 (단열 미지원)")
            if params["do_opt"] and len(atoms) > MAX_CLUSTER_OPT_ATOMS:
                params["do_opt"] = False
                log(f"클러스터 {len(atoms)}원자 > {MAX_CLUSTER_OPT_ATOMS} — "
                    f"DFT 최적화 생략, {cl_info['forcefield']} 구조 단일점 수행")
        elif user_atoms:
            # 1'') 사용자 제공 3D 구조 — conformer 탐색 생략, 그 좌표에서 출발
            stage("사용자 제공 3D 구조 사용", 3)
            atoms = user_atoms
            geom_info = {"n_conformers": 1, "forcefield": "사용자 제공",
                         "ff_energy": None}
            ranked = [(0.0, atoms)]
            conformer_populations = [{"rel_e_kcal": 0.0, "population_pct": 100.0}]
            significant = [0]
            kT_kcal = 1.98720425e-3 * temperature
            log(f"업로드 3D 구조({user_geom.get('source') or '3D 파일'} · {len(atoms)}원자)를 "
                "초기 구조로 사용 — conformer 탐색 생략"
                + ("" if params["do_opt"] else
                   " (이 프리셋은 DFT 최적화도 없어 업로드 좌표 그대로 단일점을 계산합니다)"))
        else:
            # 1) conformer 탐색 (+ DFT 재순위화)
            stage("구조 생성 (conformer 탐색)", 3)
            candidates, geom_info = smiles_to_conformers(
                smiles, n_conformers=params["n_conf"], top_k=params["n_dft_rank"])
            log(f"conformer {geom_info['n_conformers']}개 생성, {geom_info['forcefield']} "
                f"상위 {len(candidates)}개 후보 선택")
            if len(candidates) > 1:
                stage("conformer DFT 재순위화", 8)
                ranked = []
                for i, (cand_atoms, ff_e) in enumerate(candidates):
                    mol_c = _build_mol(cand_atoms, params["basis_opt"],
                                       params["charge"], params["multiplicity"])
                    mf_c = _make_mf(mol_c, params["xc"], params["disp"], None, params["scf_tol"])
                    e_c = _run_scf(mf_c, f"conformer {i + 1}/{len(candidates)}", log)
                    ranked.append((e_c, cand_atoms))
                ranked.sort(key=lambda t: t[0])
                spread = (ranked[-1][0] - ranked[0][0]) * HARTREE2KCAL
                log(f"DFT 재순위화 완료 — 후보 간 에너지 폭 {spread:.2f} kcal/mol")
            else:
                ranked = [(0.0, candidates[0][0])]
            atoms = ranked[0][1]
            # Boltzmann 가중치 (설정 온도, 재순위 전자에너지 기준)
            kT_kcal = 1.98720425e-3 * temperature
            e_min = ranked[0][0]
            rel_kcal = [(e - e_min) * HARTREE2KCAL for e, _ in ranked]
            ws = [math.exp(-dk / kT_kcal) for dk in rel_kcal]
            z = sum(ws)
            pops = [w / z for w in ws]
            conformer_populations = [
                {"rel_e_kcal": round(dk, 2), "population_pct": round(100 * p, 1)}
                for dk, p in zip(rel_kcal, pops)]
            significant = [i for i, p in enumerate(pops) if p >= 0.05][:4]

        def final_singlepoint(at, label):
            """(옵션 최적화 후) 환경 반영 최종 단일점 → 구조·mf·에너지·프런티어·쌍극자."""
            if params["do_opt"]:
                at = _optimize_state(at, params, params["charge"], params["multiplicity"], log,
                                     solvent_key=solvent_key if params["opt_in_solvent"] else None)
            mol_ = _build_mol(at, params["basis_sp"], params["charge"], params["multiplicity"])
            mf_ = _make_mf(mol_, params["xc"], params["disp"], solvent_key, params["scf_tol"])
            e_ = _run_scf(mf_, label, log)
            homo_, lumo_ = _frontier_orbitals(mf_)
            dip_ = float(np.linalg.norm(mf_.dip_moment(unit="Debye", verbose=0)))
            return at, mol_, mf_, e_, homo_, lumo_, dip_

        ensemble_avg = None
        if not explicit and params["ensemble"] and len(significant) > 1:
            # 2~3') Boltzmann 앙상블: 유의(≥5%) conformer 각각 최적화·단일점 후 가중 평균
            stage(f"Boltzmann 앙상블 ({len(significant)}개 conformer)", 18)
            members = []
            for k, ci in enumerate(significant):
                if is_cancelled():
                    raise CancelledError()
                res = final_singlepoint(ranked[ci][1], f"앙상블 conformer {k + 1}/{len(significant)}")
                members.append(res)
            e_list = [m[3] for m in members]
            e_min2 = min(e_list)
            rel2 = [(e - e_min2) * HARTREE2KCAL for e in e_list]
            ws2 = [math.exp(-dk / kT_kcal) for dk in rel2]
            z2 = sum(ws2)
            p2 = [w / z2 for w in ws2]
            dom = max(range(len(members)), key=lambda i: p2[i])
            atoms, mol, mf, e_total, homo, lumo, dipole = members[dom]
            ensemble_avg = {
                "homo_ev": sum(p * m[4] for p, m in zip(p2, members)),
                "lumo_ev": sum(p * m[5] for p, m in zip(p2, members) if m[5] is not None),
                "dipole_debye": sum(p * m[6] for p, m in zip(p2, members)),
            }
            conformer_populations = [
                {"rel_e_kcal": round(dk, 2), "population_pct": round(100 * p, 1)}
                for dk, p in zip(rel2, p2)]
            log("앙상블 가중 완료 — 지배 conformer 비율 "
                f"{100 * p2[dom]:.0f}%, 전자 기술자는 가중 평균값으로 보고")
        else:
            # 2~3) 지배 conformer(또는 클러스터) 단일 경로
            stage("DFT 구조 최적화" if params["do_opt"] else "단일점 SCF (환경 반영)", 18)
            atoms, mol, mf, e_total, homo, lumo, dipole = final_singlepoint(
                atoms, f"최종({solvent_key or 'vacuum'})")

        # 4) 기술자 추출
        stage("기술자 추출", 40)
        gap = (lumo - homo) if lumo is not None else None
        charge_models = _atomic_charges(mf, mol)
        charges = charge_models[charge_models["primary"]]
        try:
            density_cloud = desc_mod.density_cloud(mf, mol)
        except Exception as exc:  # noqa: BLE001 — 시각화용 부가 데이터
            density_cloud = None
            log(f"전자밀도 구름 생성 생략: {exc}")
        descriptors = {
            "total_energy_hartree": e_total,
            "homo_ev": round(homo, 3),
            "lumo_ev": round(lumo, 3) if lumo is not None else None,
            "gap_ev": round(gap, 3) if gap is not None else None,
            "dipole_debye": round(dipole, 3),
        }
        if not explicit:
            descriptors["conformer_populations"] = conformer_populations
        if ensemble_avg is not None:
            descriptors.update({
                "homo_ev": round(ensemble_avg["homo_ev"], 3),
                "lumo_ev": round(ensemble_avg["lumo_ev"], 3),
                "gap_ev": round(ensemble_avg["lumo_ev"] - ensemble_avg["homo_ev"], 3),
                "dipole_debye": round(ensemble_avg["dipole_debye"], 3),
            })
            notes_ensemble = ("전자 기술자(HOMO/LUMO/갭/쌍극자)는 Boltzmann 가중 평균 "
                              f"({temperature} K) — 열보정·용매화·전위는 지배 conformer 기준")
        else:
            notes_ensemble = None
        notes = [
            (("구조 최적화를 SMD 용매장 안에서 수행 (용매 중 구조 완화 반영)"
              if params["opt_in_solvent"] and solvent_key else
              "구조 최적화는 기체상에서 수행, 용매 효과는 최종 단일점에 SMD로 반영"))
            if params["do_opt"] else
            f"{geom_info['forcefield']} 역장 구조에서의 DFT 단일점 (사전 스크리닝 수준)",
            "분위기는 기록용 조건 — 명시적 대기 분자 모델은 미포함",
        ]
        if notes_ensemble:
            notes.append(notes_ensemble)

        # 5) 진동수·열역학 보정 (기체상, 최적화 수준)
        thermo_neutral = None
        if params["do_thermo"]:
            stage("진동수 계산·열역학 보정", 50)
            thermo_neutral = _thermo_correction(
                atoms, params, params["charge"], params["multiplicity"], temperature, log)

            # 허수 진동수가 있으면 안장점 — 해당 모드를 따라 흔들어 재최적화
            n_fix = 0
            while (thermo_neutral["n_imaginary"] > 0 and params["do_opt"]
                   and n_fix < 2 and not explicit):
                n_fix += 1
                stage(f"안장점 교정 재최적화 {n_fix}/2", 52)
                freqs = thermo_neutral["freqs_cm"]
                worst = int(np.argmin(freqs))
                mode = np.asarray(thermo_neutral["norm_mode"])[worst]
                log(f"허수 진동수 {freqs[worst]:.0f} cm⁻¹ 검출 — 해당 모드로 변위 후 재최적화")
                disp_atoms = [(a[0], a[1] + 0.35 * mode[i][0],
                               a[2] + 0.35 * mode[i][1], a[3] + 0.35 * mode[i][2])
                              for i, a in enumerate(atoms)]
                atoms = _optimize_state(disp_atoms, params, params["charge"],
                                        params["multiplicity"], log, label=" (안장점 교정)")
                thermo_neutral = _thermo_correction(
                    atoms, params, params["charge"], params["multiplicity"], temperature, log)
            if n_fix:
                # 구조가 바뀌었으므로 최종 단일점·전자 기술자를 다시 계산
                stage("교정 구조 재계산", 54)
                mol = _build_mol(atoms, params["basis_sp"], params["charge"],
                                 params["multiplicity"])
                mf = _make_mf(mol, params["xc"], params["disp"], solvent_key,
                              params["scf_tol"])
                e_total = _run_scf(mf, "최종(교정 구조)", log)
                homo, lumo = _frontier_orbitals(mf)
                gap = (lumo - homo) if lumo is not None else None
                dipole = float(np.linalg.norm(mf.dip_moment(unit="Debye", verbose=0)))
                charge_models = _atomic_charges(mf, mol)
                charges = charge_models[charge_models["primary"]]
                descriptors.update({
                    "total_energy_hartree": e_total,
                    "homo_ev": round(homo, 3),
                    "lumo_ev": round(lumo, 3) if lumo is not None else None,
                    "gap_ev": round(gap, 3) if gap is not None else None,
                    "dipole_debye": round(dipole, 3),
                })
                try:
                    density_cloud = desc_mod.density_cloud(mf, mol)
                except Exception:  # noqa: BLE001 — 시각화용 부가 데이터
                    density_cloud = None
                notes.append(
                    f"허수 진동수가 검출되어 해당 모드로 변위 후 {n_fix}회 재최적화했습니다 "
                    "(안장점 → 극소점 교정)")
            g_corr = thermo_neutral["g_corr_hartree"]
            descriptors.update({
                "zpe_kcal": round(thermo_neutral["zpe_hartree"] * HARTREE2KCAL, 2),
                "gibbs_correction_kcal": round(g_corr * HARTREE2KCAL, 2),
                "gibbs_energy_hartree": round(e_total + g_corr, 6),
                "entropy_cal_mol_k": round(
                    thermo_neutral["entropy_hartree_per_k"] * HARTREE2KCAL * 1000, 2),
                "n_imaginary_freqs": thermo_neutral["n_imaginary"],
            })
            descriptors["freq_scale_factor"] = params["freq_scale"]
            notes.append(
                f"열역학 보정: 기체상 조화진동자·강체회전·이상기체 근사, {temperature} K 반영 "
                f"(진동수 수준 {params['functional']}/{params['basis_opt']}, "
                f"스케일 인자 {params['freq_scale']} 적용)")
            if thermo_neutral["n_imaginary"] > 0:
                notes.append(
                    f"경고: 허수 진동수 {thermo_neutral['n_imaginary']}개 — 안정점이 아닐 수 있어 "
                    "열보정 신뢰도가 낮습니다 (구조 최적화 설정 확인 필요)")
        else:
            notes.append("열역학 보정 미수행 — 온도는 기록용 조건")

        # 6) 용매화 에너지 (동일 구조 기체상 대비)
        if solvent_key:
            stage("용매화 에너지 (기체상 참조)", 58)
            mf_gas = _make_mf(mol, params["xc"], params["disp"], None, params["scf_tol"])
            e_gas = _run_scf(mf_gas, "기체상 참조", log)
            descriptors["solvation_energy_kcal"] = round((e_total - e_gas) * HARTREE2KCAL, 2)
            e_cds = getattr(mf.with_solvent, "e_cds", None)
            if e_cds is not None:
                descriptors["smd_cds_kcal"] = round(float(e_cds) * HARTREE2KCAL, 2)

        # 6.2) 1 atm → 1 M 표준 상태 보정 + 용액상 깁스 자유에너지
        if params["do_thermo"] and thermo_neutral is not None and solvent_key:
            # ΔG(1 atm→1 M) = RT ln(V_m/1 L) = RT ln(0.082057·T), 298.15 K에서 +1.89 kcal/mol
            ss_corr_kcal = 1.98720425e-3 * temperature * math.log(0.082057 * temperature)
            descriptors["standard_state_corr_kcal"] = round(ss_corr_kcal, 2)
            descriptors["gibbs_energy_solution_hartree"] = round(
                e_total + thermo_neutral["g_corr_hartree"] + ss_corr_kcal / HARTREE2KCAL, 6)
            notes.append(
                f"용액상 깁스 자유에너지 = 용매 단일점 에너지 + 기체상 열보정 + "
                f"1 atm→1 M 표준 상태 보정(+{ss_corr_kcal:.2f} kcal/mol)")

        # 6.5) 클러스터 상호작용 에너지 (조각 분해, 클러스터 구조 고정)
        if fragments and len(fragments) <= MAX_INTERACTION_FRAGMENTS:
            stage("상호작용 에너지 (조각 분해)", 62)
            e_frag_sum = 0.0
            for fi, frag in enumerate(fragments):
                fq = params["charge"] if fi == 0 else 0
                fm = params["multiplicity"] if fi == 0 else 1
                # 전체 클러스터 basis(고스트 포함)에서 조각 에너지 → BSSE 보정
                e_frag_sum += _counterpoise_energy(
                    atoms, (frag["start"], frag["end"]), params["basis_sp"], fq, fm,
                    params["xc"], params["disp"], solvent_key, params["scf_tol"],
                    f"조각 {fi + 1}/{len(fragments)} ({frag['label']}, CP)", log)
            e_int = (e_total - e_frag_sum) * HARTREE2KCAL
            descriptors["interaction_energy_kcal"] = round(e_int, 2)
            notes.append(
                "상호작용 에너지: 클러스터 구조 고정 조각 분해 · "
                "BSSE counterpoise 보정 적용(변형 에너지는 미포함) — "
                "음수일수록 주변 분자와의 결합이 안정함")
        elif fragments:
            log(f"분자 수 {len(fragments)} > {MAX_INTERACTION_FRAGMENTS} — 상호작용 에너지 분해 생략")

        if fragments:
            notes.insert(0, "명시적 주변 분자 포함 클러스터 계산 (cluster-continuum): "
                            "모든 기술자는 클러스터 전체에 대한 값")

        # 7) 산화/환원 전위
        if want_redox and not closed_shell:
            log("중성 상태가 열린 껍질이라 자동 전위 계산 생략")
        elif want_redox:
            no_ref = _no_reference(settings)
            ref = None if no_ref else settings.get("referenceElectrode", "Li/Li+")
            e_abs = None if no_ref else presets.ABSOLUTE_POTENTIALS.get(ref, 1.44)
            if not no_ref:
                descriptors["potential_reference"] = ref
            else:
                notes.append("기준 전극 '없음' — 전위 환산 없이 IP/EA만 보고합니다")

            use_noneq = params["noneq"] and solvent_key is not None
            dm_neutral = mf.make_rdm1() if use_noneq else None

            # 음이온·EA·환원 전위는 diffuse 기저에 민감하다 (v2.0 P0-1).
            # 여분의 확산 함수가 없으면 여분 전자를 담을 자리가 부족해 EA 가
            # 낮게 나온다. 음이온에만 diffuse 기저를 쓰고, 어떤 기저를 썼는지
            # 결과에 남긴다.
            def _basis_for(dq):
                if dq < 0 and params.get("basis_anion"):
                    return params["basis_anion"]
                return params["basis_sp"]

            noneq_skipped = []

            def ion_energy_vertical(dq, label, prog):
                stage(f"{label} (수직 ΔSCF)", prog)
                basis_i = _basis_for(dq)
                mol_i = _build_mol(atoms, basis_i, params["charge"] + dq, 2)
                mf_i = _make_mf(mol_i, params["xc"], params["disp"], solvent_key,
                                params["scf_tol"])
                # 동결 용매장과 초기 밀도는 «같은 기저»에서만 쓸 수 있다.
                # 음이온에 diffuse 기저를 쓰면 행렬 크기가 달라 재사용이 불가능하다.
                same_basis = basis_i == params["basis_sp"]
                if use_noneq and same_basis:
                    _freeze_solvent_from(mf_i, dm_neutral)
                    return _run_scf(mf_i, f"{label}(비평형)", log,
                                    dm0=(dm_neutral / 2, dm_neutral / 2))
                if use_noneq and not same_basis:
                    noneq_skipped.append(label)
                return _run_scf(mf_i, label, log)

            # 서로 다른 기저의 절대 에너지를 빼면 안 된다. 음이온에 diffuse 기저를
            # 쓰면 «중성 기준 에너지»도 그 기저에서 다시 계산해야 EA 가 의미를 갖는다.
            # (이 보정 없이 sto-3g 중성 − def2-SVPD 음이온을 빼면 EA 가 28 eV 로
            #  나온다 — 기저 불완전성 차이가 그대로 EA 에 실린다.)
            def _neutral_ref(dq):
                basis_i = _basis_for(dq)
                if basis_i == params["basis_sp"]:
                    return e_total
                key = ("neutral_ref", basis_i)
                if key not in _ref_cache:
                    log(f"중성 기준 에너지를 {basis_i} 에서 재계산 (EA 기저 정합)")
                    mol_n = _build_mol(atoms, basis_i, params["charge"],
                                       params["multiplicity"])
                    _ref_cache[key] = _run_scf(
                        _make_mf(mol_n, params["xc"], params["disp"], solvent_key,
                                 params["scf_tol"]), f"중성({basis_i})", log)
                return _ref_cache[key]

            _ref_cache = {}
            e_cat_v = ion_energy_vertical(+1, "양이온", 66)
            e_an_v = ion_energy_vertical(-1, "음이온", 70)
            if noneq_skipped:
                notes.append(
                    f"{' · '.join(noneq_skipped)}은 중성과 다른 기저(diffuse)를 써서 "
                    "비평형 용매화(동결 용매장)를 적용하지 않았습니다 — 평형 용매화로 "
                    "계산되어 수직 EA 가 다소 크게 나올 수 있습니다")
            if use_noneq and not noneq_skipped:
                notes.append(
                    "수직 IP/EA는 비평형 용매화(중성 밀도로 동결한 용매장) 근사 — "
                    "용매 핵 재배향이 없는 순간 이온화를 기술. 광학 유전 응답 완화는 미포함(상한 추정)")
            ip_v = (e_cat_v - _neutral_ref(+1)) * HARTREE2EV
            ea_v = (_neutral_ref(-1) - e_an_v) * HARTREE2EV
            descriptors.update({
                "ip_vertical_ev": round(ip_v, 3),
                "ea_vertical_ev": round(ea_v, 3),
                # 어떤 기저로 음이온을 풀었는지 남긴다 — EA 의 기저 의존성 추적용
                "basis_anion": _basis_for(-1),
                "basis_diffuse_anion": bool(params.get("basis_anion")),
            })
            if not params.get("basis_anion"):
                notes.append(
                    "음이온에 diffuse 기저를 쓰지 않았습니다 — EA·환원 전위가 "
                    "기저에 민감할 수 있어 신뢰도 Method 축이 낮아집니다")

            if params["redox_adiabatic"]:
                def ion_adiabatic(dq, label, prog):
                    """이온 상태 재최적화 → 용매 SP (+열보정)."""
                    stage(f"{label} 구조 재최적화 (단열)", prog)
                    ion_atoms = _optimize_state(atoms, params, params["charge"] + dq, 2,
                                                log, label=f" ({label})")
                    mol_i = _build_mol(ion_atoms, _basis_for(dq), params["charge"] + dq, 2)
                    e_i = _run_scf(
                        _make_mf(mol_i, params["xc"], params["disp"], solvent_key,
                                 params["scf_tol"]),
                        f"{label}(단열)", log)
                    g_corr_i = None
                    if params["do_thermo"] and thermo_neutral is not None:
                        stage(f"{label} 진동수 계산", min(prog + 6, 97))
                        th_i = _thermo_correction(ion_atoms, params, params["charge"] + dq, 2,
                                                  temperature, log, label=f" ({label})")
                        g_corr_i = th_i["g_corr_hartree"]
                    return e_i, g_corr_i

                e_cat_a, g_cat = ion_adiabatic(+1, "양이온", 74)
                e_an_a, g_an = ion_adiabatic(-1, "음이온", 86)
                ip_a = (e_cat_a - _neutral_ref(+1)) * HARTREE2EV
                ea_a = (_neutral_ref(-1) - e_an_a) * HARTREE2EV
                descriptors.update({
                    "ip_adiabatic_ev": round(ip_a, 3),
                    "ea_adiabatic_ev": round(ea_a, 3),
                })
                if e_abs is not None:
                    descriptors.update({
                        "oxidation_potential_v": round(ip_a - e_abs, 3),
                        "reduction_potential_v": round(ea_a - e_abs, 3),
                    })
                    notes.append(
                        f"전위는 단열(adiabatic) IP/EA 기반 — 이온 상태 구조 재최적화 포함, "
                        f"{ref} 절대 전위 {e_abs} V 가정")
                if g_cat is not None and g_an is not None:
                    g0 = thermo_neutral["g_corr_hartree"]
                    dg_ox = (e_cat_a + g_cat - e_total - g0) * HARTREE2EV
                    dg_red = (e_total + g0 - e_an_a - g_an) * HARTREE2EV
                    descriptors.update({
                        "ip_gibbs_ev": round(dg_ox, 3),
                        "ea_gibbs_ev": round(dg_red, 3),
                    })
                    if e_abs is not None:
                        descriptors.update({
                            "oxidation_potential_gibbs_v": round(dg_ox - e_abs, 3),
                            "reduction_potential_gibbs_v": round(dg_red - e_abs, 3),
                        })
                    notes.append("ΔG 기반 IP/EA: 기체상 열보정(298 K 조화근사)을 단열 전자에너지에 합산")
            elif e_abs is not None:
                descriptors.update({
                    "oxidation_potential_v": round(ip_v - e_abs, 3),
                    "reduction_potential_v": round(ea_v - e_abs, 3),
                })
                notes.append(
                    f"전위는 수직 IP/EA 기반 근사 (구조 완화 미포함), "
                    f"{ref} 절대 전위 {e_abs} V 가정")

        # 8) 물성 지문 — 확장 기술자 (MEP · 반응성 지표 · 결합/흡착 · TDDFT)
        if want_fingerprint:
            def pair_energy(host_atoms, guest_smiles, label, prog, charge=0, mult=1):
                """host + guest 접촉 클러스터를 만들어 상호작용 에너지(kJ/mol) 산출."""
                stage(label, prog)
                cl_atoms, frags, _ = build_cluster_from_atoms(
                    host_atoms, smiles, guest_smiles, seed=7)
                mol_c = _build_mol(cl_atoms, params["basis_sp"],
                                   params["charge"] + charge, mult)
                e_c = _run_scf(_make_mf(mol_c, params["xc"], params["disp"],
                                        solvent_key, params["scf_tol"]), label, log)
                # BSSE counterpoise: 두 조각 모두 복합체 basis에서 평가
                e_host_cp = _counterpoise_energy(
                    cl_atoms, (0, frags[0]["end"]), params["basis_sp"],
                    params["charge"], params["multiplicity"], params["xc"], params["disp"],
                    solvent_key, params["scf_tol"], f"{label} 호스트(CP)", log)
                e_guest_cp = _counterpoise_energy(
                    cl_atoms, (frags[1]["start"], frags[1]["end"]), params["basis_sp"],
                    charge, mult, params["xc"], params["disp"],
                    solvent_key, params["scf_tol"], f"{label} 게스트(CP)", log)
                return (e_c - e_host_cp - e_guest_cp) * HARTREE2KJ, cl_atoms

            stage("MEP · 반응성 지표", 60)
            mep = desc_mod.mep_extremes(mf, mol)
            if mep:
                descriptors.update({k: v for k, v in mep.items() if k.endswith("_kcal")})
                descriptors["mep_points"] = {"max": mep["mep_max_point"],
                                             "min": mep["mep_min_point"]}
            if "ip_vertical_ev" in descriptors and "ea_vertical_ev" in descriptors:
                descriptors.update(desc_mod.reactivity_indices(
                    descriptors["ip_vertical_ev"], descriptors["ea_vertical_ev"]))

            # Li⁺ 결합 에너지 — MEP 최소점(전자 풍부 부위)에 Li⁺ 배치
            if mep and closed_shell:
                stage("Li⁺ 결합 에너지", 66)
                site = desc_mod.li_cation_site(mol, mep)
                li_atoms = list(atoms) + [("Li", *site)]
                mol_li = _build_mol(li_atoms, params["basis_sp"], params["charge"] + 1, 1)
                e_li_complex = _run_scf(
                    _make_mf(mol_li, params["xc"], params["disp"], solvent_key,
                             params["scf_tol"]), "Li⁺ 착물", log)
                n_host = len(atoms)
                e_host_cp = _counterpoise_energy(
                    li_atoms, (0, n_host), params["basis_sp"], params["charge"],
                    params["multiplicity"], params["xc"], params["disp"], solvent_key,
                    params["scf_tol"], "Li⁺ 착물 호스트(CP)", log)
                e_li_cp = _counterpoise_energy(
                    li_atoms, (n_host, n_host + 1), params["basis_sp"], 1, 1,
                    params["xc"], params["disp"], solvent_key, params["scf_tol"],
                    "Li⁺ 이온(CP)", log)
                descriptors["li_binding_kj"] = round(
                    (e_li_complex - e_host_cp - e_li_cp) * HARTREE2KJ, 1)
                fingerprint_structures["li_complex"] = atoms_to_xyz_block(
                    li_atoms, "Li+ 착물")

            # 자기 이량체 (바인더–바인더 수소결합/응집) 에너지
            if closed_shell:
                e_dim, dim_atoms = pair_energy(atoms, smiles, "이량체 결합 에너지", 72)
                descriptors["dimer_binding_kj"] = round(e_dim, 1)
                fingerprint_structures["dimer"] = atoms_to_xyz_block(dim_atoms, "이량체")

            # 활물질 표면 흡착 에너지 (대용 클러스터 모델)
            if closed_shell:
                ads = {}
                for si, sm in enumerate(desc_mod.SURFACE_MODELS):
                    try:
                        e_ads, ads_atoms = pair_energy(
                            atoms, sm["smiles"], f"{sm['label']} 표면 흡착", 76 + si * 4)
                        ads[sm["key"]] = {"label": sm["label"], "desc": sm["desc"],
                                          "energy_kj": round(e_ads, 1)}
                        fingerprint_structures[f"ads_{sm['key']}"] = atoms_to_xyz_block(
                            ads_atoms, f"{sm['label']} 흡착")
                    except Exception as exc:  # noqa: BLE001 — 개별 표면 실패는 건너뜀
                        log(f"{sm['label']} 표면 흡착 계산 실패: {exc}")
                if ads:
                    descriptors["surface_adsorption"] = ads
                    notes.append(
                        "결합·흡착 에너지는 모두 BSSE counterpoise 보정 적용 (변형 에너지 미포함)")
                    notes.append(
                        "표면 흡착 에너지는 슬랩이 아닌 대용 클러스터 모델 기반 — "
                        "같은 모델끼리의 상대 경향만 유효하고 다른 표면 모델·문헌 절대값과는 비교 금지")

            # 최약 결합 해리에너지 (BDE) — 균일 분해 + 라디칼 조각 재최적화
            if closed_shell:
                bonds = desc_mod.breakable_bonds(smiles)
                bde_list = []
                opt_solv = solvent_key if params["opt_in_solvent"] else None
                # ZPE·열보정은 라디칼마다 진동수 계산이 필요 — 열보정이 켜진 경우에만 수행
                bde_thermal = (params["bde_thermal"] and params["bde_relax"]
                               and params["do_thermo"] and thermo_neutral is not None)
                if bde_thermal:
                    log("BDE에 ZPE·298 K 열보정 적용 — 라디칼 조각마다 진동수 계산 수행")
                for bi, (label_b, f1, f2) in enumerate(bonds):
                    try:
                        stage(f"결합 해리에너지 {bi + 1}/{len(bonds)} ({label_b})", 90)
                        e_frozen = 0.0
                        e_relaxed = 0.0
                        zpe_sum = 0.0
                        h_sum = 0.0
                        thermo_ok = bde_thermal
                        for side, fidx in enumerate((f1, f2)):
                            frag_atoms = [atoms[i] for i in fidx]
                            # (1) 모분자 구조를 고정한 수직 조각 에너지
                            mol_v = _build_mol(frag_atoms, params["basis_sp"], 0, 2)
                            e_v = _run_scf(
                                _make_mf(mol_v, params["xc"], params["disp"],
                                         solvent_key, params["scf_tol"]),
                                f"라디칼 조각 {side + 1} 고정 ({label_b})", log)
                            e_frozen += e_v
                            # (2) 라디칼 구조 완화 후 조각 에너지 (원자 1개는 완화 불필요)
                            if params["bde_relax"] and len(frag_atoms) > 1:
                                rel_atoms = _optimize_state(
                                    frag_atoms, params, 0, 2, log,
                                    label=f" (라디칼 {label_b})", solvent_key=opt_solv)
                                mol_r = _build_mol(rel_atoms, params["basis_sp"], 0, 2)
                                e_relaxed += _run_scf(
                                    _make_mf(mol_r, params["xc"], params["disp"],
                                             solvent_key, params["scf_tol"]),
                                    f"라디칼 조각 {side + 1} 완화 ({label_b})", log)
                            else:
                                rel_atoms = frag_atoms
                                e_relaxed += e_v
                            # ZPE·열보정: 라디칼 조각의 진동수 계산 (단원자는 병진만)
                            if thermo_ok:
                                try:
                                    if len(rel_atoms) == 1:
                                        th_f = _atomic_thermo_fn(temperature)
                                    else:
                                        th_f = _thermo_correction(
                                            rel_atoms, params, 0, 2, temperature, log,
                                            label=f" (라디칼 {side + 1}, {label_b})")
                                    zpe_sum += th_f["zpe_hartree"]
                                    h_sum += th_f["h_corr_hartree"]
                                except Exception as exc:  # noqa: BLE001
                                    log(f"{label_b} 조각 {side + 1} 열보정 실패: {exc}")
                                    thermo_ok = False
                        entry = {
                            "bond": label_b,
                            "bde_kj": round((e_relaxed - e_total) * HARTREE2KJ, 1),
                            "bde_frozen_kj": round((e_frozen - e_total) * HARTREE2KJ, 1),
                        }
                        entry["relaxation_kj"] = round(
                            entry["bde_frozen_kj"] - entry["bde_kj"], 1)
                        if thermo_ok and thermo_neutral is not None:
                            d_zpe = zpe_sum - thermo_neutral["zpe_hartree"]
                            d_h = h_sum - thermo_neutral["h_corr_hartree"]
                            entry["bde_zpe_kj"] = round(
                                (e_relaxed - e_total + d_zpe) * HARTREE2KJ, 1)
                            entry["bde_298_kj"] = round(
                                (e_relaxed - e_total + d_h) * HARTREE2KJ, 1)
                            entry["zpe_correction_kj"] = round(d_zpe * HARTREE2KJ, 1)
                        bde_list.append(entry)
                    except Exception as exc:  # noqa: BLE001 — 개별 결합 실패는 건너뜀
                        log(f"{label_b} 해리에너지 계산 실패: {exc}")
                if bde_list:
                    has_298 = all("bde_298_kj" in b for b in bde_list)
                    rank_key = "bde_298_kj" if has_298 else "bde_kj"
                    weakest = min(bde_list, key=lambda b: b[rank_key])
                    descriptors["bde_min_kj"] = weakest["bde_kj"]
                    if has_298:
                        descriptors["bde_min_298_kj"] = weakest["bde_298_kj"]
                    descriptors["bde_weakest_bond"] = weakest["bond"]
                    descriptors["bde_all"] = bde_list
                    if params["bde_relax"]:
                        msg = ("결합 해리에너지(BDE)는 균일 분해 후 각 라디칼 조각을 "
                               "재최적화한 값 (완화 전 값·완화 에너지도 함께 보고)")
                        if has_298:
                            msg += (" · ZPE와 298 K 열보정 포함 값(BDE 298 K)을 함께 제공하며 "
                                    "문헌 BDE와 직접 비교할 값은 이것 (전자에너지는 고수준 basis, "
                                    "열보정은 최적화 수준 basis에서 산출)")
                        else:
                            msg += " · 0 K 전자에너지 차이이며 ZPE·열보정은 미포함"
                        notes.append(msg)
                    else:
                        notes.append(
                            "결합 해리에너지(BDE)는 조각 구조를 고정한 근사 — "
                            "라디칼 완화가 빠져 실제보다 크게 나오며 결합 간 상대 비교에 사용")

            # UV-Vis λmax (TDDFT)
            try:
                stage("UV-Vis λmax (TDDFT)", 94)
                uv = desc_mod.tddft_lambda_max(mf)
                if uv:
                    descriptors.update(uv)
                    notes.append("UV-Vis λmax는 TDDFT 수직 여기 근사 — "
                                 "진동 구조·용매 재조직화 미포함")
            except Exception as exc:  # noqa: BLE001 — TDDFT 실패는 나머지 결과 유지
                log(f"TDDFT 계산 실패: {exc}")

        # 건식 음극 바인더 적합성 판정 — 산출된 기술자를 바인더 관점으로 번역
        binder_report = None
        if want_binder:
            stage("바인더 적합성 판정", 96)
            binder_report = binder_mod.report(job["material"], descriptors)
            log(f"바인더 판정: {binder_report['summary']}")

        elapsed = time.time() - t_start
        result = {
            "descriptors": descriptors,
            "binder_report": binder_report,
            "fragments": ([{"label": f["label"], "start": f["start"], "end": f["end"]}
                           for f in fragments] if fragments else None),
            "fingerprint_structures": fingerprint_structures or None,
            "density_cloud": density_cloud,
            "conditions": {
                "environment": settings["envType"],
                "explicit_molecules": explicit_label or "없음",
                "solvent_model": (
                    f"SMD(혼합: {settings['customMixedSolvent']['name']})"
                    if settings.get("customMixedSolvent") else
                    f"SMD({solvent_key})" if solvent_key else "vacuum"),
                "temperature_k": temperature,
                "atmosphere": settings["atmosphere"],
                "reference_electrode": settings.get("referenceElectrode"),
                "method": f"{params['functional']}/{params['basis_sp']}",
                "engine": "PySCF (density fitting)",
            },
            "structure_xyz": atoms_to_xyz_block(
                atoms, f"{job['material'].get('name', '')} {params['functional']}/{params['basis_sp']}"),
            "geometry_info": geom_info,
            "mulliken_charges": [round(float(c), 3) for c in charges],
            # 전하 모델을 나란히 남긴다 — Mulliken 은 진단용, meta-Löwdin 이 주값
            "atomic_charges": charge_models,
            "notes": notes,
            "result_origin": "SERVER_CALCULATION(PySCF 실계산)",
            "provenance": _provenance(params, settings, solvent_key),
            # 이 계산이 어떤 조건으로 수행됐는지 한 벌로 — 해시가 같으면 비교 가능
            "protocol_card": protocol_mod.card(
                settings, params, settings.get("referenceElectrode")),
            "wall_time_s": round(elapsed, 1),
        }
        update({"status": "PUBLISHED", "progress": 100, "stage": "완료",
                "result": result, "finishedAt": time.time()})
        log(f"계산 완료 — 총 {elapsed:.1f}s")
        update({"logs": list(log_lines)})
    except CancelledError:
        update({"status": "FAILED", "error": "사용자 취소", "stage": "취소됨",
                "finishedAt": time.time()})
    except Exception as exc:  # noqa: BLE001 — 작업 단위 오류는 작업 실패로 기록
        log(f"오류: {exc}")
        update({"status": "FAILED", "error": str(exc), "stage": "실패",
                "finishedAt": time.time(),
                "traceback": traceback.format_exc()[-2000:]})
