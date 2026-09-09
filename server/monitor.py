"""계산 모니터링 — Raw Log 는 원본, Structured Log 는 파생 (「DFT 계산 모니터링 및
Raw Log 설계 가이드」 §1·4·5·6).

지금까지 계산이 어떻게 흘러가는지 볼 방법은 두 가지뿐이었다 — 단계 이름만 남는
화면 로그와, verbose 를 켰을 때만 생기는 PySCF 원본 로그. SCF 가 이상하게
수렴해도 반복별 에너지·잔차를 «프로그램이» 읽어 판단하지는 못했고, 구조 최적화가
최대 스텝에서 멈춰도 프로세스는 정상 종료라 결과가 그대로 PUBLISHED 됐다.

이 모듈은 엔진이 던지는 사건(단계 전환·SCF 반복·최적화 스텝·진동수·자동 복구)을
  1. data/logs/<job>.events.jsonl 에 구조화 이벤트로 남기고 (원본 로그의 byte
     offset 을 같이 적어 «원본에서 보기»로 이어진다),
  2. 작업 dict 의 monitor 요약(현재 SCF cycle·|g|·에너지, 이상 징후, attempt
     이력, heartbeat)을 갱신하며,
  3. 끝나면 PASS / REVIEW / FAIL 검증 보고서를 만든다.

원칙: OS 프로세스 종료 코드, 엔진 수렴 여부, 과학적 sanity 는 서로 다른 필드다.
프로세스가 정상 종료했다고 계산이 정확한 것은 아니다 (§5.1).

이 모듈은 PySCF 를 직접 부르지 않는다. 엔진이 envs(dict)를 넘기면 그 값만 읽는다.
그래서 이상 징후 판정·검증 등급은 실계산 없이 단위 테스트가 돈다.
"""

import hashlib
import json
import math
import os
import threading
import time
from collections import deque

import numpy as np

from . import store

HARTREE2EV = 27.211386
SEVERITY = ("INFO", "WARN", "ERROR", "FATAL")
MAX_ANOMALIES = 50
MAX_ATTEMPTS = 40
#: 요약을 저장소에 밀어 넣는 최소 간격 — SCF 콜백은 초당 수십 번 올 수 있다
SUMMARY_THROTTLE_S = 1.0
#: 궤적 파일 상한 — 넘으면 프레임 기록을 멈춘다
MAX_TRAJECTORY_BYTES = 20 * 1024 * 1024
#: RUNNING 인데 이 시간 동안 이벤트가 없으면 heartbeat 경고 (§6 No heartbeat)
HEARTBEAT_WARN_S = float(os.environ.get("RHOBENCH_HEARTBEAT_WARN_S", "180"))
#: 작은 허수 진동수 — 수치 노이즈·저주파 모드 가능성 (§2.4)
SMALL_IMAG_CM = 50.0

# 공유 결합 판정용 공유 반지름 (Å) — sanity check 에서 결합 절단·비정상 접근을 본다
COVALENT_RADII = {"H": 0.31, "B": 0.84, "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57,
                  "Si": 1.11, "P": 1.07, "S": 1.05, "Cl": 1.02, "Br": 1.20, "I": 1.39,
                  "Li": 1.28, "Na": 1.66, "K": 2.03}


def events_path(job_id: str):
    return store.LOGS_DIR / f"{store.safe_id(job_id)}.events.jsonl"


def trajectory_path(job_id: str):
    return store.LOGS_DIR / f"{store.safe_id(job_id)}.trajectory.xyz"


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


