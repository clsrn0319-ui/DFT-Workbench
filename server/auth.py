"""사용자 인증·승인 — 관리자가 승인한 계정만 사용 가능.

의존성 없이 표준 라이브러리만 사용한다:
  - 비밀번호: PBKDF2-HMAC-SHA256 (솔트 + 20만 회 반복) 해시로만 저장
  - 세션: 서버 메모리에 보관하는 무작위 토큰 (서버 재시작 시 전원 로그아웃)

첫 실행 시 관리자 계정이 없으면 자동 생성한다. 비밀번호는 환경변수
RHOBENCH_ADMIN_PASSWORD를 쓰고, 없으면 무작위 생성해 콘솔에 1회 출력한다.
"""

import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USERS_FILE = DATA_DIR / "users.json"

SESSION_TTL = 12 * 3600  # 12시간
PBKDF2_ROUNDS = 200_000

_lock = threading.RLock()
_users: dict[str, dict] = {}
_sessions: dict[str, dict] = {}
_loaded = False


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()


def _save():
    DATA_DIR.mkdir(exist_ok=True)
    tmp = USERS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(list(_users.values()), ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(USERS_FILE)
    try:
        USERS_FILE.chmod(0o600)  # 해시 파일 접근 제한
    except OSError:
        pass


def _load():
    global _loaded
    if _loaded:
        return
    _loaded = True
    if USERS_FILE.exists():
        try:
            for u in json.loads(USERS_FILE.read_text(encoding="utf-8")):
                _users[u["username"]] = u
        except (json.JSONDecodeError, OSError):
            pass
    if not _users:
        _bootstrap_admin()


def _bootstrap_admin():
    """관리자 계정 최초 생성 — 환경변수 우선, 없으면 무작위 발급 후 콘솔 안내."""
    password = os.environ.get("RHOBENCH_ADMIN_PASSWORD")
    generated = password is None
    if generated:
        password = secrets.token_urlsafe(12)
    _create_user("admin", password, is_admin=True, note="최초 관리자")
    banner = "=" * 62
    print(f"\n{banner}\n  RhoBench 관리자 계정이 생성되었습니다.\n"
          f"    아이디   : admin\n"
          f"    비밀번호 : {password}\n"
          + ("  (무작위 발급 — 지금 기록해 두세요. 다시 표시되지 않습니다)\n"
             if generated else "  (환경변수 RHOBENCH_ADMIN_PASSWORD 사용)\n")
          + f"  로그인 후 '사용자 관리'에서 연구실 구성원을 승인하세요.\n{banner}\n",
          flush=True)


def _create_user(username: str, password: str, is_admin: bool = False, note: str = ""):
    salt = secrets.token_hex(16)
    _users[username] = {
        "username": username,
        "salt": salt,
        "hash": _hash_password(password, salt),
        "is_admin": is_admin,
        "note": note,
        "created_at": time.time(),
        "last_login": None,
    }
    _save()
    return _users[username]


def public(user: dict) -> dict:
    """비밀번호 관련 필드를 제외한 안전한 표현."""
    return {k: v for k, v in user.items() if k not in ("salt", "hash")}


def list_users():
    with _lock:
        _load()
        return [public(u) for u in
                sorted(_users.values(), key=lambda u: u["created_at"])]


def add_user(username: str, password: str, is_admin: bool = False, note: str = ""):
    with _lock:
        _load()
        if username in _users:
            raise ValueError("이미 존재하는 아이디입니다.")
        if len(username) < 2 or len(password) < 8:
            raise ValueError("아이디는 2자 이상, 비밀번호는 8자 이상이어야 합니다.")
        return public(_create_user(username, password, is_admin, note))


def set_password(username: str, password: str):
    with _lock:
        _load()
        user = _users.get(username)
        if user is None:
            raise ValueError("존재하지 않는 사용자입니다.")
        if len(password) < 8:
            raise ValueError("비밀번호는 8자 이상이어야 합니다.")
        user["salt"] = secrets.token_hex(16)
        user["hash"] = _hash_password(password, user["salt"])
        _save()
        # 해당 사용자의 기존 세션 무효화
        for tok in [t for t, s in _sessions.items() if s["username"] == username]:
            _sessions.pop(tok, None)


def delete_user(username: str):
    with _lock:
        _load()
        if username not in _users:
            raise ValueError("존재하지 않는 사용자입니다.")
        if _users[username].get("is_admin") and sum(
                1 for u in _users.values() if u.get("is_admin")) <= 1:
            raise ValueError("마지막 관리자 계정은 삭제할 수 없습니다.")
        del _users[username]
        _save()
        for tok in [t for t, s in _sessions.items() if s["username"] == username]:
            _sessions.pop(tok, None)


def login(username: str, password: str):
    """성공 시 세션 토큰 반환, 실패 시 None."""
    with _lock:
        _load()
        user = _users.get(username)
        if user is None:
            # 사용자 없음도 해시 비용을 치러 타이밍 차이를 줄임
            _hash_password(password, secrets.token_hex(16))
            return None
        if not secrets.compare_digest(_hash_password(password, user["salt"]), user["hash"]):
            return None
        token = secrets.token_urlsafe(32)
        _sessions[token] = {"username": username, "expires": time.time() + SESSION_TTL}
        user["last_login"] = time.time()
        _save()
        return token


def logout(token: str):
    with _lock:
        _sessions.pop(token, None)


def resolve(token: str | None):
    """세션 토큰 → 사용자. 만료·무효면 None."""
    if not token:
        return None
    with _lock:
        _load()
        sess = _sessions.get(token)
        if sess is None:
            return None
        if sess["expires"] < time.time():
            _sessions.pop(token, None)
            return None
        user = _users.get(sess["username"])
        return public(user) if user else None
