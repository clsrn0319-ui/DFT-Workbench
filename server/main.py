"""RhoBench DFT 워크벤치 API 서버.

실행:  uvicorn server.main:app --host 0.0.0.0 --port 8000
"""

from pathlib import Path
from typing import Optional

import csv
import json
import io
import time

import os
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, binder, geometry
from . import convergence, polymer
from . import lookup as lookup_mod
from . import presets, store, worker

# 다중 사용자 보호 한도 (환경변수로 조정 가능)
MAX_ATOMS = int(os.environ.get("RHOBENCH_MAX_ATOMS", "60"))
MAX_ACTIVE_JOBS = int(os.environ.get("RHOBENCH_MAX_ACTIVE_JOBS", "4"))
SESSION_COOKIE = "rb_session"

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="RhoBench DFT Workbench", version="1.0")


class ExpertSettings(BaseModel):
    charge: int = 0
    multiplicity: int = Field(1, ge=1, le=4)
    nConformers: Optional[int] = Field(None, ge=1, le=200)
    functional: str = "PBE0-D3(BJ)"
    basis: Optional[str] = None
    optimizeGeometry: Optional[bool] = None
    thermochemistry: Optional[bool] = None
    redoxAdiabatic: Optional[bool] = None
    nonequilibriumSolvation: Optional[bool] = None
    boltzmannEnsemble: Optional[bool] = None
    optimizeInSolvent: bool = False
    bdeRelaxFragments: Optional[bool] = None
    bdeThermalCorrection: Optional[bool] = None
    freqScale: Optional[float] = Field(None, gt=0.5, lt=1.5)
    scfTol: float = 1e-8


class ExplicitMolecule(BaseModel):
    smiles: str = Field(min_length=1, max_length=200)
    name: Optional[str] = None
    count: int = Field(1, ge=1, le=10)


class MixedSolventComponent(BaseModel):
    abbr: str = Field(min_length=1, max_length=20)
    ratio: float = Field(gt=0)


