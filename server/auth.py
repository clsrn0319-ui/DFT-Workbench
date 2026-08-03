"""접속 통제 — 관리자가 공유한 비밀번호를 아는 사람만 사용할 수 있다.

개별 계정을 두지 않고 **공유 비밀번호 하나**로 출입만 통제한다.
비밀번호는 서버를 실행하는 사람(관리자)이 정하며, 웹에서는 변경할 수 없다.

  RHOBENCH_ACCESS_PASSWORD='공유할_비밀번호' uvicorn server.main:app ...

환경변수를 주지 않으면 최초 실행 시 무작위로 발급해 콘솔에 한 번 출력하고
data/access.json에 해시로 보관한다(평문 저장 없음).

의존성 없이 표준 라이브러리만 사용:
  - 비밀번호: PBKDF2-HMAC-SHA256 (솔트 + 20만 회 반복) 해시
  - 세션: 서버 메모리에 보관하는 무작위 토큰 (서버 재시작 시 전원 로그아웃)
"""

import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ACCESS_FILE = DATA_DIR / "access.json"

SESSION_TTL = 12 * 3600  # 12시간
PBKDF2_ROUNDS = 200_000

_lock = threading.RLock()
_access: dict | None = None      # {"salt": ..., "hash": ...}
_sessions: dict[str, float] = {}  # token → 만료 시각
_loaded = False


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()


def _store(password: str):
    global _access
    salt = secrets.token_hex(16)
    _access = {"salt": salt, "hash": _hash_password(password, salt),
               "updated_at": time.time()}
    DATA_DIR.mkdir(exist_ok=True)
    tmp = ACCESS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_access, indent=1), encoding="utf-8")
    tmp.replace(ACCESS_FILE)
    try:
        ACCESS_FILE.chmod(0o600)  # 해시 파일 접근 제한
    except OSError:
        pass


def _announce(password: str, generated: bool):
    bar = "=" * 64
    print(f"\n{bar}\n  RhoBench 접속 비밀번호\n\n"
          f"      {password}\n\n"
          + ("  (무작위 발급 — 지금 기록해 두세요. 다시 표시되지 않습니다)\n"
             if generated else "  (환경변수 RHOBENCH_ACCESS_PASSWORD 사용)\n")
          + "  이 비밀번호를 아는 사람만 접속할 수 있습니다. 필요한 분에게 공유하세요.\n"
            "  변경하려면 RHOBENCH_ACCESS_PASSWORD 를 새 값으로 주고 서버를 다시 실행하세요.\n"
          + bar + "\n", flush=True)


def _load():
    """환경변수가 있으면 항상 그 값을 채택(비밀번호 변경 수단), 없으면 저장본 사용."""
    global _loaded, _access
    if _loaded:
        return
    _loaded = True

    env_password = os.environ.get("RHOBENCH_ACCESS_PASSWORD")
    saved = None
    if ACCESS_FILE.exists():
        try:
            saved = json.loads(ACCESS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            saved = None

    if env_password:
        # 저장된 해시와 다르면 새 비밀번호로 교체하고 기존 세션을 모두 끊는다
        if saved and secrets.compare_digest(
                _hash_password(env_password, saved["salt"]), saved["hash"]):
            _access = saved
        else:
            _store(env_password)
            _sessions.clear()
        _announce(env_password, generated=False)
        return

    if saved:
        _access = saved
        print("\n  RhoBench: 저장된 접속 비밀번호를 사용합니다 "
              "(변경하려면 RHOBENCH_ACCESS_PASSWORD 지정 후 재실행).\n", flush=True)
        return

    generated = secrets.token_urlsafe(9)
    _store(generated)
    _announce(generated, generated=True)


def check_password(password: str) -> bool:
    with _lock:
        _load()
        if not _access:
            return False
        return secrets.compare_digest(
            _hash_password(password, _access["salt"]), _access["hash"])


def login(password: str):
    """비밀번호가 맞으면 세션 토큰 반환, 아니면 None."""
    with _lock:
        if not check_password(password):
            return None
        token = secrets.token_urlsafe(32)
        _sessions[token] = time.time() + SESSION_TTL
        return token


def logout(token: str | None):
    with _lock:
        _sessions.pop(token, None)


def is_valid(token: str | None) -> bool:
    """세션 토큰 유효성 — 만료된 토큰은 정리한다."""
    if not token:
        return False
    with _lock:
        _load()
        expires = _sessions.get(token)
        if expires is None:
            return False
        if expires < time.time():
            _sessions.pop(token, None)
            return False
        return True


def active_sessions() -> int:
    with _lock:
        now = time.time()
        for tok in [t for t, e in _sessions.items() if e < now]:
            _sessions.pop(tok, None)
        return len(_sessions)