class JobMonitor:
    """작업 하나의 구조화 로그 기록기 + 요약. 엔진이 사건을 던진다."""

    def __init__(self, job_id: str, raw=None, update=None):
        self.job_id = job_id
        self.raw = raw            # engine._RawLog — byte offset 을 얻기 위해
        self.update = update      # store 갱신 함수 (persist 플래그 지원)
        self.fh = None
        self.traj_fh = None
        self.traj_truncated = False
        self.lock = threading.Lock()
        self.attempt = 1
        self.stage_name = None
        self.n_events = 0
        self.t0 = time.time()
        self.last_push = 0.0
        self.summary = {
            "started": self.t0, "updated": self.t0, "heartbeat": self.t0,
            "stage": None, "sections": [],
            "scf": {"label": None, "cycle": None, "max_cycle": None, "energy": None,
                    "delta_e": None, "gorb": None, "ddm": None, "conv_tol": None,
                    "conv_tol_grad": None, "converged": None,
                    # runs: 시작한 SCF 수 · recovered: 복구로 살린 수 ·
                    # failed_attempts: 미수렴 attempt 수 · failed: 끝내 실패한 SCF 수
                    "runs": 0, "recovered": 0, "failed_attempts": 0, "failed": 0},
            "opt": {"label": None, "step": None, "max_steps": None, "energy": None,
                    "delta_e": None, "grad_norm": None, "grad_max": None,
                    "disp_max": None, "converged": None, "runs": 0, "unconverged": 0},
            "freq": {"n_imag": None, "lowest_cm": None, "runs": 0},
            "attempts": [], "anomalies": [], "events": 0,
            "input": None, "actual": None, "raw_log": None,
        }
        # SCF/OPT 한 번(run)의 이력 — 이상 징후 판정용
        self._scf_hist = deque(maxlen=64)
        self._scf_flags = set()
        self._opt_hist = deque(maxlen=64)
        self._opt_flags = set()
        self._opt_prev_coords = None
        self._opt_init_maxdist = None
        # 최적화 스텝·진동수 안의 SCF 는 begin_scf 없이 콜백만 온다 — cycle 1 에서
        # 자동으로 run 을 열고, 스텝 콜백에서 scanner 의 수렴 플래그로 닫는다
        self._scf_open = False
        self._scf_auto = False
        try:
            events_path(job_id).parent.mkdir(parents=True, exist_ok=True)
            self.fh = open(events_path(job_id), "a", encoding="utf-8")
        except OSError:
            self.fh = None

    # ── 기록 ────────────────────────────────────────────────────────
    def _raw_offset(self):
        fh = getattr(self.raw, "fh", None)
        if not fh:
            return None
        try:
            fh.flush()
            return int(fh.tell())
        except (OSError, ValueError):
            return None

    def event(self, kind: str, severity: str = "INFO", persist: bool = False, **fields):
        now = time.time()
        rec = {"t": round(now, 3), "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
               "job_id": self.job_id, "attempt": self.attempt, "stage": self.stage_name,
               "kind": kind, "severity": severity, "raw_offset": self._raw_offset()}
        rec.update(fields)
        with self.lock:
            self.n_events += 1
            self.summary["events"] = self.n_events
            self.summary["heartbeat"] = now
            if self.fh:
                try:
                    self.fh.write(json.dumps(rec, ensure_ascii=False, default=_json_default) + "\n")
                    self.fh.flush()
                except (OSError, ValueError, TypeError):
                    pass
        self._push(force=persist or severity in ("ERROR", "FATAL"), persist=persist)
        return rec

    def _push(self, force=False, persist=False):
        """요약을 작업 dict 에 반영 — 콜백에서는 1초에 한 번만."""
        now = time.time()
        if not force and now - self.last_push < SUMMARY_THROTTLE_S:
            return
        self.last_push = now
        self.summary["updated"] = now
        if self.update:
            try:
                self.update({"monitor": self.snapshot()}, persist=persist)
            except TypeError:
                self.update({"monitor": self.snapshot()})

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.summary, default=_json_default))

    # ── 단계·입력 ──────────────────────────────────────────────────
    def stage(self, name: str):
        self.stage_name = name
        off = self._raw_offset()
        with self.lock:
            self.summary["stage"] = name
            self.summary["sections"].append({"name": name, "offset": off,
                                             "t": round(time.time() - self.t0, 1)})
        self.event("STAGE", name=name, persist=True)

    def input_echo(self, info: dict):
        """계산 시작부 입력값 검증 (§2.1) — 실제로 엔진에 들어가는 값을 남긴다."""
        with self.lock:
            self.summary["input"] = info
        self.event("INPUT", persist=True, **info)

    def actual(self, info: dict):
        """최종 SCF 객체에서 읽은 «실제 실행값» — UI 선택값과 대조한다."""
        with self.lock:
            self.summary["actual"] = info
        self.event("MF_ACTUAL", **info)

    # ── SCF ────────────────────────────────────────────────────────
    def begin_scf(self, label: str, max_cycle=None, conv_tol=None, conv_tol_grad=None):
        with self.lock:
            self._scf_hist.clear()
            self._scf_flags.clear()
            s = self.summary["scf"]
            s.update({"label": label, "cycle": 0, "max_cycle": max_cycle,
                      "conv_tol": conv_tol, "conv_tol_grad": conv_tol_grad,
                      "converged": None, "energy": None, "delta_e": None,
                      "gorb": None, "ddm": None})
            s["runs"] += 1
            self._scf_open, self._scf_auto = True, False
        self.event("SCF_BEGIN", label=label, max_cycle=max_cycle, conv_tol=conv_tol)

    def scf_callback(self, envs: dict):
        """PySCF mf.callback — 반복마다 envs(locals) 가 들어온다."""
        try:
            if int(envs.get("cycle", -1)) == 0 and not self._scf_open:
                mf0 = envs.get("mf")
                self.begin_scf(f"{self.stage_name or 'SCF'} (내부 SCF)",
                               max_cycle=getattr(mf0, "max_cycle", None),
                               conv_tol=_num(envs.get("conv_tol")),
                               conv_tol_grad=_num(envs.get("conv_tol_grad")))
                self._scf_auto = True
        except Exception:  # noqa: BLE001
            pass
        try:
            cycle = int(envs.get("cycle", -1)) + 1
            e = _num(envs.get("e_tot"))
            last = _num(envs.get("last_hf_e"))
            de = (e - last) if (e is not None and last is not None) else None
            gorb = _num(envs.get("norm_gorb"))
            ddm = _num(envs.get("norm_ddm"))
            mf = envs.get("mf")
            max_cycle = getattr(mf, "max_cycle", None)
            conv_tol = _num(envs.get("conv_tol"))
            conv_tol_grad = _num(envs.get("conv_tol_grad"))
        except Exception:  # noqa: BLE001 — 모니터가 계산을 막으면 안 된다
            return
        with self.lock:
            s = self.summary["scf"]
            s.update({"cycle": cycle, "energy": e, "delta_e": de, "gorb": gorb, "ddm": ddm,
                      "max_cycle": max_cycle, "conv_tol": conv_tol,
                      "conv_tol_grad": conv_tol_grad})
            self._scf_hist.append((cycle, e, de, gorb))
        self.event("SCF", cycle=cycle, energy=e, delta_e=de, gorb=gorb, ddm=ddm)
        for kind, sev, msg in scf_anomalies(list(self._scf_hist), max_cycle, conv_tol_grad,
                                            self._scf_flags):
            self._scf_flags.add(kind)
            self.anomaly(kind, sev, msg)

    def end_scf(self, converged: bool, energy=None, cycles=None):
        with self.lock:
            s = self.summary["scf"]
            s["converged"] = bool(converged)
            if energy is not None:
                s["energy"] = _num(energy)
            if cycles is not None:
                s["cycle"] = cycles
            if not converged:
                s["failed_attempts"] += 1
            self._scf_open, self._scf_auto = False, False
        self.event("SCF_END", severity="INFO" if converged else "WARN",
                   converged=bool(converged), energy=_num(energy), cycles=cycles)

    def close_auto_scf(self, converged):
        """최적화 스텝 콜백에서 — 자동으로 연 내부 SCF run 을 scanner 결과로 닫는다."""
        if self._scf_open and self._scf_auto and converged is not None:
            self.end_scf(bool(converged), self.summary["scf"].get("energy"),
                         self.summary["scf"].get("cycle"))

    def fail_scf(self, label: str):
        """자동 복구까지 모두 실패한 SCF — 계산 목적 미달 (FAILED)."""
        with self.lock:
            self.summary["scf"]["failed"] += 1
        self.anomaly("scf_failed", "ERROR",
                     f"{label}: SCF 가 기본 설정·damping·level shift·SOSCF 모두에서 수렴하지 않았습니다")

    def recovery(self, n: int, label: str, change: str, reason: str, result: str):
        """자동 복구 attempt 기록 (§6.1) — 무엇을 왜 바꿨고 결과가 어땠는가."""
        rec = {"n": n, "label": label, "change": change, "reason": reason, "result": result,
               "raw_offset": self._raw_offset(), "t": round(time.time() - self.t0, 1)}
        with self.lock:
            self.summary["attempts"].append(rec)
            del self.summary["attempts"][:-MAX_ATTEMPTS]
            if result == "CONVERGED" and n > 1:
                self.summary["scf"]["recovered"] += 1
        self.event("RECOVERY", severity="WARN" if result != "CONVERGED" else "INFO",
                   persist=True, **rec)
        if self.raw and getattr(self.raw, "fh", None):
            self.raw.note(f"attempt {n:02d} — {label}: {change} ({reason}) → {result}")

    # ── 구조 최적화 ────────────────────────────────────────────────
    def begin_opt(self, label: str, max_steps=None):
        with self.lock:
            self._opt_hist.clear()
            self._opt_flags.clear()
            self._opt_prev_coords = None
            self._opt_init_maxdist = None
            o = self.summary["opt"]
            o.update({"label": label, "step": 0, "max_steps": max_steps, "converged": None,
                      "energy": None, "delta_e": None, "grad_norm": None,
                      "grad_max": None, "disp_max": None})
            o["runs"] += 1
        self.event("OPT_BEGIN", label=label, max_steps=max_steps)
        self._traj_header(label)

    def opt_callback(self, envs: dict):
        """pyberny/geomeTRIC kernel 의 callback(locals()) — 스텝마다."""
        try:
            step = int(envs.get("cycle", -1)) + 1
            e = _num(envs.get("energy"))
            grad = np.asarray(envs.get("gradients"))
            gnorm = float(np.linalg.norm(grad)) if grad.size else None
            gmax = float(np.abs(grad).max()) if grad.size else None
            mol = envs.get("mol")
            coords = mol.atom_coords(unit="Angstrom") if mol is not None else None
            syms = [mol.atom_symbol(i) for i in range(mol.natm)] if mol is not None else None
            scanner = envs.get("g_scanner")
        except Exception:  # noqa: BLE001
            return
        self.close_auto_scf(getattr(scanner, "converged", None))
        disp_max = None
        de = None
        with self.lock:
            prev_e = self._opt_hist[-1][1] if self._opt_hist else None
            if e is not None and prev_e is not None:
                de = e - prev_e
            if coords is not None and self._opt_prev_coords is not None \
                    and self._opt_prev_coords.shape == coords.shape:
                disp_max = float(np.linalg.norm(coords - self._opt_prev_coords, axis=1).max())
            self._opt_prev_coords = coords
            o = self.summary["opt"]
            o.update({"step": step, "energy": e, "delta_e": de, "grad_norm": gnorm,
                      "grad_max": gmax, "disp_max": disp_max})
            self._opt_hist.append((step, e, gnorm, disp_max))
            max_steps = o.get("max_steps")
        self.event("OPT", step=step, energy=e, delta_e=de, grad_norm=gnorm, grad_max=gmax,
                   disp_max=disp_max)
        geo = geometry_stats(coords, syms) if coords is not None else None
        if geo is not None and self._opt_init_maxdist is None:
            self._opt_init_maxdist = geo["max_dist"]
        for kind, sev, msg in opt_anomalies(list(self._opt_hist), max_steps, geo,
                                            self._opt_init_maxdist, self._opt_flags):
            self._opt_flags.add(kind)
            self.anomaly(kind, sev, msg)
        if coords is not None:
            self._traj_frame(step, e, syms, coords)

    def end_opt(self, converged: bool, steps=None):
        with self.lock:
            o = self.summary["opt"]
            o["converged"] = bool(converged)
            if steps is not None:
                o["step"] = steps
            if not converged:
                o["unconverged"] += 1
        self.event("OPT_END", severity="INFO" if converged else "WARN", persist=True,
                   converged=bool(converged), steps=steps)
        if not converged:
            self.anomaly("opt_unconverged", "ERROR",
                         f"구조 최적화({self.summary['opt'].get('label')})가 수렴 기준을 만족하지 "
                         "못한 채 멈췄습니다 (최대 스텝 도달 또는 스텝 내부 SCF 실패) — "
                         "프로세스 종료와 별개로 계산은 미수렴입니다")

    def _traj_header(self, label):
        if self.traj_fh:
            try:
                self.traj_fh.write(f"# run: {label}\n")
            except (OSError, ValueError):
                pass
            return
        try:
            trajectory_path(self.job_id).parent.mkdir(parents=True, exist_ok=True)
            self.traj_fh = open(trajectory_path(self.job_id), "a", encoding="utf-8")
            self.traj_fh.write(f"# run: {label}\n")
        except OSError:
            self.traj_fh = None

    def _traj_frame(self, step, energy, syms, coords):
        if not self.traj_fh or self.traj_truncated:
            return
        try:
            if self.traj_fh.tell() > MAX_TRAJECTORY_BYTES:
                self.traj_fh.write("# trajectory truncated\n")
                self.traj_truncated = True
                return
            lines = [f"{len(syms)}", f"step {step}  E = {energy}"]
            lines += [f"{s} {x:.6f} {y:.6f} {z:.6f}" for s, (x, y, z) in zip(syms, coords)]
            self.traj_fh.write("\n".join(lines) + "\n")
            self.traj_fh.flush()
        except (OSError, ValueError):
            pass

    # ── 진동수 ─────────────────────────────────────────────────────
    def freq(self, label: str, n_imag: int, lowest_cm: float, freqs=None):
        with self.lock:
            f = self.summary["freq"]
            f.update({"n_imag": int(n_imag), "lowest_cm": _num(lowest_cm)})
            f["runs"] += 1
        self.event("FREQ", severity="INFO" if n_imag == 0 else "WARN", persist=True,
                   label=label, n_imag=int(n_imag), lowest_cm=_num(lowest_cm),
                   freqs_cm=[round(float(x), 1) for x in list(freqs)[:12]] if freqs is not None else None)
        if n_imag > 0:
            small = abs(lowest_cm or 0) < SMALL_IMAG_CM
            self.anomaly("imaginary_freq", "WARN",
                         f"{label}: 허수 진동수 {n_imag}개 (최저 {lowest_cm:.0f} cm⁻¹) — "
                         + ("수치 노이즈·느슨한 최적화 가능성, 재최적화 검토" if small
                            else "안장점 가능성 — normal mode 확인 후 재계산"))

    # ── 이상 징후·오류 ─────────────────────────────────────────────
    def anomaly(self, kind: str, severity: str, msg: str):
        rec = {"t": round(time.time() - self.t0, 1), "kind": kind, "severity": severity,
               "msg": msg, "stage": self.stage_name, "raw_offset": self._raw_offset()}
        with self.lock:
            self.summary["anomalies"].append(rec)
            del self.summary["anomalies"][:-MAX_ANOMALIES]
        self.event("ANOMALY", severity=severity, persist=True, kind_detail=kind, msg=msg)

    def error(self, exc: BaseException, kind: str):
        self.event("ERROR", severity="FATAL", persist=True,
                   error=str(exc), error_class=type(exc).__name__, kind_detail=kind)

    # ── 마무리 ─────────────────────────────────────────────────────
    def finish(self, raw_path=None):
        """원본 로그 해시(§3.2)와 최종 요약. 파일은 닫는다."""
        info = None
        if raw_path is not None:
            try:
                if raw_path.exists():
                    h = hashlib.sha256()
                    with open(raw_path, "rb") as f:
                        for chunk in iter(lambda: f.read(1 << 20), b""):
                            h.update(chunk)
                    info = {"bytes": raw_path.stat().st_size, "sha256": h.hexdigest(),
                            "path": raw_path.name}
            except OSError:
                info = None
        with self.lock:
            self.summary["raw_log"] = info
            self.summary["finished"] = time.time()
        self.event("END", persist=True, wall_s=round(time.time() - self.t0, 1))
        for fh in (self.fh, self.traj_fh):
            if fh:
                try:
                    fh.close()
                except (OSError, ValueError):
                    pass
        self.fh = self.traj_fh = None
        return self.snapshot()


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


