"""Li⁺ 용매 경쟁 — v2.0 개정 기획서 P0-6 · 5.2.

지금까지 «이온 상호작용»은 고립된 Li⁺ 하나를 MEP 최소점에 놓고 잰 결합 에너지였다.
실제 전해액의 Li⁺ 는 이미 EC·EMC 같은 용매 2~4개에 둘러싸여 있으므로, 바인더가
Li⁺ 를 붙잡으려면 그 용매를 떼어내는 비용을 치러야 한다. 고립 Li⁺ 결합 에너지는
이 탈용매화 비용을 무시해 trapping 을 크게 과대평가한다.

그래서 기획서가 권하는 경쟁 반응을 계산한다.

    Binder + Li(solv)n⁺  ⇌  Binder·Li⁺ + n·solv

    ΔE_exchange = [E(Binder·Li⁺) + n·E(solv)] − [E(Binder) + E(Li(solv)n⁺)]

  ΔE_exchange < 0  바인더가 용매를 이기고 Li⁺ 를 붙잡는다 → trapping 위험
  ΔE_exchange > 0  용매가 이긴다 → Li⁺ 이동성 유지

모든 에너지는 같은 프로토콜(범함수·기저·SMD 용매)의 최종 단일점이다. 참조
클러스터 Li(solv)n⁺ 와 용매 분자 에너지는 용매·n·프로토콜이 같으면 후보마다 다시
계산하지 않고 data/li_reference.json 에 캐시한다.

이 모듈은 DFT 를 부르지 않는다 — 클러스터 초기 구조 생성, 결합 site 탐색, 에너지
조합, 판정, 캐시만 맡고 계산은 engine 이 한다.

한계 (결과에 그대로 표시):
  - 전자에너지(0 K) + SMD 기준이며 열보정(ΔG)은 포함하지 않는다. 41원자 클러스터의
    유한차분 Hessian 이 너무 무겁기 때문이다.
  - 배위수 n 은 고정값(기본 4)이며 배위수 앙상블·명시적 용매 microstate 는 아직 없다.
  - 바인더 쪽은 단량체/올리고머 조각의 site 별 결합이다.
"""

import json
import math
import os
import threading
import time

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem

from . import presets, store

HARTREE2KJ = 2625.4996
KB_KCAL = 1.98720425e-3
#: Li⁺–배위 원자 초기 거리 (Å) — DFT 최적화가 다듬는다
LI_DIST = 1.95
#: 판정 임계값 (kJ/mol, 잠정) — 벤치마크 전 초기 운영값
TRAP_KJ = -40.0
SOLVENT_DOMINANT_KJ = 60.0
DEFAULT_COORDINATION = 4
MODELS = ("bare", "competition")

# 배위 원자 우선순위 — 낮을수록 먼저
KIND_PRIORITY = {"카보닐 O": 0, "에테르 O": 1, "하이드록실 O": 2, "나이트릴 N": 3,
                 "아민 N": 4, "S": 5, "F": 6}


# ── 용매 성분 ────────────────────────────────────────────────────────
def solvent_components(settings: dict) -> list[dict]:
    """설정의 용매를 단일 성분 목록으로 — 혼합이면 성분마다 참조를 만든다."""
    if settings.get("envType") == "진공·기체":
        return []
    singles = {s["abbr"]: s for s in presets.SOLVENTS if s["kind"] == "single"}
    custom = settings.get("customMixedSolvent")
    if custom:
        out = []
        for c in custom["components"]:
            s = singles.get(c["abbr"])
            if s:
                out.append({"abbr": s["abbr"], "name": s["name"], "smiles": s["smiles"],
                            "ratio": float(c["ratio"])})
        return out
    sol = presets.SOLVENTS_BY_ID.get(settings.get("solventId") or "")
    if not sol:
        return []
    if sol["kind"] == "mixed":
        return [{"abbr": c["abbr"], "name": singles[c["abbr"]]["name"],
                 "smiles": singles[c["abbr"]]["smiles"], "ratio": float(c["ratio"])}
                for c in sol["components"] if c["abbr"] in singles]
    return [{"abbr": sol["abbr"], "name": sol["name"], "smiles": sol["smiles"], "ratio": 1.0}]


