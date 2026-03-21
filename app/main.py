from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app import database
from app.routes import dashboard_router, companies_router, pipeline_entries_router, fee_records_router, contracts_router
from app import models  # noqa
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


def create_app():
    app = FastAPI(title='综合管廊有偿使用费管理系统', lifespan=lifespan)
    app.mount('/static', StaticFiles(directory='app/static'), name='static')

    app.include_router(dashboard_router)
    app.include_router(companies_router)
    app.include_router(pipeline_entries_router)
    app.include_router(fee_records_router)
    app.include_router(contracts_router)
    return app


app = create_app()
