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


def parse_float_or(value: str | None, default: float = 0.0) -> float:
    """数字框留空时用默认值，避免 422。"""
    if value is None:
        return default
    stripped = value.strip()
    if not stripped:
        return default
    try:
        return float(stripped)
    except (ValueError, TypeError):
        return default


def _model_to_dict(obj) -> dict:
    result = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        if hasattr(value, 'isoformat'):
            value = value.isoformat()
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            value = str(value)
        result[column.name] = value
    return result


def backup_period_data(period) -> str:
    """删除运营期前自动备份为 JSON。"""
    import json
    from datetime import datetime
    from app.database import DATABASE_PATH
    backup_dir = DATABASE_PATH.parent / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    data = {
        'backup_at': timestamp,
        'period': _model_to_dict(period),
        'details': [_model_to_dict(d) for d in period.details],
    }
    backup_path = backup_dir / f"subsidy_period_{period.id}_{timestamp}.json"
    backup_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(backup_path)


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
        .order_by(FeasibilitySubsidyPeriod.start_date.isnot(None).desc(),
                  FeasibilitySubsidyPeriod.start_date.asc(),
                  FeasibilitySubsidyPeriod.id.asc())
        .all()
    )

    running_received = 0.0
    running_receivable = 0.0
    for period in periods:
        running_receivable += period.current_receivable or 0
        actual_received = sum((item.amount or 0) for item in period.details)
        period.cumulative_receivable = running_receivable
        period.actual_received = actual_received
        running_received += actual_received
        period.cumulative_received = running_received
        period.arrears = (period.current_receivable or 0) - actual_received
        period.cumulative_arrears = running_receivable - running_received

    totals = {
        'receivable': sum(p.current_receivable or 0 for p in periods),
        'received': sum(p.actual_received or 0 for p in periods),
        'cumulative_received': running_received,
        'arrears': sum(p.arrears or 0 for p in periods),
        'cumulative_arrears': running_receivable - running_received,
    }

    return templates.TemplateResponse(
        'feasibility_subsidy/list.html',
        {
            'request': request,
            'periods': periods,
            'totals': totals,
            'title': '可行性缺口补助',
        },
    )


@router.post('/new')
def create_period(
    operating_period: str = Form(''),
    start_date: str = Form(''),
    end_date: str = Form(''),
    current_receivable: str = Form(''),
    db: Session = Depends(get_db),
):
    amount = parse_float_or(current_receivable)
    if amount < 0:
        raise HTTPException(status_code=422, detail='当期应收金额不能为负数')
    db.add(
        FeasibilitySubsidyPeriod(
            operating_period=operating_period,
            start_date=parse_date(start_date),
            end_date=parse_date(end_date),
            current_receivable=amount,
        )
    )
    db.commit()
    return RedirectResponse(url='/feasibility-subsidy/', status_code=303)


@router.post('/{period_id}/delete')
def delete_period(period_id: int, confirm_name: str = Form(''), db: Session = Depends(get_db)):
    period = db.query(FeasibilitySubsidyPeriod).filter(FeasibilitySubsidyPeriod.id == period_id).first()
    if not period:
        return RedirectResponse(url='/feasibility-subsidy/', status_code=303)
    expected = (period.operating_period or '').strip()
    if not expected or (confirm_name or '').strip() != expected:
        raise HTTPException(status_code=422, detail='运营期名称确认不匹配，删除已取消')
    backup_period_data(period)
    db.delete(period)
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
            'title': f'编辑可行性缺口补助 - {period.operating_period}',
        },
    )


@router.post('/{period_id}/edit')
def update_period(
    period_id: int,
    operating_period: str = Form(''),
    start_date: str = Form(''),
    end_date: str = Form(''),
    current_receivable: str = Form(''),
    db: Session = Depends(get_db),
):
    period = db.query(FeasibilitySubsidyPeriod).filter(FeasibilitySubsidyPeriod.id == period_id).first()
    if not period:
        return RedirectResponse(url='/feasibility-subsidy/', status_code=303)

    amount = parse_float_or(current_receivable)
    if amount < 0:
        raise HTTPException(status_code=422, detail='当期应收金额不能为负数')
    period.operating_period = operating_period
    period.start_date = parse_date(start_date)
    period.end_date = parse_date(end_date)
    period.current_receivable = amount
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
    arrears = (period.current_receivable or 0) - actual_received

    return templates.TemplateResponse(
        'feasibility_subsidy/detail.html',
        {
            'request': request,
            'period': period,
            'details': details,
            'actual_received': actual_received,
            'arrears': arrears,
            'title': f'可行性缺口补助明细 - {period.operating_period}',
        },
    )


@router.post('/{period_id}/details/new')
def create_detail(
    period_id: int,
    received_date: str = Form(''),
    amount: str = Form(''),
    remark: str = Form(''),
    db: Session = Depends(get_db),
):
    period = db.query(FeasibilitySubsidyPeriod).filter(FeasibilitySubsidyPeriod.id == period_id).first()
    if not period:
        return RedirectResponse(url='/feasibility-subsidy/', status_code=303)

    detail_amount = parse_float_or(amount)
    if detail_amount < 0:
        raise HTTPException(status_code=422, detail='收款金额不能为负数')
    db.add(
        FeasibilitySubsidyDetail(
            period_id=period_id,
            received_date=parse_date(received_date),
            amount=detail_amount,
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


@router.get('/{period_id}/details/{detail_id}/edit', response_class=HTMLResponse)
def edit_detail(period_id: int, detail_id: int, request: Request, db: Session = Depends(get_db)):
    period = db.query(FeasibilitySubsidyPeriod).filter(FeasibilitySubsidyPeriod.id == period_id).first()
    if not period:
        return RedirectResponse(url='/feasibility-subsidy/', status_code=303)

    detail = (
        db.query(FeasibilitySubsidyDetail)
        .filter(
            FeasibilitySubsidyDetail.id == detail_id,
            FeasibilitySubsidyDetail.period_id == period_id,
        )
        .first()
    )
    if not detail:
        return RedirectResponse(url=f'/feasibility-subsidy/{period_id}', status_code=303)

    return templates.TemplateResponse(
        'feasibility_subsidy/detail_form.html',
        {
            'request': request,
            'period': period,
            'detail': detail,
            'title': '编辑收款明细',
        },
    )


@router.post('/{period_id}/details/{detail_id}/edit')
def update_detail(
    period_id: int,
    detail_id: int,
    received_date: str = Form(''),
    amount: str = Form(''),
    remark: str = Form(''),
    db: Session = Depends(get_db),
):
    detail = (
        db.query(FeasibilitySubsidyDetail)
        .filter(
            FeasibilitySubsidyDetail.id == detail_id,
            FeasibilitySubsidyDetail.period_id == period_id,
        )
        .first()
    )
    if not detail:
        return RedirectResponse(url=f'/feasibility-subsidy/{period_id}', status_code=303)

    detail_amount = parse_float_or(amount)
    if detail_amount < 0:
        raise HTTPException(status_code=422, detail='收款金额不能为负数')
    detail.received_date = parse_date(received_date)
    detail.amount = detail_amount
    detail.remark = remark
    db.commit()
    return RedirectResponse(url=f'/feasibility-subsidy/{period_id}', status_code=303)
