"""CSRF 防护：会话绑定的 token，POST/PUT/PATCH/DELETE 请求必须携带。"""
import secrets

CSRF_FIELD = 'csrf_token'
CSRF_HEADER = 'x-csrf-token'
SESSION_KEY = '_csrf_token'

# 登录/登出本身不校验（登录时尚无可信会话可绑定）
EXEMPT_PATHS = {'/login', '/logout'}


def get_csrf_token(request) -> str:
    """获取当前会话的 CSRF token，没有则生成。"""
    session = request.session
    token = session.get(SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[SESSION_KEY] = token
    return token


def validate_csrf_token(request, submitted: str | None) -> bool:
    expected = request.session.get(SESSION_KEY) if hasattr(request, 'session') else None
    if not expected or not submitted:
        return False
    return secrets.compare_digest(str(submitted), str(expected))
