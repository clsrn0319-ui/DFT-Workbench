"""물리 규칙 엔진 — 학습(core/)과 분리된 독립 모듈 (규칙 R6).

규칙 추가·판정선 갱신이 모델 재학습을 요구하지 않는다.
판정 임계값은 고정 상수가 아니라 실측 이력에서 동적으로 산출한다 (FV-04).
"""

from dry_process_ai.rules import physics  # noqa: F401
