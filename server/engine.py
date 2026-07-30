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

import time
import traceback

import numpy as np
from pyscf import gto, dft, scf
from pyscf.hessian import thermo as pyscf_thermo
from pyscf.solvent import smd

from . import presets
from .geometry import smiles_to_conformers, atoms_to_xyz_block

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
    if settings["envType"] == "진공·기체" or not settings.get("solventId"):
        return None
    sol = presets.SOLVENTS_BY_ID.get(settings["solventId"])
    if sol is None:
        raise ValueError(f"알 수 없는 용매 id: {settings['solventId']}")
    return sol.get("builtin_key") or sol["modelKey"]


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
        "basis_opt": acc["basis_opt"],
        "basis_sp": exp.get("basis") or acc["basis_sp"],
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


def _run_scf(mf, label, log):
    t0 = time.time()
    energy = mf.kernel()
    if not mf.converged:
        raise RuntimeError(f"{label} SCF 미수렴")
    log(f"{label} SCF 수렴 — E = {energy:.6f} Ha ({time.time() - t0:.1f}s)")
    return float(energy)


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


def _optimize_state(atoms, params, charge, multiplicity, log, label=""):
    """기체상 구조 최적화 후 (atoms, 최적화 수준 mf)를 반환."""
    mol = _build_mol(atoms, params["basis_opt"], charge, multiplicity)
    mf = _make_mf(mol, params["xc"], params["disp"], None, params["scf_tol"])
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
    th = pyscf_thermo.thermo(mf, freq_info["freq_au"],
                             temperature=temperature, pressure=101325)
    g_corr = float(th["G_tot"][0]) - float(e_elec)
    result = {
        "zpe_hartree": float(th["ZPE"][0]),
        "g_corr_hartree": g_corr,
        "h_corr_hartree": float(th["H_tot"][0]) - float(e_elec),
        "entropy_hartree_per_k": float(th["S_tot"][0]),
        "n_imaginary": n_imag,
        "lowest_freq_cm": float(np.min(freqs_real)),
    }
    log(f"진동수 계산{label} 완료 — 허수 진동수 {n_imag}개, "
        f"ZPE {result['zpe_hartree'] * HARTREE2KCAL:.2f} kcal/mol ({time.time() - t0:.1f}s)")
    return result


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
        want_redox = "전위" in settings.get("purpose", "")
        closed_shell = params["multiplicity"] == 1

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
            atoms = ranked[0][1]
            spread = (ranked[-1][0] - ranked[0][0]) * HARTREE2KCAL
            log(f"DFT 재순위화 완료 — 후보 간 에너지 폭 {spread:.2f} kcal/mol")
        else:
            atoms = candidates[0][0]

        # 2) DFT 구조 최적화 (기체상)
        if params["do_opt"]:
            stage("DFT 구조 최적화", 18)
            atoms = _optimize_state(atoms, params, params["charge"],
                                    params["multiplicity"], log)
            log(f"구조 최적화 완료 ({params['functional']}/{params['basis_opt']}, 기체상)")

        # 3) 최종 단일점 (환경 설정 반영)
        stage("단일점 SCF (환경 반영)", 34)
        mol = _build_mol(atoms, params["basis_sp"], params["charge"], params["multiplicity"])
        mf = _make_mf(mol, params["xc"], params["disp"], solvent_key, params["scf_tol"])
        e_total = _run_scf(mf, f"최종({solvent_key or 'vacuum'})", log)

        # 4) 기술자 추출
        stage("기술자 추출", 40)
        homo, lumo = _frontier_orbitals(mf)
        gap = (lumo - homo) if lumo is not None else None
        dip_vec = mf.dip_moment(unit="Debye", verbose=0)
        dipole = float(np.linalg.norm(dip_vec))
        _, charges = mf.mulliken_pop(verbose=0)
        descriptors = {
            "total_energy_hartree": e_total,
            "homo_ev": round(homo, 3),
            "lumo_ev": round(lumo, 3) if lumo is not None else None,
            "gap_ev": round(gap, 3) if gap is not None else None,
            "dipole_debye": round(dipole, 3),
        }
        notes = [
            "구조 최적화는 기체상에서 수행, 용매 효과는 최종 단일점에 SMD로 반영"
            if params["do_opt"] else
            f"{geom_info['forcefield']} 역장 구조에서의 DFT 단일점 (사전 스크리닝 수준)",
            "분위기는 기록용 조건 — 명시적 대기 분자 모델은 미포함",
        ]

        # 5) 진동수·열역학 보정 (기체상, 최적화 수준)
        thermo_neutral = None
        if params["do_thermo"]:
            stage("진동수 계산·열역학 보정", 50)
            thermo_neutral = _thermo_correction(
                atoms, params, params["charge"], params["multiplicity"], temperature, log)
            g_corr = thermo_neutral["g_corr_hartree"]
            descriptors.update({
                "zpe_kcal": round(thermo_neutral["zpe_hartree"] * HARTREE2KCAL, 2),
                "gibbs_correction_kcal": round(g_corr * HARTREE2KCAL, 2),
                "gibbs_energy_hartree": round(e_total + g_corr, 6),
                "entropy_cal_mol_k": round(
                    thermo_neutral["entropy_hartree_per_k"] * HARTREE2KCAL * 1000, 2),
                "n_imaginary_freqs": thermo_neutral["n_imaginary"],
            })
            notes.append(
                f"열역학 보정: 기체상 조화진동자·강체회전·이상기체 근사, {temperature} K 반영 "
                f"(진동수 수준 {params['functional']}/{params['basis_opt']})")
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

        # 7) 산화/환원 전위
        if want_redox and not closed_shell:
            log("중성 상태가 열린 껍질이라 자동 전위 계산 생략")
        elif want_redox:
            ref = settings.get("referenceElectrode", "Li/Li+")
            e_abs = presets.ABSOLUTE_POTENTIALS.get(ref, 1.44)
            descriptors["potential_reference"] = ref

            def ion_energy_vertical(dq, label, prog):
                stage(f"{label} (수직 ΔSCF)", prog)
                mol_i = _build_mol(atoms, params["basis_sp"], params["charge"] + dq, 2)
                return _run_scf(
                    _make_mf(mol_i, params["xc"], params["disp"], solvent_key, params["scf_tol"]),
                    label, log)

            e_cat_v = ion_energy_vertical(+1, "양이온", 66)
            e_an_v = ion_energy_vertical(-1, "음이온", 70)
            ip_v = (e_cat_v - e_total) * HARTREE2EV
            ea_v = (e_total - e_an_v) * HARTREE2EV
            descriptors.update({
                "ip_vertical_ev": round(ip_v, 3),
                "ea_vertical_ev": round(ea_v, 3),
            })

            if params["redox_adiabatic"]:
                def ion_adiabatic(dq, label, prog):
                    """이온 상태 재최적화 → 용매 SP (+열보정)."""
                    stage(f"{label} 구조 재최적화 (단열)", prog)
                    ion_atoms = _optimize_state(atoms, params, params["charge"] + dq, 2,
                                                log, label=f" ({label})")
                    mol_i = _build_mol(ion_atoms, params["basis_sp"], params["charge"] + dq, 2)
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
                ip_a = (e_cat_a - e_total) * HARTREE2EV
                ea_a = (e_total - e_an_a) * HARTREE2EV
                descriptors.update({
                    "ip_adiabatic_ev": round(ip_a, 3),
                    "ea_adiabatic_ev": round(ea_a, 3),
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
                        "oxidation_potential_gibbs_v": round(dg_ox - e_abs, 3),
                        "reduction_potential_gibbs_v": round(dg_red - e_abs, 3),
                    })
                    notes.append("ΔG 기반 전위: 기체상 열보정(298 K 조화근사)을 단열 전자에너지에 합산")
            else:
                descriptors.update({
                    "oxidation_potential_v": round(ip_v - e_abs, 3),
                    "reduction_potential_v": round(ea_v - e_abs, 3),
                })
                notes.append(
                    f"전위는 수직 IP/EA 기반 근사 (구조 완화 미포함), "
                    f"{ref} 절대 전위 {e_abs} V 가정")

        elapsed = time.time() - t_start
        result = {
            "descriptors": descriptors,
            "conditions": {
                "environment": settings["envType"],
                "solvent_model": f"SMD({solvent_key})" if solvent_key else "vacuum",
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
            "notes": notes,
            "result_origin": "SERVER_CALCULATION(PySCF 실계산)",
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
