"""분자 라이브러리 — «분자 검색 및 선택»·«분자 라이브러리» 화면과 계산 화면이 함께 쓰는 서버 저장소.

예전에는 물질 보관함·용매 라이브러리가 브라우저(localStorage)에 따로 있었다. 이제 모든 분자를
하나의 레코드 목록으로 서버(data/library.json)에 두고 모든 PC·사용자가 같은 목록을 본다.

  · 기본 레코드(builtin): 소재 프리셋(바인더 모노머) · 용매 프리셋 · 전해액 첨가제/염 · 벤치마크 올리고머.
    코드에서 만들고 파일에는 즐겨찾기·태그·메모 같은 덮어쓰기(overrides)만 저장한다.
  · 사용자 레코드: SMILES/InChI 로 등록. RDKit 으로 파싱·원자가 검사 후 저장한다.
  · 역할(roles): "solute"(계산 대상) · "solvent"(SMD 파라미터 보유 → 용매로 선택 가능). 둘 다 가질 수 있다.
  · 혼합 용매(mixtures): 라이브러리 용매 성분 + 비율(부피비·몰비·질량비). 계산에서는 성분 SMD 파라미터의
    부피분율 가중 평균(유효 매질 근사)으로 쓴다. 몰비·질량비는 몰질량·밀도로 부피분율로 환산한다.

검색: 이름·화학식(동분자식 이성질체는 각각) / 구조 완전 일치(InChIKey) / 부분구조(SMARTS) / 유사도(Morgan r=2 Tanimoto).
"""

import functools
import json
import re
import threading
import time
import uuid

from rdkit import Chem, DataStructs, RDLogger
from rdkit.Chem import AllChem, Descriptors, rdMolDescriptors
from rdkit.Chem.Draw import rdMolDraw2D

from . import presets, store

RDLogger.DisableLog("rdApp.*")

_lock = threading.RLock()

CATEGORIES = [
    ("monomer", "바인더 모노머"), ("polymer", "고분자·올리고머"), ("solvent", "용매"),
    ("additive", "첨가제"), ("salt", "리튬염·이온"), ("other", "기타"),
]
CATEGORY_IDS = {c for c, _ in CATEGORIES}
ROLES = ("solute", "solvent")
BASES = ("부피비", "몰비", "질량비")

# 기능기 (라이브러리 필터·유사 분자 설명용). 순서 = 표시 순서
FGROUPS = [
    ("비닐", "[CX3;!a]=[CX3;!a]"), ("카보네이트", "[OX2][CX3](=O)[OX2]"),
    ("에스터", "[#6][CX3](=O)[OX2][#6]"), ("카복실산", "[CX3](=O)[OX2H1]"),
    ("니트릴", "C#N"), ("플루오린", "[F]"), ("방향족", "[c;r6]"), ("아민·아마이드", "[NX3;!$(N=*)]"),
    ("에터", "[OD2;!$(O-C=O)]([#6])[#6]"), ("설포닐", "[SX4](=O)(=O)"), ("할로젠(Cl·Br·I)", "[Cl,Br,I]"),
]
_FG_PATTS = [(n, Chem.MolFromSmarts(s)) for n, s in FGROUPS]

# 용매 밀도 (g/mL, 25 °C 부근 · EC 는 40 °C 액상) — 몰비·질량비 → 부피분율 환산용
_SOLVENT_DENSITY = {"sol-ec": 1.321, "sol-dmc": 1.069, "sol-emc": 1.006, "sol-water": 0.997, "sol-nmp": 1.028}
_SOLVENT_CAS = {"sol-ec": "96-49-1", "sol-dmc": "616-38-6", "sol-emc": "623-53-0",
                "sol-water": "7732-18-5", "sol-nmp": "872-50-4"}
# 소재 프리셋의 표시명 — 공식·보편 약어 또는 영어 (사용자 요청)
_MATERIAL_META = {
    "vdf": ("VDF", "Vinylidene fluoride (PVDF repeat unit)", "75-38-7"),
    "aa": ("AA", "Acrylic acid (PAA repeat unit)", "79-10-7"),
    "styrene": ("Styrene", "Styrene (SBR monomer)", "100-42-5"),
    "an": ("AN", "Acrylonitrile (PAN repeat unit)", "107-13-1"),
    "mma": ("MMA", "Methyl methacrylate (PMMA repeat unit)", "80-62-6"),
}
# 전해액 첨가제·염 (기본 레코드)
_EXTRA = [
    {"key": "fec", "name": "FEC", "full": "Fluoroethylene carbonate", "smiles": "O=C1OCC(F)O1",
     "cas": "114435-02-8", "category": "additive", "tags": ["SEI 첨가제", "전해액"]},
    {"key": "vc", "name": "VC", "full": "Vinylene carbonate", "smiles": "O=C1OC=CO1",
     "cas": "872-36-6", "category": "additive", "tags": ["SEI 첨가제", "전해액"]},
    {"key": "sn", "name": "SN", "full": "Succinonitrile", "smiles": "N#CCCC#N",
     "cas": "110-61-2", "category": "additive", "tags": ["고전압 첨가제", "전해액"]},
    {"key": "lipf6", "name": "LiPF₆", "full": "Lithium hexafluorophosphate (ion pair)",
     "smiles": "[Li+].F[P-](F)(F)(F)(F)F", "cas": "21324-40-3", "category": "salt",
     "tags": ["리튬염", "이온쌍"], "note": "이온쌍(두 조각) — 음이온만 계산하려면 PF₆⁻ 레코드를 쓰세요"},
    {"key": "pf6", "name": "PF₆⁻", "full": "Hexafluorophosphate anion", "smiles": "F[P-](F)(F)(F)(F)F",
     "cas": None, "category": "salt", "tags": ["음이온", "리튬염"]},
    {"key": "tfsi", "name": "TFSI⁻", "full": "Bis(trifluoromethanesulfonyl)imide anion",
     "smiles": "FC(F)(F)S(=O)(=O)[N-]S(=O)(=O)C(F)(F)F", "cas": None, "category": "salt",
     "tags": ["음이온", "리튬염"]},
]


