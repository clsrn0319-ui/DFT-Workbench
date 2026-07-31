"""RhoBench DFT 워크벤치 API 서버.

실행:  uvicorn server.main:app --host 0.0.0.0 --port 8000
"""

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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
    scfTol: float = 1e-8


class ExplicitMolecule(BaseModel):
    smiles: str = Field(min_length=1, max_length=200)
    name: Optional[str] = None
    count: int = Field(1, ge=1, le=10)


class JobSettings(BaseModel):
    envType: str = "배터리 전해액"
    explicitMolecules: list[ExplicitMolecule] = []
    solventId: Optional[str] = "sol-ecdmc"
    temperature: float = 298.15
    atmosphere: str = "불활성"
    structure: str = "모노머"
    accuracy: str = "표준"
    purpose: str = "전자구조(구조 최적화)"
    referenceElectrode: str = "Li/Li+"
    expert: ExpertSettings = ExpertSettings()


class CustomMaterial(BaseModel):
    smiles: str = Field(min_length=1, max_length=300)
    name: Optional[str] = None


class JobRequest(BaseModel):
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
    elif settings["envType"] == "배터리 전해액" and not settings["solventId"]:
        raise HTTPException(400, "배터리 전해액 환경에는 용매 프리셋 선택이 필요합니다.")
    if settings["solventId"] and settings["solventId"] not in presets.SOLVENTS_BY_ID:
        raise HTTPException(400, f"알 수 없는 용매: {settings['solventId']}")
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
    for cm in req.customMaterials:
        targets.append({"id": None, "name": cm.name or cm.smiles,
                        "abbr": "보관함", "smiles": cm.smiles})
    if req.customSmiles:
        targets.append({"id": None, "name": req.customName or req.customSmiles,
                        "abbr": "사용자", "smiles": req.customSmiles})
    if not targets:
        raise HTTPException(400, "계산할 소재를 선택하거나 SMILES를 입력하세요.")

    jobs = []
    for material in targets:
        job = store.create_job(material, settings)
        worker.submit(job["id"])
        jobs.append(job)
    return {"jobs": jobs}


@app.get("/api/jobs")
def list_jobs():
    return {"jobs": store.list_jobs()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
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