# ── 이상 징후 판정 (§6) — 순수 함수 ─────────────────────────────────
def scf_anomalies(hist, max_cycle, conv_tol_grad, flagged) -> list:
    """hist: [(cycle, e, de, gorb), ...] 최근 순. 이미 낸 종류(flagged)는 다시 내지 않는다."""
    out = []
    if not hist:
        return out
    cycle = hist[-1][0]
    gorbs = [h[3] for h in hist if h[3] is not None]
    des = [h[2] for h in hist if h[2] is not None]
    es = [h[1] for h in hist if h[1] is not None]

    if max_cycle and "scf_max_cycle" not in flagged and cycle >= 0.8 * max_cycle:
        out.append(("scf_max_cycle", "WARN",
                    f"SCF 반복 {cycle}/{max_cycle} — max cycle 에 근접, 수렴 실패 가능"))
    # 발산: |g| 가 5회 연속 커지며 10배 이상, 또는 에너지가 1 Ha 이상 튐
    if "scf_divergence" not in flagged:
        if len(gorbs) >= 6 and all(gorbs[i] > gorbs[i - 1] for i in range(-5, 0)) \
                and gorbs[-1] > 10 * gorbs[-6]:
            out.append(("scf_divergence", "ERROR",
                        f"SCF 잔차 |g| 가 5회 연속 증가 ({gorbs[-6]:.2e} → {gorbs[-1]:.2e}) — 발산"))
        elif len(des) >= 1 and cycle > 3 and abs(des[-1]) > 1.0:
            out.append(("scf_divergence", "ERROR",
                        f"SCF 에너지가 한 번에 {des[-1]:+.2f} Ha 튀었습니다 — 발산 의심"))
    # 진동: ΔE 부호가 6회 연속 번갈아 바뀌고 |g| 는 줄지 않음
    if "scf_oscillation" not in flagged and len(des) >= 6 and len(gorbs) >= 6:
        last = des[-6:]
        alternating = all(last[i] * last[i - 1] < 0 for i in range(1, 6))
        if alternating and gorbs[-1] > 0.5 * gorbs[-6]:
            out.append(("scf_oscillation", "WARN",
                        "SCF 에너지가 두 값 사이를 오갑니다 (ΔE 부호 교대 6회, |g| 정체) — "
                        "damping/level shift 후보"))
    # 느린 수렴: 10 cycle 동안 |g| 가 절반도 안 줄고 아직 기준에서 멀다
    if "scf_slow" not in flagged and len(gorbs) >= 11 and cycle >= 12:
        far = conv_tol_grad is None or gorbs[-1] > 10 * conv_tol_grad
        if far and gorbs[-1] > 0.5 * gorbs[-11]:
            out.append(("scf_slow", "WARN",
                        f"SCF 수렴이 느립니다 — 10 cycle 동안 |g| {gorbs[-11]:.2e} → {gorbs[-1]:.2e}"))
    return out