# ── RDKit 도우미 ─────────────────────────────────────────────────────
@functools.lru_cache(maxsize=4096)
def _mol(smiles: str):
    return Chem.MolFromSmiles(smiles) if smiles else None


@functools.lru_cache(maxsize=4096)
def canonical(smiles: str) -> str | None:
    m = _mol(smiles)
    return Chem.MolToSmiles(m) if m is not None else None


def _largest_fragment(mol):
    frags = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=False)
    return max(frags, key=lambda f: f.GetNumHeavyAtoms()) if len(frags) > 1 else mol


def _identity_key(mol, stereo: bool = False, strip_salts: bool = False) -> str | None:
    """구조 완전 일치 비교 키 — InChIKey (입체 무시면 앞 14자 = 연결성)."""
    if mol is None:
        return None
    if strip_salts:
        mol = _largest_fragment(mol)
    try:
        key = Chem.MolToInchiKey(mol)
    except Exception:  # noqa: BLE001 — InChI 미지원 빌드: 정규 SMILES 로 대체
        key = Chem.MolToSmiles(mol, isomericSmiles=stereo)
        return key
    if not key:
        return Chem.MolToSmiles(mol, isomericSmiles=stereo)
    return key if stereo else key.split("-")[0]


@functools.lru_cache(maxsize=4096)
def _fingerprint(smiles: str):
    m = _mol(smiles)
    if m is None:
        return None
    try:
        from rdkit.Chem import rdFingerprintGenerator
        return rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048).GetFingerprint(m)
    except Exception:  # noqa: BLE001 — 구버전 RDKit
        return AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)


@functools.lru_cache(maxsize=2048)
def depict(smiles: str, w: int = 200, h: int = 120, highlight: tuple = ()) -> str:
    """2D 구조 SVG (배경 투명). highlight = 강조할 원자 인덱스 (부분구조 일치)."""
    m = _mol(smiles)
    if m is None:
        return ""
    m = Chem.Mol(m)
    AllChem.Compute2DCoords(m)
    d = rdMolDraw2D.MolDraw2DSVG(w, h)
    o = d.drawOptions()
    o.clearBackground = False
    o.padding = 0.12
    try:
        o.bondLineWidth = 1.6
    except Exception:  # noqa: BLE001
        pass
    kw = {}
    if highlight:
        hl = list(highlight)
        bonds = [b.GetIdx() for b in m.GetBonds() if b.GetBeginAtomIdx() in hl and b.GetEndAtomIdx() in hl]
        kw = {"highlightAtoms": hl, "highlightBonds": bonds}
    rdMolDraw2D.PrepareAndDrawMolecule(d, m, **kw)
    d.FinishDrawing()
    svg = d.GetDrawingText()
    return svg[svg.find("<svg"):].replace("\n", "")


def _fgroups(mol) -> list[str]:
    return [n for n, p in _FG_PATTS if p is not None and mol.HasSubstructMatch(p)]


def _formula_counts(formula: str) -> dict:
    out = {}
    for el, n in re.findall(r"([A-Z][a-z]?)(\d*)", formula or ""):
        out[el] = out.get(el, 0) + (int(n) if n else 1)
    return out


_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁺⁻", "0123456789+-")


def _looks_like_formula(q: str) -> bool:
    q = q.translate(_SUB).replace(" ", "")
    return bool(re.fullmatch(r"(?:[A-Z][a-z]?\d*){2,}[+-]?", q)) and any(ch.isdigit() for ch in q)


def describe(smiles: str) -> dict:
    """SMILES → 식별·구조 필드 (레코드에 저장되는 계산값)."""
    m = _mol(smiles)
    if m is None:
        raise ValueError(f"SMILES 를 해석할 수 없습니다: {smiles}")
    mh = Chem.AddHs(m)
    return {
        "canonical": Chem.MolToSmiles(m),
        "inchikey": _identity_key(m, stereo=True),
        "formula": rdMolDescriptors.CalcMolFormula(m),
        "mw": round(Descriptors.MolWt(m), 3),
        "charge": Chem.GetFormalCharge(m),
        "elements": sorted({a.GetSymbol() for a in mh.GetAtoms()}),
        "n_atoms": mh.GetNumAtoms(),
        "n_heavy": m.GetNumHeavyAtoms(),
        "fragments": len(Chem.GetMolFrags(m)),
        "stereo_centers": len(Chem.FindMolChiralCenters(m, includeUnassigned=True)),
        "groups": _fgroups(m),
    }


