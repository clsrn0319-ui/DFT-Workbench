"""계산 모니터링 — 「DFT 계산 모니터링 및 Raw Log 설계 가이드」 §11 테스트 시나리오.

정상 SCF · SCF 실패(max_cycle 작게) · 느린 수렴 · 진동 · 발산 · OPT 미수렴 ·
비정상 구조 · 자동 복구 attempt 이력 · 검증 등급 · 원본 로그 range/search.
"""

import pytest

from server import monitor, store


# ---------------------------------------------------------------- 이상 징후 (순수 함수)
def _hist(gorbs, des=None):
    des = des or [-1e-3] * len(gorbs)
    return [(i + 1, -100.0 + 1e-3 * i, d, g) for i, (g, d) in enumerate(zip(gorbs, des))]


def test_scf_anomaly_max_cycle_and_slow():
    flagged = set()
    # 12 cycle 동안 |g| 가 절반도 안 줄었다 → slow
    g = [1e-2 * (0.97 ** i) for i in range(13)]
    out = monitor.scf_anomalies(_hist(g), max_cycle=50, conv_tol_grad=1e-4, flagged=flagged)
    kinds = {k for k, _, _ in out}
    assert "scf_slow" in kinds and "scf_max_cycle" not in kinds
    # max cycle 근접 — 40/50
    out = monitor.scf_anomalies(_hist([1e-3] * 40), 50, 1e-4, set())
    assert any(k == "scf_max_cycle" for k, _, _ in out)
    # 이미 낸 종류는 다시 내지 않는다
    out = monitor.scf_anomalies(_hist([1e-3] * 40), 50, 1e-4, {"scf_max_cycle", "scf_slow"})
    assert out == []


def test_scf_anomaly_oscillation_and_divergence():
    # ΔE 부호가 6회 교대하고 |g| 는 그대로 → oscillation
    des = [(-1) ** i * 1e-3 for i in range(8)]
    out = monitor.scf_anomalies(_hist([1e-3] * 8, des), 50, 1e-4, set())
    assert any(k == "scf_oscillation" for k, sev, _ in out)
    # |g| 가 5회 연속 커지며 10배 이상 → divergence (ERROR)
    g = [1e-4, 1e-3, 5e-3, 2e-2, 1e-1, 5e-1]
    out = monitor.scf_anomalies(_hist(g), 50, 1e-4, set())
    assert any(k == "scf_divergence" and sev == "ERROR" for k, sev, _ in out)
    # 에너지가 한 번에 1 Ha 이상 튐
    out = monitor.scf_anomalies(_hist([1e-3] * 5, [-1e-3] * 4 + [2.5]), 50, 1e-4, set())
    assert any(k == "scf_divergence" for k, _, _ in out)
    # 정상 수렴 — 아무것도 내지 않는다
    g = [1e-1 * (0.3 ** i) for i in range(8)]
    assert monitor.scf_anomalies(_hist(g), 50, 1e-4, set()) == []


def test_opt_anomaly_stagnation_and_explosion():
    hist = [(i + 1, -100.0, 1e-3, 0.01) for i in range(12)]   # 기울기가 줄지 않는다
    out = monitor.opt_anomalies(hist, 100, None, None, set())
    assert any(k == "opt_stagnation" for k, _, _ in out)
    # 원자 접근 0.4 Å → explosion ERROR
    geo = monitor.geometry_stats([[0, 0, 0], [0.4, 0, 0], [3, 0, 0]])
    out = monitor.opt_anomalies([(1, -1.0, 1e-2, None)], 100, geo, 3.0, set())
    assert any(k == "geometry_explosion" and sev == "ERROR" for k, sev, _ in out)
    # 지름이 1.6배 넘게 커짐
    geo = monitor.geometry_stats([[0, 0, 0], [1.0, 0, 0], [6.0, 0, 0]])
    out = monitor.opt_anomalies([(1, -1.0, 1e-2, None)], 100, geo, 3.0, set())
    assert any(k == "geometry_explosion" for k, _, _ in out)
    # 최대 스텝 근접
    out = monitor.opt_anomalies([(85, -1.0, 1e-2, None)], 100, None, None, set())
    assert any(k == "opt_max_steps" for k, _, _ in out)


