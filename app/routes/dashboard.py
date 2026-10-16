import json
import logging
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.utils import safe_json_dumps
from app.services.statistics_service import StatisticsService
from app.models import Company, FeeRecord
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
        # 待收费用提醒：按实际未收余额统计（与收费汇总/提醒服务口径一致）
        # 不再按状态过滤：已全额收清但状态未改的不计入，部分收缴只计剩余
        outstanding = FeeRecord.amount_incl_tax - func.coalesce(FeeRecord.actual_received_amount, 0)
        pending_rows = (
            db.query(
                Company.id.label('company_id'),
                Company.short_name,
                Company.company_name,
                func.count(FeeRecord.id).label('record_count'),
                func.sum(outstanding).label('total_amount'),
                func.min(FeeRecord.planned_receivable_date).label('nearest_date'),
            )
            .join(FeeRecord, FeeRecord.company_id == Company.id)
            .filter(outstanding > 0)
            .group_by(Company.id, Company.short_name, Company.company_name)
            .all()
        )
        pending_summary = [
            {
                'company_id': row.company_id,
                'company_name': (row.short_name or row.company_name or ''),
                'record_count': row.record_count or 0,
                'total_amount': float(row.total_amount or 0),
                'nearest_date': row.nearest_date,
            }
            for row in pending_rows
        ]
        pending_summary.sort(key=lambda r: (r['nearest_date'] is None, r['nearest_date'] or ''))
        pending_total = sum(r['total_amount'] for r in pending_summary)
        # 待收明细：点击单位名弹窗展示，按紧急程度排序（逾期 > 临期7天内 > 正常 > 无日期）
        today = date.today()
        pending_detail_rows = (
            db.query(FeeRecord)
            .options(joinedload(FeeRecord.pipeline_entry))
            .filter(outstanding > 0)
            .all()
        )
        pending_details: dict[int, list] = {}
        for record in pending_detail_rows:
            due = record.planned_receivable_date
            overdue_days = (today - due).days if due and due < today else 0
            due_in_days = (due - today).days if due and due >= today else -1
            is_overdue = overdue_days > 0
            is_due_soon = 0 <= due_in_days <= 7
            if is_overdue:
                urgency = 0
            elif is_due_soon:
                urgency = 1
            elif due:
                urgency = 2
            else:
                urgency = 3
            pending_details.setdefault(record.company_id, []).append(
                {
                    'record_id': record.id,
                    'project_name': record.project_name
                    or (record.pipeline_entry.project_name if record.pipeline_entry else ''),
                    'fee_type': record.fee_type or '',
                    'charge_period': record.charge_period or '',
                    'amount_incl_tax': float(record.amount_incl_tax or 0),
                    'actual_received_amount': float(record.actual_received_amount or 0),
                    'planned_receivable_date': str(due) if due else '',
                    'payment_status': record.payment_status or '',
                    'urgency': urgency,
                    'is_overdue': is_overdue,
                    'overdue_days': overdue_days,
                    'is_due_soon': is_due_soon,
                    'due_in_days': due_in_days,
                }
            )
        for records in pending_details.values():
            records.sort(key=lambda r: (r['urgency'], r['planned_receivable_date'] or '9999'))
        pending_details_json = safe_json_dumps(pending_details)
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
            'overdue_count': 0,
            'pending_contract_count': 0,
        }
        latest_records = []
        pending_summary = []
        pending_total = 0
        pending_details_json = '{}'
    context = {
        'request': request,
        'stats': stats,
        'latest_records': latest_records,
        'pending_summary': pending_summary,
        'pending_total': pending_total,
        'pending_details_json': pending_details_json,
        'title': '首页概览',
    }

    try:
        return templates.TemplateResponse('dashboard.html', context)
    except Exception:
        logger.exception('Dashboard template rendering failed, fallback to minimal page.')
        return HTMLResponse(
            '<h1>首页概览</h1><p>页面模板加载失败，请联系管理员检查部署文件是否完整。</p>',
            status_code=200,
        )
