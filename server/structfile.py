"""3D 구조 파일 입력 — SDF/MOL(우선)·XYZ(보조) 파서.

업로드된 좌표는 «초기 구조»로 쓰인다: conformer 탐색을 건너뛰고 그 구조에서
(프리셋에 따라) DFT 최적화·단일점으로 진행한다. «구조 재탐색» 옵션을 켜면
좌표를 버리고 기존 SMILES 경로(ETKDG conformer 탐색)로 돌아간다.

형식별 취급:
  - SDF/MOL — 결합 정보가 파일에 있어 그대로 신뢰한다. 여러 분자($$$$ 구분)
    지원. 수소가 생략된 파일은 AddHs(addCoords)로 좌표를 보완한다.
    2D 좌표(평면) 파일은 결합 정보만 취하고 좌표는 쓰지 않는다.
  - XYZ — 좌표·원소만 있으므로 rdDetermineBonds 로 결합을 추정한다. 중성이
    아닌 분자는 전하를 함께 받아야 추정이 맞는다. 여러 프레임 지원.
"""

from rdkit import Chem
from rdkit.Chem import rdDetermineBonds

MAX_MOLECULES = 1000


def _atoms_of(mol) -> list:
    conf = mol.GetConformer()
    return [(a.GetSymbol(), *conf.GetAtomPosition(a.GetIdx())) for a in mol.GetAtoms()]


def _entry_from_mol(mol, name: str, source: str) -> dict:
    """RDKit mol(결합 정보 보유) → 후보 항목. 좌표 신뢰 여부를 판정한다."""
    notes = []
    smiles = Chem.MolToSmiles(Chem.RemoveHs(Chem.Mol(mol)))
    atoms = None
    if mol.GetNumConformers():
        conf = mol.GetConformer()
        if conf.Is3D():
            n_before = mol.GetNumAtoms()
            molH = Chem.AddHs(mol, addCoords=True)
            if molH.GetNumAtoms() != n_before:
                notes.append(f"수소 {molH.GetNumAtoms() - n_before}개는 파일에 없어 "
                             "좌표를 생성해 보완")
            atoms = _atoms_of(molH)
        else:
            notes.append("2D 좌표 파일 — 결합 정보만 사용하고 3D 구조는 "
                         "conformer 탐색으로 생성")
    else:
        notes.append("좌표 없음 — 결합 정보만 사용")
    return {"name": name, "smiles": smiles, "atoms": atoms,
            "n_atoms": len(atoms) if atoms else None,
            "source": source, "note": " · ".join(notes) or None,
            "ok": True, "error": None}


def _stem(filename: str) -> str:
    base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[0] if "." in base else base


def _parse_sdf(content: str, filename: str) -> list[dict]:
    out = []
    blocks = content.replace("\r\n", "\n").split("$$$$")
    idx = 0
    for block in blocks:
        if not block.strip():
            continue
        idx += 1
        if idx > MAX_MOLECULES:
            break
        # 몰블록 형식상 카운트 줄 앞의 헤더 3줄이 필요하다 — 앞쪽 빈 줄만 정돈
        text = block.lstrip("\n") + "\n"
        title = text.split("\n", 1)[0].strip()
        name = title or f"{_stem(filename) or 'mol'}-{idx}"
        mol = Chem.MolFromMolBlock(text, removeHs=False, sanitize=True)
        if mol is None:
            out.append({"name": name, "smiles": None, "atoms": None,
                        "n_atoms": None, "source": "sdf", "note": None,
                        "ok": False,
                        "error": f"{idx}번째 몰블록 해석 실패 — 파일 형식을 확인하세요"})
            continue
        out.append(_entry_from_mol(mol, name, "sdf"))
    return out


def _parse_xyz(content: str, filename: str, charge: int) -> list[dict]:
    out = []
    lines = content.replace("\r\n", "\n").split("\n")
    i, idx = 0, 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        try:
            n = int(lines[i].strip().split()[0])
        except ValueError:
            out.append({"name": f"{_stem(filename) or 'xyz'}-?", "smiles": None,
                        "atoms": None, "n_atoms": None, "source": "xyz",
                        "note": None, "ok": False,
                        "error": f"{i + 1}행: 원자 수를 읽을 수 없습니다 — XYZ 형식이 아닙니다"})
            break
        idx += 1
        if idx > MAX_MOLECULES:
            break
        comment = lines[i + 1].strip() if i + 1 < len(lines) else ""
        frame = lines[i:i + 2 + n]
        i += 2 + n
        name = comment or f"{_stem(filename) or 'xyz'}-{idx}"
        if len(frame) < 2 + n:
            out.append({"name": name, "smiles": None, "atoms": None,
                        "n_atoms": None, "source": "xyz", "note": None,
                        "ok": False, "error": "파일이 중간에 끊겨 있습니다"})
            break
        block = "\n".join(frame) + "\n"
        mol = Chem.MolFromXYZBlock(block)
        if mol is None:
            out.append({"name": name, "smiles": None, "atoms": None,
                        "n_atoms": None, "source": "xyz", "note": None,
                        "ok": False, "error": "XYZ 프레임 해석 실패"})
            continue
        try:
            rdDetermineBonds.DetermineBonds(mol, charge=charge)
        except Exception as exc:  # noqa: BLE001 — 전하·라디칼 등으로 추정 실패
            out.append({"name": name, "smiles": None, "atoms": None,
                        "n_atoms": None, "source": "xyz", "note": None,
                        "ok": False,
                        "error": ("결합 추정 실패 — XYZ에는 결합 정보가 없어 좌표에서 "
                                  f"추정하는데 실패했습니다 (전하 {charge:+d} 기준). "
                                  f"전하를 바꾸거나 SDF/MOL로 변환해 올리세요. ({exc})")})
            continue
        entry = _entry_from_mol(mol, name, "xyz")
        # XYZ 는 모든 원자가 명시돼 있고 항상 3D 로 취급한다
        if entry["atoms"] is None:
            entry["atoms"] = _atoms_of(mol)
            entry["n_atoms"] = len(entry["atoms"])
            entry["note"] = None
        out.append(entry)
    return out


def detect_format(content: str, filename: str = "") -> str:
    ext = (filename or "").lower().rsplit(".", 1)
    ext = ext[1] if len(ext) == 2 else ""
    if ext in ("sdf", "mol", "mdl"):
        return "sdf"
    if ext == "xyz":
        return "xyz"
    if "V2000" in content or "V3000" in content:
        return "sdf"
    first = content.lstrip().split("\n", 1)[0].strip().split()
    if first and first[0].isdigit():
        return "xyz"
    return "sdf"


def parse_structures(content: str, filename: str = "", charge: int = 0) -> dict:
    """3D 파일 텍스트 → 후보 목록. 형식은 확장자·내용으로 자동 감지."""
    fmt = detect_format(content, filename)
    if fmt == "xyz":
        molecules = _parse_xyz(content, filename, charge)
    else:
        molecules = _parse_sdf(content, filename)
    return {"format": fmt, "molecules": molecules,
            "n_ok": sum(1 for m in molecules if m["ok"]),
            "n_error": sum(1 for m in molecules if not m["ok"])}
