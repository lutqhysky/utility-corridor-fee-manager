from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app import database
from app.routes import dashboard_router, companies_router, pipeline_entries_router, fee_records_router, contracts_router
from app import models  # noqa
from app.services.seed_service import seed_data

app = FastAPI(title='综合管廊有偿使用费管理系统')
app.mount('/static', StaticFiles(directory='app/static'), name='static')

database.Base.metadata.create_all(bind=database.engine)
schema_upgrade = getattr(database, 'ensure_sqlite_schema', None)
if callable(schema_upgrade):
    schema_upgrade()

with database.SessionLocal() as db:
    seed_data(db)

app.include_router(dashboard_router)
app.include_router(companies_router)
app.include_router(pipeline_entries_router)
app.include_router(fee_records_router)
app.include_router(contracts_router)
