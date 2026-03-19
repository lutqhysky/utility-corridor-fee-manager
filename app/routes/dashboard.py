from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.statistics_service import StatisticsService
from app.models import FeeRecord

router = APIRouter()
templates = Jinja2Templates(directory='app/templates')


@router.get('/', response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    stats = StatisticsService.dashboard(db)
    latest_records = db.query(FeeRecord).order_by(FeeRecord.created_at.desc()).limit(8).all()
    return templates.TemplateResponse(
        'dashboard.html',
        {'request': request, 'stats': stats, 'latest_records': latest_records, 'title': '首页概览'},
    )
