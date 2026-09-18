"""워크스페이스 개편(기획서 반영) — 궤도 점 구름, 템플릿, 설정 API."""

import json

import pytest

from server import presets, store, templates


@pytest.fixture
def isolated_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture(scope="module")
def water_pbe():
    from pyscf import dft, gto
    mol = gto.M(atom="O 0 0 0.117; H 0 0.757 -0.469; H 0 -0.757 -0.469", basis="sto-3g", verbose=0)
    mf = dft.RKS(mol, xc="pbe"); mf.kernel()
    return mf, mol


def test_orbital_cloud_real_scf(water_pbe):
    """물 분자 STO-3G — HOMO−1/HOMO/LUMO/LUMO+1 점 구름이 부호·에너지·점유·기여도를 갖는다."""
    from server import descriptors
    mf, mol = water_pbe
    clouds = descriptors.orbital_clouds(mf, mol)
    assert set(clouds) == {"homo-1", "homo", "lumo", "lumo+1"}
    homo, lumo, hm1, lp1 = clouds["homo"], clouds["lumo"], clouds["homo-1"], clouds["lumo+1"]
    assert homo and lumo and lumo["index"] == homo["index"] + 1
    assert hm1 and hm1["index"] == homo["index"] - 1 and hm1["energy_ev"] < homo["energy_ev"]
    assert lp1 and lp1["index"] == lumo["index"] + 1 and lp1["energy_ev"] >= lumo["energy_ev"]
    assert homo["which"] == "homo" and homo["label"] == "HOMO" and lp1["label"] == "LUMO+1"
    assert homo["occ"] == 2 and lumo["occ"] == 0
    assert lumo["energy_ev"] > homo["energy_ev"]
    assert 50 < len(homo["points"]) <= 2500 and len(homo["value"]) == len(homo["points"])
    vals = homo["value"]
    assert any(v > 0 for v in vals) and any(v < 0 for v in vals)      # 위상 두 lobe
    assert homo["abs_max"] >= max(abs(v) for v in vals) - 1e-3
    assert all(len(p) == 3 for p in homo["points"])
    # Löwdin 기여도 — 원자별 % 합이 100 근처, 물 HOMO(1b1)는 O 가 지배
    c = homo["contributions"]
    assert c["method"] == "Löwdin" and c["atoms"][0]["atom"] == "O1" and c["atoms"][0]["pct"] > 60
    assert abs(sum(a["pct"] for a in c["atoms"]) - 100) < 1.5
    assert json.dumps(clouds)                                          # JSON 직렬화 가능


def test_orbital_grid_roundtrip_and_split(water_pbe):
    """등가면 격자 — float16 base64 로 저장되고 되돌리면 격자 모양·부호·최대값이 맞으며, split_grids 가 떼어낸다."""
    import numpy as np
    from server import descriptors
    mf, mol = water_pbe
    clouds = descriptors.orbital_clouds(mf, mol)
    g = clouds["homo"]["grid"]
    assert g["dtype"] == "f16" and len(g["shape"]) == 3 and np.prod(g["shape"]) <= descriptors.GRID_MAX_POINTS
    arr = descriptors.decode_grid(g)
    assert arr.shape == tuple(g["shape"]) and abs(float(np.abs(arr).max()) - g["abs_max"]) < 2e-3
    assert (arr > 0.02).any() and (arr < -0.02).any()                 # 두 위상의 lobe
    assert all(sp > 0 for sp in g["spacing"])
    dens = descriptors.density_cloud(mf, mol)
    assert dens["grid"] and descriptors.decode_grid(dens["grid"]).min() >= 0
    grids = descriptors.split_grids(clouds, dens)
    assert set(grids) == {"homo-1", "homo", "lumo", "lumo+1", "density"}
    assert "grid" not in clouds["homo"] and "grid" not in dens
    assert json.dumps(grids)