def geometry_stats(coords, syms=None) -> dict | None:
    """원자 간 거리 통계 — 비정상 접근·조각 분리 감지용."""
    xyz = np.asarray(coords, dtype=float)
    n = len(xyz)
    if n < 2:
        return None
    d = np.linalg.norm(xyz[:, None, :] - xyz[None, :, :], axis=2)
    iu = np.triu_indices(n, 1)
    dd = d[iu]
    i_min = int(np.argmin(dd))
    return {"min_dist": float(dd[i_min]), "max_dist": float(dd.max()),
            "min_pair": (int(iu[0][i_min]), int(iu[1][i_min]))}


def opt_anomalies(hist, max_steps, geo, init_maxdist, flagged) -> list:
    """hist: [(step, e, grad_norm, disp_max), ...]."""
    out = []
    if not hist:
        return out
    step = hist[-1][0]
    gn = [h[2] for h in hist if h[2] is not None]
    if max_steps and "opt_max_steps" not in flagged and step >= 0.8 * max_steps:
        out.append(("opt_max_steps", "WARN",
                    f"구조 최적화 {step}/{max_steps} 스텝 — 최대 스텝 근접"))
    if "opt_stagnation" not in flagged and len(gn) >= 9 and step >= 10:
        if min(gn[-8:]) > 0.9 * gn[-9]:
            out.append(("opt_stagnation", "WARN",
                        f"기울기가 8 스텝 동안 줄지 않습니다 (|grad| {gn[-9]:.2e} → {gn[-1]:.2e}) — "
                        "초기 구조·Hessian·step 설정 검토"))
    if geo is not None and "geometry_explosion" not in flagged:
        if geo["min_dist"] < 0.6:
            out.append(("geometry_explosion", "ERROR",
                        f"원자 {geo['min_pair'][0] + 1}–{geo['min_pair'][1] + 1} 거리 "
                        f"{geo['min_dist']:.2f} Å — 비정상 접근"))
        elif init_maxdist and geo["max_dist"] > 1.6 * init_maxdist:
            out.append(("geometry_explosion", "ERROR",
                        f"분자 최대 지름이 {init_maxdist:.1f} → {geo['max_dist']:.1f} Å 로 급증 — "
                        "조각 분리·구조 붕괴 의심"))
    return out


