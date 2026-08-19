"""배치 스크리닝 — 수백 개 바인더 후보의 일괄 DFT 계산과 적합/부적합 자동 판정.

기획서(05_DFT-Workbench_배치스크리닝_기획서) 구현체. 세 부분으로 이루어진다.

  1. 캠페인 저장소 — 후보 목록 + 계산 조건 + 판정 기준 + 진행 상태를 하나로
     묶은 실행 단위. data/campaigns.json 에 지속 저장되어 서버 재시작 후에도
     이어서 진행된다 (체크포인트-재개).
  2. 깔때기 오케스트레이터 — 단계(빠름 → 표준 → 정밀)별로 작업을 제출하고,
     완료를 감지해 통과자를 골라 다음 단계를 자동 제출하는 백그라운드 스레드.
     기존 작업 큐·엔진을 그대로 쓰며, 배치 작업은 단건보다 낮은 우선순위로
     들어가 일상 사용을 방해하지 않는다.
  3. 판정 엔진 — 산화·환원 전위를 활물질 구동 «범위»와 대조해
     적합 / 조건부 / 부적합 / 판정 불가 등급을 부여한다. 판정식은 기존
     esw.containment 와 같은 포함 관계이며, 안정성 마진만 더해졌다.

판정은 열역학적 스크리닝이다 — «분해될 수 있는가»를 보는 것이지
«실제 배터리에서 못 쓴다»는 뜻이 아니다 (EC/SEI 반례). 이 문구는 화면에도
그대로 표시된다.
"""

import json
import os
import threading
import time
import uuid
from pathlib import Path

from rdkit import Chem

from . import esw, geometry, presets, store, worker

