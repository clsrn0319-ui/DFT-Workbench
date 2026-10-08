"""접촉 배향 후보 — 역장 1등 하나만 쓰지 않고 여러 후보를 남기는지 확인.

역장(MMFF/UFF) 1등 배향이 DFT 1등과 다를 수 있다. 셀로비오스 이량체에서 실제로
수소결합이 맺히지 않은 배향이 역장 1등이 되어 결합 에너지가 과소평가됐다.
여기서는 후보가 서로 다른 접촉점인지, 정렬·상한이 지켜지는지, 기존 함수가
첫 후보와 같은 결과를 주는지를 본다.
"""

import numpy as np
import pytest

from server import engine, presets
from server.geometry import (build_cluster_candidates, build_cluster_from_atoms,
                             smiles_to_xyz)


@pytest.fixture(scope="module")
def host():
    atoms, _ = smiles_to_xyz("CCO", n_conformers=1)
    return atoms


def _guest_centroid(cand):
    f = cand["fragments"][1]
    xyz = np.array([a[1:4] for a in cand["atoms"][f["start"]:f["end"]]])
    return xyz.mean(axis=0)


def test_candidates_are_sorted_and_capped(host):
    cands = build_cluster_candidates(host, "CCO", "O", seed=7, n_keep=3)
    assert 1 <= len(cands) <= 3
    energies = [c["info"]["ff_energy"] for c in cands]
    assert energies == sorted(energies), "역장 에너지가 낮은 것부터 나와야 한다"
    for rank, c in enumerate(cands):
        assert c["info"]["rank"] == rank
        assert c["info"]["contact_A"] > 0


def test_candidates_are_distinct_contact_sites(host):
    cands = build_cluster_candidates(host, "CCO", "O", seed=7, n_keep=4)
    if len(cands) < 2:
        pytest.skip("이 분자에서는 서로 다른 접촉점이 1개뿐이다")
    cents = [_guest_centroid(c) for c in cands]
    for i in range(len(cents)):
        for j in range(i + 1, len(cents)):
            assert np.linalg.norm(cents[i] - cents[j]) >= 1.5, "같은 자리 후보가 중복됐다"


def test_default_keeps_one_and_matches_legacy_helper(host):
    assert len(build_cluster_candidates(host, "CCO", "O", seed=7)) == 1
    atoms, frags, info = build_cluster_from_atoms(host, "CCO", "O", seed=7)
    first = build_cluster_candidates(host, "CCO", "O", seed=7, n_keep=1)[0]
    assert frags == first["fragments"] and info["n_molecules"] == 2
    assert np.allclose([a[1:4] for a in atoms],
                       [a[1:4] for a in first["atoms"]])


def test_fragments_cover_every_atom(host):
    cand = build_cluster_candidates(host, "CCO", "O", seed=7)[0]
    a, f = cand["atoms"], cand["fragments"]
    assert f[0]["start"] == 0 and f[1]["end"] == len(a)
    assert f[0]["end"] == f[1]["start"] == len(host)


@pytest.mark.parametrize("given,expected", [(None, 1), (1, 1), (4, 4), (99, 6), (0, 1)])
def test_pair_orientations_setting_is_clamped(given, expected):
    s = {**presets.DEFAULT_SETTINGS, "expert": dict(presets.DEFAULT_SETTINGS["expert"])}
    s["expert"]["pairOrientations"] = given
    assert engine._resolve_params(s)["pair_orientations"] == expected


# ── 수소결합 자리를 겨냥한 접촉 배치 ──────────────────────────────────────────
# 종전에는 «최소 간격 2.6 Å 을 만족하는 첫 거리»에서 멈춰서, 수소결합 거리(1.8~2.0 Å)로는
# 애초에 시작할 수 없었다. 부피 큰 분자는 3.5 Å 밖에서 출발했고 역장은 거기서 끌어당기지
# 못해(UFF 에는 수소결합 항이 없다) 결합 에너지가 크게 과소평가됐다.

def test_polar_sites_finds_donors_and_acceptors():
    from server.geometry import _embed_single, _coords, _polar_sites

    mol = _embed_single("CCO", 7)                      # 에탄올 — O 받개 1개, O-H 주개 1개
    don, acc = _polar_sites(mol, _coords(mol))
    assert len(acc) == 1
    assert len(don) == 1 and mol.GetAtomWithIdx(don[0][1]).GetSymbol() == "O"


@pytest.mark.parametrize("smiles", ["O", "OCC1OC(O)C(O)C(O)C1O"])
def test_hydrogen_bonded_contacts_start_at_bond_distance(smiles):
    atoms, _ = smiles_to_xyz(smiles, n_conformers=3)
    cands = build_cluster_candidates(atoms, smiles, smiles, seed=7, n_keep=3)
    first = cands[0]["info"]
    assert first["aimed"] is True
    assert first["contact_A"] <= 2.2, "수소결합 거리에서 시작해야 한다"


def test_molecule_without_polar_hydrogen_falls_back():
    smi = "CC(F)(F)CC(F)(F)CC(F)F"                      # PVDF 3량체 — 극성 H 없음
    atoms, _ = smiles_to_xyz(smi, n_conformers=3)
    cands = build_cluster_candidates(atoms, smi, smi, seed=7, n_keep=2)
    assert all(c["info"]["aimed"] is False for c in cands)
    assert all(c["info"]["contact_A"] >= 2.3 for c in cands)


def test_aimed_candidates_are_ranked_first():
    smi = "OCC1OC(O)C(O)C(O)C1O"
    atoms, _ = smiles_to_xyz(smi, n_conformers=3)
    cands = build_cluster_candidates(atoms, smi, smi, seed=7, n_keep=4)
    aimed = [c["info"]["aimed"] for c in cands]
    assert aimed == sorted(aimed, reverse=True), "겨냥한 후보가 앞에 와야 한다"
