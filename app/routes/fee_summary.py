from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, FeeRecord

router = APIRouter(prefix='/fee-summary', tags=['fee_summary'])
templates = Jinja2Templates(directory='app/templates')


@router.get('/', response_class=HTMLResponse)
def fee_summary(request: Request, db: Session = Depends(get_db), year: int | None = None):
    base_query = (
        db.query(
            extract('year', FeeRecord.actual_received_date).label('year'),
            Company.id.label('company_id'),
            Company.company_name.label('company_name'),
            Company.short_name.label('short_name'),
            func.count(FeeRecord.id).label('record_count'),
            func.coalesce(func.sum(FeeRecord.actual_received_amount), 0).label('total_received'),
        )
        .join(Company, Company.id == FeeRecord.company_id)
        .filter(FeeRecord.actual_received_date.isnot(None))
        .filter(FeeRecord.actual_received_amount.isnot(None))
        .filter(FeeRecord.actual_received_amount > 0)
    )

    if year:
        base_query = base_query.filter(extract('year', FeeRecord.actual_received_date) == year)

    summary_rows = (
        base_query.group_by(
            extract('year', FeeRecord.actual_received_date),
            Company.id,
            Company.company_name,
            Company.short_name,
        )
        .order_by(
            extract('year', FeeRecord.actual_received_date).desc(),
            func.sum(FeeRecord.actual_received_amount).desc(),
        )
        .all()
    )

    years = [
        int(item[0])
        for item in (
            db.query(extract('year', FeeRecord.actual_received_date))
            .filter(FeeRecord.actual_received_date.isnot(None))
            .filter(FeeRecord.actual_received_amount.isnot(None))
            .filter(FeeRecord.actual_received_amount > 0)
            .distinct()
            .order_by(extract('year', FeeRecord.actual_received_date).desc())
            .all()
        )
    ]

    total_received = sum(float(row.total_received or 0) for row in summary_rows)
    company_count = len({row.company_id for row in summary_rows})

    return templates.TemplateResponse(
        'fee_summary/list.html',
        {
            'request': request,
            'summary_rows': summary_rows,
            'years': years,
            'selected_year': year,
            'total_received': total_received,
            'company_count': company_count,
            'title': '收费汇总',
        },
    )
