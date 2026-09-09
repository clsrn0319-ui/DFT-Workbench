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
from . import convergence, esw, mechanical, polymer, protocol
from . import lookup as lookup_mod
from . import checkpoint, monitor
from . import presets, scoring, screening, store, structfile, worker

# 다중 사용자 보호 한도 (환경변수로 조정 가능)
MAX_ATOMS = int(os.environ.get("RHOBENCH_MAX_ATOMS", "60"))
MAX_ACTIVE_JOBS = int(os.environ.get("RHOBENCH_MAX_ACTIVE_JOBS", "4"))
SESSION_COOKIE = "rb_session"

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="RhoBench DFT Workbench", version="1.0")


@app.on_event("startup")
def _resume_campaigns():
    """서버 재시작 시 중단된 작업을 체크포인트에서 재개하고, 캠페인을 이어서 진행한다."""
    n = worker.resubmit_pending()
    if n:
        print(f"\n  RhoBench: 중단됐던 작업 {n}건을 체크포인트에서 재개합니다.\n", flush=True)
    screening.ensure_started()


class ExpertSettings(BaseModel):
    charge: int = 0
    multiplicity: int = Field(1, ge=1, le=4)
    nConformers: Optional[int] = Field(None, ge=1, le=200)
    functional: str = "PBE0-D3(BJ)"
    basis: Optional[str] = None
    basisAnion: Optional[str] = None      # 음이온 전용 diffuse 기저 (비우면 정확도 프리셋)
    qrrho: Optional[bool] = None          # 저진동수 엔트로피 qRRHO 보정 (기본 수행)
    optimizeGeometry: Optional[bool] = None
    thermochemistry: Optional[bool] = None
    redoxAdiabatic: Optional[bool] = None
    nonequilibriumSolvation: Optional[bool] = None
    boltzmannEnsemble: Optional[bool] = None
    # 전위 conformer 민감도 (v2.0 P0-5) — None: 프리셋(표준 3·정밀 5), True: 최소 3, False: 끔
    conformerSensitivity: Optional[bool] = None
    # Li⁺ 상호작용 모델 (v2.0 P0-6) — bare: 고립 Li⁺ 결합, competition: Li(solv)n⁺ 용매 경쟁
    liModel: Optional[str] = Field(None, pattern="^(bare|competition)$")
    liCoordination: Optional[int] = Field(None, ge=1, le=6)
    liMaxSites: Optional[int] = Field(None, ge=1, le=6)
    optimizeInSolvent: bool = False
    bdeRelaxFragments: Optional[bool] = None
    bdeThermalCorrection: Optional[bool] = None
    freqScale: Optional[float] = Field(None, gt=0.5, lt=1.5)
    scfTol: float = 1e-8
    # SCF 최대 반복 (비우면 PySCF 기본 50). 모니터링 시나리오 «max_cycle 을 작게» 용도 포함
    scfMaxCycle: Optional[int] = Field(None, ge=1, le=1000)
    # PySCF 원본 로그 수준 — 간략(끔) / 상세(SCF 반복·궤도) / 디버그
    logLevel: Optional[str] = None


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


class CustomGeometry(BaseModel):
    """업로드된 3D 구조 — [원소, x, y, z] 목록 (Å). rescan이면 좌표를 버리고
    conformer 탐색부터 다시 한다."""
    atoms: list[list] = Field(min_length=1, max_length=500)
    source: str = Field("upload", max_length=20)
    rescan: bool = False


