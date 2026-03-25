from fastapi import APIRouter
from sqlalchemy import text

from app.database import SessionLocal

router = APIRouter(tags=['health'])


def _check_database() -> bool:
    db = SessionLocal()
    try:
        db.execute(text('SELECT 1'))
        return True
    except Exception:
        return False
    finally:
        db.close()


@router.get('/healthz')
@router.get('/health')
def healthcheck():
    return {'status': 'ok', 'database': 'ok' if _check_database() else 'error'}