class MixedSolvent(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    components: list[MixedSolventComponent] = Field(min_length=2, max_length=5)


class JobSettings(BaseModel):
    envType: str = "사용자 정의"
    explicitMolecules: list[ExplicitMolecule] = []
    solventId: Optional[str] = "sol-ecdmc"
    customMixedSolvent: Optional[MixedSolvent] = None  # 용매 라이브러리의 사용자 혼합 용매
    temperature: float = 298.15
    atmosphere: str = "불활성"
    structure: str = "모노머"
    accuracy: str = "표준"
    purpose: str = "전자구조(구조 최적화)"
    referenceElectrode: Optional[str] = "Li/Li+"  # "없음"/None이면 IP·EA만 보고
    expert: ExpertSettings = ExpertSettings()


class CustomMaterial(BaseModel):
    smiles: str = Field(min_length=1, max_length=300)
    name: Optional[str] = None


class JobRequest(BaseModel):
    compareFunctionals: list[str] = []  # 지정 시 범함수마다 작업을 만들어 비교
    materialIds: list[str] = []
    customMaterials: list[CustomMaterial] = []  # 물질 보관함 등 외부 등록 소재
    customSmiles: Optional[str] = None
    customName: Optional[str] = None
    settings: JobSettings = JobSettings()


def require_login(request: Request):
    """공유 비밀번호로 로그인한 세션만 API를 사용할 수 있다."""
    if not auth.is_valid(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(401, "로그인이 필요합니다.")
    return True


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


@app.post("/api/login")
def login(req: LoginRequest, response: Response):
    token = auth.login(req.password)
    if token is None:
        raise HTTPException(401, "비밀번호가 올바르지 않습니다.")
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        max_age=auth.SESSION_TTL)
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    auth.logout(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(_: bool = Depends(require_login)):
    return {"limits": {"max_atoms": MAX_ATOMS, "max_active_jobs": MAX_ACTIVE_JOBS},
            "active_sessions": auth.active_sessions()}


@app.get("/api/presets")
def get_presets(_: bool = Depends(require_login)):
    return {
        "materials": presets.MATERIALS,
        "solvents": [{k: v for k, v in s.items() if k != "smd"} for s in presets.SOLVENTS],
        "envTypes": presets.ENV_TYPES,
        "accuracy": {k: v["desc"] for k, v in presets.ACCURACY.items()},
        "functionals": list(presets.FUNCTIONALS.keys()),
        "basisSets": presets.BASIS_SETS,
        "purposes": presets.PURPOSES,
        "structures": ["모노머", "2량체", "3량체"],
        "atmospheres": ["불활성", "공기", "사용자 정의"],
        "referenceElectrodes": list(presets.ABSOLUTE_POTENTIALS.keys()),
        "defaults": presets.DEFAULT_SETTINGS,
    }


@app.get("/api/binder/candidates")
def binder_candidates(_: bool = Depends(require_login)):
    """건식 음극 바인더 후보 라이브러리 (PFAS 판정 포함)."""
    return {"candidates": binder.candidates(),
            "anode_potentials": binder.ANODE_POTENTIALS,
            "dry_process": binder.DRY_PROCESS,
            "relative_axes": [{"key": k, "axis": a, "lower_is_better": low, "detail": d}
                              for k, a, low, d in binder.RELATIVE_AXES]}


class BinderRankRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=50)


@app.post("/api/binder/rank")
def binder_rank(req: BinderRankRequest, _: bool = Depends(require_login)):
    """선택한 결과들의 상대 축을 순위로 환산한다."""
    wanted = set(req.ids)
    reports = []
    for j in store.list_jobs():
        if j["id"] not in wanted or j["status"] != "PUBLISHED" or not j.get("result"):
            continue
        # 저장본을 쓰지 않고 항상 다시 판정한다 — 순수 함수라 비용이 없고,
        # 판정 로직이 개선되면 예전 결과에도 즉시 반영된다. 바인더 목적이
        # 아니었던 결과도 이 경로로 판정된다.
        rep = binder.report(j["material"], j["result"].get("descriptors") or {})
        reports.append({"material": j["material"]["name"], "id": j["id"], "report": rep})
    if not reports:
        raise HTTPException(400, "선택한 작업 중 판정할 수 있는 완료 결과가 없습니다.")
    return {"reports": reports, "ranks": binder.rank(reports)}


class ConvergenceRequest(BaseModel):
    smiles: str = Field(min_length=1, max_length=300)
    name: Optional[str] = None
    lengths: list[int] = Field(default=list(convergence.DEFAULT_LENGTHS),
                               min_length=2, max_length=6)
    settings: JobSettings = JobSettings()


@app.post("/api/convergence/preview")
def convergence_preview(req: ConvergenceRequest, _: bool = Depends(require_login)):
    """제출 전 확인 — 길이별 올리고머와 물성이 정의되는 최소 길이."""
    lengths = sorted({n for n in req.lengths if 1 <= n <= 12})
    series = convergence.build_series(req.smiles, lengths)
    for entry in series:
        if entry.get("smiles"):
            entry["atom_count"] = geometry.atom_count(entry["smiles"])
            entry["over_limit"] = entry["atom_count"] > MAX_ATOMS
    return {"series": series,
            "minimum_defined": convergence.minimum_defined_length(req.smiles),
            "max_atoms": MAX_ATOMS}


@app.post("/api/convergence/submit")
def convergence_submit(req: ConvergenceRequest, _: bool = Depends(require_login)):
    """사슬 길이 계열을 한 번에 제출한다. 각 작업에 계열 정보를 붙여 둔다."""
    lengths = sorted({n for n in req.lengths if 1 <= n <= 12})
    series = convergence.build_series(req.smiles, lengths)
    usable = [e for e in series if e.get("smiles")
              and geometry.atom_count(e["smiles"]) <= MAX_ATOMS]
    if len(usable) < 2:
        raise HTTPException(
            400, f"원자 수 상한({MAX_ATOMS}) 안에서 계산 가능한 사슬 길이가 2개 미만입니다. "
                 "더 짧은 길이를 고르거나 RHOBENCH_MAX_ATOMS 를 올리세요.")
    if store.count_active() + len(usable) > MAX_ACTIVE_JOBS:
        raise HTTPException(
            400, f"동시 실행 가능한 작업은 {MAX_ACTIVE_JOBS}개입니다 "
                 f"(현재 {store.count_active()}개 진행 중, 요청 {len(usable)}개).")

    settings = req.settings.model_dump()
    # 계열 안에서는 구조 설정이 의미가 없다 — 길이를 SMILES 로 직접 지정하기 때문
    settings["structure"] = "모노머"
    base = req.name or req.smiles
    series_id = "SER-" + secrets.token_hex(4).upper()

    jobs = []
    for entry in usable:
        material = {"id": None, "name": f"{base} (n={entry['n']})",
                    "smiles": entry["smiles"]}
        job = store.create_job(material, settings)
        store.update_job(job["id"], {"series": {
            "id": series_id, "base_name": base, "base_smiles": req.smiles,
            "n": entry["n"]}})
        worker.submit(job["id"])
        jobs.append(store.get_job(job["id"]))
    return {"series_id": series_id, "jobs": jobs,
            "skipped": [e for e in series if e not in usable]}


@app.get("/api/convergence/series")
def convergence_series(_: bool = Depends(require_login)):
    """등록된 사슬 길이 계열 목록."""
    groups: dict[str, dict] = {}
    for j in store.list_jobs():
        s = j.get("series")
        if not s:
            continue
        g = groups.setdefault(s["id"], {
            "series_id": s["id"], "base_name": s["base_name"],
            "base_smiles": s["base_smiles"], "jobs": []})
        g["jobs"].append({"id": j["id"], "n": s["n"], "status": j["status"]})
    for g in groups.values():
        g["jobs"].sort(key=lambda x: x["n"])
        g["done"] = sum(1 for x in g["jobs"] if x["status"] == "PUBLISHED")
        g["total"] = len(g["jobs"])
    return {"series": sorted(groups.values(), key=lambda g: -g["total"])}


@app.get("/api/convergence/analyze")
def convergence_analyze(series_id: str, _: bool = Depends(require_login)):
    """완료된 길이별 결과로 물성별 수렴을 판정한다."""
    entries = []
    base = None
    for j in store.list_jobs():
        s = j.get("series")
        if not s or s["id"] != series_id:
            continue
        base = base or {"name": s["base_name"], "smiles": s["base_smiles"]}
        if j["status"] == "PUBLISHED" and j.get("result"):
            entries.append({"n": s["n"], "job_id": j["id"],
                            "descriptors": j["result"].get("descriptors") or {}})
    if base is None:
        raise HTTPException(404, "해당 계열을 찾을 수 없습니다.")
    if len(entries) < 2:
        raise HTTPException(
            400, f"완료된 길이가 {len(entries)}개뿐입니다 — 수렴 판정에는 2개 이상이 필요합니다.")
    result = convergence.analyze(entries, base_smiles=base["smiles"])
    result["series_id"] = series_id
    result["base"] = base
    result["minimum_defined"] = convergence.minimum_defined_length(base["smiles"])
    return result


class PolymerRequest(BaseModel):
    smiles: str = Field(min_length=1, max_length=300)
    name: Optional[str] = None


@app.post("/api/polymer/card")
def polymer_card(req: PolymerRequest, _: bool = Depends(require_login)):
    """Step 1 — 구조만으로 즉시 산출되는 고분자 물성 카드 (DFT 불필요)."""
    return polymer.property_card({"name": req.name, "smiles": req.smiles})


@app.post("/api/polymer/cards")
def polymer_cards(req: BinderRankRequest, _: bool = Depends(require_login)):
    """완료된 계산 결과에 DFT 경로 물성을 더한 물성 카드 묶음."""
    wanted = set(req.ids)
    cards = []
    for j in store.list_jobs():
        if j["id"] not in wanted or j["status"] != "PUBLISHED" or not j.get("result"):
            continue
        card = polymer.property_card(j["material"], j["result"].get("descriptors"))
        card["job_id"] = j["id"]
        cards.append(card)
    if not cards:
        raise HTTPException(400, "선택한 작업 중 물성 카드를 만들 수 있는 결과가 없습니다.")
    return {"cards": cards}


class PfasCheckRequest(BaseModel):
    smiles: str = Field(min_length=1, max_length=300)


@app.post("/api/binder/pfas")
def binder_pfas(req: PfasCheckRequest, _: bool = Depends(require_login)):
    """구조만으로 PFAS 해당 여부를 즉시 판정 (DFT 계산 불필요)."""
    return binder.pfas_check(req.smiles)


class LookupRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)