# ── 상태 판정 (§5) ───────────────────────────────────────────────────
def classify_error(exc: BaseException) -> str:
    """OS 실행 실패(CRASHED)와 계산 목적 미달(FAILED)을 나눈다."""
    name = type(exc).__name__
    msg = str(exc)
    if name == "CancelledError" or "사용자 취소" in msg:
        return "CANCELLED"
    if isinstance(exc, (MemoryError, OSError)) or "memory" in msg.lower() \
            or "killed" in msg.lower():
        return "CRASHED"
    if "미수렴" in msg or "not converged" in msg.lower() or "converge" in msg.lower():
        return "FAILED"
    if isinstance(exc, (ValueError, RuntimeError, KeyError, TypeError, IndexError)):
        return "FAILED"
    return "CRASHED"


def bonded_pairs_from_smiles(smiles: str):
    """SMILES 의 결합 목록 — geometry.smiles_to_conformers 와 같은 원자 순서(AddHs)."""
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    mol = Chem.AddHs(mol)
    return [(b.GetBeginAtomIdx(), b.GetEndAtomIdx()) for b in mol.GetBonds()], \
        [a.GetSymbol() for a in mol.GetAtoms()]


def sanity_geometry(atoms, smiles: str | None, check_bonds: bool = True) -> dict:
    """결과 구조의 화학적 sanity (§2.5) — 비정상 접근, 결합 절단."""
    syms = [a[0] for a in atoms]
    coords = np.array([a[1:4] for a in atoms], dtype=float)
    out = {"min_dist": None, "too_close": [], "broken_bonds": [], "checked_bonds": False}
    geo = geometry_stats(coords, syms)
    if geo is None:
        return out
    out["min_dist"] = round(geo["min_dist"], 3)
    d = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=2)
    n = len(syms)
    for i in range(n):
        for j in range(i + 1, n):
            r = COVALENT_RADII.get(syms[i], 0.9) + COVALENT_RADII.get(syms[j], 0.9)
            if d[i, j] < 0.55 * r:
                out["too_close"].append({"i": i + 1, "j": j + 1, "dist": round(float(d[i, j]), 3),
                                         "pair": f"{syms[i]}{i + 1}–{syms[j]}{j + 1}"})
    if check_bonds and smiles:
        try:
            res = bonded_pairs_from_smiles(smiles)
        except Exception:  # noqa: BLE001
            res = None
        if res and len(res[1]) == n and res[1] == syms:
            out["checked_bonds"] = True
            for i, j in res[0]:
                r = COVALENT_RADII.get(syms[i], 0.9) + COVALENT_RADII.get(syms[j], 0.9)
                if d[i, j] > 1.3 * r + 0.15:
                    out["broken_bonds"].append({"i": i + 1, "j": j + 1,
                                                "dist": round(float(d[i, j]), 3),
                                                "pair": f"{syms[i]}{i + 1}–{syms[j]}{j + 1}"})
    return out