class JobRequest(BaseModel):
    compareFunctionals: list[str] = []  # 지정 시 범함수마다 작업을 만들어 비교
    materialIds: list[str] = []
    customMaterials: list[CustomMaterial] = []  # 물질 보관함 등 외부 등록 소재
    customSmiles: Optional[str] = None
    customName: Optional[str] = None
    customGeometry: Optional[CustomGeometry] = None  # customSmiles의 업로드 3D 좌표
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
        "diffuseBasisSets": presets.DIFFUSE_BASIS_SETS,
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
    # 비닐 단량체면 n=1이 판정에서 빠지므로, 제출 «전»에 알려 길이를 더 넣게 한다
    seg = convergence.monomer_is_chain_segment(req.smiles)
    judged = [n for n in lengths if not (n == 1 and not seg["same_species"])]
    return {"series": series,
            "minimum_defined": convergence.minimum_defined_length(req.smiles),
            "monomer_excluded": not seg["same_species"],
            "exclusion_note": seg["note"],
            "judged_lengths": judged,
            "extrapolation_available": len(judged) >= 3,
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


class EswDiagnoseRequest(BaseModel):
    job_id: Optional[str] = None
    smiles: Optional[str] = Field(default=None, max_length=300)
    name: Optional[str] = None
    descriptors: Optional[dict] = None
    electrode: str = "graphite"


@app.post("/api/esw/diagnose")
def esw_diagnose(req: EswDiagnoseRequest, _: bool = Depends(require_login)):
    """ESW 판정을 구조까지 되짚는다 — 「왜 경계인가」."""
    material, desc, e_abs = None, req.descriptors or {}, 1.44
    if req.job_id:
        job = store.get_job(req.job_id)
        if job is None or job.get("status") != "PUBLISHED" or not job.get("result"):
            raise HTTPException(404, "완료된 작업을 찾을 수 없습니다.")
        material = job["material"]
        desc = job["result"].get("descriptors") or {}
        ref = (job.get("settings") or {}).get("referenceElectrode")
        e_abs = presets.ABSOLUTE_POTENTIALS.get(ref, 1.44)
    elif req.smiles:
        material = {"name": req.name or req.smiles, "smiles": req.smiles}
    else:
        raise HTTPException(400, "job_id 또는 smiles 중 하나가 필요합니다.")
    try:
        return esw.diagnose(material, desc, electrode=req.electrode, e_abs=e_abs)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/esw/electrodes")
def esw_electrodes(_: bool = Depends(require_login)):
    """전극 구동 «범위» — 단일 전위값이 아니라 범위로 판정한다."""
    return {"electrodes": esw.ELECTRODE_WINDOWS,
            "lumo_reference": esw.LUMO_REFERENCE}

@app.get("/api/protocol/card")
def protocol_meta(_: bool = Depends(require_login)):
    """프로토콜 규약 · 검증 상태 — 결과를 인용할 때 함께 밝혀야 할 정보."""
    return {
        "protocol_version": protocol.PROTOCOL_VERSION,
        "reference_conventions": protocol.REFERENCE_CONVENTIONS,
        "default_convention": protocol.DEFAULT_CONVENTION,
        "convention_spread_v": protocol.CONVENTION_SPREAD_V,
        "environment_levels": protocol.ENVIRONMENT_LEVELS,
        "confidence_axes": [{"key": k, "label": l, "detail": d}
                            for k, l, d in protocol.CONFIDENCE_AXES],
        "validation": protocol.validation_status(),
        "uncertainty_v": esw.DEFAULT_UNCERTAINTY_V,
        "uncertainty_source": esw.UNCERTAINTY_SOURCE,
    }


@app.post("/api/esw/gate")
def esw_gate(req: EswDiagnoseRequest, _: bool = Depends(require_login)):
    """불확실성을 반영한 Hard Gate — Robust Pass / Borderline / Robust Fail."""
    desc = req.descriptors or {}
    if req.job_id:
        job = store.get_job(req.job_id)
        if job is None or not job.get("result"):
            raise HTTPException(404, "완료된 작업을 찾을 수 없습니다.")
        desc = job["result"].get("descriptors") or {}
    red = esw.first_present(desc, "reduction_potential_gibbs_v", "reduction_potential_v")
    ox = esw.first_present(desc, "oxidation_potential_gibbs_v", "oxidation_potential_v")
    if red is None or ox is None:
        raise HTTPException(400, "전위 데이터가 없어 게이트를 적용할 수 없습니다.")
    win = esw.ELECTRODE_BY_KEY.get(req.electrode)
    if win is None:
        raise HTTPException(400, f"알 수 없는 전극: {req.electrode}")
    # conformer 편차가 있으면 잠정 폭에 합성해 구간을 넓힌다 (P0-5)
    return esw.gate_with_uncertainty(red, ox, win,
                                     conformer_std_v=desc.get("conformer_spread_v"))


class MechanicalRequest(BaseModel):
    smiles: str = Field(min_length=1, max_length=300)
    name: Optional[str] = None
    temperature_c: float = Field(default=25.0, ge=-273.0, le=600.0)
    entanglement_mw: Optional[float] = Field(default=None, gt=0, le=1e6)


@app.post("/api/mechanical/card")
def mechanical_card(req: MechanicalRequest, _: bool = Depends(require_login)):
    """Step 2 — 사용 온도에서의 역학 상태 판정과 문헌 탄성 상수."""
    return mechanical.report(req.smiles, req.temperature_c,
                             entanglement_mw=req.entanglement_mw, name=req.name)


@app.post("/api/mechanical/states")
def mechanical_states(req: MechanicalRequest, _: bool = Depends(require_login)):
    """건식 바인더 후보 전체를 한 온도에서 한 번에 판정한다."""
    rows = []
    for cand in binder.DRY_BINDER_CANDIDATES + binder.PFAS_REFERENCES:
        st = mechanical.state_at(cand["smiles"], req.temperature_c)
        rows.append({"name": cand["name"], "smiles": cand["smiles"],
                     "state": st["state"], "confident": st["confident"],
                     "tg_c": st.get("tg_c"), "tm_c": st.get("tm_c"),
                     "decomp_c": st.get("decomp_c"), "note": st.get("note")})
    return {"temperature_c": req.temperature_c, "rows": rows,
            "refusal": mechanical.REFUSAL}


@app.post("/api/mechanical/elastic")
def mechanical_elastic(payload: dict, _: bool = Depends(require_login)):
    """탄성 관계식 환산 — (E, ν) 또는 (K, G) 중 한 쌍을 받는다."""
    try:
        return mechanical.elastic_constants(
            e_gpa=payload.get("e_gpa"), poisson=payload.get("poisson"),
            bulk_gpa=payload.get("bulk_gpa"), shear_gpa=payload.get("shear_gpa"),
            density_g_cm3=payload.get("density_g_cm3"))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


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


class StructureParseRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5_000_000)
    filename: str = Field("", max_length=300)
    charge: int = Field(0, ge=-4, le=4)   # XYZ 결합 추정용 (SDF/MOL은 무관)


