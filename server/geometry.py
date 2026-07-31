"""RDKit 기반 3D 구조 생성: SMILES → conformer 앙상블 → 역장 최적화 → 최저 에너지 구조.

명시적 용매화(cluster-continuum)용 클러스터 빌더 포함: 용질 주위에 지정 분자들을
겹치지 않게 배치한 뒤 전체를 역장으로 이완시킨다.
"""

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Geometry import Point3D


class GeometryError(Exception):
    pass


def smiles_to_conformers(smiles: str, n_conformers: int = 15, top_k: int = 1, seed: int = 42):
    """SMILES에서 역장 에너지 오름차순 상위 top_k개 conformer를 생성한다.

    Returns:
        candidates: [(atoms, ff_energy), ...]  — atoms = [(symbol, x, y, z), ...] (Å)
        info: {"n_conformers": int, "forcefield": str, "ff_energy": float}
    """
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise GeometryError(f"SMILES 파싱 실패: {smiles!r}")
    mol = Chem.AddHs(mol)

    params = AllChem.ETKDGv3()
    params.randomSeed = seed
    params.pruneRmsThresh = 0.5
    conf_ids = AllChem.EmbedMultipleConfs(mol, numConfs=max(1, n_conformers), params=params)
    if len(conf_ids) == 0:
        # 임베딩 실패 시 랜덤 좌표 허용으로 재시도
        params.useRandomCoords = True
        conf_ids = AllChem.EmbedMultipleConfs(mol, numConfs=max(1, n_conformers), params=params)
    if len(conf_ids) == 0:
        raise GeometryError(f"3D 임베딩 실패: {smiles!r}")

    forcefield = "MMFF94"
    results = AllChem.MMFFOptimizeMoleculeConfs(mol, maxIters=2000)
    if all(code != 0 for code, _ in results):
        forcefield = "UFF"
        results = AllChem.UFFOptimizeMoleculeConfs(mol, maxIters=2000)

    energies = [(e, cid) for (code, e), cid in zip(results, conf_ids) if code == 0]
    if not energies:
        # 최적화가 모두 실패해도 임베딩 좌표는 사용 가능
        energies = [(float("nan"), conf_ids[0])]
    energies.sort(key=lambda t: t[0])

    def _extract(conf_id):
        conf = mol.GetConformer(conf_id)
        return [(a.GetSymbol(), *conf.GetAtomPosition(a.GetIdx())) for a in mol.GetAtoms()]

    candidates = [(_extract(cid), e) for e, cid in energies[:max(1, top_k)]]
    return candidates, {
        "n_conformers": len(conf_ids),
        "forcefield": forcefield,
        "ff_energy": energies[0][0],
    }


def smiles_to_xyz(smiles: str, n_conformers: int = 15, seed: int = 42):
    """최저 에너지 conformer 하나만 반환하는 편의 함수."""
    candidates, info = smiles_to_conformers(smiles, n_conformers, top_k=1, seed=seed)
    return candidates[0][0], info


def oligomerize(smiles: str, n_units: int) -> str:
    """비닐 모노머(C=C 보유)를 head-to-tail 부가 중합 방식으로 n량체 SMILES로 변환.

    비고리·비방향족 C=C 하나를 골라 단일결합으로 바꾸고 사슬로 연결한다
    (양 끝은 수소 캡핑). 이중결합이 여러 개면 첫 번째를 사용한다.
    """
    if n_units <= 1:
        return smiles
    base = Chem.MolFromSmiles(smiles)
    if base is None:
        raise GeometryError(f"SMILES 파싱 실패: {smiles!r}")
    target = None
    for bond in base.GetBonds():
        if (bond.GetBondType() == Chem.BondType.DOUBLE and not bond.GetIsAromatic()
                and not bond.IsInRing()
                and bond.GetBeginAtom().GetSymbol() == "C"
                and bond.GetEndAtom().GetSymbol() == "C"):
            target = bond
            break
    if target is None:
        raise GeometryError(
            "중합 가능한 C=C 이중결합이 없어 2량체/3량체를 만들 수 없습니다 — 모노머로 계산하세요")
    a_idx, b_idx = target.GetBeginAtomIdx(), target.GetEndAtomIdx()
    n_atoms = base.GetNumAtoms()
    combo = base
    for _ in range(n_units - 1):
        combo = Chem.CombineMols(combo, base)
    rw = Chem.RWMol(combo)
    for u in range(n_units):
        off = u * n_atoms
        rw.GetBondBetweenAtoms(a_idx + off, b_idx + off).SetBondType(Chem.BondType.SINGLE)
        if u < n_units - 1:
            rw.AddBond(b_idx + off, a_idx + (u + 1) * n_atoms, Chem.BondType.SINGLE)
    mol = rw.GetMol()
    Chem.SanitizeMol(mol)
    return Chem.MolToSmiles(mol)