DATA_DIR = Path(os.environ.get(
    "RHOBENCH_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
CAMPAIGNS_FILE = DATA_DIR / "campaigns.json"

# 자원 보호 — 환경변수로 조정
MAX_CANDIDATES = int(os.environ.get("RHOBENCH_MAX_BATCH", "500"))
BATCH_PARALLEL = max(1, int(os.environ.get("RHOBENCH_BATCH_PARALLEL", "1")))
# 실패 누적률이 이 값을 넘으면 캠페인을 자동 일시정지하고 관리자 확인을 유도
FAIL_PAUSE_RATIO = float(os.environ.get("RHOBENCH_BATCH_FAIL_RATIO", "0.3"))

RESTART_ERROR = "서버 재시작으로 중단됨"

# 분자당 대략 소요 시간(초) — 실행 확인 화면의 추정용. 실측이 쌓이면 실측 우선.
ESTIMATE_S = {"빠름": 120, "표준": 1200, "정밀": 3600}

# 판정에 필요한 목적 — 전위가 없으면 판정 자체가 불가능하다
SCREEN_PURPOSE = "전자구조 + 산화/환원 전위"

THERMO_NOTE = ("이 판정은 열역학적 스크리닝입니다 — «분해될 수 있는가»를 보는 "
               "것이지 «실제 배터리에서 못 쓴다»는 뜻이 아닙니다. 대표 반례: "
               "EC는 계산상 음극에서 환원 분해되지만 그 분해 산물이 안정적인 "
               "보호막(SEI)을 만들어 상용 전해액의 표준 성분으로 쓰입니다.")

_lock = threading.RLock()
_campaigns: dict[str, dict] = {}
_loaded = False


# ---------------------------------------------------------------- 저장소
def _load():
    global _loaded
    if _loaded:
        return
    _loaded = True
    if CAMPAIGNS_FILE.exists():
        try:
            for c in json.loads(CAMPAIGNS_FILE.read_text(encoding="utf-8")):
                _campaigns[c["id"]] = c
        except (json.JSONDecodeError, OSError):
            pass


def _persist():
    DATA_DIR.mkdir(exist_ok=True)
    tmp = CAMPAIGNS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(list(_campaigns.values()), ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(CAMPAIGNS_FILE)


def _log(camp: dict, msg: str):
    camp.setdefault("logs", []).append(f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}")


# ---------------------------------------------------------------- 후보 파싱
def _canonical(smiles: str):
    mol = Chem.MolFromSmiles(smiles)
    return Chem.MolToSmiles(mol) if mol is not None else None


def _split_line(line: str) -> list[str]:
    for sep in (",", "\t", ";"):
        if sep in line:
            return [f.strip().strip('"') for f in line.split(sep)]
    return [line.strip()]


def parse_candidates(text: str, structure: str = "모노머",
                     max_atoms: int = 60) -> dict:
    """CSV(이름,SMILES[,메모]) 또는 한 줄 SMILES 목록을 검증된 후보로 바꾼다.

    - 열 순서는 자동 감지 — SMILES 로 해석되는 필드를 구조로, 나머지를 이름으로
    - 헤더 행(smiles/name 등 단어만 있고 구조가 없는 행)은 자동 건너뜀
    - 중복은 캐노니컬 SMILES 기준으로 제거 (첫 등장만 유지)
    - 2량체·3량체 구조 선택 시 올리고머로 전개한 뒤 원자 수 상한을 검사
    """
    n_units = {"모노머": 1, "2량체": 2, "3량체": 3}.get(structure, 1)
    rows, seen = [], {}
    ok_count = 0
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = _split_line(line)
        smiles, name = None, None
        for f in fields:
            if smiles is None and f and _canonical(f) is not None:
                smiles = f
            elif f and name is None:
                name = f
        row = {"line": line_no, "name": name or smiles or line,
               "smiles": smiles, "ok": False, "error": None}
        if smiles is None:
            # 헤더 행이면 조용히 건너뛴다 — 오류 목록에 잡음을 넣지 않는다
            joined = " ".join(fields).lower()
            if line_no <= 2 and any(w in joined for w in ("smiles", "name", "이름", "구조")):
                continue
            row["error"] = "SMILES 로 해석되는 필드가 없습니다"
            rows.append(row)
            continue
        canonical = _canonical(smiles)
        if canonical in seen:
            row["error"] = f"{seen[canonical]}행과 중복 구조 (제외)"
            rows.append(row)
            continue
        seen[canonical] = line_no
        row["canonical"] = canonical
        calc_smiles = smiles
        if n_units > 1:
            try:
                calc_smiles = geometry.oligomerize(smiles, n_units)
            except geometry.GeometryError as exc:
                row["error"] = f"{structure} 전개 실패: {exc}"
                rows.append(row)
                continue
        atoms = geometry.atom_count(calc_smiles)
        row.update({"calc_smiles": calc_smiles, "atoms": atoms})
        if atoms > max_atoms:
            row["error"] = f"원자 수 {atoms}개 — 상한 {max_atoms}개 초과"
            rows.append(row)
            continue
        row["ok"] = True
        ok_count += 1
        rows.append(row)
    return {"rows": rows, "n_ok": ok_count,
            "n_error": sum(1 for r in rows if not r["ok"]),
            "structure": structure, "max_atoms": max_atoms}


# ---------------------------------------------------------------- 판정 엔진
def _potentials(desc: dict):
    """ΔG 기반 전위가 있으면 우선 사용 — esw.diagnose 와 같은 규칙."""
    red = desc.get("reduction_potential_gibbs_v", desc.get("reduction_potential_v"))
    ox = desc.get("oxidation_potential_gibbs_v", desc.get("oxidation_potential_v"))
    return red, ox


def judge(desc: dict, electrodes: list[str], margin_v: float) -> dict:
    """전극 구동 범위 전체가 ESW 안에 얼마나 여유 있게 들어오는지로 등급을 매긴다.

    여유(margin) = min(구동 하단 − 환원 전위, 산화 전위 − 구동 상단)
      여유 ≥ 안정성 마진  → 적합
      0 ≤ 여유 < 마진     → 조건부 적합 (계산 오차 범위 — 정밀 재확인 권장)
      여유 < 0            → 부적합 (구동 범위 안에서 열역학적 분해)
    """
    red, ox = _potentials(desc)
    if red is None or ox is None:
        return {"grade": "판정 불가", "per_electrode": [], "worst_margin_v": None,
                "reduction_v": red, "oxidation_v": ox,
                "note": "산화·환원 전위가 없어 판정할 수 없습니다"}
    per = []
    for key in electrodes:
        win = esw.ELECTRODE_BY_KEY[key]
        m = round(min(win["low"] - red, ox - win["high"]), 3)
        grade = "적합" if m >= margin_v else ("조건부" if m >= 0 else "부적합")
        per.append({"electrode": key, "label": win["label"], "side": win["side"],
                    "window": [win["low"], win["high"]],
                    "margin_v": m, "grade": grade})
    worst = min(p["margin_v"] for p in per)
    if all(p["grade"] == "적합" for p in per):
        grade = "적합"
    elif any(p["grade"] == "부적합" for p in per):
        grade = "부적합"
    else:
        grade = "조건부"
    return {"grade": grade, "per_electrode": per, "worst_margin_v": worst,
            "reduction_v": red, "oxidation_v": ox, "note": None}


# ---------------------------------------------------------------- 캠페인
def _stage_settings(camp: dict, stage_idx: int) -> dict:
    s = dict(camp["settings"])
    s["accuracy"] = camp["stages"][stage_idx]["accuracy"]
    s["purpose"] = SCREEN_PURPOSE
    # 후보는 이미 올리고머로 전개되어 있다 — 엔진이 다시 전개하지 않도록
    s["structure"] = "모노머"
    return s


def create_campaign(name: str, candidates: list[dict], electrodes: list[str],
                    margin_v: float, stages: list[dict], settings: dict) -> dict:
    """검증된 후보 목록으로 캠페인을 만들고 즉시 시작한다."""
    with _lock:
        _load()
        cid = "CAM-" + time.strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6].upper()
        camp = {
            "id": cid,
            "name": name or cid,
            "status": "RUNNING",   # RUNNING · PAUSED · DONE · CANCELLED
            "createdAt": time.time(),
            "finishedAt": None,
            "electrodes": electrodes,
            "margin_v": margin_v,
            "stages": [{"accuracy": st["accuracy"], "keep": st.get("keep")}
                       for st in stages],
            "stageIndex": 0,
            "settings": settings,
            "structure": settings.get("structure", "모노머"),
            "autoPaused": False,
            "candidates": [
                {"idx": i, "name": c["name"], "smiles": c["smiles"],
                 "canonical": c.get("canonical") or c["smiles"],
                 "calcSmiles": c.get("calc_smiles") or c["smiles"],
                 "atoms": c.get("atoms"),
                 "alive": True, "failed": False, "cutStage": None,
                 "error": None, "retries": {}, "jobs": {}, "verdict": None}
                for i, c in enumerate(candidates)],
            "logs": [],
        }
        _log(camp, f"캠페인 생성 — 후보 {len(candidates)}개 · "
                   f"단계 {' → '.join(st['accuracy'] for st in camp['stages'])} · "
                   f"전극 {', '.join(electrodes)} · 마진 {margin_v} V")
        _campaigns[cid] = camp
        _persist()
    ensure_started()
    return camp


def get_campaign(cid: str):
    with _lock:
        _load()
        return _campaigns.get(cid)


def list_campaigns():
    with _lock:
        _load()
        return sorted(_campaigns.values(), key=lambda c: c["createdAt"], reverse=True)


def set_status(cid: str, status: str) -> bool:
    """pause / resume / cancel 상태 전이."""
    with _lock:
        _load()
        camp = _campaigns.get(cid)
        if camp is None or camp["status"] in ("DONE", "CANCELLED"):
            return False
        if status == "CANCELLED":
            # 진행 중인 배치 작업도 함께 취소한다
            for c in camp["candidates"]:
                jid = c["jobs"].get(str(camp["stageIndex"]))
                if jid:
                    job = store.get_job(jid)
                    if job and job["status"] in ("QUEUED", "RUNNING"):
                        store.request_cancel(jid)
            camp["finishedAt"] = time.time()
        if status == "RUNNING":
            camp["autoPaused"] = False
        camp["status"] = status
        _log(camp, {"RUNNING": "재개", "PAUSED": "일시정지", "CANCELLED": "취소"}
             .get(status, status))
        _persist()
        return True


def delete_campaign(cid: str) -> bool:
    with _lock:
        _load()
        camp = _campaigns.get(cid)
        if camp is None:
            return False
        if camp["status"] in ("RUNNING", "PAUSED"):
            return False   # 먼저 취소해야 지울 수 있다
        del _campaigns[cid]
        _persist()
        return True


# ---------------------------------------------------------------- 캐시 재사용
def _relevant(settings: dict) -> tuple:
    """결과 재사용 판단에 쓰는 조건 지문 — 이 조합이 같으면 같은 계산이다."""
    exp = settings.get("expert") or {}
    return (settings.get("accuracy"), settings.get("solventId"),
            settings.get("customMixedSolvent") is None or json.dumps(
                settings.get("customMixedSolvent"), sort_keys=True),
            round(float(settings.get("temperature", 298.15)), 2),
            settings.get("referenceElectrode"), settings.get("envType"),
            exp.get("functional"), exp.get("basis"),
            exp.get("charge", 0), exp.get("multiplicity", 1))


def _find_cached(canonical: str, settings: dict):
    """같은 구조·같은 조건의 PUBLISHED 결과가 이미 있으면 재계산하지 않는다."""
    want = _relevant(settings)
    for j in store.list_jobs():
        if j["status"] != "PUBLISHED" or not j.get("result"):
            continue
        js = j.get("settings") or {}
        # 전위가 산출된 목적이어야 판정에 쓸 수 있다
        if not any(w in (js.get("purpose") or "") for w in ("전위", "지문", "바인더")):
            continue
        if _relevant(js) != want:
            continue
        if _canonical(j["material"].get("smiles", "")) == canonical:
            return j
    return None


# ---------------------------------------------------------------- 오케스트레이터
def _batch_active_count() -> int:
    return sum(1 for j in store.list_jobs()
               if j.get("campaign") and j["status"] in ("QUEUED", "RUNNING"))


def _rank_score(c: dict, camp: dict, stage_idx: int):
    jid = c["jobs"].get(str(stage_idx))
    job = store.get_job(jid) if jid else None
    if not job or job["status"] != "PUBLISHED" or not job.get("result"):
        return None
    desc = job["result"].get("descriptors") or {}
    v = judge(desc, camp["electrodes"], camp["margin_v"])
    return v["worst_margin_v"]


def _advance(camp: dict):
    """캠페인 하나를 한 걸음 진행시킨다 — 제출·재시도·단계 전환·판정."""
    stage_idx = camp["stageIndex"]
    stage_key = str(stage_idx)
    alive = [c for c in camp["candidates"] if c["alive"]]
    if not alive:
        camp["status"] = "DONE"
        camp["finishedAt"] = time.time()
        _log(camp, "살아남은 후보가 없어 종료")
        return

    pending, n_done, n_failed_stage = [], 0, 0
    for c in alive:
        jid = c["jobs"].get(stage_key)
        job = store.get_job(jid) if jid else None
        if job is None:
            pending.append(c)
            continue
        if job["status"] == "PUBLISHED":
            n_done += 1
        elif job["status"] == "FAILED":
            if RESTART_ERROR in (job.get("error") or ""):
                # 서버 재시작 유탄 — 재시도 횟수를 쓰지 않고 다시 제출
                del c["jobs"][stage_key]
                pending.append(c)
                _log(camp, f"{c['name']}: 서버 재시작으로 중단 — 재제출")
            elif c["retries"].get(stage_key, 0) < 1:
                c["retries"][stage_key] = c["retries"].get(stage_key, 0) + 1
                del c["jobs"][stage_key]
                pending.append(c)
                _log(camp, f"{c['name']}: 실패({job.get('error')}) — 자동 재시도 1회")
            else:
                c["alive"] = False
                c["failed"] = True
                c["error"] = job.get("error") or "계산 실패"
                n_failed_stage += 1
                _log(camp, f"{c['name']}: 재시도 후에도 실패 — 판정 불가로 분류")
        # QUEUED / RUNNING → 기다린다

    # 실패 누적률 보호 — 조건이 잘못된 캠페인이 밤새 실패만 쌓는 것을 막는다
    n_failed_total = sum(1 for c in camp["candidates"] if c["failed"])
    if (camp["status"] == "RUNNING" and len(camp["candidates"]) >= 10
            and n_failed_total / len(camp["candidates"]) > FAIL_PAUSE_RATIO
            and not camp.get("autoPaused")):
        camp["status"] = "PAUSED"
        camp["autoPaused"] = True
        _log(camp, f"실패율 {n_failed_total}/{len(camp['candidates'])} — "
                   "임계 초과로 자동 일시정지. 조건을 확인한 뒤 재개하세요.")
        return

    # 제출 — 배치 전용 동시 실행 한도 안에서, 캐시가 있으면 계산 없이 연결
    slots = BATCH_PARALLEL - _batch_active_count()
    for c in pending:
        cached = _find_cached(c["canonical"], _stage_settings(camp, stage_idx))
        if cached is not None:
            c["jobs"][stage_key] = cached["id"]
            _log(camp, f"{c['name']}: 동일 조건 기존 결과 재사용 ({cached['id']})")
            continue
        if slots <= 0:
            continue
        settings = _stage_settings(camp, stage_idx)
        material = {"id": None, "name": c["name"], "abbr": "배치",
                    "smiles": c["calcSmiles"]}
        job = store.create_job(material, settings)
        store.update_job(job["id"], {"campaign": {
            "id": camp["id"], "name": camp["name"], "stage": stage_idx,
            "accuracy": camp["stages"][stage_idx]["accuracy"]}})
        worker.submit(job["id"], priority=worker.PRIORITY_BATCH)
        c["jobs"][stage_key] = job["id"]
        slots -= 1

    # 단계 완료 판정 — 살아 있는 모든 후보가 이 단계에서 PUBLISHED 인가
    alive = [c for c in camp["candidates"] if c["alive"]]
    done = [c for c in alive
            if (store.get_job(c["jobs"].get(stage_key)) or {}).get("status") == "PUBLISHED"]
    if not alive or len(done) < len(alive):
        return

    last_stage = stage_idx == len(camp["stages"]) - 1
    if last_stage:
        _finalize(camp)
        return

    # 깔때기 — 안정성 여유 순으로 상위 keep 만 다음 단계로
    keep = camp["stages"][stage_idx].get("keep")
    scored = sorted(done, key=lambda c: (_rank_score(c, camp, stage_idx) is None,
                                         -(_rank_score(c, camp, stage_idx) or -1e9)))
    survivors = scored if not keep else scored[:keep]
    survivor_ids = {c["idx"] for c in survivors}
    for c in done:
        if c["idx"] not in survivor_ids:
            c["alive"] = False
            c["cutStage"] = stage_idx
    camp["stageIndex"] = stage_idx + 1
    _log(camp, f"{stage_idx + 1}단계({camp['stages'][stage_idx]['accuracy']}) 완료 — "
               f"{len(done)}개 중 {len(survivors)}개가 "
               f"{stage_idx + 2}단계({camp['stages'][stage_idx + 1]['accuracy']})로 진출")


def _finalize(camp: dict):
    """마지막 단계 완료 — 최종 판정을 저장하고 캠페인을 닫는다."""
    stage_key = str(camp["stageIndex"])
    for c in camp["candidates"]:
        if not c["alive"]:
            continue
        job = store.get_job(c["jobs"].get(stage_key))
        if job and job["status"] == "PUBLISHED" and job.get("result"):
            desc = job["result"].get("descriptors") or {}
            c["verdict"] = judge(desc, camp["electrodes"], camp["margin_v"])
    camp["status"] = "DONE"
    camp["finishedAt"] = time.time()
    graded = [c for c in camp["candidates"] if c.get("verdict")]
    n_fit = sum(1 for c in graded if c["verdict"]["grade"] == "적합")
    n_cond = sum(1 for c in graded if c["verdict"]["grade"] == "조건부")
    _log(camp, f"캠페인 완료 — 적합 {n_fit} · 조건부 {n_cond} · "
               f"부적합 {len(graded) - n_fit - n_cond} · "
               f"판정 불가 {sum(1 for c in camp['candidates'] if c['failed'])}")


_TICK_S = 3.0
_orc_started = False
_orc_lock = threading.Lock()


def _orchestrator_loop():
    while True:
        try:
            with _lock:
                _load()
                running = [c for c in _campaigns.values() if c["status"] == "RUNNING"]
                for camp in running:
                    before = json.dumps(camp, sort_keys=True, ensure_ascii=False,
                                        default=str)
                    _advance(camp)
                    if json.dumps(camp, sort_keys=True, ensure_ascii=False,
                                  default=str) != before:
                        _persist()
        except Exception:  # noqa: BLE001 — 오케스트레이터는 죽지 않아야 함
            pass
        time.sleep(_TICK_S)


def ensure_started():
    global _orc_started
    with _orc_lock:
        if not _orc_started:
            threading.Thread(target=_orchestrator_loop, daemon=True,
                             name="screening-orchestrator").start()
            _orc_started = True


# ---------------------------------------------------------------- 조회용 뷰
def _candidate_view(c: dict, camp: dict) -> dict:
    stage_idx = camp["stageIndex"]
    jid = c["jobs"].get(str(stage_idx))
    job = store.get_job(jid) if jid else None
    if c["failed"]:
        state, detail = "판정 불가", c.get("error")
    elif c["cutStage"] is not None:
        state = "탈락"
        detail = f"{c['cutStage'] + 1}단계에서 순위 미달"
    elif camp["status"] in ("DONE", "CANCELLED"):
        state, detail = ("완료", None) if c.get("verdict") else ("중단", None)
    elif job is None:
        state, detail = "대기", None
    else:
        state = {"QUEUED": "대기", "RUNNING": "계산 중",
                 "PUBLISHED": "완료", "FAILED": "재시도 대기"}.get(job["status"], "대기")
        detail = job.get("stage") if job["status"] == "RUNNING" else None

    # 판정: 최종 판정이 있으면 그것을, 없으면 마지막 완료 단계의 잠정 판정
    verdict = c.get("verdict")
    provisional = False
    if verdict is None:
        for si in range(len(camp["stages"]) - 1, -1, -1):
            j = store.get_job(c["jobs"].get(str(si)))
            if j and j["status"] == "PUBLISHED" and j.get("result"):
                verdict = judge(j["result"].get("descriptors") or {},
                                camp["electrodes"], camp["margin_v"])
                provisional = True
                break
    return {"idx": c["idx"], "name": c["name"], "smiles": c["smiles"],
            "calcSmiles": c["calcSmiles"], "atoms": c["atoms"],
            "state": state, "detail": detail,
            "alive": c["alive"], "failed": c["failed"], "cutStage": c["cutStage"],
            "jobs": c["jobs"], "verdict": verdict, "provisional": provisional,
            "progress": (job or {}).get("progress") if job else None}


def campaign_view(camp: dict) -> dict:
    """진행률·판정을 계산해 붙인 캠페인 상세 — API 응답용."""
    stage_idx = camp["stageIndex"]
    stages = []
    for si, st in enumerate(camp["stages"]):
        entered = [c for c in camp["candidates"]
                   if str(si) in c["jobs"] or (c["alive"] and si == stage_idx)
                   or (c["cutStage"] is not None and si <= c["cutStage"])]
        jobs = [store.get_job(c["jobs"].get(str(si))) for c in camp["candidates"]]
        jobs = [j for j in jobs if j]
        done = sum(1 for c in camp["candidates"]
                   if (store.get_job(c["jobs"].get(str(si))) or {}).get("status") == "PUBLISHED")
        stages.append({"accuracy": st["accuracy"], "keep": st.get("keep"),
                       "n_entered": len(entered) if si <= stage_idx else 0,
                       "n_done": done,
                       "state": ("완료" if si < stage_idx
                                 or (si == stage_idx and camp["status"] == "DONE")
                                 else "대기" if si > stage_idx
                                 else {"RUNNING": "진행 중", "PAUSED": "일시정지",
                                       "CANCELLED": "중단"}.get(camp["status"], "진행 중"))})

    cands = [_candidate_view(c, camp) for c in camp["candidates"]]
    # 순위 — 판정 가능한 후보를 안정성 여유 내림차순으로
    ranked = sorted([c for c in cands if c["verdict"] and
                     c["verdict"]["worst_margin_v"] is not None],
                    key=lambda c: -c["verdict"]["worst_margin_v"])
    for rank, c in enumerate(ranked, start=1):
        c["rank"] = rank

    n_alive = sum(1 for c in camp["candidates"] if c["alive"])
    cur_done = stages[stage_idx]["n_done"] if stage_idx < len(stages) else 0
    # 남은 시간 추정 — 이 단계에서 실측된 계산 시간이 있으면 그것을 쓴다
    walls = []
    for c in camp["candidates"]:
        j = store.get_job(c["jobs"].get(str(stage_idx)))
        if j and j["status"] == "PUBLISHED" and j.get("result"):
            w = j["result"].get("wall_time_s")
            if isinstance(w, (int, float)):
                walls.append(w)
    per_mol = (sum(walls) / len(walls)) if walls else \
        ESTIMATE_S.get(camp["stages"][stage_idx]["accuracy"] if stage_idx < len(camp["stages"]) else "표준", 1200)
    remaining = max(0, n_alive - cur_done)
    eta_s = None
    if camp["status"] == "RUNNING" and remaining:
        eta_s = int(remaining * per_mol / BATCH_PARALLEL)
        # 뒤 단계 추정도 더한다
        for si in range(stage_idx + 1, len(camp["stages"])):
            n = camp["stages"][si - 1].get("keep") or remaining
            eta_s += int(n * ESTIMATE_S.get(camp["stages"][si]["accuracy"], 1200)
                         / BATCH_PARALLEL)

    counts = {
        "total": len(camp["candidates"]),
        "alive": n_alive,
        "fit": sum(1 for c in cands if c["verdict"] and not c["provisional"]
                   and c["verdict"]["grade"] == "적합"),
        "conditional": sum(1 for c in cands if c["verdict"] and not c["provisional"]
                           and c["verdict"]["grade"] == "조건부"),
        "unfit": sum(1 for c in cands if c["verdict"] and not c["provisional"]
                     and c["verdict"]["grade"] == "부적합"),
        "failed": sum(1 for c in cands if c["failed"]),
        "cut": sum(1 for c in cands if c["cutStage"] is not None),
    }
    return {**{k: v for k, v in camp.items() if k != "candidates"},
            "stages": stages, "candidates": cands, "counts": counts,
            "eta_s": eta_s, "batch_parallel": BATCH_PARALLEL,
            "thermo_note": THERMO_NOTE}


def campaign_summary(camp: dict) -> dict:
    stage_idx = camp["stageIndex"]
    stage_key = str(stage_idx)
    n_done_stage = sum(
        1 for c in camp["candidates"]
        if (store.get_job(c["jobs"].get(stage_key)) or {}).get("status") == "PUBLISHED")
    return {"id": camp["id"], "name": camp["name"], "status": camp["status"],
            "createdAt": camp["createdAt"], "finishedAt": camp["finishedAt"],
            "autoPaused": camp.get("autoPaused", False),
            "electrodes": camp["electrodes"], "margin_v": camp["margin_v"],
            "stages": [st["accuracy"] for st in camp["stages"]],
            "stageIndex": stage_idx,
            "n_candidates": len(camp["candidates"]),
            "n_alive": sum(1 for c in camp["candidates"] if c["alive"]),
            "n_failed": sum(1 for c in camp["candidates"] if c["failed"]),
            "n_done_stage": n_done_stage}


def estimate(n_candidates: int, stages: list[dict]) -> dict:
    """실행 확인 화면용 — 단계별 대상 수와 예상 소요."""
    out, n = [], n_candidates
    total_s = 0
    for st in stages:
        per = ESTIMATE_S.get(st["accuracy"], 1200)
        sec = int(n * per / BATCH_PARALLEL)
        out.append({"accuracy": st["accuracy"], "n": n, "per_mol_s": per,
                    "stage_s": sec})
        total_s += sec
        n = min(n, st.get("keep") or n)
    return {"stages": out, "total_s": total_s, "batch_parallel": BATCH_PARALLEL}