def parse(text: str, kind: str = "auto") -> dict:
    """입력 검증 — 파싱 · 원자가 검사 · 정규화. 오류는 원자 번호와 함께 돌려준다."""
    t = (text or "").strip()
    if not t:
        return {"ok": False, "error": "입력이 비어 있습니다."}
    is_inchi = kind == "inchi" or t.startswith("InChI=")
    if is_inchi:
        try:
            m = Chem.MolFromInchi(t, sanitize=True)
        except Exception:  # noqa: BLE001
            m = None
        if m is None:
            return {"ok": False, "error": "InChI 를 해석할 수 없습니다 — «InChI=1S/…» 형식인지 확인하세요."}
    else:
        m = Chem.MolFromSmiles(t, sanitize=False)
        if m is None:
            hints = []
            if t.count("(") != t.count(")"):
                hints.append(f"괄호 짝이 맞지 않습니다 (여는 괄호 {t.count('(')}개 · 닫는 괄호 {t.count(')')}개)")
            if t.count("[") != t.count("]"):
                hints.append("대괄호 [ ] 짝이 맞지 않습니다")
            ring = re.sub(r"\[[^\]]*\]", "", t)
            for d in set(re.findall(r"%\d\d|\d", ring)):
                if ring.count(d) % 2:
                    hints.append(f"고리 번호 {d} 가 한 번만 쓰였습니다")
            if re.search(r"^[=#]|[=#]$|[=#]{2}", t):
                hints.append("결합 기호(= #) 위치가 잘못되었습니다")
            bad = [tok for tok in re.findall(r"(?<!\[)[A-Z][a-z]?", re.sub(r"\[[^\]]*\]", "", t))
                   if tok not in ("B", "C", "N", "O", "P", "S", "F", "I", "Cl", "Br")]
            if bad:
                hints.append(f"대괄호 없이 쓸 수 없는 원소: {', '.join(sorted(set(bad)))} (예: [Li+])")
            return {"ok": False, "error": "SMILES 문법 오류" + (" — " + " · ".join(hints) if hints else "")}
        problems = Chem.DetectChemistryProblems(m)
        if problems:
            msgs = []
            for p in problems[:3]:
                idx = p.GetAtomIdx() if hasattr(p, "GetAtomIdx") else None
                where = f"원자 {idx + 1} ({m.GetAtomWithIdx(idx).GetSymbol()})" if idx is not None else ""
                kind_ = "원자가 초과" if "Valence" in p.GetType() else ("방향족 고리 해석 실패" if "Kekul" in p.GetType() else p.GetType())
                msgs.append(f"{kind_} {where}".strip())
            return {"ok": False, "error": " · ".join(msgs) + " — 결합 차수나 전하를 확인하세요.",
                    "problems": [p.Message() for p in problems[:3]]}
        Chem.SanitizeMol(m)
    smi = Chem.MolToSmiles(m)
    info = describe(smi)
    existing = find_by_key(info["inchikey"])
    return {"ok": True, "input": t, **info, "svg": depict(smi, 260, 160),
            "existing": existing["id"] if existing else None,
            "existing_name": existing["name"] if existing else None}


# ── 기본 레코드 ───────────────────────────────────────────────────────
def _builtin_records() -> list[dict]:
    recs = []
    for m in presets.MATERIALS:
        name, full, cas = _MATERIAL_META.get(m["id"], (m.get("abbr") or m["name"], m["name"], None))
        recs.append({"id": "MOL-" + m["id"].upper(), "name": name, "full": full,
                     "smiles": m["smiles"]["모노머"], "cas": cas, "category": "monomer",
                     "roles": ["solute"], "tags": ["바인더 모노머"], "note": m.get("note") or "",
                     "presetId": m["id"], "oligomers": {k: v for k, v in m["smiles"].items() if k != "모노머"},
                     "source": "프리셋"})
    for s in presets.SOLVENTS:
        if s["kind"] != "single":
            continue
        abbr = "Water" if s["abbr"] == "H2O" else s["abbr"]
        recs.append({"id": "MOL-" + s["id"].split("-", 1)[1].upper(), "name": abbr, "full": s["name"],
                     "smiles": s["smiles"], "cas": _SOLVENT_CAS.get(s["id"]), "category": "solvent",
                     "roles": ["solvent", "solute"], "tags": ["SMD"], "note": s.get("note") or "",
                     "solventId": s["id"], "density": _SOLVENT_DENSITY.get(s["id"]),
                     "source": "프리셋 (구 용매 라이브러리)"})
    for e in _EXTRA:
        recs.append({"id": "MOL-" + e["key"].upper(), "name": e["name"], "full": e["full"],
                     "smiles": e["smiles"], "cas": e.get("cas"), "category": e["category"],
                     "roles": ["solute"], "tags": list(e.get("tags") or []), "note": e.get("note") or "",
                     "source": "프리셋 (전해액)"})
    try:
        from . import benchmark
        for set_id, doc in benchmark._load_all().items():
            for ent in doc.get("entries", []):
                if not ent.get("smiles"):
                    continue
                en = {"ptfe": "PTFE trimer", "pvdf": "PVDF trimer", "parafilm": "n-Hexane (paraffin trimer)"}
                recs.append({"id": f"MOL-BENCH-{ent['id'].upper()}", "name": en.get(ent["id"], ent["id"]),
                             "full": f"{ent.get('model', '')} · H-capped (benchmark geometry)",
                             "smiles": ent["smiles"], "cas": None, "category": "polymer",
                             "roles": ["solute"], "tags": ["올리고머 n=3", "벤치마크"],
                             "note": f"벤치마크 세트 {set_id} 좌표 — «벤치마크» 메뉴에서 논문 값과 비교",
                             "source": f"벤치마크 ({doc.get('id', set_id)})"})
    except Exception:  # noqa: BLE001 — 벤치마크 파일이 없어도 라이브러리는 동작
        pass
    for r in recs:
        r["builtin"] = True
    return recs


_BUILTIN_MIXTURES = [
    {"id": "sol-ecdmc", "name": "EC/DMC 1:1", "basis": "부피비",
     "components": [{"id": "MOL-EC", "ratio": 1}, {"id": "MOL-DMC", "ratio": 1}],
     "builtin": True, "presetSolventId": "sol-ecdmc",
     "note": "표준 전해액 베이스 — 프리셋 SMD 파라미터(부피분율 가중 평균)"},
]