def test_grid_store_and_api(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from server import main, store
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    store.save_grids("JOB-G1", {"homo": {"shape": [2, 2, 2], "data": "AAAA"}})
    assert store.grid_path("JOB-G1") in store.job_files("JOB-G1")
    assert store.load_grids("JOB-G1")["homo"]["shape"] == [2, 2, 2]
    monkeypatch.setattr(main, "_job_or_404", lambda job_id: {"id": job_id})
    assert main.get_job_grids("JOB-G1", _=True)["homo"]["shape"] == [2, 2, 2]
    store.delete_grids("JOB-G1")
    assert store.load_grids("JOB-G1") is None
    with pytest.raises(HTTPException) as ei:
        main.get_job_grids("JOB-G1", _=True)
    assert ei.value.status_code == 404


def test_orbital_levels_window(water_pbe):
    """준위 목록 — HOMO 를 중심으로 이름·에너지·점유가 매겨지고 에너지는 오름차순."""
    from server import descriptors
    mf, mol = water_pbe
    lv = descriptors.orbital_levels(mf, mol)
    labels = [x["label"] for x in lv["levels"]]
    assert "HOMO" in labels and "LUMO" in labels and "HOMO−1" in labels and "LUMO+1" in labels
    es = [x["energy_ev"] for x in lv["levels"]]
    assert es == sorted(es) and lv["spin"] == "restricted"
    h = next(x for x in lv["levels"] if x["label"] == "HOMO")
    assert h["index"] == lv["homo_index"] and h["occ"] == 2
    assert next(x for x in lv["levels"] if x["label"] == "LUMO")["occ"] == 0


def test_tddft_states_have_transition_labels(water_pbe):
    """TD-DFT 상태 목록 — 각 상태에 ΔE·파장·f·주 기여 궤도쌍(HOMO−i → LUMO+a)과 가중치."""
    from server import descriptors
    mf, mol = water_pbe
    uv = descriptors.tddft_lambda_max(mf, nstates=3)
    st = uv["uvvis_states"]
    assert len(st) == 3 and st[0]["state"] == 1
    for row in st:
        assert row["energy_ev"] > 0 and row["wavelength_nm"] > 0 and row["osc_strength"] >= 0
        assert "→" in row["transition"] and 0 < row["weight_pct"] <= 100.0
    assert st[0]["energy_ev"] <= st[1]["energy_ev"] <= st[2]["energy_ev"]
    assert st[0]["transition"].startswith("HOMO")
    bright = max(st, key=lambda r: r["osc_strength"])
    assert abs(bright["energy_ev"] - uv["uvvis_excitation_ev"]) < 1e-3


def test_thermo_public_keeps_freqs_only():
    import numpy as np
    from server import engine
    th = {"norm_mode": np.zeros((3, 3, 3)), "freqs_cm": np.array([1500.2, 3600.7, -20.0]),
          "zpe_hartree": 0.02, "g_corr_hartree": 0.01, "h_corr_hartree": 0.03,
          "entropy_hartree_per_k": 1e-4, "n_imaginary": 1, "lowest_freq_cm": -20.0, "qrrho": None}
    pub = engine._thermo_public(th)
    assert "norm_mode" not in pub and pub["freqs_cm"] == [-20.0, 1500.2, 3600.7]
    assert pub["n_imaginary"] == 1 and pub["zpe_hartree"] == 0.02
    assert engine._thermo_public(None) is None and json.dumps(pub)


def test_builtin_templates_are_valid():
    for t in templates.BUILTIN:
        assert t["builtin"] and t["id"].startswith("tpl-")
        s = templates.validate_settings(t["settings"])
        assert s["accuracy"] in presets.ACCURACY and s["purpose"] in presets.PURPOSES
        assert s["solventId"] in presets.SOLVENTS_BY_ID
        assert s["expert"]["functional"] in presets.FUNCTIONALS


def test_template_save_list_delete(isolated_templates):
    n0 = len(templates.list_templates())
    tpl = templates.save("내 표준 조건", {"accuracy": "표준", "solventId": "sol-water",
                                      "expert": {"functional": "B3LYP-D3(BJ)"}}, desc="수계", electrodes=["graphite"])
    assert tpl["id"].startswith("tpl-") and tpl["builtin"] is False
    assert len(templates.list_templates()) == n0 + 1
    assert templates.get(tpl["id"])["settings"]["solventId"] == "sol-water"
    assert (isolated_templates / "templates.json").exists()
    with pytest.raises(ValueError):
        templates.save("내 표준 조건", {})                       # 이름 중복
    with pytest.raises(ValueError):
        templates.save("x", {"accuracy": "초정밀"})             # 없는 프리셋
    with pytest.raises(ValueError):
        templates.delete("tpl-ncm811-binder")                  # 기본 템플릿 삭제 불가
    assert templates.delete(tpl["id"]) is True
    assert templates.delete(tpl["id"]) is False
    assert len(templates.list_templates()) == n0


def test_template_api_handlers(isolated_templates):
    from fastapi import HTTPException
    from server import main
    req = main.TemplateRequest(name="API 템플릿", settings={"accuracy": "빠름"})
    out = main.create_template(req, _=True)
    assert out["template"]["name"] == "API 템플릿"
    assert any(t["id"] == out["template"]["id"] for t in main.list_templates(_=True)["templates"])
    with pytest.raises(HTTPException) as ei:
        main.create_template(req, _=True)
    assert ei.value.status_code == 400
    assert main.delete_template(out["template"]["id"], _=True)["templates"]
    with pytest.raises(HTTPException) as ei2:
        main.delete_template("tpl-없음", _=True)
    assert ei2.value.status_code == 404


def test_settings_endpoint_reports_backend_and_limits():
    from server import main
    s = main.get_settings(_=True)
    assert s["backend"]["backend"] in ("cpu", "gpu") and "requested" in s["backend"]
    assert s["limits"]["max_atoms"] == main.MAX_ATOMS
    assert s["engine"]["pyscf"] and s["code"]


def test_snapshot_inlines_pages_script():
    from server.main import _snapshot_html
    html = _snapshot_html([])
    assert '<script src="/static/pages.js">' not in html