@app.post("/api/structures/parse")
def structures_parse(req: StructureParseRequest, _: bool = Depends(require_login)):
    """3D 구조 파일(SDF/MOL·XYZ) 텍스트를 후보 목록으로 해석한다.

    단건 계산·배치 스크리닝 공용. 좌표는 초기 구조로 쓰이며(conformer 탐색
    생략), «구조 재탐색» 옵션으로 기존 경로로 되돌릴 수 있다.
    """
    parsed = structfile.parse_structures(req.content, req.filename, req.charge)
    for m in parsed["molecules"]:
        if m["ok"] and m["n_atoms"] and m["n_atoms"] > MAX_ATOMS:
            m["ok"] = False
            m["error"] = f"원자 수 {m['n_atoms']}개 — 상한 {MAX_ATOMS}개 초과"
    parsed["n_ok"] = sum(1 for m in parsed["molecules"] if m["ok"])
    parsed["n_error"] = sum(1 for m in parsed["molecules"] if not m["ok"])
    parsed["max_atoms"] = MAX_ATOMS
    return parsed


class ScreeningParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    structure: str = "모노머"


class ScreeningCandidate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    smiles: str = Field(min_length=1, max_length=300)
    geometry: Optional[CustomGeometry] = None   # 업로드 3D 구조 (선택)


class ScreeningStage(BaseModel):
    accuracy: str
    # 계산량 상한 — 임계값을 통과해도 이 개수까지만 다음 단계로 보낸다
    keep: Optional[int] = Field(None, ge=1, le=10_000)
    # 통과 임계값 (안정성 여유, V). None 이면 개수 기준만 적용 (v2.0 14.7)
    threshold: Optional[float] = Field(None, ge=-5.0, le=5.0)


class CustomElectrode(BaseModel):
    """사용자 정의 활물질 — 구동 전위 범위(V vs Li/Li+)를 직접 지정한다."""
    label: str = Field(min_length=1, max_length=40)
    low: float = Field(ge=-0.5, le=6.0)
    high: float = Field(ge=-0.5, le=6.0)


class ScoringConfig(BaseModel):
    """5대 DFT Score 설정 (기획서 7장) — 켜면 마지막 단계에서 물성 지문까지 계산."""
    enabled: bool = False
    preset: str = "균등"
    weights: Optional[dict] = None   # 축 키 → 가중치 (서버가 합=1 로 재정규화)


class ScreeningCampaignRequest(BaseModel):
    name: str = Field("", max_length=100)
    candidates: list[ScreeningCandidate] = Field(min_length=1)
    electrodes: list[str] = Field(default=[], max_length=5)
    customElectrodes: list[CustomElectrode] = Field(default=[], max_length=5)
    marginV: float = Field(0.3, ge=0.0, le=2.0)
    stages: list[ScreeningStage] = Field(min_length=1, max_length=3)
    rescanGeometry: bool = False   # 업로드 3D 좌표를 버리고 conformer 탐색부터
    scoring: ScoringConfig = ScoringConfig()
    settings: JobSettings = JobSettings()