# ── 저장소 ────────────────────────────────────────────────────────────
def _path():
    return store.DATA_DIR / "library.json"


def _load() -> dict:
    p = _path()
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            d.setdefault("molecules", []); d.setdefault("mixtures", []); d.setdefault("overrides", {})
            return d
        except (json.JSONDecodeError, OSError):
            pass
    return {"version": 1, "molecules": [], "mixtures": [], "overrides": {}}


def _save(d: dict):
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


_BUILTIN_CACHE = None


def _builtins():
    global _BUILTIN_CACHE
    if _BUILTIN_CACHE is None:
        out = []
        for r in _builtin_records():
            try:
                out.append({**r, **describe(r["smiles"])})
            except ValueError:
                continue
        _BUILTIN_CACHE = out
    return _BUILTIN_CACHE


def molecules() -> list[dict]:
    """전체 레코드 (기본 + 사용자). 기본 레코드에는 덮어쓰기(즐겨찾기·태그·메모)를 반영."""
    with _lock:
        d = _load()
        ov = d["overrides"]
        out = []
        for r in _builtins():
            o = ov.get(r["id"], {})
            out.append({**r, "fav": bool(o.get("fav", False)),
                        "tags": o.get("tags", r["tags"]), "note": o.get("note", r.get("note", ""))})
        for r in d["molecules"]:
            out.append({**r, "builtin": False, "fav": bool(r.get("fav", False))})
        return out


def get(mol_id: str) -> dict | None:
    return next((m for m in molecules() if m["id"] == mol_id), None)


def find_by_key(inchikey: str | None) -> dict | None:
    if not inchikey:
        return None
    return next((m for m in molecules() if m.get("inchikey") == inchikey), None)


def mixtures() -> list[dict]:
    with _lock:
        return [dict(m) for m in _BUILTIN_MIXTURES] + [{**m, "builtin": False} for m in _load()["mixtures"]]


def _clean_tags(tags) -> list[str]:
    out = []
    for t in tags or []:
        t = str(t).strip()[:30]
        if t and t not in out:
            out.append(t)
    return out[:12]


def _smd_vector(p: dict | None) -> list | None:
    """사용자 용매의 SMD 파라미터 → PySCF solvent_db 8-벡터 [n, n25, α, β, γ, ε, φ, ψ]."""
    if not p:
        return None
    try:
        n = float(p["n"]); eps = float(p["eps"])
        alpha = float(p.get("alpha", 0) or 0); beta = float(p.get("beta", 0) or 0)
        gamma = float(p.get("gamma", 0) or 0)
        phi = float(p.get("phi", 0) or 0); psi = float(p.get("psi", 0) or 0)
    except (KeyError, TypeError, ValueError):
        raise ValueError("용매 SMD 파라미터는 굴절률 n 과 유전율 ε 가 필요합니다.")
    if not (1.0 <= n <= 2.0):
        raise ValueError("굴절률 n 은 1.0–2.0 범위여야 합니다.")
    if not (1.0 <= eps <= 200):
        raise ValueError("유전율 ε 는 1–200 범위여야 합니다.")
    if not (0 <= alpha <= 2 and 0 <= beta <= 2 and 0 <= gamma <= 200):
        raise ValueError("α·β 는 0–2, 표면장력 γ 는 0–200 cal/mol·Å² 범위여야 합니다.")
    return [n, n, alpha, beta, gamma, eps, phi, psi]


def add_molecule(req: dict) -> dict:
    """사용자 레코드 등록 — 같은 구조(InChIKey)가 이미 있으면 ValueError(기존 id 포함)."""
    text = (req.get("smiles") or req.get("inchi") or "").strip()
    info = parse(text, "inchi" if req.get("inchi") and not req.get("smiles") else "auto")
    if not info["ok"]:
        raise ValueError(info["error"])
    if info["existing"]:
        raise ValueError(f"이미 라이브러리에 있습니다: {info['existing_name']} ({info['existing']})")
    name = (req.get("name") or "").strip()[:60] or info["formula"]
    category = req.get("category") if req.get("category") in CATEGORY_IDS else "other"
    roles = [r for r in (req.get("roles") or ["solute"]) if r in ROLES] or ["solute"]
    smd = _smd_vector(req.get("smd")) if "solvent" in roles else None
    if "solvent" in roles and smd is None:
        raise ValueError("용매 역할에는 SMD 파라미터(굴절률 n · 유전율 ε, 선택: α · β · γ)가 필요합니다.")
    density = req.get("density")
    density = float(density) if density not in (None, "") else None
    if density is not None and not (0.3 <= density <= 5):
        raise ValueError("밀도는 0.3–5 g/mL 범위여야 합니다.")
    rec = {"id": "MOL-U" + uuid.uuid4().hex[:6].upper(), "name": name,
           "full": (req.get("full") or "").strip()[:120], "smiles": info["canonical"],
           "input": info["input"], "cas": (req.get("cas") or "").strip()[:20] or None,
           "category": category, "roles": roles, "tags": _clean_tags(req.get("tags")),
           "note": (req.get("note") or "").strip()[:300], "source": (req.get("source") or "사용자 등록")[:60],
           "smd": smd, "density": density, "fav": False, "created": time.time(),
           "synonyms": _clean_tags(req.get("synonyms"))[:8]}
    rec.update(describe(rec["smiles"]))
    with _lock:
        d = _load()
        d["molecules"].append(rec)
        _save(d)
    return {**rec, "builtin": False}