def validate(summary: dict, params: dict | None = None, desc: dict | None = None,
             geometry: dict | None = None, error: str | None = None,
             error_kind: str | None = None) -> dict:
    """PASS / REVIEW / FAIL (+ CRASHED · CANCELLED) — 근거를 checks 로 남긴다 (§5.2)."""
    params = params or {}
    desc = desc or {}
    checks = []

    def add(key, label, status, detail):
        checks.append({"key": key, "label": label, "status": status, "detail": detail})

    # 1) 프로세스 / 실행 환경
    if error:
        st = {"CRASHED": "fail", "CANCELLED": "skip"}.get(error_kind, "fail")
        add("process", "프로세스", st,
            f"{error_kind or 'FAILED'} — {error}")
    else:
        add("process", "프로세스", "pass", "정상 종료")

    scf = summary.get("scf") or {}
    opt = summary.get("opt") or {}
    freq = summary.get("freq") or {}
    anomalies = summary.get("anomalies") or []
    attempts = summary.get("attempts") or []

    # 2) SCF — 엔진 기준 수렴 + 자동 복구 이력
    if scf.get("runs"):
        if scf.get("failed"):
            add("scf", "SCF 수렴", "fail", f"SCF 최종 미수렴 {scf['failed']}회 (총 {scf['runs']}회)")
        elif scf.get("recovered"):
            n_att = len([a for a in attempts if a.get("n", 1) > 1])
            add("scf", "SCF 수렴", "review",
                f"모든 SCF 수렴 ({scf['runs']}회) — 자동 복구 {scf['recovered']}회, "
                f"변경 attempt {n_att}건 확인 필요")
        else:
            add("scf", "SCF 수렴", "pass", f"SCF {scf['runs']}회 모두 기본 설정으로 수렴")
    else:
        add("scf", "SCF 수렴", "skip", "SCF 기록 없음")

    # 3) 구조 최적화
    if params.get("do_opt") or opt.get("runs"):
        if opt.get("unconverged"):
            add("opt", "구조 최적화", "fail",
                f"미수렴으로 중단 {opt['unconverged']}회 (총 {opt['runs']}회 · 최대 스텝 도달 또는 스텝 내부 SCF 실패) — "
                "프로세스 종료와 별개로 계산 미완")
        elif any(a["kind"] == "opt_stagnation" for a in anomalies):
            add("opt", "구조 최적화", "review", f"{opt['runs']}회 수렴 — 정체 경고 있음")
        elif opt.get("runs"):
            add("opt", "구조 최적화", "pass", f"{opt['runs']}회 모두 수렴")
        else:
            add("opt", "구조 최적화", "skip", "최적화 미요청")
    else:
        add("opt", "구조 최적화", "skip", "최적화 미요청 (역장 구조 단일점)")

    # 4) 진동수
    if params.get("do_thermo") or freq.get("runs"):
        n_imag = desc.get("n_imaginary_freqs", freq.get("n_imag"))
        if n_imag is None:
            add("freq", "진동수 검증", "fail" if params.get("do_thermo") and not error
                else "skip", "요청했으나 진동수 결과 없음 — Validated 로 승격 불가")
        elif n_imag == 0:
            add("freq", "진동수 검증", "pass", "허수 진동수 없음 — 극소점")
        else:
            low = freq.get("lowest_cm")
            small = low is not None and abs(low) < SMALL_IMAG_CM
            add("freq", "진동수 검증", "review",
                f"허수 진동수 {n_imag}개 (최저 {low:.0f} cm⁻¹) — "
                + ("작은 값: 수치 노이즈·저주파 모드 가능, 재최적화 검토"
                   if small else "안장점 가능성 — 구조·normal mode 확인"))
    else:
        add("freq", "진동수 검증", "skip", "진동수 미요청")

    # 5) 화학적 sanity — 구조
    if geometry:
        if geometry.get("too_close"):
            p = geometry["too_close"][0]
            add("geometry", "구조 sanity", "review",
                f"원자 간 비정상 접근 {p['pair']} {p['dist']} Å 외 {len(geometry['too_close']) - 1}건")
        elif geometry.get("broken_bonds"):
            p = geometry["broken_bonds"][0]
            add("geometry", "구조 sanity", "review",
                f"입력 결합이 늘어남 {p['pair']} {p['dist']} Å 외 {len(geometry['broken_bonds']) - 1}건 "
                "— 결합 절단·조각 분리 의심")
        else:
            add("geometry", "구조 sanity", "pass",
                f"최단 원자 간 거리 {geometry.get('min_dist')} Å"
                + (" · 입력 결합 유지" if geometry.get("checked_bonds") else " · 결합 대조 생략"))
    elif not error:
        add("geometry", "구조 sanity", "skip", "구조 없음")

    # 6) 전자 상태 sanity — 스핀 오염, HOMO/LUMO 단위
    spin = desc.get("spin_contamination")
    if spin:
        worst = max(spin, key=lambda s: abs(s.get("deviation") or 0))
        if abs(worst.get("deviation") or 0) > 0.1:
            add("spin", "스핀 상태", "review",
                f"{worst['label']}: ⟨S²⟩ {worst['s2']:.3f} (기대 {worst['expected']:.3f}) — "
                "스핀 오염, UKS 결과 신뢰도 저하")
        else:
            add("spin", "스핀 상태", "pass",
                f"⟨S²⟩ 편차 최대 {abs(worst.get('deviation') or 0):.3f}")
    if desc.get("homo_ev") is not None:
        homo, gap = desc.get("homo_ev"), desc.get("gap_ev")
        if homo > 0 or (gap is not None and gap <= 0):
            add("orbitals", "궤도 에너지", "review",
                f"HOMO {homo:+.2f} eV · gap {gap} eV — 단위 변환 또는 전자 상태 확인")
        else:
            add("orbitals", "궤도 에너지", "pass", f"HOMO {homo:+.2f} eV · gap {gap} eV")

    # 7) 설정 반영 — 실제 실행값이 요청값과 같은가 (§2.1)
    actual = summary.get("actual") or {}
    if actual and params:
        mism = []
        if actual.get("xc") and params.get("xc") and actual["xc"].lower() != params["xc"].lower():
            mism.append(f"범함수 {params['xc']}→{actual['xc']}")
        if params.get("disp") and not actual.get("disp"):
            mism.append("분산 보정 미적용")
        if mism:
            add("settings", "설정 반영", "review", " · ".join(mism))
        else:
            add("settings", "설정 반영", "pass",
                f"{actual.get('xc')} · 분산 {actual.get('disp') or '없음'} · "
                f"용매 {actual.get('solvent') or 'vacuum'}")

    # 8) 이상 징후 요약
    errs = [a for a in anomalies if a["severity"] in ("ERROR", "FATAL")]
    warns = [a for a in anomalies if a["severity"] == "WARN"]
    if errs:
        add("anomalies", "이상 징후", "review", f"ERROR {len(errs)}건 · WARN {len(warns)}건 — 원본 로그 확인")
    elif warns:
        add("anomalies", "이상 징후", "review", f"WARN {len(warns)}건")
    else:
        add("anomalies", "이상 징후", "pass", "없음")

    if error:
        grade = error_kind or "FAILED"
    elif any(c["status"] == "fail" for c in checks):
        grade = "FAIL"
    elif any(c["status"] == "review" for c in checks):
        grade = "REVIEW"
    else:
        grade = "PASS"
    worst = next((c for c in checks if c["status"] == "fail"), None) \
        or next((c for c in checks if c["status"] == "review"), None)
    return {
        "grade": grade,
        "checks": checks,
        "summary": (f"{grade} — {worst['label']}: {worst['detail']}" if worst else
                    f"{grade} — 프로세스·SCF·구조·진동수·sanity 모두 통과"),
        "rule": ("프로세스 정상 종료 ≠ 계산 정확. SCF·구조·진동수 수렴과 화학적 sanity 를 "
                 "따로 확인해 PASS/REVIEW/FAIL 을 정한다"),
        "protocol": "MONITOR-v1",
    }


