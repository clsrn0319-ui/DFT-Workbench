"""테스트 공통 설정 — 로그·이벤트·궤적 파일을 실제 data/logs 가 아닌 임시 폴더에 쓴다.

모니터가 항상 구조화 이벤트를 남기고 원본 로그 기본이 «상세»가 되면서, 실계산
테스트가 저장소의 data/logs 에 TEST-* 파일을 남기게 됐다. 여기서 막는다.
"""

import pytest

from server import store


@pytest.fixture(autouse=True)
def _isolated_logs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOGS_DIR", tmp_path / "logs")
    yield