def update_molecule(mol_id: str, patch: dict) -> dict:
    with _lock:
        d = _load()
        user = next((m for m in d["molecules"] if m["id"] == mol_id), None)
        if user is None:
            if not any(m["id"] == mol_id for m in _builtins()):
                raise KeyError(mol_id)
            o = d["overrides"].setdefault(mol_id, {})
            if "fav" in patch:
                o["fav"] = bool(patch["fav"])
            if "tags" in patch:
                o["tags"] = _clean_tags(patch["tags"])
            if "note" in patch:
                o["note"] = str(patch["note"] or "")[:300]
            _save(d)
            return get(mol_id)
        for k in ("name", "full", "cas", "note"):
            if k in patch:
                user[k] = (str(patch[k] or "").strip()[:120]) or (user[k] if k == "name" else None)
        if "fav" in patch:
            user["fav"] = bool(patch["fav"])
        if "tags" in patch:
            user["tags"] = _clean_tags(patch["tags"])
        if "category" in patch and patch["category"] in CATEGORY_IDS:
            user["category"] = patch["category"]
        if "density" in patch:
            v = patch["density"]
            user["density"] = float(v) if v not in (None, "") else None
        if "roles" in patch or "smd" in patch:
            roles = [r for r in (patch.get("roles") or user["roles"]) if r in ROLES] or ["solute"]
            smd = _smd_vector(patch["smd"]) if patch.get("smd") else user.get("smd")
            if "solvent" in roles and not smd:
                raise ValueError("용매 역할에는 SMD 파라미터가 필요합니다.")
            user["roles"], user["smd"] = roles, smd
        _save(d)
        return {**user, "builtin": False}


def delete_molecule(mol_id: str) -> bool:
    with _lock:
        d = _load()
        n = len(d["molecules"])
        d["molecules"] = [m for m in d["molecules"] if m["id"] != mol_id]
        if len(d["molecules"]) == n:
            if any(m["id"] == mol_id for m in _builtins()):
                raise ValueError("기본 레코드는 지울 수 없습니다 (즐겨찾기·태그만 바꿀 수 있습니다).")
            return False
        _save(d)
        return True


def import_browser(items: list[dict]) -> dict:
    """예전 브라우저 보관함·용매 라이브러리 항목을 서버 라이브러리로 옮긴다 (중복·오류는 건너뜀)."""
    added, skipped, errors = [], 0, []
    for it in items[:500]:
        if it.get("mixture"):
            continue
        smi = (it.get("smiles") or "").strip()
        if not smi:
            skipped += 1
            continue
        try:
            rec = add_molecule({"smiles": smi, "name": it.get("name"), "full": it.get("full"),
                                "category": it.get("category") or "other", "tags": it.get("tags") or ["브라우저 보관함"],
                                "source": "브라우저 보관함에서 이전"})
            added.append(rec["id"])
        except ValueError as exc:
            if "이미 라이브러리" in str(exc):
                skipped += 1
            else:
                errors.append(f"{it.get('name') or smi}: {exc}")
    mixes = 0
    for mx in [it for it in items if it.get("mixture")][:50]:
        try:
            save_mixture(mx["mixture"])
            mixes += 1
        except ValueError as exc:
            errors.append(f"{mx['mixture'].get('name')}: {exc}")
    return {"added": len(added), "skipped": skipped, "mixtures": mixes, "errors": errors[:20]}


# ── 혼합 용매 ─────────────────────────────────────────────────────────
def _solvent_record(ref: dict) -> dict:
    """성분 참조 {id} 또는 {abbr}(예전 형식) → 용매 레코드 + SMD 벡터."""
    rec = None
    if ref.get("id"):
        rec = get(ref["id"])
        if rec is None and ref["id"] in presets.SOLVENTS_BY_ID:
            rec = next((m for m in molecules() if m.get("solventId") == ref["id"]), None)
    elif ref.get("abbr"):
        ab = "Water" if ref["abbr"] in ("H2O", "Water") else ref["abbr"]
        rec = next((m for m in molecules() if m.get("solventId") and m["name"] == ab), None)
    if rec is None:
        raise ValueError(f"용매 성분을 찾을 수 없습니다: {ref.get('id') or ref.get('abbr')}")
    if "solvent" not in rec.get("roles", []):
        raise ValueError(f"{rec['name']} 은(는) 용매 역할(SMD 파라미터)이 없습니다.")
    vec = None
    if rec.get("solventId"):
        sol = presets.SOLVENTS_BY_ID[rec["solventId"]]
        vec = list(sol["smd"]) if sol.get("smd") else list(presets.WATER_SMD_FOR_MIX)
    elif rec.get("smd"):
        vec = list(rec["smd"])
    if not vec:
        raise ValueError(f"{rec['name']} 의 SMD 파라미터가 없습니다.")
    return {**rec, "vec": vec}


