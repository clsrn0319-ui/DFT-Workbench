"""GPU 스위치 — 기본은 꺼짐(CPU 그대로), 켰는데 못 쓰면 CPU 폴백, 켜져서 되면 결과가 CPU 객체로 돌아온다."""

import numpy as np
import pytest

from server import gpu


@pytest.fixture(autouse=True)
def _reset_probe(monkeypatch):
    monkeypatch.setattr(gpu, "_probe", None)
    monkeypatch.setattr(gpu, "_warned", False)
    yield


def test_default_is_cpu_and_leaves_objects_alone(monkeypatch):
    monkeypatch.setattr(gpu, "ENABLED", False)
    assert gpu.backend() == "cpu" and gpu.active() is False
    obj = object()
    assert gpu.to_gpu(obj) is obj
    assert gpu.sync_back(obj, obj) is obj
    assert gpu.describe().startswith("계산 백엔드: CPU")
    assert gpu.info()["requested"] is False


def test_enabled_without_backend_falls_back_to_cpu(monkeypatch):
    """RHOBENCH_GPU=1 이지만 gpu4pyscf 가 없으면 이유를 남기고 CPU 로."""
    monkeypatch.setattr(gpu, "ENABLED", True)
    monkeypatch.setattr(gpu, "_import_backend", lambda: (_ for _ in ()).throw(ImportError("No module named 'gpu4pyscf'")))
    assert gpu.backend() == "cpu"
    p = gpu.probe()
    assert p["available"] is False and "gpu4pyscf" in p["reason"]
    msg = gpu.describe(log=lambda m: None)
    assert "CPU 로 계산" in msg and "gpu4pyscf" in msg
    obj = object()
    assert gpu.to_gpu(obj, log=lambda m: None) is obj


class _FakeArray:
    """cupy 흉내 — .get() 으로 numpy 를 돌려준다."""
    def __init__(self, a): self._a = np.asarray(a)
    def get(self): return self._a.copy()


class _FakeGpuMF:
    """GPU mf 흉내 — 실제 SCF 는 CPU 객체로 돌리고, 결과를 cupy 모양으로 노출한다."""
    def __init__(self, cpu):
        self._cpu = cpu
        self.converged = False
        self.e_tot = None
        self.callback = None
        self.max_cycle = 50

    def kernel(self, dm0=None):
        e = self._cpu.kernel(dm0) if dm0 is not None else self._cpu.kernel()
        self.converged = bool(self._cpu.converged)
        self.e_tot = e
        self.mo_coeff = _FakeArray(self._cpu.mo_coeff)
        self.mo_energy = _FakeArray(self._cpu.mo_energy)
        self.mo_occ = _FakeArray(self._cpu.mo_occ)
        self.cycles = getattr(self._cpu, "cycles", None)
        return e

    def make_rdm1(self):
        return _FakeArray(self._cpu.make_rdm1())


def test_scf_on_gpu_path_syncs_results_back(monkeypatch):
    """엔진 _run_scf: GPU 객체로 돌린 뒤 CPU 객체가 수렴 상태·궤도(numpy)를 갖는다."""
    from pyscf import dft, gto
    from server import engine
    mol = gto.M(atom="H 0 0 0; H 0 0 0.74", basis="sto-3g", verbose=0)
    mf = dft.RKS(mol, xc="pbe")
    mf.callback = lambda envs: None
    monkeypatch.setattr(gpu, "ENABLED", True)
    monkeypatch.setattr(gpu, "_probe", {"available": True, "reason": "", "device": "fake", "gpu4pyscf": "x", "cupy": "y"})
    shadow = dft.RKS(mol, xc="pbe")
    fake = _FakeGpuMF(shadow)
    monkeypatch.setattr(mf, "to_gpu", lambda: fake, raising=False)
    logs = []
    e = engine._run_scf(mf, "테스트", logs.append)
    assert fake.converged and fake.callback is mf.callback       # 실행 옵션이 GPU 객체로 옮겨짐
    assert mf.converged is True and abs(mf.e_tot - e) < 1e-10
    assert isinstance(mf.mo_coeff, np.ndarray) and isinstance(mf.mo_energy, np.ndarray)
    assert abs(float(mf.mo_energy[0]) - float(shadow.mo_energy[0])) < 1e-10
    # 되돌아온 CPU 객체로 후처리(밀도 행렬)가 가능해야 한다
    assert mf.make_rdm1().shape == (2, 2)
    assert any("SCF 수렴" in m for m in logs)


def test_frozen_solvent_stays_on_cpu(monkeypatch):
    monkeypatch.setattr(gpu, "ENABLED", True)
    monkeypatch.setattr(gpu, "_probe", {"available": True, "reason": "", "device": "fake", "gpu4pyscf": "x", "cupy": "y"})

    class Sv: frozen = True
    class MF:
        with_solvent = Sv()
        def to_gpu(self): raise AssertionError("동결 용매장은 GPU 로 보내면 안 된다")
    mf = MF()
    logs = []
    assert gpu.to_gpu(mf, logs.append) is mf and "CPU" in logs[0]


def test_to_gpu_conversion_failure_falls_back(monkeypatch):
    monkeypatch.setattr(gpu, "ENABLED", True)
    monkeypatch.setattr(gpu, "_probe", {"available": True, "reason": "", "device": "fake", "gpu4pyscf": "x", "cupy": "y"})

    class MF:
        def to_gpu(self): raise NotImplementedError("no gpu impl")
    mf = MF()
    logs = []
    assert gpu.to_gpu(mf, logs.append) is mf and "CPU" in logs[0]


def test_to_numpy_handles_cupy_like_and_plain():
    assert gpu.to_numpy(_FakeArray([1.0, 2.0])).tolist() == [1.0, 2.0]
    assert gpu.to_numpy([3, 4]).tolist() == [3, 4]
    assert gpu.to_numpy(None) is None


def test_provenance_records_backend():
    from server import presets
    from server.engine import _provenance, _resolve_params
    s = {**presets.DEFAULT_SETTINGS, "expert": dict(presets.DEFAULT_SETTINGS["expert"])}
    prov = _provenance(_resolve_params(s), s, None)
    assert prov["backend"] == "cpu" and prov["gpu"]["requested"] is False