# ── 기하 ─────────────────────────────────────────────────────────────
def _embed(smiles: str, seed: int = 42):
    mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
    params = AllChem.ETKDGv3()
    params.randomSeed = seed
    if AllChem.EmbedMolecule(mol, params) < 0:
        params.useRandomCoords = True
        AllChem.EmbedMolecule(mol, params)
    try:
        AllChem.MMFFOptimizeMolecule(mol, maxIters=2000)
    except Exception:  # noqa: BLE001
        pass
    conf = mol.GetConformer()
    xyz = np.array([[conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y,
                     conf.GetAtomPosition(i).z] for i in range(mol.GetNumAtoms())])
    return mol, xyz


def atom_kind(atom) -> str | None:
    """Li⁺ 배위 가능한 원자의 종류 — 아니면 None."""
    s = atom.GetSymbol()
    if s == "O":
        if any(b.GetBondTypeAsDouble() == 2.0 for b in atom.GetBonds()):
            return "카보닐 O"
        if atom.GetTotalNumHs() > 0:
            return "하이드록실 O"
        return "에테르 O"
    if s == "N":
        if atom.GetFormalCharge() > 0 or atom.GetDegree() >= 4:
            return None
        if any(b.GetBondTypeAsDouble() == 3.0 for b in atom.GetBonds()):
            return "나이트릴 N"
        if atom.GetIsAromatic() and atom.GetTotalNumHs() > 0:
            return None                      # 피롤형 N — 고립쌍이 π 에 쓰인다
        return "아민 N"
    if s in ("S", "F"):
        return s
    return None


def coordinating_atom(mol) -> int:
    """용매 분자에서 Li⁺ 가 배위할 원자 — 카보닐 O > 에테르 O > … 순."""
    best = None
    for atom in mol.GetAtoms():
        kind = atom_kind(atom)
        if kind is None:
            continue
        pri = KIND_PRIORITY[kind]
        if best is None or pri < best[0]:
            best = (pri, atom.GetIdx())
    return best[1] if best else 0


def directions(n: int) -> np.ndarray:
    """배위수별 이상 다면체 방향 — 1 단일, 2 선형, 3 삼각평면, 4 사면체, 5 삼각쌍뿔, 6 팔면체."""
    z = np.array([0.0, 0.0, 1.0])
    if n <= 1:
        return np.array([z])
    if n == 2:
        return np.array([z, -z])
    if n == 3:
        return np.array([[math.cos(a), math.sin(a), 0.0] for a in (0, 2 * math.pi / 3, 4 * math.pi / 3)])
    if n == 4:
        t = np.array([[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]], dtype=float)
        return t / math.sqrt(3)
    if n == 5:
        tri = [[math.cos(a), math.sin(a), 0.0] for a in (0, 2 * math.pi / 3, 4 * math.pi / 3)]
        return np.array(tri + [z, -z])
    return np.array([z, -z, [1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0]], dtype=float)


def _rot_align(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """단위벡터 a 를 b 로 보내는 회전 (Rodrigues)."""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-8:
        if c > 0:
            return np.eye(3)
        # 반대 방향 — a 에 수직인 아무 축으로 180°
        p = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        axis = np.cross(a, p)
        axis /= np.linalg.norm(axis)
        return _rot_axis(axis, math.pi)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))


def _rot_axis(axis: np.ndarray, ang: float) -> np.ndarray:
    axis = axis / np.linalg.norm(axis)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + math.sin(ang) * k + (1 - math.cos(ang)) * (k @ k)


