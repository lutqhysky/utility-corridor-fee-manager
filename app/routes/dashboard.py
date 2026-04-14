import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.services.statistics_service import StatisticsService
from app.models import FeeRecord
from app.paths import TEMPLATES_DIR

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
logger = logging.getLogger(__name__)


@router.get('/', response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    try:
        stats = StatisticsService.dashboard(db)
        latest_records = (
            db.query(FeeRecord)
            .options(joinedload(FeeRecord.company), joinedload(FeeRecord.pipeline_entry))
            .order_by(FeeRecord.created_at.desc())
            .limit(8)
            .all()
        )
        for record in latest_records:
            record.dashboard_project_name = (
                record.project_name
                or (record.pipeline_entry.project_name if record.pipeline_entry else '')
            )
    except Exception:
        logger.exception('Dashboard data query failed, fallback to empty values.')
        stats = {
            'company_count': 0,
            'pipeline_count': 0,
            'fee_record_count': 0,
            'total_receivable': 0,
            'total_received': 0,
            'total_unreceived': 0,
            'overdue_amount': 0,
        }
        latest_records = []
    context = {'request': request, 'stats': stats, 'latest_records': latest_records, 'title': '首页概览'}

    try:
        return templates.TemplateResponse('dashboard.html', context)
    except Exception:
        logger.exception('Dashboard template rendering failed, fallback to minimal page.')
        return HTMLResponse(
            '<h1>首页概览</h1><p>页面模板加载失败，请联系管理员检查部署文件是否完整。</p>',
            status_code=200,
        )