def _embed_single(smiles: str, seed: int):
    """SMILES 하나를 3D 임베딩 + 역장 최적화한 RDKit mol로 반환."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise GeometryError(f"SMILES 파싱 실패: {smiles!r}")
    mol = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = seed
    if AllChem.EmbedMolecule(mol, params) != 0:
        params.useRandomCoords = True
        if AllChem.EmbedMolecule(mol, params) != 0:
            raise GeometryError(f"3D 임베딩 실패: {smiles!r}")
    if AllChem.MMFFOptimizeMolecule(mol, maxIters=2000) != 0:
        AllChem.UFFOptimizeMolecule(mol, maxIters=2000)
    return mol


def _coords(mol):
    conf = mol.GetConformer()
    return np.array([[*conf.GetAtomPosition(i)] for i in range(mol.GetNumAtoms())])


def _random_rotation(rng):
    q = rng.normal(size=4)
    q /= np.linalg.norm(q)
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


def build_cluster(solute_smiles: str, explicit, n_conformers: int = 10, seed: int = 42):
    """용질 + 명시적 주변 분자들의 클러스터 구조를 생성한다.

    explicit: [(smiles, count), ...]
    배치: 각 분자를 무작위 방향·자세로 용질 주위에 최소 접촉거리 2.0 Å 이상으로
    놓은 뒤, 전체 클러스터를 MMFF(폴백 UFF)로 이완.

    Returns:
        atoms: [(symbol, x, y, z), ...]
        fragments: [{"label", "start", "end", "smiles"}, ...] (원자 인덱스 구간, 용질이 첫 항목)
        info: {"forcefield": str, "n_molecules": int}
    """
    rng = np.random.default_rng(seed)

    solute_atoms, _ = smiles_to_xyz(solute_smiles, n_conformers=n_conformers, seed=seed)
    solute = Chem.MolFromSmiles(solute_smiles)
    solute = Chem.AddHs(solute)
    conf = Chem.Conformer(solute.GetNumAtoms())
    for i, (_, x, y, z) in enumerate(solute_atoms):
        conf.SetAtomPosition(i, Point3D(x, y, z))
    solute.RemoveAllConformers()
    solute.AddConformer(conf)

    placed_mols = [solute]
    placed_xyz = _coords(solute) - _coords(solute).mean(axis=0)
    center_shift = _coords(solute).mean(axis=0)

    for smi, count in explicit:
        template = _embed_single(smi, seed)
        t_xyz = _coords(template) - _coords(template).mean(axis=0)
        t_radius = np.linalg.norm(t_xyz, axis=1).max() + 1.0
        for _ in range(int(count)):
            ok = False
            for _try in range(200):
                direction = rng.normal(size=3)
                direction /= np.linalg.norm(direction)
                rot_xyz = t_xyz @ _random_rotation(rng).T
                cluster_radius = np.linalg.norm(placed_xyz, axis=1).max()
                for dist in np.arange(max(cluster_radius - 1.0, 1.0), cluster_radius + t_radius + 6.0, 0.4):
                    cand = rot_xyz + direction * (dist + t_radius)
                    dmin = np.min(np.linalg.norm(
                        placed_xyz[:, None, :] - cand[None, :, :], axis=2))
                    if dmin >= 2.0:
                        placed_xyz = np.vstack([placed_xyz, cand])
                        mol_copy = Chem.Mol(template)
                        c = mol_copy.GetConformer()
                        for i, p in enumerate(cand):
                            c.SetAtomPosition(i, Point3D(*(p + center_shift)))
                        placed_mols.append(mol_copy)
                        ok = True
                        break
                if ok:
                    break
            if not ok:
                raise GeometryError(f"클러스터 배치 실패: {smi} — 공간을 찾지 못함")

    combined = placed_mols[0]
    for m in placed_mols[1:]:
        combined = Chem.CombineMols(combined, m)
    combined = Chem.RWMol(combined)
    Chem.SanitizeMol(combined)

    forcefield = "MMFF94"
    if AllChem.MMFFOptimizeMolecule(combined, maxIters=5000) != 0:
        forcefield = "UFF"
        AllChem.UFFOptimizeMolecule(combined, maxIters=5000)

    conf = combined.GetConformer()
    atoms = [(a.GetSymbol(), *conf.GetAtomPosition(a.GetIdx())) for a in combined.GetAtoms()]

    fragments = [{"label": "용질", "start": 0, "end": solute.GetNumAtoms(),
                  "smiles": solute_smiles}]
    idx = solute.GetNumAtoms()
    for smi, count in explicit:
        n = Chem.AddHs(Chem.MolFromSmiles(smi)).GetNumAtoms()
        for k in range(int(count)):
            fragments.append({"label": f"{smi} #{k + 1}", "start": idx, "end": idx + n,
                              "smiles": smi})
            idx += n
    return atoms, fragments, {"forcefield": forcefield, "n_molecules": len(fragments)}


def atoms_to_xyz_block(atoms, comment=""):
    lines = [str(len(atoms)), comment]
    for sym, x, y, z in atoms:
        lines.append(f"{sym} {x:.6f} {y:.6f} {z:.6f}")
    return "\n".join(lines) + "\n"