# ---------------------------------------------------------------- sanity · 상태 판정
def test_sanity_geometry_detects_broken_bond_and_close_contact():
    # 에탄올 C-C 결합을 3 Å 로 늘림 — SMILES 결합 대조로 잡는다
    from server.geometry import smiles_to_xyz
    atoms, _ = smiles_to_xyz("CCO", n_conformers=1)
    ok = monitor.sanity_geometry(atoms, "CCO")
    assert ok["checked_bonds"] and not ok["broken_bonds"] and not ok["too_close"]
    stretched = [(a[0], a[1] + (3.0 if i == 0 else 0.0), a[2], a[3]) for i, a in enumerate(atoms)]
    bad = monitor.sanity_geometry(stretched, "CCO")
    assert bad["broken_bonds"]
    close = list(atoms)
    close[1] = (close[1][0], close[0][1] + 0.3, close[0][2], close[0][3])
    assert monitor.sanity_geometry(close, "CCO")["too_close"]
    # 원자 순서가 SMILES 와 다르면 결합 대조는 생략하고 접근만 본다
    assert monitor.sanity_geometry(atoms[::-1], "CCO")["checked_bonds"] is False


def test_classify_error_separates_crash_from_failure():
    assert monitor.classify_error(RuntimeError("양이온 SCF 미수렴 — 모두 실패")) == "FAILED"
    assert monitor.classify_error(MemoryError()) == "CRASHED"
    assert monitor.classify_error(OSError("disk full")) == "CRASHED"
    assert monitor.classify_error(ValueError("전하·다중도 조합")) == "FAILED"


def _summary(**over):
    base = {"scf": {"runs": 5, "recovered": 0, "failed": 0},
            "opt": {"runs": 1, "unconverged": 0}, "freq": {"runs": 1, "n_imag": 0, "lowest_cm": 30.0},
            "anomalies": [], "attempts": [], "actual": {"xc": "pbe0", "disp": "d3bj", "solvent": None}}
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


PARAMS = {"do_opt": True, "do_thermo": True, "xc": "pbe0", "disp": "d3bj"}
DESC = {"homo_ev": -6.5, "gap_ev": 5.0, "n_imaginary_freqs": 0}
GEO = {"min_dist": 1.09, "too_close": [], "broken_bonds": [], "checked_bonds": True}


def test_validation_pass_review_fail_grades():
    ok = monitor.validate(_summary(), PARAMS, DESC, GEO)
    assert ok["grade"] == "PASS"
    st = {c["key"]: c["status"] for c in ok["checks"]}
    assert st["scf"] == "pass" and st["opt"] == "pass" and st["freq"] == "pass" \
        and st["geometry"] == "pass" and st["settings"] == "pass"
    # 자동 복구로 수렴 → REVIEW (기록 검토 대상)
    rv = monitor.validate(_summary(scf={"recovered": 1}, attempts=[{"n": 2}]), PARAMS, DESC, GEO)
    assert rv["grade"] == "REVIEW" and "복구" in rv["summary"]
    # 작은 허수 진동수 → REVIEW, 프로세스는 정상
    im = monitor.validate(_summary(freq={"n_imag": 1, "lowest_cm": -22.0}), PARAMS,
                          {**DESC, "n_imaginary_freqs": 1}, GEO)
    assert im["grade"] == "REVIEW" and "노이즈" in im["summary"]
    # 구조 최적화가 최대 스텝에서 멈춤 → 프로세스 정상 종료여도 FAIL
    fl = monitor.validate(_summary(opt={"unconverged": 1}), PARAMS, DESC, GEO)
    assert fl["grade"] == "FAIL" and "미수렴" in fl["summary"]
    # 스핀 오염 → REVIEW
    sp = monitor.validate(_summary(), PARAMS, {**DESC, "spin_contamination": [
        {"label": "음이온", "s2": 1.05, "expected": 0.75, "deviation": 0.30}]}, GEO)
    assert sp["grade"] == "REVIEW" and any(c["key"] == "spin" for c in sp["checks"])
    # 실행 실패 → 등급은 오류 종류
    cr = monitor.validate(_summary(), PARAMS, error="MemoryError", error_kind="CRASHED")
    assert cr["grade"] == "CRASHED" and cr["checks"][0]["status"] == "fail"
    # 설정 불일치 (요청 분산 보정이 실제로 안 붙음)
    ms = monitor.validate(_summary(actual={"xc": "pbe0", "disp": None}), PARAMS, DESC, GEO)
    assert ms["grade"] == "REVIEW" and any(c["key"] == "settings" and c["status"] == "review"
                                           for c in ms["checks"])


# ---------------------------------------------------------------- 기록기 (DFT 없이)
class _FakeMf:
    max_cycle = 50