# ── 읽기 (API) ─────────────────────────────────────────────────────────
def read_events(job_id: str, after: int = 0, limit: int = 500, kinds=None) -> dict:
    path = events_path(job_id)
    if not path.exists():
        return {"exists": False, "events": [], "total": 0, "after": after}
    out, total = [], 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            total += 1
            if total <= after or len(out) >= limit:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if kinds and rec.get("kind") not in kinds:
                continue
            rec["n"] = total
            out.append(rec)
    return {"exists": True, "events": out, "total": total, "after": after}


def scf_history(job_id: str, run: int | None = None, max_runs: int = 12) -> dict:
    """SCF run 별 cycle 이력 — 차트용. 최근 max_runs 개만."""
    ev = read_events(job_id, 0, 10 ** 7, kinds=("SCF_BEGIN", "SCF", "SCF_END"))
    runs = []
    for r in ev["events"]:
        if r["kind"] == "SCF_BEGIN":
            runs.append({"label": r.get("label"), "max_cycle": r.get("max_cycle"),
                         "cycles": [], "converged": None, "start_n": r["n"]})
        elif r["kind"] == "SCF" and runs:
            runs[-1]["cycles"].append({"cycle": r.get("cycle"), "energy": r.get("energy"),
                                       "delta_e": r.get("delta_e"), "gorb": r.get("gorb"),
                                       "ddm": r.get("ddm")})
        elif r["kind"] == "SCF_END" and runs:
            runs[-1]["converged"] = r.get("converged")
            runs[-1]["end_n"] = r["n"]
    if run is not None and 0 <= run < len(runs):
        return {"runs": [runs[run]], "total_runs": len(runs)}
    return {"runs": runs[-max_runs:], "total_runs": len(runs)}