def build_li_cluster(solv_smiles: str, n: int, li_dist: float = LI_DIST, seed: int = 42):
    """Li(solv)n⁺ 초기 구조 — 배위 원자가 Li⁺ 쪽을 향하도록 다면체 방향에 배치.

    MMFF 는 Li⁺ 를 제대로 다루지 못해(용매가 4 Å 밖에 머문다) 역장 이완 대신
    기하학적으로 놓고 DFT 최적화에 맡긴다. 각 분자는 자기 축 둘레로 돌려 이미 놓인
    분자와 가장 멀어지는 자세를 고른다.

    Returns: atoms [(sym, x, y, z), ...] — Li 가 첫 원자, fragments 정보.
    """
    mol, xyz = _embed(solv_smiles, seed)
    ca = coordinating_atom(mol)
    syms = [a.GetSymbol() for a in mol.GetAtoms()]
    shell = xyz - xyz[ca]                        # 배위 원자를 원점에
    v = shell.mean(axis=0)
    if np.linalg.norm(v) < 1e-3:                 # 단원자·대칭 — 임의 축
        v = np.array([0.0, 0.0, 1.0])
    atoms = [("Li", 0.0, 0.0, 0.0)]
    placed = np.zeros((0, 3))
    frags = [{"label": "Li⁺", "start": 0, "end": 1, "smiles": "[Li+]"}]
    for k, u in enumerate(directions(int(n))):
        base = shell @ _rot_align(v, u).T + u * li_dist
        best, best_d = base, -1.0
        for ang in np.linspace(0, 2 * math.pi, 24, endpoint=False):
            cand = base @ _rot_axis(u, ang).T
            if placed.shape[0]:
                d = np.linalg.norm(cand[:, None, :] - placed[None, :, :], axis=2).min()
            else:
                d = float("inf")
            if d > best_d:
                best, best_d = cand, d
        start = len(atoms)
        atoms.extend((s, float(p[0]), float(p[1]), float(p[2])) for s, p in zip(syms, best))
        frags.append({"label": f"{solv_smiles} #{k + 1}", "start": start, "end": len(atoms),
                      "smiles": solv_smiles})
        placed = np.vstack([placed, best])
    return atoms, frags


def cluster_stats(atoms) -> dict:
    """Li–배위 원자 거리와 분자 간 최소 거리 — 초기 구조 sanity."""
    xyz = np.array([a[1:4] for a in atoms])
    li = xyz[0]
    d_li = np.linalg.norm(xyz[1:] - li, axis=1)
    return {"n_atoms": len(atoms), "li_min": round(float(d_li.min()), 3),
            "li_max": round(float(d_li.max()), 3)}


# ── 바인더 결합 site 탐색 ─────────────────────────────────────────────
def li_sites(atoms, smiles: str | None, mep_site=None, max_sites: int = 3,
             li_dist: float = LI_DIST) -> list[dict]:
    """Li⁺ 를 놓아 볼 site 목록 — MEP 최소점 + 헤테로원자(고립쌍) 부위.

    max_sites=1 이면 예전처럼 MEP 최소점 하나만 쓴다. 헤테로원자 site 는 SMILES 의
    원자 순서가 좌표와 일치할 때만(엔진의 conformer 경로) 만든다.
    """
    out = []
    if mep_site is not None:
        out.append({"label": "MEP 최소점", "kind": "MEP", "atom": None,
                    "pos": [float(x) for x in mep_site]})
    if max_sites <= 1 and out:
        return out[:1]
    xyz = np.array([a[1:4] for a in atoms], dtype=float)
    syms = [a[0] for a in atoms]
    cands = []
    if smiles:
        mol = Chem.MolFromSmiles(smiles)
        if mol is not None:
            mol = Chem.AddHs(mol)
            if mol.GetNumAtoms() == len(atoms) and [a.GetSymbol() for a in mol.GetAtoms()] == syms:
                for atom in mol.GetAtoms():
                    kind = atom_kind(atom)
                    if kind is None:
                        continue
                    i = atom.GetIdx()
                    nbrs = [n.GetIdx() for n in atom.GetNeighbors()]
                    if not nbrs:
                        continue
                    d = xyz[i] - xyz[nbrs].mean(axis=0)
                    if np.linalg.norm(d) < 1e-3:
                        continue
                    pos = xyz[i] + d / np.linalg.norm(d) * li_dist
                    cands.append((KIND_PRIORITY[kind], i, kind, pos))
    cands.sort(key=lambda t: (t[0], t[1]))
    for pri, i, kind, pos in cands:
        if any(np.linalg.norm(np.array(o["pos"]) - pos) < 1.6 for o in out):
            continue
        out.append({"label": f"{syms[i]}{i + 1} ({kind})", "kind": kind, "atom": i + 1,
                    "pos": [float(x) for x in pos]})
    if not out and len(atoms):
        # 헤테로원자가 없고 MEP 도 없으면 — 질량중심 위쪽
        c = xyz.mean(axis=0)
        out.append({"label": "질량중심 위", "kind": "fallback", "atom": None,
                    "pos": [float(c[0]), float(c[1]), float(c[2] + 2.5)]})
    return out[:max(1, int(max_sites))]


