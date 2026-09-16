"""워크스페이스 개편(기획서 반영) — 궤도 점 구름, 템플릿, 설정 API."""

import json

import pytest

from server import presets, store, templates


@pytest.fixture
def isolated_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


def test_orbital_cloud_real_scf():
    """물 분자 STO-3G — HOMO/LUMO 점 구름이 부호·에너지·격자 정보를 갖고, LUMO 는 HOMO 위 궤도다."""
    from pyscf import dft, gto
    from server import descriptors
    mol = gto.M(atom="O 0 0 0.117; H 0 0.757 -0.469; H 0 -0.757 -0.469", basis="sto-3g", verbose=0)
    mf = dft.RKS(mol, xc="pbe"); mf.kernel()
    clouds = descriptors.orbital_clouds(mf, mol)
    homo, lumo = clouds["homo"], clouds["lumo"]
    assert homo and lumo and lumo["index"] == homo["index"] + 1
    assert homo["which"] == "homo" and lumo["energy_ev"] > homo["energy_ev"]
    assert 50 < len(homo["points"]) <= 2500 and len(homo["value"]) == len(homo["points"])
    vals = homo["value"]
    assert any(v > 0 for v in vals) and any(v < 0 for v in vals)      # 위상 두 lobe
    assert homo["abs_max"] >= max(abs(v) for v in vals) - 1e-3
    assert all(len(p) == 3 for p in homo["points"])
    assert json.dumps(clouds)                                          # JSON 직렬화 가능


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
