from contextlib import asynccontextmanager

import logging
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app import database
from app import models  # noqa
from app.auth import (
    PUBLIC_EXACT_PATHS,
    PUBLIC_PATH_PREFIXES,
    build_login_redirect,
    get_current_username,
    get_session_https_only,
    get_session_secret,
)
from app.csrf import CSRF_FIELD, CSRF_HEADER, EXEMPT_PATHS, get_csrf_token, validate_csrf_token
from app.paths import STATIC_DIR, TEMPLATES_DIR
from app.routes import (
    auth_router,
    companies_router,
    contracts_router,
    dashboard_router,
    fee_records_router,
    fee_standards_router,
    fee_summary_router,
    feasibility_subsidy_router,
    settings_router,
    data_dashboard_router,
    health_router,
    pipeline_entries_router,
)
from app.services.reminder_service import fee_reminder_scheduler
from app.services.seed_service import seed_data
# 引入新路由

def initialize_application():
    database.Base.metadata.create_all(bind=database.engine)
    schema_upgrade = getattr(database, 'ensure_sqlite_schema', None)
    if callable(schema_upgrade):
        schema_upgrade()

    with database.SessionLocal() as db:
        seed_data(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_application()
    fee_reminder_scheduler.start()
    try:
        yield
    finally:
        fee_reminder_scheduler.stop()


def register_routers(app: FastAPI):
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(companies_router)
    app.include_router(pipeline_entries_router)
    app.include_router(fee_records_router)
    app.include_router(fee_standards_router)
    app.include_router(contracts_router)
    app.include_router(fee_summary_router)
    app.include_router(feasibility_subsidy_router)
    app.include_router(settings_router)
    app.include_router(data_dashboard_router)


logger = logging.getLogger(__name__)
error_templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class CsrfMiddleware(BaseHTTPMiddleware):
    """CSRF 防护：可变请求必须携带与会话绑定的 token。"""

    async def dispatch(self, request: Request, call_next):
        # 模板用 request.state.csrf_token 渲染隐藏字段
        try:
            request.state.csrf_token = get_csrf_token(request)
        except Exception:
            request.state.csrf_token = ''

        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            path = request.url.path
            if path not in EXEMPT_PATHS:
                submitted = request.headers.get(CSRF_HEADER)
                if not submitted:
                    content_type = request.headers.get('content-type', '')
                    # 注意：不能在这里调 request.form()（Starlette 0.45 下游会读到空表单），
                    # 用 request.body()（带缓存，下游可重读）+ 手动解析 urlencoded。
                    if 'application/x-www-form-urlencoded' in content_type:
                        try:
                            body = await request.body()
                            fields = dict(parse_qsl(body.decode('utf-8', errors='ignore')))
                            submitted = fields.get(CSRF_FIELD)
                        except Exception:
                            submitted = None
                if not validate_csrf_token(request, submitted):
                    return error_templates.TemplateResponse(
                        'error.html',
                        {
                            'request': request,
                            'status_code': 403,
                            'title': '请求被拒绝',
                            'message': '安全校验未通过（CSRF token 缺失或已过期），请刷新页面后重试。',
                        },
                        status_code=403,
                    )
        return await call_next(request)


class RequireLoginMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 这里先读一次当前用户，供模板等地方使用
        request.state.user = get_current_username(request)

        # 放行公开路径
        if path in PUBLIC_EXACT_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES):
            return await call_next(request)

        # 未登录则跳转登录页
        if not request.state.user:
            next_url = request.url.path
            if request.url.query:
                next_url = f'{next_url}?{request.url.query}'
            return RedirectResponse(url=build_login_redirect(next_url), status_code=303)

        return await call_next(request)


def create_app():
    app = FastAPI(
        title='综合管廊有偿使用费管理系统',
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')

    # 先加登录校验中间件
    app.add_middleware(RequireLoginMiddleware)

    # CSRF 中间件（需要 session，必须在 SessionMiddleware 内层）
    app.add_middleware(CsrfMiddleware)

    # 再加 SessionMiddleware
    # 这样 SessionMiddleware 会在更外层先执行，request.scope['session'] 就可用了
    https_only = get_session_https_only()
    if not https_only:
        logger.warning('生产部署请设置 APP_SESSION_HTTPS_ONLY=true，否则会话 Cookie 不带 Secure 标志')
    app.add_middleware(
        SessionMiddleware,
        secret_key=get_session_secret(),
        session_cookie='corridor_fee_session',
        same_site='lax',
        https_only=https_only,
        max_age=60 * 60 * 12,
    )

    register_routers(app)

    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return error_templates.TemplateResponse(
            'error.html',
            {'request': request, 'status_code': 422, 'title': '出错了',
             'message': '提交的数据有误，请检查必填项后重试。'},
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            message = '页面不存在或已被删除。'
        elif exc.status_code == 403:
            message = exc.detail if isinstance(exc.detail, str) else '无权访问。'
        elif exc.status_code == 422:
            message = exc.detail if isinstance(exc.detail, str) else '提交的数据有误，请检查后重试。'
        else:
            message = exc.detail if isinstance(exc.detail, str) else f'请求出错（{exc.status_code}）。'
        return error_templates.TemplateResponse(
            'error.html',
            {'request': request, 'status_code': exc.status_code, 'title': '出错了', 'message': message},
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception('Unhandled exception')
        return error_templates.TemplateResponse(
            'error.html',
            {'request': request, 'status_code': 500, 'title': '出错了', 'message': '服务器内部错误，请稍后重试或联系管理员。'},
            status_code=500,
        )

    return app


app = create_app()
