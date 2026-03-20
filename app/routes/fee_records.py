from datetime import datetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Company, FeeRecord, PipelineEntry
from app.services.fee_calc_service import calc_tax

router = APIRouter(prefix='/fee-records', tags=['fee_records'])
templates = Jinja2Templates(directory='app/templates')


def parse_date(value: str):
    return datetime.strptime(value, '%Y-%m-%d').date() if value else None


@router.get('/', response_class=HTMLResponse)
def list_records(request: Request, db: Session = Depends(get_db), company_id: int | None = None, status: str = ''):
    query = db.query(FeeRecord)
    if company_id:
        query = query.filter(FeeRecord.company_id == company_id)
    if status:
        query = query.filter(FeeRecord.payment_status == status)

    records = query.order_by(FeeRecord.planned_receivable_date.desc()).all()
    companies = db.query(Company).order_by(Company.company_name).all()

    return templates.TemplateResponse(
        'fee_records/list.html',
        {
            'request': request,
            'records': records,
            'companies': companies,
            'selected_company_id': company_id,
            'selected_status': status,
            'title': '收费记录'
        }
    )


@router.get('/new', response_class=HTMLResponse)
def new_record(request: Request, db: Session = Depends(get_db)):
    companies = db.query(Company).order_by(Company.company_name).all()
    pipeline_entries = db.query(PipelineEntry).order_by(PipelineEntry.id.desc()).all()
    statuses = ['未开始', '待收缴', '部分收缴', '已收缴', '已逾期']

    return templates.TemplateResponse(
        'fee_records/form.html',
        {
            'request': request,
            'record': None,
            'companies': companies,
            'pipeline_entries': pipeline_entries,
            'statuses': statuses,
            'title': '新增收费记录'
        }
    )


@router.post('/new')
def create_record(
    company_id: int = Form(...),
    pipeline_entry_id: int | None = Form(None),
    fee_type: str = Form(...),
    charge_period: str = Form(''),
    period_year: int | None = Form(None),
    period_quarter: int | None = Form(None),
    amount_excl_tax: float = Form(0),
    tax_rate: float = Form(0),
    planned_receivable_date: str = Form(''),
    remind_date: str = Form(''),
    latest_payment_date: str = Form(''),
    actual_received_amount: float = Form(0),
    actual_received_date: str = Form(''),
    payment_status: str = Form('待收缴'),
    is_invoiced: str = Form('否'),
    remark: str = Form(''),
    db: Session = Depends(get_db),
):
    tax_amount, amount_incl_tax = calc_tax(amount_excl_tax, tax_rate)

    db.add(FeeRecord(
        company_id=company_id,
        pipeline_entry_id=pipeline_entry_id,
        fee_type=fee_type,
        charge_period=charge_period,
        period_year=period_year,
        period_quarter=period_quarter,
        amount_excl_tax=amount_excl_tax,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        amount_incl_tax=amount_incl_tax,
        planned_receivable_date=parse_date(planned_receivable_date),
        remind_date=parse_date(remind_date),
        latest_payment_date=parse_date(latest_payment_date),
        actual_received_amount=actual_received_amount,
        actual_received_date=parse_date(actual_received_date),
        payment_status=payment_status,
        is_invoiced=is_invoiced,
        remark=remark,
    ))
    db.commit()
    return RedirectResponse(url='/fee-records/', status_code=303)


@router.get('/{record_id}/edit', response_class=HTMLResponse)
def edit_record(record_id: int, request: Request, db: Session = Depends(get_db)):
    record = db.query(FeeRecord).filter(FeeRecord.id == record_id).first()
    if not record:
        return RedirectResponse(url='/fee-records/', status_code=303)

    companies = db.query(Company).order_by(Company.company_name).all()
    pipeline_entries = db.query(PipelineEntry).order_by(PipelineEntry.id.desc()).all()
    statuses = ['未开始', '待收缴', '部分收缴', '已收缴', '已逾期']

    return templates.TemplateResponse(
        'fee_records/form.html',
        {
            'request': request,
            'record': record,
            'companies': companies,
            'pipeline_entries': pipeline_entries,
            'statuses': statuses,
            'title': '编辑收费记录'
        }
    )


@router.post('/{record_id}/edit')
def update_record(
    record_id: int,
    company_id: int = Form(...),
    pipeline_entry_id: int | None = Form(None),
    fee_type: str = Form(...),
    charge_period: str = Form(''),
    period_year: int | None = Form(None),
    period_quarter: int | None = Form(None),
    amount_excl_tax: float = Form(0),
    tax_rate: float = Form(0),
    planned_receivable_date: str = Form(''),
    remind_date: str = Form(''),
    latest_payment_date: str = Form(''),
    actual_received_amount: float = Form(0),
    actual_received_date: str = Form(''),
    payment_status: str = Form('待收缴'),
    is_invoiced: str = Form('否'),
    remark: str = Form(''),
    db: Session = Depends(get_db),
):
    record = db.query(FeeRecord).filter(FeeRecord.id == record_id).first()
    if not record:
        return RedirectResponse(url='/fee-records/', status_code=303)

    tax_amount, amount_incl_tax = calc_tax(amount_excl_tax, tax_rate)

    record.company_id = company_id
    record.pipeline_entry_id = pipeline_entry_id
    record.fee_type = fee_type
    record.charge_period = charge_period
    record.period_year = period_year
    record.period_quarter = period_quarter
    record.amount_excl_tax = amount_excl_tax
    record.tax_rate = tax_rate
    record.tax_amount = tax_amount
    record.amount_incl_tax = amount_incl_tax
    record.planned_receivable_date = parse_date(planned_receivable_date)
    record.remind_date = parse_date(remind_date)
    record.latest_payment_date = parse_date(latest_payment_date)
    record.actual_received_amount = actual_received_amount
    record.actual_received_date = parse_date(actual_received_date)
    record.payment_status = payment_status
    record.is_invoiced = is_invoiced
    record.remark = remark

    db.commit()
    return RedirectResponse(url='/fee-records/', status_code=303)


@router.post('/{record_id}/delete')
def delete_record(record_id: int, db: Session = Depends(get_db)):
    record = db.query(FeeRecord).filter(FeeRecord.id == record_id).first()
    if not record:
        return RedirectResponse(url='/fee-records/', status_code=303)

    db.delete(record)
    db.commit()
    return RedirectResponse(url='/fee-records/', status_code=303)