@app.get("/api/screening/meta")
def screening_meta(_: bool = Depends(require_login)):
    """배치 스크리닝 화면 구성용 — 전극·프리셋·한도·추정 단가."""
    return {"electrodes": esw.ELECTRODE_WINDOWS,
            "accuracy": {k: v["desc"] for k, v in presets.ACCURACY.items()},
            "estimate_s": screening.ESTIMATE_S,
            "max_candidates": screening.MAX_CANDIDATES,
            "batch_parallel": screening.BATCH_PARALLEL,
            "max_atoms": MAX_ATOMS,
            "default_margin_v": 0.3,
            "vertical_red_buffer": screening.VERTICAL_RED_BUFFER,
            "score_axes": scoring.AXES,
            "weight_presets": scoring.WEIGHT_PRESETS,
            "score_anchors": scoring.ANCHORS,
            "protocol_version": scoring.PROTOCOL_VERSION,
            "purpose": screening.SCREEN_PURPOSE,
            "thermo_note": screening.THERMO_NOTE}


@app.post("/api/screening/parse")
def screening_parse(req: ScreeningParseRequest, _: bool = Depends(require_login)):
    """후보 목록 텍스트(CSV·SMILES 줄 목록)를 검증한다 — 제출 전 확인용."""
    if req.structure not in ("모노머", "2량체", "3량체"):
        raise HTTPException(400, f"알 수 없는 구조: {req.structure}")
    parsed = screening.parse_candidates(req.text, structure=req.structure,
                                        max_atoms=MAX_ATOMS)
    if parsed["n_ok"] > screening.MAX_CANDIDATES:
        parsed["warning"] = (f"유효 후보 {parsed['n_ok']}개 — 캠페인 상한 "
                             f"{screening.MAX_CANDIDATES}개를 초과합니다. 나눠서 제출하세요.")
    return parsed


class ScreeningParseXlsxRequest(BaseModel):
    contentB64: str = Field(min_length=1, max_length=20_000_000)   # base64 인코딩 .xlsx
    structure: str = "모노머"


@app.post("/api/screening/parse-xlsx")
def screening_parse_xlsx(req: ScreeningParseXlsxRequest,
                         _: bool = Depends(require_login)):
    """엑셀(.xlsx) 후보 목록 검증 — 첫 시트를 CSV 로 변환해 같은 검증을 거친다."""
    if req.structure not in ("모노머", "2량체", "3량체"):
        raise HTTPException(400, f"알 수 없는 구조: {req.structure}")
    import base64
    import binascii
    try:
        data = base64.b64decode(req.contentB64, validate=True)
    except binascii.Error:
        raise HTTPException(400, "파일 인코딩이 올바르지 않습니다.")
    try:
        text = screening.xlsx_to_text(data)
    except Exception as exc:  # noqa: BLE001 — openpyxl 오류를 사용자 문구로
        raise HTTPException(400, f"엑셀 파일을 읽지 못했습니다: {exc}")
    if not text.strip():
        raise HTTPException(400, "엑셀 첫 시트가 비어 있습니다.")
    parsed = screening.parse_candidates(text, structure=req.structure,
                                        max_atoms=MAX_ATOMS)
    if parsed["n_ok"] > screening.MAX_CANDIDATES:
        parsed["warning"] = (f"유효 후보 {parsed['n_ok']}개 — 캠페인 상한 "
                             f"{screening.MAX_CANDIDATES}개를 초과합니다. 나눠서 제출하세요.")
    return parsed