def resolve_mixture(mix: dict) -> dict:
    """{name, basis, components:[{id|abbr, ratio}]} → 부피분율 · 유효 SMD 벡터 · 이름."""
    basis = mix.get("basis") or "부피비"
    if basis not in BASES:
        raise ValueError(f"비율 기준은 {', '.join(BASES)} 중 하나여야 합니다.")
    comps = [c for c in (mix.get("components") or []) if float(c.get("ratio") or 0) > 0]
    if not comps:
        raise ValueError("혼합 용매 성분이 없습니다 (비율 0 초과 성분이 1개 이상 필요).")
    if len(comps) > 6:
        raise ValueError("혼합 용매 성분은 6개까지입니다.")
    recs = [_solvent_record(c) for c in comps]
    if len({r["id"] for r in recs}) != len(recs):
        raise ValueError("같은 용매 성분이 두 번 들어 있습니다.")
    ratios = [float(c["ratio"]) for c in comps]
    tot = sum(ratios)
    if basis == "부피비":
        vol = [r / tot for r in ratios]
    else:
        vol = []
        for rec, r in zip(recs, ratios):
            if not rec.get("density"):
                raise ValueError(f"{basis}로 환산하려면 {rec['name']} 의 밀도가 필요합니다 — 라이브러리에서 밀도를 입력하세요.")
            vol.append((r / tot) * (rec["mw"] if basis == "몰비" else 1.0) / rec["density"])
    vt = sum(vol)
    frac = [v / vt for v in vol]
    vec = [sum(f * rec["vec"][i] for f, rec in zip(frac, recs)) for i in range(8)]
    auto = "/".join(r["name"] for r in recs) + (" " + ":".join(f"{x:g}" for x in ratios) if len(recs) > 1 else "")
    name = (mix.get("name") or "").strip() or auto
    key = "smd:mix-" + "-".join(f"{r['id'].lower()}{f:.4f}" for r, f in zip(recs, frac))
    return {"name": name, "basis": basis, "key": key, "vector": vec,
            "eps": round(vec[5], 3), "n": round(vec[0], 4),
            "components": [{"id": r["id"], "name": r["name"], "smiles": r["smiles"], "ratio": x,
                            "volume_fraction": round(f, 4), "solventId": r.get("solventId")}
                           for r, x, f in zip(recs, ratios, frac)]}


def save_mixture(mix: dict) -> dict:
    res = resolve_mixture(mix)
    if len(res["components"]) < 2:
        raise ValueError("혼합 프리셋은 성분이 2개 이상이어야 합니다 (단일 용매는 라이브러리 레코드를 그대로 쓰세요).")
    rec = {"id": "MIX-" + uuid.uuid4().hex[:6].upper(), "name": res["name"], "basis": res["basis"],
           "components": [{"id": c["id"], "ratio": c["ratio"]} for c in res["components"]],
           "note": (mix.get("note") or "")[:200], "created": time.time()}
    with _lock:
        d = _load()
        if any(m["name"] == rec["name"] for m in d["mixtures"]) or any(m["name"] == rec["name"] for m in _BUILTIN_MIXTURES):
            raise ValueError(f"같은 이름의 혼합 용매가 있습니다: {rec['name']}")
        d["mixtures"].append(rec)
        _save(d)
    return {**rec, "builtin": False}


def delete_mixture(mix_id: str) -> bool:
    with _lock:
        d = _load()
        n = len(d["mixtures"])
        d["mixtures"] = [m for m in d["mixtures"] if m["id"] != mix_id]
        if len(d["mixtures"]) == n:
            return False
        _save(d)
        return True


def resolve_solvent(settings: dict) -> dict | None:
    """계산 설정의 용매 → {key, vector(None=PySCF 내장/등록된 키), label, mixture(상세|None)}.

    solventId: 프리셋 용매 id(sol-…) · 라이브러리 용매 레코드 id(MOL-…) · 저장한 혼합 용매 id(MIX-…)
    customMixedSolvent: {name, basis, components:[{id|abbr, ratio}]} — 계산 화면에서 직접 구성한 혼합
    """
    if settings.get("envType") == "진공·기체":
        return None
    custom = settings.get("customMixedSolvent")
    if custom:
        res = resolve_mixture(custom)
        return {"key": res["key"], "vector": res["vector"], "label": f"SMD(혼합: {res['name']} · {res['basis']})",
                "mixture": {k: res[k] for k in ("name", "basis", "eps", "n", "components")}}
    sid = settings.get("solventId")
    if not sid:
        return None
    if sid in presets.SOLVENTS_BY_ID:
        sol = presets.SOLVENTS_BY_ID[sid]
        key = sol.get("builtin_key") or sol["modelKey"]
        return {"key": key, "vector": None, "label": f"SMD({key})", "mixture": None}
    if sid.startswith("MIX-"):
        mx = next((m for m in mixtures() if m["id"] == sid), None)
        if mx is None:
            raise ValueError(f"저장된 혼합 용매를 찾을 수 없습니다: {sid}")
        res = resolve_mixture(mx)
        return {"key": res["key"], "vector": res["vector"], "label": f"SMD(혼합: {res['name']} · {res['basis']})",
                "mixture": {k: res[k] for k in ("name", "basis", "eps", "n", "components")}}
    rec = _solvent_record({"id": sid})
    if rec.get("solventId"):
        return resolve_solvent({**settings, "solventId": rec["solventId"]})
    return {"key": f"smd:lib-{rec['id'].lower()}", "vector": rec["vec"],
            "label": f"SMD({rec['name']} · 라이브러리)", "mixture": None}


