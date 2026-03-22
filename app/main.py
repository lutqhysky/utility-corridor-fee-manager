from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app import database
from app.routes import dashboard_router, companies_router, pipeline_entries_router, fee_records_router, contracts_router
from app import models  # noqa
from app.services.reminder_service import fee_reminder_scheduler
from app.services.seed_service import seed_data


database.Base.metadata.create_all(bind=database.engine)
schema_upgrade = getattr(database, 'ensure_sqlite_schema', None)
if callable(schema_upgrade):
    schema_upgrade()

with database.SessionLocal() as db:
    seed_data(db)

app = create_app()