@app.post("/api/screening/campaigns")
def screening_create(req: ScreeningCampaignRequest, _: bool = Depends(require_login)):
    for e in req.electrodes:
        if e not in esw.ELECTRODE_BY_KEY:
            raise HTTPException(400, f"알 수 없는 전극: {e}")
    customs = []
    for i, ce in enumerate(req.customElectrodes, start=1):
        if ce.low >= ce.high:
            raise HTTPException(400, f"{ce.label}: 구동 하한이 상한보다 작아야 합니다.")
        customs.append({"key": f"custom-{i}", "label": ce.label,
                        "low": ce.low, "high": ce.high, "nominal": ce.high,
                        "side": "사용자", "note": "사용자 정의 활물질"})
    electrodes = req.electrodes + [c["key"] for c in customs]
    if not electrodes:
        raise HTTPException(400, "대상 활물질을 선택하거나 사용자 정의 활물질을 추가하세요.")
    for st in req.stages:
        if st.accuracy not in presets.ACCURACY:
            raise HTTPException(400, f"알 수 없는 정확도 프리셋: {st.accuracy}")
    if len(req.candidates) > screening.MAX_CANDIDATES:
        raise HTTPException(400, f"후보는 캠페인당 {screening.MAX_CANDIDATES}개까지입니다 "
                                 f"(요청 {len(req.candidates)}개).")
    settings = req.settings.model_dump()
    if settings["envType"] == "진공·기체":
        settings["solventId"] = None
        settings["customMixedSolvent"] = None
    if settings["solventId"] and settings["solventId"] not in presets.SOLVENTS_BY_ID:
        raise HTTPException(400, f"알 수 없는 용매: {settings['solventId']}")
    if settings.get("customMixedSolvent"):
        known = {s["abbr"] for s in presets.SOLVENTS if s["kind"] == "single"}
        for comp in settings["customMixedSolvent"]["components"]:
            if comp["abbr"] not in known:
                raise HTTPException(
                    400, f"혼합 용매 성분 '{comp['abbr']}'의 SMD 파라미터가 없어 계산할 수 없습니다.")

    # 후보를 서버에서 다시 검증한다 — 파싱 화면을 거치지 않은 API 호출 대비
    structure = settings.get("structure", "모노머")
    validated = []
    for c in req.candidates:
        row = screening.parse_candidates(
            f"{c.name},{c.smiles}", structure=structure,
            max_atoms=MAX_ATOMS)["rows"]
        if not row or not row[0]["ok"]:
            err = row[0]["error"] if row else "해석 실패"
            raise HTTPException(400, f"{c.name}: {err}")
        v = row[0]
        # 업로드 3D 좌표 — 모노머 계산에서만 초기 구조로 사용한다.
        # 올리고머 전개는 SMILES 를 새로 만들므로 좌표를 이어받을 수 없다.
        if c.geometry is not None and structure == "모노머":
            v["geometry"] = {**c.geometry.model_dump(),
                             "rescan": c.geometry.rescan or req.rescanGeometry}
        validated.append(v)

    scoring_cfg = None
    if req.scoring.enabled:
        if req.scoring.preset not in scoring.WEIGHT_PRESETS:
            raise HTTPException(400, f"알 수 없는 가중치 프리셋: {req.scoring.preset}")
        scoring_cfg = {"enabled": True, "preset": req.scoring.preset,
                       "weights": scoring.normalize_weights(
                           req.scoring.weights, req.scoring.preset)}
    camp = screening.create_campaign(
        name=req.name, candidates=validated, electrodes=electrodes,
        margin_v=req.marginV, stages=[st.model_dump() for st in req.stages],
        settings=settings, custom_electrodes=customs, scoring_cfg=scoring_cfg)
    return {"campaign": screening.campaign_summary(camp),
            "estimate": screening.estimate(len(validated),
                                           [st.model_dump() for st in req.stages])}


@app.get("/api/screening/campaigns")
def screening_list(_: bool = Depends(require_login)):
    return {"campaigns": [screening.campaign_summary(c)
                          for c in screening.list_campaigns()]}


def _campaign_or_404(cid: str) -> dict:
    camp = screening.get_campaign(cid)
    if camp is None:
        raise HTTPException(404, "캠페인을 찾을 수 없습니다.")
    return camp


@app.get("/api/screening/campaigns/{cid}")
def screening_detail(cid: str, _: bool = Depends(require_login)):
    return screening.campaign_view(_campaign_or_404(cid))


@app.post("/api/screening/campaigns/{cid}/pause")
def screening_pause(cid: str, _: bool = Depends(require_login)):
    _campaign_or_404(cid)
    if not screening.set_status(cid, "PAUSED"):
        raise HTTPException(400, "일시정지할 수 없는 상태입니다.")
    return {"ok": True}


@app.post("/api/screening/campaigns/{cid}/resume")
def screening_resume(cid: str, _: bool = Depends(require_login)):
    _campaign_or_404(cid)
    if not screening.set_status(cid, "RUNNING"):
        raise HTTPException(400, "재개할 수 없는 상태입니다.")
    return {"ok": True}


@app.post("/api/screening/campaigns/{cid}/cancel")
def screening_cancel(cid: str, _: bool = Depends(require_login)):
    _campaign_or_404(cid)
    if not screening.set_status(cid, "CANCELLED"):
        raise HTTPException(400, "취소할 수 없는 상태입니다.")
    return {"ok": True}