def solvent_components(settings: dict) -> list[dict]:
    """Li⁺ 용매 경쟁 참조용 — 설정의 용매를 단일 성분 목록 [{abbr, name, smiles, ratio}] 으로."""
    try:
        res = resolve_solvent(settings)
    except ValueError:
        return []
    if res is None:
        return []
    if res["mixture"]:
        return [{"abbr": c["name"], "name": c["name"], "smiles": c["smiles"], "ratio": float(c["ratio"]),
                 "volume_fraction": float(c["volume_fraction"])} for c in res["mixture"]["components"]]
    sid = settings.get("solventId")
    if sid in presets.SOLVENTS_BY_ID:
        sol = presets.SOLVENTS_BY_ID[sid]
        if sol["kind"] == "mixed":
            mx = next((m for m in _BUILTIN_MIXTURES if m.get("presetSolventId") == sid), None)
            if mx:
                r = resolve_mixture(mx)
                return [{"abbr": c["name"], "name": c["name"], "smiles": c["smiles"],
                         "ratio": float(c["ratio"])} for c in r["components"]]
            return []
        rec = next((m for m in molecules() if m.get("solventId") == sid), None)
        return [{"abbr": rec["name"] if rec else sol["abbr"], "name": sol["name"], "smiles": sol["smiles"], "ratio": 1.0}]
    rec = get(sid) if sid else None
    return [{"abbr": rec["name"], "name": rec.get("full") or rec["name"], "smiles": rec["smiles"], "ratio": 1.0}] if rec else []


def solvent_view(rec: dict) -> dict | None:
    """화면에서 유효 매질을 미리 계산할 수 있도록 용매 레코드의 SMD 값·밀도를 준다."""
    if "solvent" not in rec.get("roles", []):
        return None
    try:
        r = _solvent_record({"id": rec["id"]})
    except ValueError:
        return None
    v = r["vec"]
    return {"vec": v, "n": v[0], "alpha": v[2], "beta": v[3], "gamma": v[4], "eps": v[5], "density": rec.get("density")}


# ── 계산 이력 연결 ────────────────────────────────────────────────────
def _job_view(j: dict) -> dict:
    r = j.get("result") or {}
    d = r.get("descriptors") or {}
    c = r.get("conditions") or {}
    s = j.get("settings") or {}
    return {"id": j["id"], "status": j["status"], "grade": (j.get("validation") or r.get("validation") or {}).get("grade"),
            "method": c.get("method") or f"{(s.get('expert') or {}).get('functional', '')} · {s.get('accuracy', '')}",
            "solvent": c.get("solvent_model") or ("vacuum" if s.get("envType") == "진공·기체" else ""),
            "structure": s.get("structure") or "모노머", "when": j.get("finishedAt") or j.get("createdAt"),
            "homo": d.get("homo_ev"), "lumo": d.get("lumo_ev"), "gap": d.get("gap_ev"),
            "progress": j.get("progress"), "grids": bool(r.get("grids_available"))}


def job_index(jobs: list[dict] | None = None) -> dict:
    """레코드 id → 관련 작업 목록 (최근순). 연결 기준: libraryId → 프리셋 id → 정규 SMILES."""
    jobs = store.list_jobs() if jobs is None else jobs
    mols = molecules()
    by_can = {}
    for m in mols:
        by_can.setdefault(m["canonical"], []).append(m["id"])
    by_preset = {m["presetId"]: m["id"] for m in mols if m.get("presetId")}
    out = {}
    for j in jobs:
        mat = j.get("material") or {}
        ids = set()
        if mat.get("libraryId"):
            ids.add(mat["libraryId"])
        if mat.get("id") and mat["id"] in by_preset:
            ids.add(by_preset[mat["id"]])
        can = canonical(mat.get("smiles") or "")
        if can:
            ids.update(by_can.get(can, []))
        for i in ids:
            out.setdefault(i, []).append(j)
    for i in out:
        out[i].sort(key=lambda j: -(j.get("finishedAt") or j.get("createdAt") or 0))
    return out


def listing(jobs: list[dict] | None = None, with_svg: bool = True) -> dict:
    idx = job_index(jobs)
    mols = []
    for m in molecules():
        js = idx.get(m["id"], [])
        row = {k: v for k, v in m.items() if k not in ("smd",)}
        row["solvent"] = solvent_view(m)
        row["jobs"] = [_job_view(j) for j in js[:8]]
        row["n_jobs"] = len(js)
        if with_svg:
            row["svg"] = depict(m["smiles"])
        mols.append(row)
    return {"molecules": mols, "mixtures": mixtures(), "categories": [{"id": c, "label": l} for c, l in CATEGORIES],
            "bases": list(BASES), "fgroups": [n for n, _ in FGROUPS]}


