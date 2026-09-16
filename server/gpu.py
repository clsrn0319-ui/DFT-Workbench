"""GPU 백엔드 스위치 — GPU4PySCF 를 쓸지 결정하고, 못 쓰면 조용히 CPU 로 돌아간다.

  - RHOBENCH_GPU=1 (또는 true/yes/on) 일 때만 켜진다. 기본은 꺼짐 → 지금까지와 완전히 같은 CPU 경로.
  - 켜져 있어도 gpu4pyscf·cupy 가 없거나 CUDA 장치가 없으면 경고 한 줄을 남기고 CPU 로 계산한다.
  - 엔진은 무거운 구간(SCF · 구조 최적화 기울기 · Hessian)만 GPU 객체로 돌리고, 결과(궤도·에너지)는
    CPU 객체에 되돌려 놓는다. 전하 분석·MEP·TDDFT 같은 후처리는 CPU 객체를 그대로 쓰므로 바뀌지 않는다.
  - 어떤 경로로 계산했는지는 결과의 provenance(backend: cpu | gpu)에 남는다.

GPU 서버 준비: CUDA 12 드라이버 + `pip install gpu4pyscf-cuda12x` (scripts/ncp_setup.sh --gpu).
"""
from __future__ import annotations

import os
import threading

import numpy as np

ENABLED = os.environ.get("RHOBENCH_GPU", "").strip().lower() in ("1", "true", "yes", "on")

_probe: dict | None = None
_lock = threading.Lock()
_warned = False


def _import_backend():
    """gpu4pyscf 와 cupy 를 불러 장치 정보를 돌려준다. 실패하면 예외."""
    import cupy  # noqa: F401
    import gpu4pyscf  # noqa: F401
    from cupy.cuda import runtime
    n = runtime.getDeviceCount()
    if n < 1:
        raise RuntimeError("CUDA 장치가 없습니다")
    props = runtime.getDeviceProperties(0)
    name = props.get("name", b"")
    if isinstance(name, bytes):
        name = name.decode(errors="replace")
    return {"device": name, "devices": n,
            "gpu4pyscf": getattr(gpu4pyscf, "__version__", "?"),
            "cupy": getattr(cupy, "__version__", "?")}


def probe() -> dict:
    """한 번만 검사해 캐시한다: {available, reason, device, gpu4pyscf, cupy}."""
    global _probe
    with _lock:
        if _probe is None:
            if not ENABLED:
                _probe = {"available": False, "reason": "RHOBENCH_GPU 가 켜져 있지 않음"}
            else:
                try:
                    _probe = {"available": True, "reason": "", **_import_backend()}
                except Exception as exc:  # noqa: BLE001 — 어떤 이유든 CPU 로 폴백
                    _probe = {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
        return dict(_probe)


def active() -> bool:
    return ENABLED and probe()["available"]


def backend() -> str:
    return "gpu" if active() else "cpu"


def info() -> dict:
    p = probe()
    return {"backend": backend(), "requested": ENABLED, **{k: v for k, v in p.items() if k != "available"}}


def describe(log=None) -> str:
    """작업 시작 시 한 줄 기록용. 켰는데 못 쓰면 경고를 한 번만 남긴다."""
    global _warned
    p = probe()
    if not ENABLED:
        return "계산 백엔드: CPU (PySCF)"
    if p["available"]:
        return f"계산 백엔드: GPU (GPU4PySCF {p['gpu4pyscf']} · {p['device']})"
    msg = f"계산 백엔드: CPU — RHOBENCH_GPU=1 이지만 GPU 를 쓸 수 없어 CPU 로 계산합니다 ({p['reason']})"
    if log and not _warned:
        _warned = True
    return msg


def to_numpy(x):
    """cupy 배열이면 host 로, 아니면 그대로 numpy 로."""
    if x is None:
        return None
    if hasattr(x, "get") and not isinstance(x, (dict, np.ndarray)):
        try:
            return np.asarray(x.get())
        except TypeError:
            pass
    return np.asarray(x)


def to_gpu(mf, log=None):
    """CPU mf → GPU mf. 스위치가 꺼졌거나 변환이 안 되면 원래 객체를 돌려준다.

    비평형 용매장(frozen)처럼 GPU 쪽에 대응이 없는 상태는 CPU 에 남긴다.
    """
    if not active():
        return mf
    sv = getattr(mf, "with_solvent", None)
    if sv is not None and getattr(sv, "frozen", False):
        if log:
            log("비평형(동결) 용매장 계산은 GPU 대응이 없어 CPU 로 수행합니다")
        return mf
    try:
        g = mf.to_gpu()
    except Exception as exc:  # noqa: BLE001
        if log:
            log(f"GPU 변환 실패 — 이 단계는 CPU 로 계산합니다 ({type(exc).__name__}: {exc})")
        return mf
    # to_gpu 가 복사하지 않을 수 있는 실행 옵션은 명시적으로 옮긴다
    for attr in ("callback", "max_cycle", "conv_tol", "damp", "level_shift", "verbose"):
        if hasattr(mf, attr):
            try:
                setattr(g, attr, getattr(mf, attr))
            except Exception:  # noqa: BLE001
                pass
    return g


def sync_back(mf, g):
    """GPU 객체의 SCF 결과를 CPU 객체에 되돌려 놓는다 (같은 객체면 아무것도 안 한다)."""
    if g is mf:
        return mf
    mf.converged = bool(getattr(g, "converged", False))
    if getattr(g, "e_tot", None) is not None:
        mf.e_tot = float(g.e_tot)
    for attr in ("mo_coeff", "mo_energy", "mo_occ"):
        v = getattr(g, attr, None)
        if v is not None:
            if isinstance(v, (tuple, list)):          # UKS: (alpha, beta)
                setattr(mf, attr, tuple(to_numpy(a) for a in v))
            else:
                setattr(mf, attr, to_numpy(v))
    for attr in ("cycles", "scf_summary"):
        if hasattr(g, attr):
            try:
                setattr(mf, attr, getattr(g, attr))
            except Exception:  # noqa: BLE001
                pass
    sv_g = getattr(g, "with_solvent", None)
    sv = getattr(mf, "with_solvent", None)
    if sv is not None and sv_g is not None:
        for attr in ("e_cds", "e"):
            v = getattr(sv_g, attr, None)
            if v is not None:
                try:
                    setattr(sv, attr, float(v))
                except (TypeError, ValueError):
                    pass
    return mf
