"""RhoBench DFT 워크벤치 API 서버.

실행:  uvicorn server.main:app --host 0.0.0.0 --port 8000
"""

from pathlib import Path
from typing import Optional

import csv
import io
import time

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import geometry
from . import lookup as lookup_mod
from . import presets, store, worker

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


@app.get("/api/presets")
def get_presets():
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


class LookupRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)


@app.post("/api/lookup")
def lookup_compound(req: LookupRequest):
    return lookup_mod.lookup(req.query)


@app.post("/api/jobs")
def submit_jobs(req: JobRequest):
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

    functionals = req.compareFunctionals or [settings["expert"]["functional"]]
    for f in functionals:
        if f not in presets.FUNCTIONALS:
            raise HTTPException(400, f"지원하지 않는 범함수: {f}")

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


@app.get("/api/export")
def export_results(format: str = "json"):
    """PUBLISHED 결과 일괄 내보내기 — 표 형식(csv) 또는 전체 원본(json)."""
    jobs = [j for j in store.list_jobs() if j["status"] == "PUBLISHED" and j.get("result")]
    if format == "json":
        return JSONResponse(
            content={"exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "n_results": len(jobs), "jobs": jobs},
            headers={"Content-Disposition": 'attachment; filename="rhobench_results.json"'})

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
    return Response(
        content="\ufeff" + buf.getvalue(),  # BOM — Excel 한글 깨짐 방지
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="rhobench_results.csv"'})


@app.get("/api/jobs")
def list_jobs():
    return {"jobs": store.list_jobs()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    return job


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str):
    old = store.get_job(job_id)
    if old is None:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    if old["status"] != "FAILED":
        raise HTTPException(400, "실패한 작업만 재시도할 수 있습니다.")
    job = store.create_job(old["material"], old["settings"])
    job["logs"].append(f"재시도 — 원본 작업 {job_id}")
    store.update_job(job["id"], {"logs": job["logs"]})
    worker.submit(job["id"])
    return job


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if not store.request_cancel(job_id):
        raise HTTPException(400, "취소할 수 없는 상태입니다.")
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    if not store.delete_job(job_id):
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
