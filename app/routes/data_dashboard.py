from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.paths import TEMPLATES_DIR
from app.services.data_dashboard_service import get_data_dashboard

router = APIRouter(prefix='/data-dashboard', tags=['data_dashboard'])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get('/', response_class=HTMLResponse)
def data_dashboard(request: Request, db: Session = Depends(get_db)):
    data = get_data_dashboard(db)
    return templates.TemplateResponse(
        'data_dashboard.html',
        {'request': request, 'data': data, 'title': '数据看板'},
    )
