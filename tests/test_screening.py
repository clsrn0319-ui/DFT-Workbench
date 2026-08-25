"""배치 스크리닝 단위 테스트 — DFT 없이 파싱·판정·깔때기 로직을 검증한다.

실행: python -m pytest tests/test_screening.py -v
"""

import pytest

from server import screening, store


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """캠페인·작업 저장소를 테스트 전용 임시 파일로 격리한다."""
    monkeypatch.setattr(screening, "CAMPAIGNS_FILE", tmp_path / "campaigns.json")
    monkeypatch.setattr(screening, "DATA_DIR", tmp_path)
    monkeypatch.setattr(screening, "_campaigns", {})
    monkeypatch.setattr(screening, "_loaded", True)
    monkeypatch.setattr(store, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_jobs", {})
    monkeypatch.setattr(store, "_loaded", True)
    # 오케스트레이터 스레드는 띄우지 않는다 — _advance 를 직접 호출해 결정적으로 검증
    monkeypatch.setattr(screening, "ensure_started", lambda: None)


# ---------------------------------------------------------------- 파싱
def test_parse_csv_name_smiles():
    out = screening.parse_candidates("VDF,C=C(F)F\nAA,C=CC(=O)O")
    assert out["n_ok"] == 2 and out["n_error"] == 0
    assert out["rows"][0]["name"] == "VDF"
    assert out["rows"][0]["smiles"] == "C=C(F)F"


def test_parse_smiles_first_column_order_free():
    """열 순서가 반대(SMILES,이름)여도 SMILES 필드를 자동 감지한다."""
    out = screening.parse_candidates("C=C(F)F,VDF")
    row = out["rows"][0]
    assert row["ok"] and row["smiles"] == "C=C(F)F" and row["name"] == "VDF"


def test_parse_header_row_skipped():
    out = screening.parse_candidates("name,smiles\nVDF,C=C(F)F")
    assert out["n_ok"] == 1 and out["n_error"] == 0


def test_parse_duplicates_and_errors():
    text = "a,C=C(F)F\nb,FC(F)=C\nc,not-a-smiles((("
    out = screening.parse_candidates(text)
    assert out["n_ok"] == 1                       # b 는 a 와 같은 구조 → 중복 제외
    errors = [r["error"] for r in out["rows"] if not r["ok"]]
    assert any("중복" in e for e in errors)
    assert any("해석" in e for e in errors)


def test_parse_atom_limit():
    out = screening.parse_candidates("big,CCCCCCCCCC", max_atoms=10)
    assert out["n_ok"] == 0
    assert "상한" in out["rows"][0]["error"]


def test_parse_oligomer_expansion():
    out = screening.parse_candidates("VDF,C=C(F)F", structure="2량체")
    row = out["rows"][0]
    assert row["ok"] and row["calc_smiles"] != row["smiles"]
    assert row["atoms"] > 6


# ---------------------------------------------------------------- 판정
def _desc(red, ox):
    return {"reduction_potential_v": red, "oxidation_potential_v": ox}


def test_judge_fit_on_cathode():
    # NCM811 구동 3.00~4.30 V — ESW −1 ~ 5.0 V 면 여유 0.70 V ≥ 0.3 → 적합
    v = screening.judge(_desc(-1.0, 5.0), ["ncm811"], 0.3)
    assert v["grade"] == "적합"
    assert v["per_electrode"][0]["margin_v"] == pytest.approx(0.7)


def test_judge_conditional_within_margin():
    # 여유 0.10 V — 0 이상이지만 마진 0.3 미만 → 조건부
    v = screening.judge(_desc(-1.0, 4.40), ["ncm811"], 0.3)
    assert v["grade"] == "조건부"


def test_judge_unfit():
    # 산화 전위 4.0 V < 구동 상단 4.3 V → 부적합 (충전 상단에서 산화)
    v = screening.judge(_desc(-1.0, 4.0), ["ncm811"], 0.3)
    assert v["grade"] == "부적합"


def test_judge_reduction_side_anode():
    # 흑연 구동 0.01~0.25 V — 환원 전위 +0.5 V 는 하단보다 높음 → 부적합
    v = screening.judge(_desc(0.5, 6.0), ["graphite"], 0.3)
    assert v["grade"] == "부적합"


def test_judge_gibbs_potentials_preferred():
    desc = {"reduction_potential_v": 0.5, "oxidation_potential_v": 4.0,
            "reduction_potential_gibbs_v": -1.0, "oxidation_potential_gibbs_v": 5.0}
    v = screening.judge(desc, ["ncm811"], 0.3)
    assert v["grade"] == "적합"          # ΔG 기반 값으로 판정해야 적합


def test_judge_multi_electrode_worst_wins():
    # NCM811 은 적합인데 흑연은 부적합 → 전체 부적합
    v = screening.judge(_desc(0.5, 5.0), ["ncm811", "graphite"], 0.3)
    assert v["grade"] == "부적합"
    grades = {p["electrode"]: p["grade"] for p in v["per_electrode"]}
    assert grades["ncm811"] == "적합" and grades["graphite"] == "부적합"


def test_judge_missing_potentials():
    v = screening.judge({}, ["ncm811"], 0.3)
    assert v["grade"] == "판정 불가"


# ---------------------------------------------------------------- 깔때기
def _fake_publish(job_id, red, ox, wall=10):
    store.update_job(job_id, {
        "status": "PUBLISHED",
        "result": {"descriptors": _desc(red, ox), "wall_time_s": wall}})


def _make_campaign(n=3, stages=None, keep=2):
    cands = screening.parse_candidates(
        "\n".join(f"m{i},{'C' * (i + 1)}O" for i in range(n)))["rows"]
    return screening.create_campaign(
        name="테스트", candidates=[c for c in cands if c["ok"]],
        electrodes=["ncm811"], margin_v=0.3,
        stages=stages or [{"accuracy": "빠름", "keep": keep}, {"accuracy": "표준"}],
        settings={"envType": "진공·기체", "solventId": None, "temperature": 298.15,
                  "structure": "모노머", "referenceElectrode": "Li/Li+",
                  "accuracy": "빠름", "purpose": screening.SCREEN_PURPOSE,
                  "expert": {"functional": "PBE0-D3(BJ)", "basis": None,
                             "charge": 0, "multiplicity": 1}})


@pytest.fixture
def no_worker(monkeypatch):
    """worker.submit 을 무력화 — 작업은 QUEUED 로 남고 테스트가 직접 완료시킨다."""
    from server import worker
    monkeypatch.setattr(worker, "submit", lambda job_id, priority=0: None)


def _stage_jobs(camp, stage):
    return {c["name"]: c["jobs"].get(str(stage)) for c in camp["candidates"]}


def test_funnel_submit_respects_parallel_limit(no_worker, monkeypatch):
    monkeypatch.setattr(screening, "BATCH_PARALLEL", 2)
    camp = _make_campaign(n=3)
    screening._advance(camp)
    submitted = [j for j in _stage_jobs(camp, 0).values() if j]
    assert len(submitted) == 2      # 한도 2 → 3개 중 2개만 제출


def test_funnel_cut_and_advance(no_worker, monkeypatch):
    monkeypatch.setattr(screening, "BATCH_PARALLEL", 10)
    camp = _make_campaign(n=3, keep=2)
    screening._advance(camp)        # 1단계 전체 제출
    jobs = _stage_jobs(camp, 0)
    assert all(jobs.values())
    # 완료 처리 — m0 가 가장 여유 크고 m2 가 가장 작다
    _fake_publish(jobs["m0"], -1.0, 5.5)
    _fake_publish(jobs["m1"], -1.0, 5.0)
    _fake_publish(jobs["m2"], -1.0, 4.6)
    screening._advance(camp)        # 단계 전환 — 상위 2개만 생존
    assert camp["stageIndex"] == 1
    alive = {c["name"] for c in camp["candidates"] if c["alive"]}
    assert alive == {"m0", "m1"}
    cut = [c for c in camp["candidates"] if c["cutStage"] == 0]
    assert len(cut) == 1 and cut[0]["name"] == "m2"


def test_funnel_finalize_grades(no_worker, monkeypatch):
    monkeypatch.setattr(screening, "BATCH_PARALLEL", 10)
    camp = _make_campaign(n=2, stages=[{"accuracy": "빠름"}])   # 단일 단계
    screening._advance(camp)
    jobs = _stage_jobs(camp, 0)
    _fake_publish(jobs["m0"], -1.0, 5.0)    # 여유 0.7 → 적합
    _fake_publish(jobs["m1"], -1.0, 4.4)    # 여유 0.1 → 조건부
    screening._advance(camp)
    assert camp["status"] == "DONE"
    verdicts = {c["name"]: c["verdict"]["grade"] for c in camp["candidates"]}
    assert verdicts == {"m0": "적합", "m1": "조건부"}
    view = screening.campaign_view(camp)
    assert view["counts"]["fit"] == 1 and view["counts"]["conditional"] == 1
    ranks = {c["name"]: c.get("rank") for c in view["candidates"]}
    assert ranks["m0"] == 1 and ranks["m1"] == 2


def test_funnel_retry_then_fail(no_worker, monkeypatch):
    monkeypatch.setattr(screening, "BATCH_PARALLEL", 10)
    camp = _make_campaign(n=1, stages=[{"accuracy": "빠름"}])
    screening._advance(camp)
    j1 = _stage_jobs(camp, 0)["m0"]
    store.update_job(j1, {"status": "FAILED", "error": "SCF 미수렴"})
    screening._advance(camp)        # 자동 재시도 1회 — 새 작업 제출
    j2 = _stage_jobs(camp, 0)["m0"]
    assert j2 and j2 != j1
    store.update_job(j2, {"status": "FAILED", "error": "SCF 미수렴"})
    screening._advance(camp)        # 두 번째 실패 → 판정 불가
    cand = camp["candidates"][0]
    assert cand["failed"] and not cand["alive"]
    screening._advance(camp)        # 살아남은 후보 없음 → 종료
    assert camp["status"] == "DONE"


def test_funnel_restart_resubmits_without_retry_penalty(no_worker, monkeypatch):
    monkeypatch.setattr(screening, "BATCH_PARALLEL", 10)
    camp = _make_campaign(n=1, stages=[{"accuracy": "빠름"}])
    screening._advance(camp)
    j1 = _stage_jobs(camp, 0)["m0"]
    # 서버 재시작 시 store 가 붙이는 오류 문구 그대로
    store.update_job(j1, {"status": "FAILED", "error": screening.RESTART_ERROR})
    screening._advance(camp)
    j2 = _stage_jobs(camp, 0)["m0"]
    assert j2 and j2 != j1
    assert camp["candidates"][0]["retries"] == {}   # 재시도 횟수를 쓰지 않았다


def test_cache_reuse_skips_computation(no_worker, monkeypatch):
    monkeypatch.setattr(screening, "BATCH_PARALLEL", 10)
    camp1 = _make_campaign(n=1, stages=[{"accuracy": "빠름"}])
    screening._advance(camp1)
    j1 = _stage_jobs(camp1, 0)["m0"]
    _fake_publish(j1, -1.0, 5.0)
    screening._advance(camp1)
    assert camp1["status"] == "DONE"
    # 같은 구조·같은 조건의 두 번째 캠페인 — 기존 결과를 그대로 연결해야 한다
    camp2 = _make_campaign(n=1, stages=[{"accuracy": "빠름"}])
    screening._advance(camp2)
    assert _stage_jobs(camp2, 0)["m0"] == j1
    screening._advance(camp2)
    assert camp2["status"] == "DONE"


def test_auto_pause_on_high_failure(no_worker, monkeypatch):
    monkeypatch.setattr(screening, "BATCH_PARALLEL", 100)
    camp = _make_campaign(n=10, stages=[{"accuracy": "빠름"}])
    screening._advance(camp)
    jobs = _stage_jobs(camp, 0)
    for name, jid in jobs.items():
        store.update_job(jid, {"status": "FAILED", "error": "SCF 미수렴"})
    screening._advance(camp)        # 전원 재시도 제출
    for name, jid in _stage_jobs(camp, 0).items():
        store.update_job(jid, {"status": "FAILED", "error": "SCF 미수렴"})
    screening._advance(camp)        # 전원 확정 실패 → 실패율 100% → 자동 일시정지
    assert camp["status"] == "PAUSED" and camp["autoPaused"]


# ---------------------------------------------------------------- 수직 전위 보정
def test_judge_basis_and_vertical_note():
    v = screening.judge(_desc(-1.0, 5.0), ["ncm811"], 0.3)
    assert v["basis"] == "수직" and "수직" in v["note"]
    v2 = screening.judge({"reduction_potential_gibbs_v": -1.0,
                          "oxidation_potential_gibbs_v": 5.0}, ["ncm811"], 0.3)
    assert v2["basis"] == "ΔG 기반" and v2["note"] is None
    v3 = screening.judge({**_desc(-1.0, 5.0), "ea_adiabatic_ev": 0.4}, ["ncm811"], 0.3)
    assert v3["basis"] == "단열"


def test_cut_buffer_flips_vertical_ranking(no_worker, monkeypatch):
    """수직 전위 단계의 컷 순위 — 환원 쪽이 한계인 후보는 보수 보정으로 밀린다."""
    monkeypatch.setattr(screening, "BATCH_PARALLEL", 10)
    monkeypatch.setattr(screening, "VERTICAL_RED_BUFFER", 0.5)
    camp = _make_campaign(n=2, stages=[{"accuracy": "빠름", "keep": 1},
                                       {"accuracy": "표준"}])
    screening._advance(camp)
    jobs = _stage_jobs(camp, 0)
    # m0: 산화 쪽 한계 (NCM811 여유 0.40 — 보정과 무관)
    _fake_publish(jobs["m0"], -2.0, 4.70)
    # m1: 환원 쪽 한계 (보정 없이 0.45 로 m0 을 이기지만, +0.5 보정 후 −0.05)
    _fake_publish(jobs["m1"], 2.55, 9.0)
    screening._advance(camp)
    alive = {c["name"] for c in camp["candidates"] if c["alive"]}
    assert alive == {"m0"}


def test_cut_buffer_not_applied_to_adiabatic(no_worker, monkeypatch):
    """단열·ΔG 기반 결과에는 보정을 걸지 않는다."""
    monkeypatch.setattr(screening, "BATCH_PARALLEL", 10)
    monkeypatch.setattr(screening, "VERTICAL_RED_BUFFER", 0.5)
    camp = _make_campaign(n=2, stages=[{"accuracy": "표준", "keep": 1},
                                       {"accuracy": "정밀"}])
    screening._advance(camp)
    jobs = _stage_jobs(camp, 0)
    store.update_job(jobs["m0"], {"status": "PUBLISHED", "result": {"descriptors": {
        **_desc(-2.0, 4.70), "ea_adiabatic_ev": 0.0}}})
    store.update_job(jobs["m1"], {"status": "PUBLISHED", "result": {"descriptors": {
        **_desc(2.55, 9.0), "ea_adiabatic_ev": 0.0}}})
    screening._advance(camp)
    alive = {c["name"] for c in camp["candidates"] if c["alive"]}
    assert alive == {"m1"}     # 보정 미적용 → 여유 0.45 > 0.40


# ---------------------------------------------------------------- 배치 결과 슬림화
def test_slim_removes_density_cloud(no_worker, monkeypatch):
    monkeypatch.setattr(screening, "BATCH_PARALLEL", 10)
    monkeypatch.setattr(screening, "SLIM_BATCH", True)
    camp = _make_campaign(n=1, stages=[{"accuracy": "빠름"}])
    screening._advance(camp)
    jid = _stage_jobs(camp, 0)["m0"]
    store.update_job(jid, {"status": "PUBLISHED", "result": {
        "descriptors": _desc(-1.0, 5.0),
        "density_cloud": [[0.0, 0.0, 0.0]] * 100,
        "structure_xyz": "3\n\nO 0 0 0\n", "notes": []}})
    screening._advance(camp)
    job = store.get_job(jid)
    assert job["result"]["density_cloud"] is None
    assert job["result"]["slimmed"] is True
    assert job["result"]["structure_xyz"]                 # 3D 구조는 유지
    assert any("용량 절약" in n for n in job["result"]["notes"])
    assert camp["status"] == "DONE"                       # 판정에는 영향 없음


def test_slim_disabled_keeps_cloud(no_worker, monkeypatch):
    monkeypatch.setattr(screening, "BATCH_PARALLEL", 10)
    monkeypatch.setattr(screening, "SLIM_BATCH", False)
    camp = _make_campaign(n=1, stages=[{"accuracy": "빠름"}])
    screening._advance(camp)
    jid = _stage_jobs(camp, 0)["m0"]
    store.update_job(jid, {"status": "PUBLISHED", "result": {
        "descriptors": _desc(-1.0, 5.0), "density_cloud": [[0.0, 0.0, 0.0]]}})
    screening._advance(camp)
    assert store.get_job(jid)["result"]["density_cloud"] is not None