# ── 에너지 조합·판정 ─────────────────────────────────────────────────
def exchange_kj(e_complex: float, e_binder: float, ref: dict) -> float:
    """ΔE_exchange (kJ/mol) — 참조 dict 의 e_cluster·e_solvent·n 사용."""
    n = int(ref["n"])
    return (e_complex + n * ref["e_solvent"] - e_binder - ref["e_cluster"]) * HARTREE2KJ


def verdict(dE_kj: float | None) -> dict:
    if dE_kj is None:
        return {"key": "n/a", "label": "판정 불가", "note": "용매 경쟁 값 없음"}
    if dE_kj < TRAP_KJ:
        return {"key": "trapping", "label": "Li⁺ trapping 위험",
                "note": f"바인더가 용매 껍질을 이기고 Li⁺ 를 붙잡는다 (ΔE_exchange {dE_kj:+.0f} kJ/mol < {TRAP_KJ:.0f})"}
    if dE_kj <= SOLVENT_DOMINANT_KJ:
        return {"key": "competitive", "label": "용매와 경쟁",
                "note": f"바인더와 용매의 Li⁺ 배위가 대등 ({TRAP_KJ:.0f} ≤ {dE_kj:+.0f} ≤ {SOLVENT_DOMINANT_KJ:.0f} kJ/mol)"}
    return {"key": "solvent", "label": "용매 우세",
            "note": f"용매 껍질이 유지된다 — Li⁺ 이동성 확보 (ΔE_exchange {dE_kj:+.0f} > {SOLVENT_DOMINANT_KJ:.0f} kJ/mol)"}


def summarize(sites: list[dict], refs: list[dict], e_binder: float, temperature: float,
              model: str, n: int) -> dict:
    """site 별 결합·경쟁 값과 분포·대푯값을 한 벌로.

    sites: [{"label","kind","e_complex","binding_kj",...}]  (e_complex: 착물 총 에너지, Ha)
    refs:  [{"abbr","n","e_cluster","e_solvent","e_li","solvation_kj_per_molecule",...}]
    """
    out = {"model": model, "coordination": n, "n_sites": len(sites), "sites": [], "references": []}
    if not sites:
        return out
    kT = KB_KCAL * temperature
    e_min = min(s["e_complex"] for s in sites)
    ws = [math.exp(-(s["e_complex"] - e_min) * 627.5095 / kT) for s in sites]
    z = sum(ws)
    primary = None
    if refs:
        primary = min(refs, key=lambda r: r["solvation_kj_per_molecule"])
    for s, w in zip(sites, ws):
        row = {"label": s["label"], "kind": s.get("kind"), "binding_kj": s["binding_kj"],
               "rel_e_kcal": round((s["e_complex"] - e_min) * 627.5095, 2),
               "population_pct": round(100 * w / z, 1), "exchange_kj": {}}
        for r in refs:
            row["exchange_kj"][r["abbr"]] = round(exchange_kj(s["e_complex"], e_binder, r), 1)
        if primary:
            row["exchange_primary_kj"] = row["exchange_kj"][primary["abbr"]]
        out["sites"].append(row)
    for r in refs:
        out["references"].append({k: r.get(k) for k in
                                  ("abbr", "name", "n", "solvation_kj_per_molecule", "cached",
                                   "optimized", "n_atoms", "wall_s", "created")})
    strongest = min(out["sites"], key=lambda r: r["binding_kj"])
    out["strongest_site"] = strongest["label"]
    out["binding_min_kj"] = strongest["binding_kj"]
    out["binding_boltzmann_kj"] = round(sum(r["binding_kj"] * r["population_pct"] / 100
                                            for r in out["sites"]), 1)
    if primary:
        out["primary_solvent"] = primary["abbr"]
        trap = min(out["sites"], key=lambda r: r["exchange_primary_kj"])
        out["exchange_min_kj"] = trap["exchange_primary_kj"]
        out["exchange_min_site"] = trap["label"]
        out["exchange_boltzmann_kj"] = round(sum(r["exchange_primary_kj"] * r["population_pct"] / 100
                                                 for r in out["sites"]), 1)
        out["verdict"] = verdict(out["exchange_min_kj"])
        out["thresholds_kj"] = {"trapping": TRAP_KJ, "solvent_dominant": SOLVENT_DOMINANT_KJ}
    out["note"] = _note(out)
    return out


