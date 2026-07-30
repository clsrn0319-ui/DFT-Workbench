"""PySCF 기반 실제 DFT 계산 엔진.

계산 흐름 (run_job):
  1. RDKit conformer 탐색 → 최저 에너지 3D 구조
  2. (옵션) DFT 기체상 구조 최적화 — geomeTRIC 우선, 없으면 pyberny
  3. 최종 단일점 SCF — SMD implicit 용매화(환경 설정) + D3(BJ) 분산 보정
  4. 기술자(descriptor) 추출: 전자에너지, HOMO/LUMO/갭, 쌍극자, Mulliken 전하
  5. 용매 환경이면 동일 구조 기체상 SCF로 용매화 에너지 산출
  6. (옵션) 수직 IP/EA ΔSCF → 기준 전극(Li/Li⁺, SHE) 대비 산화/환원 전위

환경 설정의 실제 반영:
  - 용매: SMD 파라미터(유전상수·굴절률·표면장력·H-결합 파라미터)로 해밀토니안에 반영
  - 온도: 결과 메타데이터로 기록 (진동수 계산 미수행 — 열보정 없음, 결과 노트에 명시)
  - 분위기: 기록용 메타데이터 (단일 분자 DFT는 대기를 명시적으로 모델링하지 않음)
"""

import time
import traceback

import numpy as np
from pyscf import gto, dft, scf
from pyscf.solvent import smd

from . import presets
from .geometry import smiles_to_xyz, atoms_to_xyz_block

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
    return {
        "n_conf": exp.get("nConformers") or acc["n_conf"],
        "do_opt": acc["do_opt"] if exp.get("optimizeGeometry") is None else bool(exp["optimizeGeometry"]),
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


def _optimize_geometry(mf, log):
    """DFT 기체상 구조 최적화. geomeTRIC → pyberny 순으로 시도."""
    try:
        from pyscf.geomopt.geometric_solver import optimize as geo_opt
        log("구조 최적화 시작 (geomeTRIC)")
        return geo_opt(mf, maxsteps=100)
    except ImportError:
        from pyscf.geomopt.berny_solver import optimize as berny_opt
        log("구조 최적화 시작 (pyberny)")
        return berny_opt(mf, maxsteps=100)


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

        # 1) conformer 탐색
        stage("구조 생성 (conformer 탐색)", 5)
        atoms, geom_info = smiles_to_xyz(smiles, n_conformers=params["n_conf"])
        log(f"conformer {geom_info['n_conformers']}개 생성, {geom_info['forcefield']} "
            f"최저 에너지 구조 선택")

        # 2) DFT 구조 최적화 (기체상)
        if params["do_opt"]:
            stage("DFT 구조 최적화", 20)
            mol_opt = _build_mol(atoms, params["basis_opt"], params["charge"], params["multiplicity"])
            mf_opt = _make_mf(mol_opt, params["xc"], params["disp"], None, params["scf_tol"])
            mol_final = _optimize_geometry(mf_opt, log)
            coords = mol_final.atom_coords(unit="Angstrom")
            atoms = [(mol_final.atom_symbol(i), *coords[i]) for i in range(mol_final.natm)]
            log(f"구조 최적화 완료 ({params['functional']}/{params['basis_opt']}, 기체상)")

        # 3) 최종 단일점 (환경 설정 반영)
        stage("단일점 SCF (환경 반영)", 55)
        mol = _build_mol(atoms, params["basis_sp"], params["charge"], params["multiplicity"])
        mf = _make_mf(mol, params["xc"], params["disp"], solvent_key, params["scf_tol"])
        e_total = _run_scf(mf, f"최종({solvent_key or 'vacuum'})", log)

        # 4) 기술자 추출
        stage("기술자 추출", 70)
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
            "온도·분위기는 기록용 조건 — 진동 열보정 및 명시적 대기 모델은 미포함",
        ]

        # 5) 용매화 에너지 (동일 구조 기체상 대비)
        if solvent_key:
            stage("용매화 에너지 (기체상 참조)", 78)
            mf_gas = _make_mf(mol, params["xc"], params["disp"], None, params["scf_tol"])
            e_gas = _run_scf(mf_gas, "기체상 참조", log)
            dg_solv_kcal = (e_total - e_gas) * HARTREE2KCAL
            descriptors["solvation_energy_kcal"] = round(dg_solv_kcal, 2)
            e_cds = getattr(mf.with_solvent, "e_cds", None)
            if e_cds is not None:
                descriptors["smd_cds_kcal"] = round(float(e_cds) * HARTREE2KCAL, 2)

        # 6) 산화/환원 전위 (수직 ΔSCF)
        if "전위" in settings.get("purpose", ""):
            if params["multiplicity"] != 1:
                log("중성 상태가 열린 껍질이라 자동 전위 계산 생략")
            else:
                ref = settings.get("referenceElectrode", "Li/Li+")
                e_abs = presets.ABSOLUTE_POTENTIALS.get(ref, 1.44)
                stage("산화 전위 (양이온 ΔSCF)", 84)
                mol_cat = _build_mol(atoms, params["basis_sp"], params["charge"] + 1, 2)
                e_cat = _run_scf(
                    _make_mf(mol_cat, params["xc"], params["disp"], solvent_key, params["scf_tol"]),
                    "양이온", log)
                stage("환원 전위 (음이온 ΔSCF)", 92)
                mol_an = _build_mol(atoms, params["basis_sp"], params["charge"] - 1, 2)
                e_an = _run_scf(
                    _make_mf(mol_an, params["xc"], params["disp"], solvent_key, params["scf_tol"]),
                    "음이온", log)
                ip = (e_cat - e_total) * HARTREE2EV
                ea = (e_total - e_an) * HARTREE2EV
                descriptors.update({
                    "ip_vertical_ev": round(ip, 3),
                    "ea_vertical_ev": round(ea, 3),
                    "oxidation_potential_v": round(ip - e_abs, 3),
                    "reduction_potential_v": round(ea - e_abs, 3),
                    "potential_reference": ref,
                })
                notes.append(
                    f"전위는 수직 IP/EA 기반 근사 (구조 완화·열보정 미포함), "
                    f"{ref} 절대 전위 {e_abs} V 가정")

        elapsed = time.time() - t_start
        result = {
            "descriptors": descriptors,
            "conditions": {
                "environment": settings["envType"],
                "solvent_model": f"SMD({solvent_key})" if solvent_key else "vacuum",
                "temperature_k": settings["temperature"],
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
