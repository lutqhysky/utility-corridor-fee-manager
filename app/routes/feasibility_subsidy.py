from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import FeasibilitySubsidyDetail, FeasibilitySubsidyPeriod
from app.paths import TEMPLATES_DIR

router = APIRouter(prefix='/feasibility-subsidy', tags=['feasibility_subsidy'])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f'日期格式错误: {value}，正确格式应为 YYYY-MM-DD') from exc


@router.get('/', response_class=HTMLResponse)
def list_periods(request: Request, db: Session = Depends(get_db)):
    periods = (
        db.query(FeasibilitySubsidyPeriod)
        .options(joinedload(FeasibilitySubsidyPeriod.details))
        .order_by(FeasibilitySubsidyPeriod.start_date.asc(), FeasibilitySubsidyPeriod.id.asc())
        .all()
    )

    running_received = 0.0
    running_payable = 0.0
    for period in periods:
        actual_received = sum((item.amount or 0) for item in period.details)
        period.actual_received = actual_received
        running_payable += period.current_receivable or 0
        period.cumulative_payable = running_payable
        running_received += actual_received
        period.cumulative_received = running_received
        period.arrears = (period.current_receivable or 0) - actual_received
        period.cumulative_arrears = running_payable - running_received

    return templates.TemplateResponse(
        'feasibility_subsidy/list.html',
        {
            'request': request,
            'periods': periods,
            'title': '可行性缺口补助',
        },
    )


@router.post('/new')
def create_period(
    operating_period: str = Form(''),
    start_date: str = Form(''),
    end_date: str = Form(''),
    current_receivable: float = Form(0),
    db: Session = Depends(get_db),
):
    db.add(
        FeasibilitySubsidyPeriod(
            operating_period=operating_period,
            start_date=parse_date(start_date),
            end_date=parse_date(end_date),
            current_receivable=current_receivable,
        )
    )
    db.commit()
    return RedirectResponse(url='/feasibility-subsidy/', status_code=303)




@router.get('/{period_id}/edit', response_class=HTMLResponse)
def edit_period(period_id: int, request: Request, db: Session = Depends(get_db)):
    period = db.query(FeasibilitySubsidyPeriod).filter(FeasibilitySubsidyPeriod.id == period_id).first()
    if not period:
        return RedirectResponse(url='/feasibility-subsidy/', status_code=303)

    return templates.TemplateResponse(
        'feasibility_subsidy/form.html',
        {
            'request': request,
            'period': period,
            'title': f'修改运营期 - {period.operating_period}',
        },
    )


@router.post('/{period_id}/edit')
def update_period(
    period_id: int,
    operating_period: str = Form(''),
    start_date: str = Form(''),
    end_date: str = Form(''),
    current_receivable: float = Form(0),
    db: Session = Depends(get_db),
):
    period = db.query(FeasibilitySubsidyPeriod).filter(FeasibilitySubsidyPeriod.id == period_id).first()
    if not period:
        return RedirectResponse(url='/feasibility-subsidy/', status_code=303)

    period.operating_period = operating_period
    period.start_date = parse_date(start_date)
    period.end_date = parse_date(end_date)
    period.current_receivable = current_receivable

    db.commit()
    return RedirectResponse(url='/feasibility-subsidy/', status_code=303)

@router.post('/{period_id}/delete')
def delete_period(period_id: int, db: Session = Depends(get_db)):
    period = db.query(FeasibilitySubsidyPeriod).filter(FeasibilitySubsidyPeriod.id == period_id).first()
    if period:
        db.delete(period)
        db.commit()
    return RedirectResponse(url='/feasibility-subsidy/', status_code=303)


@router.get('/{period_id}', response_class=HTMLResponse)
def period_detail(period_id: int, request: Request, db: Session = Depends(get_db)):
    period = (
        db.query(FeasibilitySubsidyPeriod)
        .options(joinedload(FeasibilitySubsidyPeriod.details))
        .filter(FeasibilitySubsidyPeriod.id == period_id)
        .first()
    )
    if not period:
        return RedirectResponse(url='/feasibility-subsidy/', status_code=303)

    details = sorted(period.details, key=lambda item: (item.received_date is None, item.received_date, item.id))
    actual_received = sum((item.amount or 0) for item in details)

    return templates.TemplateResponse(
        'feasibility_subsidy/detail.html',
        {
            'request': request,
            'period': period,
            'details': details,
            'actual_received': actual_received,
            'title': f'可行性缺口补助明细 - {period.operating_period}',
        },
    )


@router.post('/{period_id}/details/new')
def create_detail(
    period_id: int,
    received_date: str = Form(''),
    amount: float = Form(0),
    remark: str = Form(''),
    db: Session = Depends(get_db),
):
    period = db.query(FeasibilitySubsidyPeriod).filter(FeasibilitySubsidyPeriod.id == period_id).first()
    if not period:
        return RedirectResponse(url='/feasibility-subsidy/', status_code=303)

    db.add(
        FeasibilitySubsidyDetail(
            period_id=period_id,
            received_date=parse_date(received_date),
            amount=amount,
            remark=remark,
        )
    )
    db.commit()
    return RedirectResponse(url=f'/feasibility-subsidy/{period_id}', status_code=303)


@router.post('/{period_id}/details/{detail_id}/delete')
def delete_detail(period_id: int, detail_id: int, db: Session = Depends(get_db)):
    detail = (
        db.query(FeasibilitySubsidyDetail)
        .filter(
            FeasibilitySubsidyDetail.id == detail_id,
            FeasibilitySubsidyDetail.period_id == period_id,
        )
        .first()
    )
    if detail:
        db.delete(detail)
        db.commit()
    return RedirectResponse(url=f'/feasibility-subsidy/{period_id}', status_code=303)
