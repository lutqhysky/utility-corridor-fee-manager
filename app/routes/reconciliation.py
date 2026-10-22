from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.paths import TEMPLATES_DIR
from app.services.reconciliation_service import get_reconciliation

router = APIRouter(prefix='/reconciliation')
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get('/', response_class=HTMLResponse)
def reconciliation_page(request: Request, db: Session = Depends(get_db)):
    data = get_reconciliation(db)
    return templates.TemplateResponse(request, 'reconciliation/list.html', {'data': data})