def opt_history(job_id: str, max_runs: int = 6) -> dict:
    ev = read_events(job_id, 0, 10 ** 7, kinds=("OPT_BEGIN", "OPT", "OPT_END"))
    runs = []
    for r in ev["events"]:
        if r["kind"] == "OPT_BEGIN":
            runs.append({"label": r.get("label"), "max_steps": r.get("max_steps"),
                         "steps": [], "converged": None})
        elif r["kind"] == "OPT" and runs:
            runs[-1]["steps"].append({k: r.get(k) for k in
                                      ("step", "energy", "delta_e", "grad_norm", "grad_max", "disp_max")})
        elif r["kind"] == "OPT_END" and runs:
            runs[-1]["converged"] = r.get("converged")
    return {"runs": runs[-max_runs:], "total_runs": len(runs)}


def heartbeat_view(job: dict, now: float | None = None) -> dict:
    """RUNNING 작업의 heartbeat 나이 — 오래 조용하면 경고 (§6 No heartbeat)."""
    now = now or time.time()
    mon = job.get("monitor") or {}
    hb = mon.get("heartbeat") or job.get("createdAt")
    age = round(now - hb, 1) if hb else None
    stale = bool(job.get("status") == "RUNNING" and age is not None and age > HEARTBEAT_WARN_S)
    return {"age_s": age, "stale": stale, "warn_after_s": HEARTBEAT_WARN_S}


def job_monitor_view(job: dict, now: float | None = None) -> dict:
    """대시보드 한 줄 — 작업 상태 + 모니터 요약 + 검증 등급."""
    mon = job.get("monitor") or {}
    val = job.get("validation") or ((job.get("result") or {}).get("validation"))
    hb = heartbeat_view(job, now)
    grade = (val or {}).get("grade")
    if job.get("status") in ("QUEUED", "RUNNING"):
        grade = "RUN" if job["status"] == "RUNNING" else "QUEUED"
    anomalies = mon.get("anomalies") or []
    return {
        "id": job["id"], "name": (job.get("material") or {}).get("name"),
        "smiles": (job.get("material") or {}).get("smiles"),
        "status": job.get("status"), "stage": job.get("stage"), "progress": job.get("progress"),
        "accuracy": (job.get("settings") or {}).get("accuracy"),
        "campaign": job.get("campaign"), "createdAt": job.get("createdAt"),
        "finishedAt": job.get("finishedAt"), "error": job.get("error"),
        "grade": grade, "validation_summary": (val or {}).get("summary"),
        "scf": mon.get("scf"), "opt": mon.get("opt"), "freq": mon.get("freq"),
        "attempts": len(mon.get("attempts") or []),
        "recovered": (mon.get("scf") or {}).get("recovered", 0),
        "anomalies": anomalies[-6:],
        "n_error": sum(1 for a in anomalies if a["severity"] in ("ERROR", "FATAL")),
        "n_warn": sum(1 for a in anomalies if a["severity"] == "WARN"),
        "heartbeat": hb, "events": mon.get("events", 0),
        "raw_log": mon.get("raw_log"),
        "wall_s": ((job.get("result") or {}).get("wall_time_s")
                   if job.get("result") else
                   round((now or time.time()) - (mon.get("started") or job.get("createdAt") or 0), 1)
                   if job.get("status") == "RUNNING" else None),
    }


# ── 원본 로그 읽기 도우미 (§9) ────────────────────────────────────────
SEVERITY_PATTERNS = {
    "ERROR": ("error", "fatal", "traceback", "exception", "abort", "not converged", "미수렴", "오류", "실패"),
    "WARN": ("warn", "warning", "imaginary", "재시도", "경고", "damping"),
    "OK": ("converged", "수렴 —", "완료"),
}


def offset_to_line(path, offset: int | None) -> int | None:
    """byte offset → 1-based line 번호 (원본 로그 «해당 위치로 이동»용)."""
    if offset is None:
        return None
    try:
        n = 0
        remaining = int(offset)
        with open(path, "rb") as f:
            while remaining > 0:
                chunk = f.read(min(1 << 20, remaining))
                if not chunk:
                    break
                n += chunk.count(b"\n")
                remaining -= len(chunk)
        return n + 1
    except OSError:
        return None


def read_log_lines(path, start: int = 1, count: int = 400) -> dict:
    """line range 읽기 — 브라우저에 전체를 주지 않는다 (§9.1)."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    total = len(lines)
    start = max(1, start)
    end = min(total, start + count - 1)
    return {"start": start, "end": end, "total": total,
            "lines": lines[start - 1:end]}


def search_log(path, query: str, limit: int = 200, ignore_case: bool = True) -> dict:
    q = query.lower() if ignore_case else query
    hits = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            hay = line.lower() if ignore_case else line
            if q in hay:
                hits.append({"line": n, "text": line.rstrip("\n")[:300]})
                if len(hits) >= limit:
                    break
    return {"query": query, "hits": hits, "truncated": len(hits) >= limit}
