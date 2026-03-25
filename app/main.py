from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
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
from app.paths import STATIC_DIR
from app.routes import (
    auth_router,
    companies_router,
    contracts_router,
    dashboard_router,
    fee_records_router,
    fee_summary_router,
    health_router,
    pipeline_entries_router,
)
from app.services.reminder_service import fee_reminder_scheduler
from app.services.seed_service import seed_data


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
    app.include_router(contracts_router)
    app.include_router(fee_summary_router)


def create_app():
    app = FastAPI(
        title='综合管廊有偿使用费管理系统',
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=get_session_secret(),
        session_cookie='corridor_fee_session',
        same_site='lax',
        https_only=get_session_https_only(),
        max_age=60 * 60 * 12,
    )

    app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')

    @app.middleware('http')
    async def require_login(request: Request, call_next):
        path = request.url.path
        request.state.user = get_current_username(request)

        if path in PUBLIC_EXACT_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES):
            return await call_next(request)

        if not request.state.user:
            next_url = request.url.path
            if request.url.query:
                next_url = f'{next_url}?{request.url.query}'
            return RedirectResponse(url=build_login_redirect(next_url), status_code=303)

        return await call_next(request)

    register_routers(app)
    return app


app = create_app()