@app.post("/api/lookup")
def lookup_compound(req: LookupRequest, _: bool = Depends(require_login)):
    return lookup_mod.lookup(req.query)


@app.post("/api/jobs")
def submit_jobs(req: JobRequest, _: bool = Depends(require_login)):
    settings = req.settings.model_dump()
    if settings["envType"] == "진공·기체":
        settings["solventId"] = None
        settings["customMixedSolvent"] = None
    if settings["solventId"] and settings["solventId"] not in presets.SOLVENTS_BY_ID:
        raise HTTPException(400, f"알 수 없는 용매: {settings['solventId']}")
    if settings["customMixedSolvent"]:
        known = {s["abbr"] for s in presets.SOLVENTS if s["kind"] == "single"}
        for comp in settings["customMixedSolvent"]["components"]:
            if comp["abbr"] not in known:
                raise HTTPException(
                    400, f"혼합 용매 성분 '{comp['abbr']}'의 SMD 파라미터가 없어 계산할 수 없습니다.")
    if settings["accuracy"] not in presets.ACCURACY:
        raise HTTPException(400, f"알 수 없는 정확도 프리셋: {settings['accuracy']}")
    total_explicit = sum(m["count"] for m in settings["explicitMolecules"])
    if total_explicit > 10:
        raise HTTPException(400, f"명시적 주변 분자는 총 10개까지 가능합니다 (현재 {total_explicit}개).")

    targets = []
    for mid in req.materialIds:
        mat = presets.MATERIALS_BY_ID.get(mid)
        if mat is None:
            raise HTTPException(400, f"알 수 없는 소재: {mid}")
        smiles = mat["smiles"].get(settings["structure"])
        if not smiles:
            raise HTTPException(400, f"{mat['name']}: '{settings['structure']}' 구조가 정의되지 않았습니다.")
        targets.append({"id": mid, "name": mat["name"], "abbr": mat["abbr"], "smiles": smiles})
    n_units = {"모노머": 1, "2량체": 2, "3량체": 3}.get(settings["structure"], 1)

    def resolve_custom(smiles, name):
        if n_units > 1:
            try:
                smiles = geometry.oligomerize(smiles, n_units)
            except geometry.GeometryError as exc:
                raise HTTPException(400, f"{name}: {exc}")
        return smiles

    for cm in req.customMaterials:
        name = cm.name or cm.smiles
        targets.append({"id": None, "name": name, "abbr": "보관함",
                        "smiles": resolve_custom(cm.smiles, name)})
    if req.customSmiles:
        name = req.customName or req.customSmiles
        targets.append({"id": None, "name": name, "abbr": "사용자",
                        "smiles": resolve_custom(req.customSmiles, name)})
    if not targets:
        raise HTTPException(400, "계산할 소재를 선택하거나 SMILES를 입력하세요.")

    # 자원 보호: 분자 크기 상한 (수소 포함 원자 수)
    for t in targets:
        n_atoms = geometry.atom_count(t["smiles"])
        extra = sum(geometry.atom_count(m["smiles"]) * m["count"]
                    for m in settings["explicitMolecules"])
        if n_atoms + extra > MAX_ATOMS:
            raise HTTPException(
                400, f"{t['name']}: 원자 수 {n_atoms + extra}개로 상한 {MAX_ATOMS}개를 초과합니다. "
                     "구조를 줄이거나 명시적 주변 분자를 줄이세요.")

    functionals = req.compareFunctionals or [settings["expert"]["functional"]]
    for f in functionals:
        if f not in presets.FUNCTIONALS:
            raise HTTPException(400, f"지원하지 않는 범함수: {f}")

    # 자원 보호: 서버 전체 동시 작업 수 제한 (공유 서버)
    n_new = len(targets) * len(functionals)
    n_active = store.count_active()
    if n_active + n_new > MAX_ACTIVE_JOBS:
        raise HTTPException(
            400, f"서버에서 동시에 실행 가능한 작업은 {MAX_ACTIVE_JOBS}개입니다 "
                 f"(현재 {n_active}개 진행 중, 요청 {n_new}개). 완료를 기다리거나 취소하세요.")

    jobs = []
    for material in targets:
        for f in functionals:
            job_settings = {**settings, "expert": {**settings["expert"], "functional": f}}
            label = dict(material)
            if len(functionals) > 1:
                label["name"] = f"{material['name']} · {f}"
            job = store.create_job(label, job_settings)
            worker.submit(job["id"])
            jobs.append(job)
    return {"jobs": jobs}


