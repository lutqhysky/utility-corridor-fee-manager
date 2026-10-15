from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FeeStandard
from app.paths import TEMPLATES_DIR

router = APIRouter(prefix='/fee-standards', tags=['fee_standards'])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f'日期格式错误: {value}，正确格式应为 YYYY-MM-DD') from exc


def parse_optional_float(value: str | None):
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f'数字格式错误: {value}') from exc


def get_standard_or_404(db: Session, standard_id: int) -> FeeStandard:
    standard = db.query(FeeStandard).filter(FeeStandard.id == standard_id).first()
    if not standard:
        raise HTTPException(status_code=404, detail='收费标准不存在')
    return standard


@router.get('/', response_class=HTMLResponse)
def list_standards(
    request: Request,
    db: Session = Depends(get_db),
    keyword: str = '',
    active: str = '',
    fee_type: str = '',
    pipeline_type: str = '',
):
    query = db.query(FeeStandard)
    if keyword:
        like = f'%{keyword}%'
        query = query.filter(
            FeeStandard.fee_type.like(like)
            | FeeStandard.pipeline_type.like(like)
            | FeeStandard.specification.like(like)
        )
    if fee_type:
        query = query.filter(FeeStandard.fee_type == fee_type)
    if pipeline_type:
        query = query.filter(FeeStandard.pipeline_type == pipeline_type)
    if active == '1':
        query = query.filter(FeeStandard.is_active.is_(True))
    elif active == '0':
        query = query.filter(FeeStandard.is_active.is_not(True))
    standards = query.order_by(FeeStandard.id.desc()).all()
    active_count = db.query(func.count(FeeStandard.id)).filter(FeeStandard.is_active.is_(True)).scalar() or 0
    fee_type_options = [
        row[0] for row in db.query(FeeStandard.fee_type).distinct().order_by(FeeStandard.fee_type).all() if row[0]
    ]
    pipeline_type_options = [
        row[0] for row in db.query(FeeStandard.pipeline_type).distinct().order_by(FeeStandard.pipeline_type).all() if row[0]
    ]
    return templates.TemplateResponse(
        'fee_standards/list.html',
        {
            'request': request,
            'standards': standards,
            'keyword': keyword,
            'selected_active': active,
            'selected_fee_type': fee_type,
            'selected_pipeline_type': pipeline_type,
            'fee_type_options': fee_type_options,
            'pipeline_type_options': pipeline_type_options,
            'active_count': active_count,
            'title': '收费标准',
        },
    )


@router.get('/new', response_class=HTMLResponse)
def new_standard(request: Request):
    return templates.TemplateResponse(
        'fee_standards/form.html', {'request': request, 'standard': None, 'title': '新增收费标准'}
    )


@router.post('/new')
def create_standard(
    fee_type: str = Form(...),
    pipeline_type: str = Form(''),
    specification: str = Form(''),
    unit_price_excl_tax: str = Form(''),
    billing_unit: str = Form(''),
    tax_rate: str = Form(''),
    price_period: str = Form(''),
    is_active: str = Form(''),
    effective_date: str = Form(''),
    remark: str = Form(''),
    db: Session = Depends(get_db),
):
    if not fee_type.strip():
        raise HTTPException(status_code=422, detail='费用类型不能为空')
    db.add(FeeStandard(
        fee_type=fee_type.strip(),
        pipeline_type=pipeline_type.strip(),
        specification=specification.strip(),
        unit_price_excl_tax=parse_optional_float(unit_price_excl_tax),
        billing_unit=billing_unit.strip(),
        tax_rate=parse_optional_float(tax_rate),
        price_period=price_period.strip(),
        is_active=bool(is_active),
        effective_date=parse_date(effective_date),
        remark=remark.strip(),
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail='已存在相同的收费标准（费用类型+管线类型+规格重复）') from exc
    return RedirectResponse(url='/fee-standards/', status_code=303)


@router.get('/{standard_id}/edit', response_class=HTMLResponse)
def edit_standard(standard_id: int, request: Request, db: Session = Depends(get_db)):
    standard = get_standard_or_404(db, standard_id)
    return templates.TemplateResponse(
        'fee_standards/form.html',
        {'request': request, 'standard': standard, 'title': '编辑收费标准'},
    )


@router.post('/{standard_id}/edit')
def update_standard(
    standard_id: int,
    fee_type: str = Form(...),
    pipeline_type: str = Form(''),
    specification: str = Form(''),
    unit_price_excl_tax: str = Form(''),
    billing_unit: str = Form(''),
    tax_rate: str = Form(''),
    price_period: str = Form(''),
    is_active: str = Form(''),
    effective_date: str = Form(''),
    remark: str = Form(''),
    db: Session = Depends(get_db),
):
    standard = get_standard_or_404(db, standard_id)
    if not fee_type.strip():
        raise HTTPException(status_code=422, detail='费用类型不能为空')
    standard.fee_type = fee_type.strip()
    standard.pipeline_type = pipeline_type.strip()
    standard.specification = specification.strip()
    standard.unit_price_excl_tax = parse_optional_float(unit_price_excl_tax)
    standard.billing_unit = billing_unit.strip()
    standard.tax_rate = parse_optional_float(tax_rate)
    standard.price_period = price_period.strip()
    standard.is_active = bool(is_active)
    standard.effective_date = parse_date(effective_date)
    standard.remark = remark.strip()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail='已存在相同的收费标准（费用类型+管线类型+规格重复）') from exc
    return RedirectResponse(url='/fee-standards/', status_code=303)


@router.post('/{standard_id}/delete')
def delete_standard(standard_id: int, db: Session = Depends(get_db)):
    standard = get_standard_or_404(db, standard_id)
    db.delete(standard)
    db.commit()
    return RedirectResponse(url='/fee-standards/', status_code=303)
