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

from . import presets
from .geometry import smiles_to_conformers, build_cluster, atoms_to_xyz_block

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


def _run_scf(mf, label, log, dm0=None):
    t0 = time.time()
    energy = mf.kernel(dm0) if dm0 is not None else mf.kernel()
    if not mf.converged:
        raise RuntimeError(f"{label} SCF 미수렴")
    log(f"{label} SCF 수렴 — E = {energy:.6f} Ha ({time.time() - t0:.1f}s)")
    return float(energy)


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
        explicit = [(m["smiles"], m["count"]) for m in (settings.get("explicitMolecules") or [])]
        explicit_label = " + ".join(
            f"{m['count']}× {m.get('name') or m['smiles']}"
            for m in (settings.get("explicitMolecules") or []))
        fragments = None

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
                at = _optimize_state(at, params, params["charge"], params["multiplicity"], log)
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
        _, charges = mf.mulliken_pop(verbose=0)
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
            "구조 최적화는 기체상에서 수행, 용매 효과는 최종 단일점에 SMD로 반영"
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
                frag_atoms = atoms[frag["start"]:frag["end"]]
                fq = params["charge"] if fi == 0 else 0
                fm = params["multiplicity"] if fi == 0 else 1
                mol_f = _build_mol(frag_atoms, params["basis_sp"], fq, fm)
                mf_f = _make_mf(mol_f, params["xc"], params["disp"], solvent_key,
                                params["scf_tol"])
                e_frag_sum += _run_scf(mf_f, f"조각 {fi + 1}/{len(fragments)} ({frag['label']})", log)
            e_int = (e_total - e_frag_sum) * HARTREE2KCAL
            descriptors["interaction_energy_kcal"] = round(e_int, 2)
            notes.append(
                "상호작용 에너지: 클러스터 구조 고정 조각 분해(변형·BSSE 보정 미포함) — "
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

            def ion_energy_vertical(dq, label, prog):
                stage(f"{label} (수직 ΔSCF)", prog)
                mol_i = _build_mol(atoms, params["basis_sp"], params["charge"] + dq, 2)
                mf_i = _make_mf(mol_i, params["xc"], params["disp"], solvent_key,
                                params["scf_tol"])
                if use_noneq:
                    _freeze_solvent_from(mf_i, dm_neutral)
                    return _run_scf(mf_i, f"{label}(비평형)", log,
                                    dm0=(dm_neutral / 2, dm_neutral / 2))
                return _run_scf(mf_i, label, log)

            e_cat_v = ion_energy_vertical(+1, "양이온", 66)
            e_an_v = ion_energy_vertical(-1, "음이온", 70)
            if use_noneq:
                notes.append(
                    "수직 IP/EA는 비평형 용매화(중성 밀도로 동결한 용매장) 근사 — "
                    "용매 핵 재배향이 없는 순간 이온화를 기술. 광학 유전 응답 완화는 미포함(상한 추정)")
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

        elapsed = time.time() - t_start
        result = {
            "descriptors": descriptors,
            "fragments": ([{"label": f["label"], "start": f["start"], "end": f["end"]}
                           for f in fragments] if fragments else None),
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