def test_job_monitor_records_events_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(monitor, "SUMMARY_THROTTLE_S", 0.0)   # 1초 조절을 풀어 콜백 갱신을 본다
    pushed = []
    m = monitor.JobMonitor("T-1", raw=None, update=lambda p, persist=True: pushed.append((persist, p)))
    m.stage("단일점")
    m.begin_scf("최종", max_cycle=50, conv_tol=1e-8)
    mf = _FakeMf()
    for c in range(6):
        m.scf_callback({"cycle": c, "e_tot": -1.0 - 0.1 * c, "last_hf_e": -1.0 - 0.1 * (c - 1),
                        "norm_gorb": 1e-2 * 0.3 ** c, "norm_ddm": 1e-2, "mf": mf,
                        "conv_tol": 1e-8, "conv_tol_grad": 1e-4})
    m.end_scf(True, -1.5, 6)
    m.recovery(1, "최종", "기본 설정", "SCF 미수렴", "FAILED")
    m.recovery(2, "최종", "damping 0.4", "미수렴", "CONVERGED")
    m.freq("진동수", 1, -18.0, [-18.0, 40.0, 120.0])
    snap = m.finish(None)
    assert snap["scf"]["cycle"] == 6 and snap["scf"]["converged"] is True and snap["scf"]["runs"] == 1
    assert snap["scf"]["recovered"] == 1 and len(snap["attempts"]) == 2
    assert snap["freq"]["n_imag"] == 1 and any(a["kind"] == "imaginary_freq" for a in snap["anomalies"])
    assert snap["sections"][0]["name"] == "단일점"
    # 파일에는 STAGE·SCF_BEGIN·SCF×6·SCF_END·RECOVERY×2·FREQ·ANOMALY·END 가 있다
    ev = monitor.read_events("T-1")
    kinds = [e["kind"] for e in ev["events"]]
    assert kinds.count("SCF") == 6 and "RECOVERY" in kinds and "END" in kinds
    assert ev["total"] == len(kinds)
    hist = monitor.scf_history("T-1")
    assert hist["total_runs"] == 1 and len(hist["runs"][0]["cycles"]) == 6
    # 단계 전환·복구 같은 사건은 persist=True 로, 반복 콜백은 메모리만
    assert any(p for p, _ in pushed) and any(not p for p, _ in pushed)
    # after= 로 이어 읽기
    assert [e["n"] for e in monitor.read_events("T-1", after=3, limit=2)["events"]] == [4, 5]


