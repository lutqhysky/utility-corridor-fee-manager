from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.database import Base, engine, SessionLocal, ensure_sqlite_schema
from app.routes import dashboard_router, companies_router, pipeline_entries_router, fee_records_router, contracts_router
from app import models  # noqa
from app.services.seed_service import seed_data

app = FastAPI(title='综合管廊有偿使用费管理系统')
app.mount('/static', StaticFiles(directory='app/static'), name='static')

Base.metadata.create_all(bind=engine)
ensure_sqlite_schema()
with SessionLocal() as db:
    seed_data(db)

app.include_router(dashboard_router)
app.include_router(companies_router)
app.include_router(pipeline_entries_router)
app.include_router(fee_records_router)
app.include_router(contracts_router)