CSV_COLUMNS = [
    ("job_id", lambda j: j["id"]),
    ("material", lambda j: j["material"]["name"]),
    ("smiles", lambda j: j["material"].get("smiles", "")),
    ("status", lambda j: j["status"]),
    ("method", lambda j: (j.get("result") or {}).get("conditions", {}).get("method", "")),
    ("solvent_model", lambda j: (j.get("result") or {}).get("conditions", {}).get("solvent_model", "")),
    ("temperature_k", lambda j: (j.get("result") or {}).get("conditions", {}).get("temperature_k", "")),
    ("wall_time_s", lambda j: (j.get("result") or {}).get("wall_time_s", "")),
]


def _csv_text(jobs: list[dict]) -> str:
    desc_keys = []
    for j in jobs:
        for k, v in j["result"]["descriptors"].items():
            if isinstance(v, (int, float)) and k not in desc_keys:
                desc_keys.append(k)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([c[0] for c in CSV_COLUMNS] + desc_keys)
    for j in jobs:
        d = j["result"]["descriptors"]
        writer.writerow([c[1](j) for c in CSV_COLUMNS]
                        + [d.get(k, "") for k in desc_keys])
    return buf.getvalue()


def _js_literal(value) -> str:
    """JS에 그대로 심어도 안전한 JSON 리터럴 (</script>·HTML 주석 차단)."""
    return (json.dumps(value, ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


# 서버 없이 열리는 사본에 심는 계층 — API 호출을 파일 안의 결과로 대체한다.
SNAPSHOT_SHIM_JS = r"""
(function () {
  var D = window.__RB_SNAPSHOT__;
  var DENY = {detail: "결과 보기 전용 페이지입니다 — 새 계산·조회는 RhoBench 서버에서 하세요."};

  function reply(body, ok) {
    return Promise.resolve({
      ok: ok !== false, status: ok !== false ? 200 : 400,
      json: function () { return Promise.resolve(body); },
      text: function () { return Promise.resolve(JSON.stringify(body)); }
    });
  }

  window.fetch = function (input, opts) {
    var url = String(typeof input === "string" ? input : (input && input.url) || "");
    var method = ((opts && opts.method) || "GET").toUpperCase();
    if (method !== "GET") return reply(DENY, false);
    if (url.indexOf("/api/me") === 0) return reply({limits: D.limits, active_sessions: 0});
    if (url.indexOf("/api/presets") === 0) return reply(D.presets);
    var one = url.match(/^\/api\/jobs\/([^/?]+)$/);
    if (one) {
      var hit = D.jobs.filter(function (j) { return j.id === decodeURIComponent(one[1]); })[0];
      return hit ? reply(hit) : reply({detail: "작업을 찾을 수 없습니다."}, false);
    }
    if (url.indexOf("/api/jobs") === 0) return reply({jobs: D.jobs});
    return reply(DENY, false);
  };

  function download(name, text, type) {
    var url = URL.createObjectURL(new Blob([text], {type: type}));
    var a = document.createElement("a");
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function note(text) {
    var p = document.createElement("p");
    p.className = "rb-note";
    p.setAttribute("data-rb-snapshot", "1");
    p.textContent = text;
    return p;
  }

  function prependNote(viewId, text) {
    var v = document.getElementById(viewId);
    if (!v || v.querySelector("[data-rb-snapshot]")) return;
    var first = v.querySelector("h1");
    v.insertBefore(note(text), first ? first.nextSibling : v.firstChild);
  }

  var done = false;
  var timer = setInterval(function () {
    if (done || !document.getElementById("rbv-results")) return;

    var label = "결과 보기 전용 페이지 — 계산 " + D.jobs.length + "건 · " +
      D.exported_at + " 기준 · 결과·그래프·3D 구조는 모두 그대로 보실 수 있습니다.";
    prependNote("rbv-results", label);
    prependNote("rbv-compare", label);
    prependNote("rbv-calc", "이 페이지에서는 새 계산을 제출할 수 없습니다 " +
      "(DFT 계산에는 PySCF 서버가 필요합니다). 아래 설정은 어떤 조건으로 " +
      "계산했는지 보여 주기 위해 그대로 두었습니다.");
    prependNote("rbv-lookup", "이 페이지에서는 물질 조회를 할 수 없습니다 " +
      "(인터넷 조회와 RDKit이 필요합니다).");

    ["submit-btn", "lookup-btn", "add-explicit"].forEach(function (id) {
      var b = document.getElementById(id);
      if (b) { b.disabled = true; b.title = "결과 보기 전용 페이지입니다"; }
    });

    var csv = document.getElementById("export-csv");
    if (csv) csv.onclick = function () {
      download("rhobench_results.csv", D.csv, "text/csv;charset=utf-8");
    };
    var js = document.getElementById("export-json");
    if (js) js.onclick = function () {
      download("rhobench_results.json", JSON.stringify(
        {exported_at: D.exported_at, n_results: D.jobs.length, jobs: D.jobs}, null, 1),
        "application/json");
    };
    var html = document.getElementById("export-html");
    if (html) html.style.display = "none";   // 사본에서 다시 사본을 만들 수는 없다

    var out = document.getElementById("rb-logout");
    if (out) out.style.display = "none";
    var who = document.getElementById("rb-whoami");
    if (who) who.textContent = "결과 보기";

    // 원본 부트 스크립트가 뒤늦게 계산 화면을 열므로, 그 뒤에 결과 화면으로 되돌린다
    [300, 900, 1800, 3200].forEach(function (ms) {
      setTimeout(function () {
        if (window.rbOpenResults) window.rbOpenResults();
      }, ms);
    });

    done = true;
    clearInterval(timer);
  }, 200);
  setTimeout(function () { clearInterval(timer); }, 20000);
})();
"""


def _snapshot_html(jobs: list[dict]) -> str:
    """서버 없이 열리는 결과 보기 전용 HTML 한 파일을 만든다.

    화면(web/index.html)과 로직(web/app.js)을 그대로 담고, 그 앞에 fetch 가로채기
    계층을 넣어 API 대신 파일에 심어 둔 결과를 돌려준다. 계산 제출·물질 조회처럼
    서버가 필요한 동작은 안내 문구와 함께 잠긴다.
    """
    page = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    marker = '<script src="/static/app.js"></script>'
    if marker not in page:
        raise HTTPException(500, "index.html에서 app.js 로드 지점을 찾지 못했습니다.")

    snapshot = {
        "exported_at": time.strftime("%Y-%m-%d %H:%M"),
        "jobs": jobs,
        "presets": get_presets(_=True),
        "limits": {"max_atoms": MAX_ATOMS, "max_active_jobs": MAX_ACTIVE_JOBS},
        "csv": "\ufeff" + _csv_text(jobs),
    }
    shim = ("<script>\nwindow.__RB_SNAPSHOT__ = " + _js_literal(snapshot) + ";\n"
            + SNAPSHOT_SHIM_JS + "\n</script>")
    # app.js 안의 </script> 는 HTML 파서가 스크립트를 끊지 않도록 감싼다
    inline = "<script>\n" + app_js.replace("</script", "<\\/script") + "\n</script>"
    return page.replace(marker, shim + "\n" + inline)


@app.get("/api/export")
def export_results(format: str = "json", ids: str = "",
                   _: bool = Depends(require_login)):
    """PUBLISHED 결과 내보내기 — ids를 주면 해당 작업만, 없으면 전체.

    format: json · csv · html(서버 없이 열리는 단일 파일 사본)
    """
    wanted = {i.strip() for i in ids.split(",") if i.strip()}
    jobs = [j for j in store.list_jobs()
            if j["status"] == "PUBLISHED" and j.get("result")
            and (not wanted or j["id"] in wanted)]
    if wanted and not jobs:
        raise HTTPException(400, "선택한 작업 중 내보낼 수 있는 완료 결과가 없습니다.")
    if format == "json":
        return JSONResponse(
            content={"exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "n_results": len(jobs), "jobs": jobs},
            headers={"Content-Disposition": 'attachment; filename="rhobench_results.json"'})

    if format == "html":
        if not jobs:
            raise HTTPException(400, "내보낼 완료 결과가 없습니다. 먼저 계산을 완료하세요.")
        return Response(
            content=_snapshot_html(jobs),
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="rhobench_results.html"'})

    return Response(
        content="\ufeff" + _csv_text(jobs),  # BOM — Excel 한글 깨짐 방지
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="rhobench_results.csv"'})


def _job_or_404(job_id: str) -> dict:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    return job


@app.get("/api/jobs")
def list_jobs(_: bool = Depends(require_login)):
    return {"jobs": store.list_jobs()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, _: bool = Depends(require_login)):
    return _job_or_404(job_id)


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, _: bool = Depends(require_login)):
    old = _job_or_404(job_id)
    if old["status"] != "FAILED":
        raise HTTPException(400, "실패한 작업만 재시도할 수 있습니다.")
    if store.count_active() >= MAX_ACTIVE_JOBS:
        raise HTTPException(400, f"동시 실행 가능한 작업은 {MAX_ACTIVE_JOBS}개입니다.")
    job = store.create_job(old["material"], old["settings"])
    job["logs"].append(f"재시도 — 원본 작업 {job_id}")
    store.update_job(job["id"], {"logs": job["logs"]})
    worker.submit(job["id"])
    return job


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str, _: bool = Depends(require_login)):
    _job_or_404(job_id)
    if not store.request_cancel(job_id):
        raise HTTPException(400, "취소할 수 없는 상태입니다.")
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str, _: bool = Depends(require_login)):
    _job_or_404(job_id)
    if not store.delete_job(job_id):
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