def test_opt_callback_tracks_steps_and_trajectory(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOGS_DIR", tmp_path)
    import numpy as np
    from pyscf import gto
    m = monitor.JobMonitor("T-2", raw=None, update=None)
    m.begin_opt("구조 최적화", max_steps=100)
    mol = gto.M(atom="H 0 0 0; H 0 0 0.74", basis="sto-3g", verbose=0)
    for step in range(3):
        mol.set_geom_([("H", (0, 0, 0)), ("H", (0, 0, 0.74 + 0.01 * step))], unit="Angstrom")
        m.opt_callback({"cycle": step, "energy": -1.1 - 0.001 * step,
                        "gradients": np.full((2, 3), 1e-2 * (0.5 ** step)), "mol": mol})
    m.end_opt(False, 3)
    snap = m.finish(None)
    assert snap["opt"]["step"] == 3 and snap["opt"]["converged"] is False and snap["opt"]["unconverged"] == 1
    assert snap["opt"]["disp_max"] == pytest.approx(0.01, abs=1e-6)
    assert any(a["kind"] == "opt_unconverged" and a["severity"] == "ERROR" for a in snap["anomalies"])
    traj = monitor.trajectory_path("T-2").read_text(encoding="utf-8")
    assert traj.count("step ") == 3 and traj.startswith("# run: 구조 최적화")
    oh = monitor.opt_history("T-2")
    assert len(oh["runs"][0]["steps"]) == 3 and oh["runs"][0]["converged"] is False


def test_raw_log_helpers_range_search_offset(tmp_path):
    p = tmp_path / "x.log"
    lines = [f"line {i}" for i in range(1, 51)]
    lines[20] = "cycle= 3 E= -1.0  |g|= 1e-3"
    lines[40] = "SCF not converged"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rng = monitor.read_log_lines(p, 10, 5)
    assert rng["start"] == 10 and rng["end"] == 14 and rng["total"] == 50 and len(rng["lines"]) == 5
    hits = monitor.search_log(p, "CONVERGED")
    assert hits["hits"][0]["line"] == 41
    # byte offset → 줄 번호: 20줄이 지나간 위치는 21번째 줄
    off = len(("\n".join(lines[:20]) + "\n").encode())
    assert monitor.offset_to_line(p, off) == 21
    assert monitor.offset_to_line(p, None) is None


def test_heartbeat_and_dashboard_view():
    now = 1_000_000.0
    job = {"id": "J", "status": "RUNNING", "createdAt": now - 500, "material": {"name": "m"},
           "settings": {"accuracy": "표준"}, "monitor": {"heartbeat": now - 400, "started": now - 500,
                                                       "scf": {"cycle": 7, "recovered": 0},
                                                       "anomalies": [{"severity": "WARN"}]}}
    hb = monitor.heartbeat_view(job, now)
    assert hb["stale"] is True and hb["age_s"] == 400.0
    v = monitor.job_monitor_view(job, now)
    assert v["grade"] == "RUN" and v["n_warn"] == 1 and v["wall_s"] == 500.0
    done = {**job, "status": "PUBLISHED", "validation": {"grade": "PASS", "summary": "ok"},
            "result": {"wall_time_s": 12.0}}
    assert monitor.job_monitor_view(done, now)["grade"] == "PASS"
    assert monitor.heartbeat_view(done, now)["stale"] is False


# ---------------------------------------------------------------- 실계산 시나리오 (§11)
def _settings(**over):
    from server import presets
    s = {**presets.DEFAULT_SETTINGS, "expert": dict(presets.DEFAULT_SETTINGS["expert"])}
    exp = over.pop("expert", {})
    s.update(over)
    s["expert"].update(exp)
    return s


def test_run_job_writes_raw_log_events_and_validation():
    """정상 SCF — 원본 로그(기본 상세)·구조화 이벤트·PASS 검증 보고서가 함께 남는다."""
    from server.engine import run_job
    job = {"id": "T-RUN", "material": {"id": None, "name": "water", "smiles": "O"},
           "settings": _settings(envType="진공·기체", solventId=None, accuracy="빠름",
                                 expert={"basis": "sto-3g", "nConformers": 1}),
           "logs": []}
    state = {}
    run_job(job, update=state.update)
    assert state["status"] == "PUBLISHED", state.get("error")
    assert store.raw_log_path("T-RUN").exists(), "원본 로그는 기본으로 남아야 한다"
    mon = state["monitor"]
    assert mon["scf"]["runs"] >= 1 and mon["scf"]["converged"] is True and mon["scf"]["failed"] == 0
    assert mon["raw_log"]["sha256"] and mon["raw_log"]["bytes"] > 0
    assert mon["input"]["n_electrons"] == 10 and mon["input"]["charge_spin_consistent"] is True
    assert mon["actual"]["xc"] == "pbe0" and mon["actual"]["converged"] is True
    val = state["result"]["validation"]
    assert val["grade"] == "PASS", val["summary"]
    assert state["validation"]["grade"] == "PASS"
    ev = monitor.read_events("T-RUN")
    assert any(e["kind"] == "SCF" and e["raw_offset"] for e in ev["events"])
    assert any(e["kind"] == "INPUT" for e in ev["events"])
    # 구조화 이벤트의 offset 이 원본 로그의 실제 줄로 이어진다
    first_scf = next(e for e in ev["events"] if e["kind"] == "SCF")
    assert monitor.offset_to_line(store.raw_log_path("T-RUN"), first_scf["raw_offset"]) >= 1


def test_run_job_small_max_cycle_records_recovery_attempts():
    """SCF 실패 시나리오 — max_cycle 을 2 로 두면 1차 실패 후 자동 복구가 attempt 이력을 남기고
    검증 등급은 REVIEW 가 된다 (성공만 남기면 재현성이 떨어진다, 가이드 §6.1)."""
    from server.engine import run_job
    job = {"id": "T-MAXCYC", "material": {"id": None, "name": "water", "smiles": "O"},
           "settings": _settings(envType="진공·기체", solventId=None, accuracy="빠름",
                                 expert={"basis": "sto-3g", "nConformers": 1, "scfMaxCycle": 2}),
           "logs": []}
    state = {}
    run_job(job, update=state.update)
    assert state["status"] == "PUBLISHED", state.get("error")
    mon = state["monitor"]
    assert mon["input"]["scf_max_cycle"] == 2
    assert mon["attempts"] and mon["attempts"][0]["result"] == "FAILED"
    assert any(a["result"] == "CONVERGED" and a["n"] > 1 for a in mon["attempts"])
    assert mon["scf"]["recovered"] >= 1
    assert state["result"]["validation"]["grade"] == "REVIEW"
    assert any(a["kind"] == "scf_max_cycle" for a in mon["anomalies"])
    raw = store.raw_log_path("T-MAXCYC").read_text(encoding="utf-8", errors="replace")
    assert "attempt 02" in raw   # 원본 로그에도 attempt 구분선이 남는다


def test_run_job_rejects_impossible_charge_spin():
    """입력값 검증 — 홀수 전자에 다중도 1 은 계산 전에 명확한 오류로 막는다."""
    from server.engine import run_job
    job = {"id": "T-SPIN", "material": {"id": None, "name": "water cation", "smiles": "O"},
           "settings": _settings(envType="진공·기체", solventId=None, accuracy="빠름",
                                 expert={"basis": "sto-3g", "nConformers": 1, "charge": 1,
                                         "multiplicity": 1}),
           "logs": []}
    state = {}
    run_job(job, update=state.update)
    assert state["status"] == "FAILED" and "다중도" in state["error"]
    assert state["errorKind"] == "FAILED" and state["validation"]["grade"] == "FAILED"
