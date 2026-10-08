"""Conformer 세트 — 구조를 먼저 찾아 눈으로 확인하고, 고른 구조로만 DFT 계산을 돌린다.

구조 준비(역장, 수 초)와 DFT 계산(큐, 수 시간)을 나누기 위한 모듈이다.
세트 하나는 data/conformers/<id>.json 한 파일이다:
  - molecule: 이름 · SMILES(전개 후) · 라이브러리 레코드 · 구조(모노머/2량체/3량체)
  - settings: 탐색 설정(개수 · seed · 중복 제거 RMSD)과 기준 구조 정책
  - conformers: 좌표 · 역장 에너지 · (재순위 시) DFT 에너지 · 주사슬 비틀림각 · 기준 대비 RMSD
기준 구조(all-trans 등)를 쓰면 그 구조가 1번이 되고, 모든 비교는 그 구조를 기준으로 한다.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid

from . import geometry as geo
from . import store

HARTREE2KCAL = 627.5094740631
RT_KCAL = 1.98720425e-3 * 298.15
REFERENCE_POLICIES = ("auto", "all-trans", "pattern")

_lock = threading.RLock()
_rank_threads: dict[str, threading.Thread] = {}


def _dir():
    return store.DATA_DIR / "conformers"


def _path(set_id: str):
    return _dir() / f"{store.safe_id(set_id)}.json"


def _save(doc: dict) -> dict:
    with _lock:
        _dir().mkdir(parents=True, exist_ok=True)
        p = _path(doc["id"])
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    return doc


def get(set_id: str) -> dict | None:
    p = _path(set_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_sets() -> list[dict]:
    """세트 목록 — 좌표는 빼고 요약만 (최근 생성순). 라이브러리 분자와 묶어서 돌려준다."""
    out = []
    if not _dir().exists():
        return out
    for p in _dir().glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append(summary(d))
    out.sort(key=lambda d: d.get("createdAt") or 0, reverse=True)
    return attach_library(out)


def _library_match(mol: dict):
    """세트의 분자에 해당하는 라이브러리 레코드 — libraryId 가 없으면 SMILES 로 찾는다.

    돌려주는 값: (레코드 | None, "id" | "smiles" | None). 탐색할 때 라이브러리를 거치지
    않았거나 libraryId 가 없던 시절의 세트도 같은 분자 아래로 모이게 하기 위한 것이다.
    """
    from . import library as lib_mod
    mol = mol or {}
    rec = lib_mod.get(mol.get("libraryId")) if mol.get("libraryId") else None
    if rec:
        return rec, "id"
    key = lib_mod.canonical(mol.get("input_smiles") or mol.get("smiles") or "")
    if not key:
        return None, None
    for m in lib_mod.molecules():
        if lib_mod.canonical(m.get("smiles") or "") == key:
            return m, "smiles"
    return None, None


def attach_library(sets: list[dict]) -> list[dict]:
    for s in sets:
        rec, how = _library_match(s.get("molecule"))
        s["library"] = {"id": rec["id"], "name": rec.get("name")} if rec else None
        s["linked_by"] = how
    return sets


def link_library(set_id: str) -> dict:
    """세트의 분자를 라이브러리에 등록(이미 있으면 연결)하고 libraryId 를 세트에 적는다."""
    from . import library as lib_mod
    doc = get(set_id)
    if doc is None:
        raise KeyError(set_id)
    mol = doc.get("molecule") or {}
    rec, _how = _library_match(mol)
    if rec is None:
        smiles = (mol.get("input_smiles") or mol.get("smiles") or "").strip()
        if not smiles:
            raise ValueError("세트에 SMILES 가 없어 등록할 수 없습니다.")
        rec = lib_mod.add_molecule({"name": mol.get("name"), "smiles": smiles,
                                    "source": "conformer 탐색"})
    mol["libraryId"] = rec["id"]
    doc["molecule"] = mol
    _save(doc)
    return {"library": {"id": rec["id"], "name": rec.get("name")},
            "set": attach_library([summary(doc)])[0]}


def delete(set_id: str) -> bool:
    p = _path(set_id)
    if not p.exists():
        return False
    try:
        p.unlink()
    except OSError:
        return False
    return True


def summary(doc: dict) -> dict:
    return {k: doc.get(k) for k in ("id", "molecule", "settings", "createdAt", "rank_status")} | {
        "n_conformers": len(doc.get("conformers") or []),
        "n_ranked": sum(1 for c in doc.get("conformers") or [] if c.get("dft_energy") is not None),
    }


def public(doc: dict, with_atoms: bool = True) -> dict:
    """화면에 주는 형태 — populations 를 그때그때 계산해 붙인다."""
    confs = [dict(c) for c in doc.get("conformers") or []]
    pops = populations(confs)
    for c, p in zip(confs, pops):
        c["population_pct"] = round(p, 1)
        if not with_atoms:
            c.pop("atoms", None)
    return {**doc, "conformers": confs}


def populations(confs: list[dict]) -> list[float]:
    """Boltzmann 비율(%) — DFT 에너지가 있으면 그것으로, 없으면 역장 에너지로."""
    if not confs:
        return []
    use_dft = all(c.get("dft_energy") is not None for c in confs)
    es = [(c["dft_energy"] if use_dft else c["ff_energy"]) for c in confs]
    lo = min(es)
    ws = [math.exp(-(e - lo) / RT_KCAL) for e in es]
    z = sum(ws) or 1.0
    return [100 * w / z for w in ws]


def search(req: dict) -> dict:
    """conformer 탐색 (역장 — DFT 아님). 기준 구조 정책이 auto 가 아니면 그 구조가 1번."""
    smiles = (req.get("smiles") or "").strip()
    if not smiles:
        raise ValueError("SMILES 가 필요합니다.")
    structure = req.get("structure") or "모노머"
    n_units = {"모노머": 1, "2량체": 2, "3량체": 3}.get(structure, 1)
    calc_smiles = geo.oligomerize(smiles, n_units) if (n_units > 1 or geo.has_attachment_points(smiles)) else smiles
    policy = req.get("reference") or "auto"
    if policy not in REFERENCE_POLICIES:
        raise ValueError(f"알 수 없는 기준 구조 정책: {policy}")
    pattern = (req.get("pattern") or "").strip()
    if policy == "pattern" and not pattern:
        raise ValueError("비틀림 패턴을 넣으세요 (예: T G T G').")
    n = max(1, min(int(req.get("nConformers") or 20), 200))
    seed = int(req.get("seed") or 42)
    prune = float(req.get("pruneRms") or 0.5)

    ref_atoms = ref_info = None
    if policy != "auto":
        ref_atoms, ref_info = geo.build_torsion_start(calc_smiles, pattern if policy == "pattern" else "T")
        if not ref_info["torsions"]:
            policy, ref_atoms, ref_info = "auto", None, None   # 주사슬 비틀림이 없으면 기준을 둘 수 없다

    found, info = geo.conformer_set(calc_smiles, n, seed, prune)
    quads = [tuple(t["atoms"]) for t in (ref_info or {}).get("torsions", [])]
    if not quads:
        from rdkit import Chem
        mol = Chem.AddHs(Chem.MolFromSmiles(calc_smiles))
        path = geo.backbone_path(mol)
        quads = [tuple(path[i:i + 4]) for i in range(max(0, len(path) - 3))]

    records = []
    if ref_atoms is not None:
        records.append({"atoms": ref_atoms, "ff_energy_raw": ref_info.get("ff_energy"), "is_reference": True})
    for atoms, e in found:
        if ref_atoms is not None and geo.rmsd(ref_atoms, atoms) < prune:
            continue           # 기준 구조와 사실상 같은 구조는 중복으로 보지 않는다
        records.append({"atoms": atoms, "ff_energy_raw": e, "is_reference": False})

    base_atoms = records[0]["atoms"]
    raw = [r["ff_energy_raw"] for r in records if r["ff_energy_raw"] is not None]
    e_min = min(raw) if raw else 0.0
    conformers = []
    for i, r in enumerate(records):
        e = r["ff_energy_raw"]
        conformers.append({
            "index": i + 1,
            "is_reference": r["is_reference"],
            "ff_energy": round((e - e_min), 3) if e is not None else None,
            "dft_energy": None,
            "torsions": [round(geo.dihedral_deg(r["atoms"], q), 1) for q in quads],
            "rmsd_to_reference": round(geo.rmsd(base_atoms, r["atoms"]), 3),
            "atoms": [[a[0], round(float(a[1]), 5), round(float(a[2]), 5), round(float(a[3]), 5)] for a in r["atoms"]],
        })
    # 기준 구조를 1번으로 두고 나머지는 역장 에너지 순
    doc = {
        "id": "CONF-" + time.strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:4].upper(),
        "molecule": {"name": (req.get("name") or "").strip()[:60] or calc_smiles,
                     "smiles": calc_smiles, "input_smiles": smiles,
                     "libraryId": req.get("libraryId"), "structure": structure,
                     "n_atoms": len(base_atoms)},
        "settings": {"reference": policy, "pattern": pattern if policy == "pattern" else ("T" if policy == "all-trans" else None),
                     "nConformers": n, "seed": seed, "pruneRms": prune,
                     "forcefield": info["forcefield"], "backbone": (ref_info or {}).get("backbone_elements"),
                     "n_generated": info["n_generated"], "n_kept": len(conformers)},
        "conformers": conformers,
        "rank_status": None,
        "createdAt": time.time(),
    }
    return _save(doc)


def reference_label(doc: dict) -> str:
    s = doc.get("settings") or {}
    if s.get("reference") == "all-trans":
        return "all-trans"
    if s.get("reference") == "pattern":
        return f"패턴 {s.get('pattern')}"
    return "최저 에너지"


# ── 작업 목록 묶음 ─────────────────────────────────────────────────────
#: 세트에서 제출한 작업의 이름 — «분자 이름 · conf #3» (범함수 비교면 뒤에 더 붙는다)
JOB_NAME_SEP = " · conf #"


def job_group(job: dict) -> dict | None:
    """작업 하나가 어느 conformer 세트에서 나왔는지 — 목록에서 한 줄로 묶는 열쇠.

    세트에서 제출한 작업은 material.conformer.set 에 세트 id 가 적혀 있어 그것이
    열쇠가 된다. 그 꼬리표가 없던 시절의 작업은 이름 앞부분(«분자 이름 · conf #3»
    의 «분자 이름»)을 열쇠로 쓴다 — 세트 id 는 알 수 없지만 같은 분자의 conformer
    끼리는 모인다. 세트에서 나온 작업이 아니면 None.
    """
    mat = job.get("material") or {}
    name = mat.get("name") or ""
    conf = mat.get("conformer") or {}
    settings = job.get("settings") or {}
    if conf.get("set"):
        return {"key": "set:" + str(conf["set"]), "setId": conf["set"],
                "name": name.split(JOB_NAME_SEP)[0].strip() or name,
                "index": conf.get("index"),
                "reference": conf.get("reference"),
                "structure": conf.get("structure") or settings.get("structure"),
                "nTotal": conf.get("n_total"),
                "resolvedBy": "set"}
    if JOB_NAME_SEP in name:
        mol, _, rest = name.partition(JOB_NAME_SEP)
        mol = mol.strip()
        m = re.match(r"\s*(\d+)", rest)
        return {"key": "name:" + mol, "setId": None, "name": mol,
                "index": int(m.group(1)) if m else None,
                "reference": None,
                "structure": settings.get("structure"),
                "nTotal": None,
                "resolvedBy": "name"}
    return None


def attach_job_groups(jobs: list[dict]) -> list[dict]:
    """작업 목록에 conformer 세트 묶음 정보를 붙인 얕은 사본을 돌려준다.

    저장된 작업 dict 를 그대로 고치면 jobs.json 에 파생값이 섞이므로 사본에 붙인다.
    """
    return [{**j, "conformerGroup": job_group(j)} for j in jobs]


# ── DFT 재순위 ─────────────────────────────────────────────────────────
def rank(set_id: str, indices: list[int], settings: dict | None = None) -> dict:
    """고른 conformer 만 단일점 DFT 로 다시 계산해 순위를 바로잡는다 (백그라운드).

    계산 큐(본 계산)와 별개로 돌며, 끝나면 세트 파일에 dft_energy 를 남긴다.
    """
    doc = get(set_id)
    if doc is None:
        raise KeyError(set_id)
    if _rank_threads.get(set_id) and _rank_threads[set_id].is_alive():
        raise RuntimeError("이 세트의 DFT 재순위가 이미 돌고 있습니다.")
    want = [c for c in doc["conformers"] if c["index"] in set(indices)]
    if len(want) < 1:
        raise ValueError("재순위할 conformer 를 고르세요.")
    doc["rank_status"] = {"state": "running", "done": 0, "total": len(want),
                          "started": time.time(), "indices": [c["index"] for c in want]}
    _save(doc)

    def worker():
        from . import engine, presets
        s = {**presets.DEFAULT_SETTINGS, "expert": dict(presets.DEFAULT_SETTINGS["expert"])}
        s.update(settings or {})
        s["expert"].update((settings or {}).get("expert") or {})
        params = engine._resolve_params(s)
        if s["expert"].get("basis"):
            params["basis_opt"] = s["expert"]["basis"]      # 재순위는 단일점 하나 — 요청한 기저로
        done, err = 0, None
        for c in want:
            try:
                e = _single_point(c["atoms"], params)
            except Exception as exc:  # noqa: BLE001 — 하나가 실패해도 나머지는 계속
                err = str(exc)[:200]
                continue
            with _lock:
                cur = get(set_id) or doc
                for rec in cur["conformers"]:
                    if rec["index"] == c["index"]:
                        rec["dft_energy_hartree"] = e
                done += 1
                base = [r.get("dft_energy_hartree") for r in cur["conformers"] if r.get("dft_energy_hartree") is not None]
                lo = min(base) if base else 0.0
                for rec in cur["conformers"]:
                    h = rec.get("dft_energy_hartree")
                    rec["dft_energy"] = round((h - lo) * HARTREE2KCAL, 3) if h is not None else None
                cur["rank_status"] = {**(cur.get("rank_status") or {}), "state": "running",
                                      "done": done, "total": len(want), "error": err}
                _save(cur)
        with _lock:
            cur = get(set_id) or doc
            cur["rank_status"] = {**(cur.get("rank_status") or {}), "state": "done", "done": done,
                                  "total": len(want), "finished": time.time(), "error": err,
                                  "method": f"{params['functional']}/{params['basis_opt']} 단일점"}
            _save(cur)

    t = threading.Thread(target=worker, name=f"rank-{set_id}", daemon=True)
    _rank_threads[set_id] = t
    t.start()
    return doc


def _single_point(atoms, params) -> float:
    """재순위용 단일점 — 본 계산의 모니터·원본 로그 전역을 건드리지 않도록 직접 만든다
    (계산 큐의 작업과 같은 프로세스에서 동시에 돌 수 있다)."""
    from pyscf import dft, gto, scf
    mol = gto.M(atom=[(a[0], (a[1], a[2], a[3])) for a in atoms], basis=params["basis_opt"],
                charge=params["charge"], spin=params["multiplicity"] - 1, unit="Angstrom", verbose=0)
    xc = params["xc"]
    if xc == "hf":
        mf = scf.RHF(mol) if mol.spin == 0 else scf.UHF(mol)
    else:
        mf = dft.RKS(mol, xc=xc) if mol.spin == 0 else dft.UKS(mol, xc=xc)
    mf = mf.density_fit()
    mf.conv_tol = params["scf_tol"]
    if params.get("disp"):
        try:
            mf.disp = params["disp"]
        except Exception:  # noqa: BLE001 — pyscf-dispersion 미설치
            pass
    e = float(mf.kernel())
    if not mf.converged:
        raise RuntimeError("SCF 가 수렴하지 않았습니다")
    return e


def job_targets(set_id: str, indices: list[int]) -> list[dict]:
    """계산 제출용 — 고른 conformer 마다 «업로드 3D 구조» 경로의 소재 하나."""
    doc = get(set_id)
    if doc is None:
        raise KeyError(set_id)
    picked = [c for c in doc["conformers"] if c["index"] in set(indices)]
    if not picked:
        raise ValueError("계산할 conformer 를 고르세요.")
    label = reference_label(doc)
    out = []
    for c in picked:
        out.append({
            "id": None,
            "name": f"{doc['molecule']['name']} · conf #{c['index']}",
            "abbr": "conformer",
            "smiles": doc["molecule"]["smiles"],
            "libraryId": doc["molecule"].get("libraryId"),
            "geometry": {"atoms": c["atoms"], "source": "conformer", "rescan": False},
            "conformer": {"set": doc["id"], "index": c["index"], "reference": label,
                          "structure": doc["molecule"].get("structure"),
                          "n_total": len(doc["conformers"]),
                          "ff_energy": c.get("ff_energy"), "dft_energy": c.get("dft_energy")},
        })
    return out
