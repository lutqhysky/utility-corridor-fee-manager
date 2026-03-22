from datetime import datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from urllib.parse import quote
from app.database import get_db
from app.models import Company, FeeRecord, PipelineEntry
from app.services.fee_calc_service import calc_tax
from app.services.reminder_service import SUPPORTED_CHANNELS, get_reminder_settings, run_fee_reminders, save_reminder_settings

router = APIRouter(prefix='/fee-records', tags=['fee_records'])
templates = Jinja2Templates(directory='app/templates')


def parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f'日期格式错误: {value}，正确格式应为 YYYY-MM-DD') from exc


def validate_record_relations(db: Session, company_id: int, pipeline_entry_id: int | None):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail='单位不存在')

    if pipeline_entry_id is None:
        return

    pipeline_entry = db.query(PipelineEntry).filter(PipelineEntry.id == pipeline_entry_id).first()
    if not pipeline_entry:
        raise HTTPException(status_code=404, detail='入廊记录不存在')
    if pipeline_entry.company_id != company_id:
        raise HTTPException(status_code=422, detail='收费记录关联的入廊记录与所选单位不一致')


@router.get('/', response_class=HTMLResponse)
def list_records(
    request: Request,
    db: Session = Depends(get_db),
    company_id: int | None = None,
    status: str = '',
    notice: str = '',
):
    query = db.query(FeeRecord)
    if company_id:
        query = query.filter(FeeRecord.company_id == company_id)
    if status:
        query = query.filter(FeeRecord.payment_status == status)

    records = query.order_by(FeeRecord.planned_receivable_date.desc()).all()
    companies = db.query(Company).order_by(Company.company_name).all()
    reminder_settings = get_reminder_settings(db)

    return templates.TemplateResponse(
        'fee_records/list.html',
        {
            'request': request,
            'records': records,
            'companies': companies,
            'selected_company_id': company_id,
            'selected_status': status,
            'notice': notice,
            'reminder_settings': reminder_settings,
            'title': '收费记录'
        }
    )


@router.post('/reminders/run')
def run_reminders(db: Session = Depends(get_db)):
    result = run_fee_reminders(db)
    return RedirectResponse(url=f'/fee-records/?notice={quote(result.message)}', status_code=303)


@router.post('/reminders/settings')
def update_reminder_settings(
    channel: str = Form(''),
    webhook_url: str = Form(''),
    days_ahead: int = Form(3),
    check_interval_seconds: int = Form(300),
    db: Session = Depends(get_db),
):
    channel = channel.strip().lower()
    if channel and channel not in SUPPORTED_CHANNELS:
        raise HTTPException(status_code=422, detail='提醒渠道只支持 dingtalk 或 wecom')

    save_reminder_settings(
        db=db,
        channel=channel,
        webhook_url=webhook_url,
        days_ahead=days_ahead,
        check_interval_seconds=check_interval_seconds,
    )
    return RedirectResponse(url=f'/fee-records/?notice={quote("提醒配置已保存")}', status_code=303)


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
    validate_record_relations(db, company_id, pipeline_entry_id)
    tax_amount, amount_incl_tax = calc_tax(amount_excl_tax, tax_rate)

    db.add(
        FeeRecord(
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
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail='收费记录保存失败，请确认关联数据有效') from exc
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

    validate_record_relations(db, company_id, pipeline_entry_id)
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

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail='收费记录更新失败，请确认关联数据有效') from exc
    return RedirectResponse(url='/fee-records/', status_code=303)


@router.post('/{record_id}/delete')
def delete_record(record_id: int, db: Session = Depends(get_db)):
    record = db.query(FeeRecord).filter(FeeRecord.id == record_id).first()
    if not record:
        return RedirectResponse(url='/fee-records/', status_code=303)

    db.delete(record)
    db.commit()
    return RedirectResponse(url='/fee-records/', status_code=303)