def _note(s: dict) -> str:
    head = (f"Li⁺ site {s['n_sites']}개 — 가장 강한 결합 {s['strongest_site']} "
            f"({s['binding_min_kj']:+.0f} kJ/mol, CP 보정). ")
    if s.get("primary_solvent"):
        v = s["verdict"]
        return head + (f"용매 경쟁 Li({s['primary_solvent']}){s['coordination']}⁺ 대비 ΔE_exchange "
                       f"{s['exchange_min_kj']:+.0f} kJ/mol ({s['exchange_min_site']}) → {v['label']}. "
                       "전자에너지+SMD 기준(열보정 미포함), 배위수 고정.")
    return head + "용매 경쟁 미계산 — 고립 Li⁺ 결합은 탈용매화 비용을 무시해 trapping 을 과대평가합니다."


# ── 참조 클러스터 캐시 ────────────────────────────────────────────────
_lock = threading.Lock()
_CACHE_OVERRIDE = None


def cache_path():
    return _CACHE_OVERRIDE or (store.DATA_DIR / "li_reference.json")


def reference_key(comp_smiles: str, n: int, params: dict, solvent_key: str | None) -> str:
    body = {"solvent": comp_smiles, "n": int(n), "functional": params.get("functional"),
            "basis_opt": params.get("basis_opt"), "basis_sp": params.get("basis_sp"),
            "disp": params.get("disp"), "smd": solvent_key, "do_opt": bool(params.get("do_opt")),
            "opt_in_solvent": bool(params.get("opt_in_solvent")), "scf_tol": params.get("scf_tol")}
    return json.dumps(body, sort_keys=True, ensure_ascii=False)


def _load() -> dict:
    p = cache_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def get_reference(comp: dict, n: int, params: dict, solvent_key: str | None, compute):
    """캐시에 있으면 그것을, 없으면 compute() 로 만들어 저장한다."""
    key = reference_key(comp["smiles"], n, params, solvent_key)
    with _lock:
        cache = _load()
        hit = cache.get(key)
    if hit:
        return {**hit, "cached": True, "abbr": comp["abbr"], "name": comp.get("name"), "n": int(n)}
    t0 = time.time()
    ref = compute()
    ref.update({"abbr": comp["abbr"], "name": comp.get("name"), "smiles": comp["smiles"],
                "n": int(n), "created": time.strftime("%Y-%m-%d %H:%M"),
                "wall_s": round(time.time() - t0, 1), "key": key,
                "solvation_kj_per_molecule": round(
                    (ref["e_cluster"] - ref["e_li"] - n * ref["e_solvent"]) * HARTREE2KJ / n, 1)})
    with _lock:
        cache = _load()
        cache[key] = ref
        try:
            p = cache_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            pass
    return {**ref, "cached": False}


def get_constant(key: str, compute):
    """프로토콜별 상수(예: 고립 Li⁺ 에너지) — 한 번 계산해 같은 캐시 파일에 둔다."""
    with _lock:
        cache = _load()
        hit = cache.get(key)
    if hit is not None:
        return hit
    val = compute()
    with _lock:
        cache = _load()
        cache[key] = val
        try:
            p = cache_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            pass
    return val


def list_references() -> list[dict]:
    with _lock:
        cache = _load()
    return [{k: v.get(k) for k in ("abbr", "name", "smiles", "n", "solvation_kj_per_molecule",
                                    "created", "wall_s", "optimized", "n_atoms", "key")}
            for v in cache.values() if isinstance(v, dict)]