@app.delete("/api/screening/campaigns/{cid}")
def screening_delete(cid: str, _: bool = Depends(require_login)):
    _campaign_or_404(cid)
    if not screening.delete_campaign(cid):
        raise HTTPException(400, "진행 중인 캠페인은 먼저 취소해야 삭제할 수 있습니다.")
    return {"ok": True}


@app.post("/api/screening/campaigns/{cid}/reverify")
def screening_reverify(cid: str, _: bool = Depends(require_login)):
    """LUMO 불일치 후보만 표준 정확도로 재검증하는 후속 캠페인을 만든다."""
    camp = _campaign_or_404(cid)
    if camp["status"] not in ("DONE", "CANCELLED"):
        raise HTTPException(400, "완료된 캠페인에서만 재검증을 시작할 수 있습니다.")
    try:
        new = screening.reverify_lumo(camp)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"campaign": screening.campaign_summary(new)}


@app.get("/api/screening/campaigns/{cid}/export")
def screening_export(cid: str, format: str = "csv",
                     _: bool = Depends(require_login)):
    """판정표 내보내기 — 계산 조건이 함께 기록되어 재현 가능하다."""
    view = screening.campaign_view(_campaign_or_404(cid))
    if format == "json":
        return JSONResponse(
            content={"exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"), **view},
            headers={"Content-Disposition":
                     f'attachment; filename="{cid}_screening.json"'})
    buf = io.StringIO()
    writer = csv.writer(buf)
    elec = view["electrodes"]
    head = ["rank", "name", "smiles", "grade", "provisional",
            "worst_margin_v", "reduction_v", "oxidation_v",
            "lumo_naive_red_v", "lumo_mismatch"]
    head += [f"margin_v[{e}]" for e in elec] + [f"grade[{e}]" for e in elec]
    scoring_on = bool((view.get("scoring") or {}).get("enabled"))
    if scoring_on:
        head += ["total_score", "penalty", "hard_fail", "confidence"]
        head += [f"score[{k}]" for k, _ in scoring.AXES]
        head += ["score_reasons"]
    head += ["functional_groups", "state", "error", "job_ids",
             "campaign", "stages", "margin_setting_v", "solvent", "temperature_k",
             "functional", "reference_electrode", "protocol"]
    writer.writerow(head)
    s = view["settings"]
    const = [view["name"], " → ".join(st["accuracy"] for st in view["stages"]),
             view["margin_v"], s.get("solventId") or "vacuum", s.get("temperature"),
             (s.get("expert") or {}).get("functional"), s.get("referenceElectrode"),
             view.get("protocol") or ""]
    for c in sorted(view["candidates"],
                    key=lambda x: (x.get("rank") is None, x.get("rank") or 0)):
        v = c.get("verdict") or {}
        sc = c.get("score") or {}
        per = {p["electrode"]: p for p in v.get("per_electrode", [])}
        writer.writerow(
            [c.get("rank", ""), c["name"], c["smiles"], v.get("grade", "판정 불가"),
             "예" if c.get("provisional") else "",
             v.get("worst_margin_v", ""), v.get("reduction_v", ""),
             v.get("oxidation_v", ""),
             (v.get("lumo_check") or {}).get("naive_red_v", ""),
             " / ".join((v.get("lumo_check") or {}).get("mismatch", []))]
            + [per.get(e, {}).get("margin_v", "") for e in elec]
            + [per.get(e, {}).get("grade", "") for e in elec]
            + (([sc.get("total", ""), sc.get("penalty", ""),
                 "예" if sc.get("hard_fail") else "", sc.get("confidence", "")]
                + [((sc.get("axes") or {}).get(k) or {}).get("score", "")
                   for k, _ in scoring.AXES]
                + [" / ".join(sc.get("reasons") or [])]) if scoring_on else [])
            + [" · ".join(c.get("fgroups") or []), c["state"], c.get("detail") or "",
               " ".join(c["jobs"].values())] + const)
    return Response(
        content="﻿" + buf.getvalue(),  # BOM - Excel 한글 깨짐 방지
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="{cid}_screening.csv"'})


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
        target = {"id": None, "name": name, "abbr": "사용자",
                  "smiles": resolve_custom(req.customSmiles, name)}
        if req.customGeometry is not None:
            if n_units > 1 and not req.customGeometry.rescan:
                raise HTTPException(
                    400, "2량체·3량체 전개 시에는 업로드 3D 좌표를 쓸 수 없습니다 — "
                         "구조를 «모노머»로 두거나 «구조 재탐색»을 켜세요.")
            for a in req.customGeometry.atoms:
                if len(a) != 4 or not isinstance(a[0], str):
                    raise HTTPException(400, "3D 좌표 형식 오류 — [원소, x, y, z] 목록이어야 합니다.")
            target["geometry"] = req.customGeometry.model_dump()
        targets.append(target)
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


@app.get("/api/jobs/{job_id}/log")
def get_job_log(job_id: str, tail: int = 400, download: bool = False,
                start: Optional[int] = None, count: int = 400,
                search: Optional[str] = None, offset: Optional[int] = None,
                _: bool = Depends(require_login)):
    """PySCF 원본 로그 (모니터링 가이드 §9 Raw Log Viewer).

    - 기본: 끝 tail 줄 (실시간 tail)
    - start=&count=: line range (대용량 로그를 한 번에 주지 않는다)
    - offset=: byte offset → 그 줄 주변 (구조화 이벤트의 «원본에서 보기»)
    - search=: 검색 — 일치하는 줄 번호·내용 (최대 200건)
    - download=true: 전체 파일
    - 단계별 시작 줄(sections)을 함께 준다 — SCF/OPT/FREQ 구간으로 바로 이동
    """
    job = _job_or_404(job_id)
    path = store.raw_log_path(job_id)
    if not path.exists():
        level = (job["settings"].get("expert") or {}).get("logLevel") or engine.DEFAULT_LOG_LEVEL
        return {"exists": False, "level": level,
                "note": ("원본 로그가 없습니다 — 전문가 설정의 «원본 로그 수준»이 "
                         "«간략»이면 기록하지 않습니다. 상세·디버그로 바꾸고 다시 계산하세요."
                         if engine.LOG_LEVELS.get(level, 0) == 0
                         else "이 작업이 시작되기 전 버전에서 만들어졌거나 파일이 지워졌습니다.")}
    size = path.stat().st_size
    if download:
        return FileResponse(path, media_type="text/plain; charset=utf-8",
                            filename=f"rhobench-{job_id}.log")
    if search:
        return {"exists": True, "bytes": size, **monitor.search_log(path, search)}
    mon = job.get("monitor") or {}
    sections = [{"name": s["name"], "line": monitor.offset_to_line(path, s.get("offset")),
                 "t": s.get("t")} for s in (mon.get("sections") or [])]
    raw_info = mon.get("raw_log")
    if offset is not None:
        line = monitor.offset_to_line(path, offset) or 1
        start = max(1, line - 5)
    if start is not None:
        rng = monitor.read_log_lines(path, start, max(1, min(count, 5000)))
        return {"exists": True, "bytes": size, "lines": rng["total"], "start": rng["start"],
                "end": rng["end"], "text": "".join(rng["lines"]), "sections": sections,
                "sha256": (raw_info or {}).get("sha256"), "truncated": True}
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    shown = lines if tail <= 0 else lines[-tail:]
    first = 1 if tail <= 0 else max(1, len(lines) - len(shown) + 1)
    return {"exists": True, "bytes": size, "lines": len(lines),
            "truncated": tail > 0 and len(lines) > tail,
            "start": first, "end": len(lines), "sections": sections,
            "sha256": (raw_info or {}).get("sha256"),
            "text": "".join(shown)}


@app.get("/api/jobs/{job_id}/events")
def get_job_events(job_id: str, after: int = 0, limit: int = 500,
                   kinds: Optional[str] = None, _: bool = Depends(require_login)):
    """구조화 로그(JSONL) — 원본 로그에서 파생된 이벤트. after=N 이후만 준다."""
    _job_or_404(job_id)
    ks = tuple(k for k in (kinds or "").split(",") if k) or None
    return monitor.read_events(job_id, after, max(1, min(limit, 5000)), kinds=ks)


@app.get("/api/jobs/{job_id}/monitor")
def get_job_monitor(job_id: str, _: bool = Depends(require_login)):
    """작업 하나의 모니터 상세 — 요약·검증 보고서·SCF/OPT 이력·attempt."""
    job = _job_or_404(job_id)
    mon = job.get("monitor") or {}
    path = store.raw_log_path(job_id)
    anomalies = []
    for a in mon.get("anomalies") or []:
        a = dict(a)
        a["line"] = monitor.offset_to_line(path, a.get("raw_offset")) if path.exists() else None
        anomalies.append(a)
    attempts = []
    for a in mon.get("attempts") or []:
        a = dict(a)
        a["line"] = monitor.offset_to_line(path, a.get("raw_offset")) if path.exists() else None
        attempts.append(a)
    return {
        "view": monitor.job_monitor_view(job),
        "monitor": {**mon, "anomalies": anomalies, "attempts": attempts},
        "validation": job.get("validation") or (job.get("result") or {}).get("validation"),
        "scf_history": monitor.scf_history(job_id),
        "opt_history": monitor.opt_history(job_id),
        "raw_log_exists": path.exists(),
        "trajectory_exists": monitor.trajectory_path(job_id).exists(),
        "heartbeat_warn_s": monitor.HEARTBEAT_WARN_S,
    }


@app.get("/api/li-references")
def li_references(_: bool = Depends(require_login)):
    """Li⁺ 용매 경쟁 참조 클러스터 캐시 — 어떤 용매·n·프로토콜이 이미 계산돼 있는가."""
    from . import licomp
    return {"references": licomp.list_references(),
            "thresholds_kj": {"trapping": licomp.TRAP_KJ,
                              "solvent_dominant": licomp.SOLVENT_DOMINANT_KJ},
            "default_coordination": licomp.DEFAULT_COORDINATION}


@app.get("/api/jobs/{job_id}/trajectory")
def get_job_trajectory(job_id: str, _: bool = Depends(require_login)):
    _job_or_404(job_id)
    path = monitor.trajectory_path(job_id)
    if not path.exists():
        raise HTTPException(404, "최적화 궤적이 없습니다.")
    return FileResponse(path, media_type="chemical/x-xyz", filename=f"rhobench-{job_id}-trajectory.xyz")


@app.get("/api/monitor")
def monitor_dashboard(campaign: Optional[str] = None, limit: int = 200,
                      _: bool = Depends(require_login)):
    """관리자 대시보드 (가이드 §8) — 모든 작업의 stage·SCF·OPT·FREQ·판정 한눈에.

    실행·대기 중인 작업이 먼저, 그다음 최근 완료 순. campaign=ID 로 캠페인만 본다.
    """
    now = time.time()
    jobs = store.list_jobs()
    if campaign:
        jobs = [j for j in jobs if (j.get("campaign") or {}).get("id") == campaign]
    order = {"RUNNING": 0, "QUEUED": 1}
    jobs.sort(key=lambda j: (order.get(j["status"], 2), -(j.get("createdAt") or 0)))
    views = [monitor.job_monitor_view(j, now) for j in jobs[:max(1, min(limit, 1000))]]
    counts = {"running": 0, "queued": 0, "PASS": 0, "REVIEW": 0, "FAIL": 0,
              "CRASHED": 0, "CANCELLED": 0, "FAILED": 0, "ungraded": 0, "stale": 0}
    for j in jobs:
        if j["status"] == "RUNNING":
            counts["running"] += 1
            if monitor.heartbeat_view(j, now)["stale"]:
                counts["stale"] += 1
        elif j["status"] == "QUEUED":
            counts["queued"] += 1
        else:
            g = ((j.get("validation") or (j.get("result") or {}).get("validation") or {})
                 .get("grade"))
            counts[g if g in counts else "ungraded"] += 1
    campaigns = sorted({(j.get("campaign") or {}).get("id"): (j.get("campaign") or {}).get("name")
                        for j in store.list_jobs() if j.get("campaign")}.items())
    return {"jobs": views, "counts": counts, "total": len(jobs),
            "campaigns": [{"id": cid, "name": name} for cid, name in campaigns],
            "heartbeat_warn_s": monitor.HEARTBEAT_WARN_S, "now": now}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, _: bool = Depends(require_login)):
    old = _job_or_404(job_id)
    if old["status"] != "FAILED":
        raise HTTPException(400, "실패한 작업만 재시도할 수 있습니다.")
    if store.count_active() >= MAX_ACTIVE_JOBS:
        raise HTTPException(400, f"동시 실행 가능한 작업은 {MAX_ACTIVE_JOBS}개입니다.")
    job = store.create_job(old["material"], old["settings"])
    job["logs"].append(f"재시도 — 원본 작업 {job_id}")
    # 원본 작업의 체크포인트가 있으면 물려받아 끝난 단계부터 이어서 계산한다
    if checkpoint.copy(job_id, job["id"]):
        cp = checkpoint.summary(job["id"]) or {}
        job["logs"].append("원본 작업의 체크포인트 승계 — 완료 단계: " + ", ".join(cp.get("labels") or []))
        store.update_job(job["id"], {"logs": job["logs"], "checkpoint": cp})
    else:
        store.update_job(job["id"], {"logs": job["logs"]})
    worker.submit(job["id"], priority=worker.PRIORITY_BATCH if old.get("campaign") else worker.PRIORITY_INTERACTIVE)
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