# ── 검색 ─────────────────────────────────────────────────────────────
def search(mode: str, query: str, threshold: float = 0.35, stereo: bool = False,
           strip_salts: bool = True, limit: int = 200) -> dict:
    q = (query or "").strip()
    mols = molecules()
    rows, note, parsed = [], "", None
    if mode == "name":
        if not q:
            return {"mode": mode, "rows": [{"id": m["id"], "score": 0} for m in mols], "note": "전체 목록"}
        ql = q.lower().translate(_SUB)
        if _looks_like_formula(q):
            want = _formula_counts(q.translate(_SUB).replace(" ", "").rstrip("+-"))
            for m in mols:
                if _formula_counts(re.sub(r"[+-]\d*$", "", m["formula"])) == want:
                    rows.append({"id": m["id"], "score": 3, "reason": "화학식 일치"})
            note = f"화학식 {q} — 같은 화학식의 이성질체는 각각 표시합니다 ({len(rows)}개)"
        for m in mols:
            if any(r["id"] == m["id"] for r in rows):
                continue
            hay = [m["name"], m.get("full") or "", m.get("cas") or "", m["formula"], m["smiles"],
                   *(m.get("tags") or []), *(m.get("synonyms") or [])]
            hl = [h.lower().translate(_SUB) for h in hay]
            if ql in (m["name"].lower(), (m.get("cas") or "").lower()):
                rows.append({"id": m["id"], "score": 3, "reason": "이름·CAS 일치"})
            elif any(h.startswith(ql) for h in hl):
                rows.append({"id": m["id"], "score": 2, "reason": "앞부분 일치"})
            elif any(ql in h for h in hl):
                rows.append({"id": m["id"], "score": 1, "reason": "부분 일치"})
        pm = _mol(q) if re.search(r"[=#()\[\]@+\-\d]|^[BCNOPSFIcnos]+$", q) else None
        if pm is not None:
            key = _identity_key(pm)
            for m in mols:
                if _identity_key(_mol(m["smiles"])) == key and not any(r["id"] == m["id"] for r in rows):
                    rows.append({"id": m["id"], "score": 3, "reason": "SMILES 구조 일치"})
        rows.sort(key=lambda r: -r["score"])
    elif mode in ("exact", "sub", "sim"):
        info = parse(q)
        parsed = {k: info.get(k) for k in ("ok", "error", "canonical", "formula", "mw", "charge", "inchikey", "svg", "existing")}
        if mode == "sub":
            patt = Chem.MolFromSmarts(q)
            if patt is None and info["ok"]:
                patt = _mol(info["canonical"])
            if patt is None:
                return {"mode": mode, "rows": [], "note": "", "parsed": parsed, "error": info.get("error") or "부분구조 패턴을 해석할 수 없습니다."}
            for m in mols:
                mm = _mol(m["smiles"])
                hit = mm.GetSubstructMatch(patt) if mm is not None else ()
                if hit:
                    rows.append({"id": m["id"], "score": round(len(hit) / max(1, mm.GetNumAtoms()), 3),
                                 "match": list(hit), "svg": depict(m["smiles"], 200, 120, tuple(hit)),
                                 "reason": "부분구조 포함"})
            rows.sort(key=lambda r: -r["score"])
            note = f"부분구조 «{q}» 를 포함하는 분자 {len(rows)}개 — 일치한 원자를 구조에서 강조했습니다"
        elif not info["ok"]:
            return {"mode": mode, "rows": [], "note": "", "parsed": parsed, "error": info["error"]}
        elif mode == "exact":
            key = _identity_key(_mol(info["canonical"]), stereo=stereo, strip_salts=strip_salts)
            for m in mols:
                if _identity_key(_mol(m["smiles"]), stereo=stereo, strip_salts=strip_salts) == key:
                    rows.append({"id": m["id"], "score": 1, "reason": "구조 완전 일치"})
            note = ("완전 일치 — InChIKey" + (" 전체(입체 구분)" if stereo else " 연결성 부분(입체 무시)")
                    + (" · 염·용매화물은 가장 큰 조각으로 비교" if strip_salts else ""))
        else:
            fq = _fingerprint(info["canonical"])
            for m in mols:
                fm = _fingerprint(m["smiles"])
                if fm is None or fq is None:
                    continue
                s = DataStructs.TanimotoSimilarity(fq, fm)
                if s >= threshold:
                    rows.append({"id": m["id"], "score": round(s, 3), "reason": f"Tanimoto {s:.2f}"})
            rows.sort(key=lambda r: -r["score"])
            note = f"유사도 — Morgan 지문(r=2, 2048 bit) Tanimoto ≥ {threshold:g}. 유사도가 «같은 구조»를 뜻하지는 않습니다."
    else:
        raise ValueError(f"알 수 없는 검색 방식: {mode}")
    return {"mode": mode, "query": q, "rows": rows[:limit], "note": note, "parsed": parsed}


# ── 3D 구조 · 내보내기 ────────────────────────────────────────────────
def _rdkit_3d(smiles: str):
    m = Chem.AddHs(_mol(smiles))
    p = AllChem.ETKDGv3()
    p.randomSeed = 42
    if AllChem.EmbedMolecule(m, p) < 0:
        p.useRandomCoords = True
        if AllChem.EmbedMolecule(m, p) < 0:
            raise ValueError("3D 좌표를 만들지 못했습니다.")
    try:
        AllChem.MMFFOptimizeMolecule(m, maxIters=2000)
    except Exception:  # noqa: BLE001
        pass
    return m


def structure(mol_id: str) -> dict:
    """미리보기 3D 구조 — 계산된 최적화 구조가 있으면 그것, 없으면 RDKit 생성 conformer."""
    rec = get(mol_id)
    if rec is None:
        raise KeyError(mol_id)
    for j in job_index().get(mol_id, []):
        r = j.get("result") or {}
        if j["status"] == "PUBLISHED" and r.get("structure_xyz") and (j.get("settings") or {}).get("structure", "모노머") == "모노머":
            return {"xyz": r["structure_xyz"], "source": f"DFT 최적화 구조 ({j['id']})", "job": j["id"]}
    m = _rdkit_3d(rec["smiles"])
    return {"xyz": Chem.MolToXYZBlock(m), "source": "RDKit ETKDG + MMFF (생성 conformer — DFT 전)", "job": None}


def export(mol_id: str, fmt: str) -> tuple[str, str]:
    rec = get(mol_id)
    if rec is None:
        raise KeyError(mol_id)
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", rec["name"]) or rec["id"]
    if fmt == "smi":
        return f"{rec['smiles']}\t{rec['name']}\n", f"{base}.smi"
    if fmt == "xyz":
        return structure(mol_id)["xyz"], f"{base}.xyz"
    if fmt in ("sdf", "mol"):
        m = _rdkit_3d(rec["smiles"])
        m.SetProp("_Name", rec["name"])
        block = Chem.MolToMolBlock(m)
        return (block + "\n$$$$\n" if fmt == "sdf" else block), f"{base}.{fmt}"
    raise ValueError("형식은 xyz · sdf · mol · smi 중 하나입니다.")
