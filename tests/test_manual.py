"""프로그램 안 사용 설명서 — 본문 원본(web/manual_content.js)·도움말 배치(web/help.js)·API 의 정합성.

설명서 본문은 web/manual_content.js 하나에서 «사용 설명서» 페이지, ? 도움말 패널, Word 파일이
모두 나온다. 여기서는 그 원본이 깨지지 않았는지, ? 버튼이 가리키는 절이 실제로 있는지,
Word 내려받기와 공유용 HTML 스냅샷이 설명서를 포함하는지를 검사한다.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "web" / "manual_content.js"
HELP_JS = ROOT / "web" / "help.js"
INDEX = ROOT / "web" / "index.html"

BLOCK_TYPES = {"p", "h2", "h3", "ul", "ol", "tip", "warn", "code", "table", "qa"}


def load_manual() -> dict:
    text = CONTENT.read_text(encoding="utf-8")
    i = text.index("window.RB_MANUAL")
    body = text[text.index("=", i) + 1:].strip().rstrip(";")
    return json.loads(body)


def section_ids(manual: dict) -> set[str]:
    ids = set()
    for ch in manual["chapters"]:
        ids.add(ch["id"])
        for b in ch["blocks"]:
            if b["t"] == "h2":
                ids.add(b["id"])
    return ids


def test_manual_content_is_well_formed():
    """원본 파일은 JSON 으로 읽히고, 장·절 id 가 규칙(chN / sN-k)대로 유일해야 한다."""
    m = load_manual()
    assert m["version"] and m["date"] and m["title"]
    assert len(m["chapters"]) >= 13

    seen = set()
    for ch in m["chapters"]:
        assert re.fullmatch(r"ch(\d+|[A-Z])", ch["id"]), ch["id"]
        assert ch["id"] not in seen
        seen.add(ch["id"])
        assert ch["title"] and ch["blocks"]
        k = 0
        for b in ch["blocks"]:
            assert b["t"] in BLOCK_TYPES, b
            if b["t"] == "h2":
                k += 1
                assert b["id"] == f"s{ch['num']}-{k}", (b["id"], ch["num"], k)
                assert b["id"] not in seen
                seen.add(b["id"])
            elif b["t"] == "table":
                assert len(b["headers"]) == len(b["widths"])
                for row in b["rows"]:
                    assert len(row) == len(b["headers"]), (ch["id"], row)
            elif b["t"] in ("ul", "ol"):
                assert b["items"]
            elif b["t"] == "qa":
                assert b["q"] and b["a"], b
        if "goto" in ch:
            assert ch["goto"]["mode"] and ch["goto"]["label"]

    # v3.1 에 남아 있던 빈 FAQ 틀(«Q. 질문 / 답»)이 다시 들어오지 않도록
    assert not any(b.get("q") == "질문" for ch in m["chapters"] for b in ch["blocks"])


def test_help_anchors_point_to_existing_sections():
    """help.js 의 기본 ? 도움말이 가리키는 절·장은 모두 설명서에 있어야 한다."""
    ids = section_ids(load_manual())
    src = HELP_JS.read_text(encoding="utf-8")
    defaults = src[src.index("var DEFAULTS"):src.index("var MODE_CHAPTER")]
    refs = re.findall(r'section:\s*"([^"]+)"', defaults)
    assert len(refs) >= 30
    missing = sorted({r for r in refs if r not in ids})
    assert not missing, missing

    modes = re.findall(r'\b[a-z]+:\s*"(ch\d+)"', src[src.index("var MODE_CHAPTER"):src.index("var HOST_SEL")])
    assert modes and all(m in ids for m in modes)

    anchor_ids = re.findall(r'\{ id:\s*"([^"]+)"', defaults)
    assert len(anchor_ids) == len(set(anchor_ids)), "도움말 id 중복"


def test_index_wires_manual_page():
    """index.html 에 «사용 설명서» 메뉴·mode-manual·스크립트 로드가 있어야 한다."""
    page = INDEX.read_text(encoding="utf-8")
    assert '{label: "사용 설명서", mode: "manual"}' in page
    assert "#rb-real.mode-manual #rbv-manual{display:block}" in page
    assert '<div id="rbv-manual" class="rbv">' in page
    assert page.index('<script src="/static/app.js">') < page.index('<script src="/static/manual_content.js">') \
        < page.index('<script src="/static/help.js">')
    assert "window.rbOpenMode = openReal" in page
    assert '"mode-manual"' in page[page.index("function openReal"):]


def test_snapshot_inlines_manual_and_help():
    """공유용 HTML 사본에도 설명서 본문과 도움말 스크립트가 들어가야 한다(서버 없이 열리므로)."""
    from server.main import _snapshot_html
    html = _snapshot_html([])
    assert '<script src="/static/manual_content.js">' not in html
    assert '<script src="/static/help.js">' not in html
    assert "window.RB_MANUAL = {" in html
    assert "rb-help-layout" in html


def test_manual_docx_download_requires_login(tmp_path, monkeypatch):
    """Word 파일은 로그인한 세션에만 내려주고, 파일명·형식이 맞아야 한다.

    (테스트 환경에 httpx 가 없어 TestClient 대신 의존성·핸들러를 직접 호출한다.)
    """
    from types import SimpleNamespace
    from fastapi import HTTPException
    from server import auth
    from server.main import MANUAL_DOCX, SESSION_COOKIE, manual_docx, require_login

    monkeypatch.setattr(auth, "ACCESS_FILE", tmp_path / "access.json")
    monkeypatch.setattr(auth, "DATA_DIR", tmp_path)
    monkeypatch.setattr(auth, "_access", None)
    monkeypatch.setattr(auth, "_sessions", {})
    monkeypatch.setattr(auth, "_loaded", False)
    monkeypatch.setenv("RHOBENCH_ACCESS_PASSWORD", "manual-test-pw")

    with pytest.raises(HTTPException) as ei:
        require_login(SimpleNamespace(cookies={}))
    assert ei.value.status_code == 401

    token = auth.login("manual-test-pw")
    assert require_login(SimpleNamespace(cookies={SESSION_COOKIE: token})) is True

    resp = manual_docx(_=True)
    assert resp.status_code == 200
    assert resp.media_type.startswith("application/vnd.openxmlformats-officedocument.wordprocessingml")
    assert "07_DFT-Workbench" in resp.headers.get("content-disposition", "")
    assert Path(resp.path) == MANUAL_DOCX
    assert MANUAL_DOCX.read_bytes()[:2] == b"PK"      # docx = zip


def test_manual_docx_missing_gives_404(monkeypatch, tmp_path):
    from fastapi import HTTPException
    from server import main
    monkeypatch.setattr(main, "MANUAL_DOCX", tmp_path / "없음.docx")
    with pytest.raises(HTTPException) as ei:
        main.manual_docx(_=True)
    assert ei.value.status_code == 404


def test_manual_docx_matches_content_version():
    """docs/ 의 Word 파일은 원본(manual_content.js)과 같은 버전으로 만들어져 있어야 한다."""
    import zipfile
    from server.main import MANUAL_DOCX
    m = load_manual()
    with zipfile.ZipFile(MANUAL_DOCX) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    text = re.sub(r"<[^>]+>", "", xml)
    assert f"{m['version']} ({m['date']})" in text
    for ch in m["chapters"][:3]:
        assert ch["title"] in text
