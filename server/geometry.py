"""RDKit 기반 3D 구조 생성: SMILES → conformer 앙상블 → 역장 최적화 → 최저 에너지 구조."""

from rdkit import Chem
from rdkit.Chem import AllChem


class GeometryError(Exception):
    pass


def smiles_to_xyz(smiles: str, n_conformers: int = 15, seed: int = 42):
    """SMILES에서 최저 에너지 conformer의 원자 좌표를 생성한다.

    Returns:
        atoms: [(symbol, x, y, z), ...] (Å)
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
        best_id = conf_ids[0]
        best_e = float("nan")
    else:
        best_e, best_id = min(energies)

    conf = mol.GetConformer(best_id)
    atoms = []
    for atom in mol.GetAtoms():
        pos = conf.GetAtomPosition(atom.GetIdx())
        atoms.append((atom.GetSymbol(), pos.x, pos.y, pos.z))
    return atoms, {
        "n_conformers": len(conf_ids),
        "forcefield": forcefield,
        "ff_energy": best_e,
    }


def atoms_to_xyz_block(atoms, comment=""):
    lines = [str(len(atoms)), comment]
    for sym, x, y, z in atoms:
        lines.append(f"{sym} {x:.6f} {y:.6f} {z:.6f}")
    return "\n".join(lines) + "\n"
