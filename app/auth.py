import hashlib
import hmac
import os
import secrets
from urllib.parse import quote


SESSION_USER_KEY = 'admin_username'
LOGIN_PATH = '/login'
LOGOUT_PATH = '/logout'

PUBLIC_EXACT_PATHS = {
    LOGIN_PATH,
    LOGOUT_PATH,
    '/health',
    '/healthz',
    '/favicon.ico',
}

PUBLIC_PATH_PREFIXES = (
    '/static',
)


def get_admin_username() -> str:
    return os.getenv('APP_ADMIN_USERNAME', 'admin').strip() or 'admin'


def get_admin_password() -> str:
    return os.getenv('APP_ADMIN_PASSWORD', '').strip()


def get_admin_password_hash() -> str:
    return os.getenv('APP_ADMIN_PASSWORD_HASH', '').strip()


def is_auth_configured() -> bool:
    return bool(get_admin_password_hash() or get_admin_password())


def get_session_secret() -> str:
    secret = os.getenv('APP_SESSION_SECRET', '').strip()
    if secret:
        return secret
    # 没配置时自动生成一个临时 secret，重启后会话会失效，但比裸奔安全
    return secrets.token_urlsafe(32)


def get_session_https_only() -> bool:
    value = os.getenv('APP_SESSION_HTTPS_ONLY', 'false').strip().lower()
    return value in {'1', 'true', 'yes', 'on'}


def normalize_next_url(next_url: str | None) -> str:
    if not next_url:
        return '/'
    next_url = next_url.strip()
    if not next_url.startswith('/'):
        return '/'
    if next_url.startswith('//'):
        return '/'
    # 反斜杠可被浏览器解析为 //，如 /\evil.com 会跳到外部站
    if '\\' in next_url:
        return '/'
    return next_url


def build_login_redirect(next_url: str) -> str:
    safe_next = normalize_next_url(next_url)
    return f'{LOGIN_PATH}?next={quote(safe_next, safe="/?=&")}'


def get_current_username(request) -> str | None:
    session = request.scope.get('session') or {}
    return session.get(SESSION_USER_KEY)


def is_authenticated(request) -> bool:
    return bool(get_current_username(request))


def login_user(request, username: str) -> None:
    request.session[SESSION_USER_KEY] = username


# 登录暴力破解防护：内存记录各 IP 失败次数（单进程；多 worker 需换 Redis/DB）
_LOGIN_FAILS: dict[str, list[float]] = {}
_LOGIN_MAX_FAILS = 5
_LOGIN_WINDOW_SECONDS = 300
_LOGIN_LOCK_SECONDS = 600


def _client_ip(request) -> str:
    forwarded = request.headers.get('x-forwarded-for')
    if forwarded:
        return forwarded.split(',')[0].strip()
    client = request.client
    return client.host if client else 'unknown'


def is_login_locked(request) -> bool:
    import time
    ip = _client_ip(request)
    now = time.time()
    fails = [t for t in _LOGIN_FAILS.get(ip, []) if now - t < _LOGIN_WINDOW_SECONDS]
    _LOGIN_FAILS[ip] = fails
    return len(fails) >= _LOGIN_MAX_FAILS


def record_login_fail(request) -> None:
    import time
    ip = _client_ip(request)
    _LOGIN_FAILS.setdefault(ip, []).append(time.time())


def clear_login_fails(request) -> None:
    _LOGIN_FAILS.pop(_client_ip(request), None)


def logout_user(request) -> None:
    request.session.pop(SESSION_USER_KEY, None)


def generate_password_hash(password: str, iterations: int = 390000) -> str:
    salt_hex = secrets.token_hex(16)
    derived_key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        bytes.fromhex(salt_hex),
        iterations,
    )
    return f'pbkdf2_sha256${iterations}${salt_hex}${derived_key.hex()}'


def verify_password(password: str) -> bool:
    stored_hash = get_admin_password_hash()
    if stored_hash:
        return verify_password_hash(password, stored_hash)

    stored_plain = get_admin_password()
    if stored_plain:
        return hmac.compare_digest(password, stored_plain)

    return False


def verify_password_hash(password: str, stored_hash: str) -> bool:
    """
    支持格式：
    pbkdf2_sha256$390000$salt_hex$hash_hex
    """
    try:
        algorithm, iteration_text, salt_hex, expected_hex = stored_hash.split('$', 3)
        if algorithm != 'pbkdf2_sha256':
            return False

        iterations = int(iteration_text)
        derived_key = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            bytes.fromhex(salt_hex),
            iterations,
        )
        return hmac.compare_digest(derived_key.hex(), expected_hex)
    except Exception:
        return False
