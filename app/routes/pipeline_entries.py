from datetime import datetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Company, PipelineEntry, PipelineEntryDetail

router = APIRouter(prefix='/pipeline-entries', tags=['pipeline_entries'])
templates = Jinja2Templates(directory='app/templates')


def parse_date(value: str):
    return datetime.strptime(value, '%Y-%m-%d').date() if value else None


@router.get('/', response_class=HTMLResponse)
def list_entries(request: Request, db: Session = Depends(get_db), company_id: int | None = None):
    query = db.query(PipelineEntry)
    if company_id:
        query = query.filter(PipelineEntry.company_id == company_id)
    entries = query.order_by(PipelineEntry.id.desc()).all()
    companies = db.query(Company).order_by(Company.company_name).all()
    return templates.TemplateResponse(
        'pipeline_entries/list.html',
        {
            'request': request,
            'entries': entries,
            'companies': companies,
            'selected_company_id': company_id,
            'title': '入廊管线清单'
        }
    )


@router.get('/new', response_class=HTMLResponse)
def new_entry(request: Request, db: Session = Depends(get_db)):
    companies = db.query(Company).order_by(Company.company_name).all()
    return templates.TemplateResponse(
        'pipeline_entries/form.html',
        {
            'request': request,
            'entry': None,
            'companies': companies,
            'title': '新增入廊记录'
        }
    )


@router.post('/new')
def create_entry(
    company_id: int = Form(...),
    cabin_type: str = Form(''),
    project_name: str = Form(''),
    pipeline_type: str = Form(''),
    specification: str = Form(''),
    actual_length: float = Form(0),
    quantity_or_hole_count: float = Form(0),
    entry_date: str = Form(''),
    contract_sign_date_entry: str = Form(''),
    contract_sign_date_maintenance: str = Form(''),
    has_entry_application: str = Form(''),
    remark: str = Form(''),
    entry_fee_tax_rate: float = Form(0),
    maintenance_fee_tax_rate: float = Form(0),
    entry_fee_discount: float = Form(1),
    maintenance_fee_discount: float = Form(1),
    db: Session = Depends(get_db),
):
    db.add(PipelineEntry(
        company_id=company_id,
        cabin_type=cabin_type,
        project_name=project_name,
        pipeline_type=pipeline_type,
        specification=specification,
        actual_length=actual_length,
        quantity_or_hole_count=quantity_or_hole_count,
        entry_date=parse_date(entry_date),
        contract_sign_date_entry=parse_date(contract_sign_date_entry),
        contract_sign_date_maintenance=parse_date(contract_sign_date_maintenance),
        has_entry_application=has_entry_application,
        remark=remark,
        entry_fee_tax_rate=entry_fee_tax_rate,
        maintenance_fee_tax_rate=maintenance_fee_tax_rate,
        entry_fee_discount=entry_fee_discount,
        maintenance_fee_discount=maintenance_fee_discount,
    ))
    db.commit()
    return RedirectResponse(url='/pipeline-entries/', status_code=303)


@router.get('/{entry_id}', response_class=HTMLResponse)
def entry_detail(entry_id: int, request: Request, db: Session = Depends(get_db)):
    entry = db.query(PipelineEntry).filter(PipelineEntry.id == entry_id).first()
    if not entry:
        return RedirectResponse(url='/pipeline-entries/', status_code=303)

    entry_fee_excl_tax_total = sum((item.entry_amount_excl_tax or 0) for item in entry.details)
    maintenance_fee_excl_tax_total = sum((item.maintenance_amount_excl_tax or 0) for item in entry.details)

    entry_fee_tax_rate = entry.entry_fee_tax_rate or 0
    maintenance_fee_tax_rate = entry.maintenance_fee_tax_rate or 0

    entry_fee_discount = entry.entry_fee_discount or 1
    maintenance_fee_discount = entry.maintenance_fee_discount or 1

    entry_fee_tax_amount = entry_fee_excl_tax_total * entry_fee_tax_rate
    entry_fee_incl_tax_total = entry_fee_excl_tax_total + entry_fee_tax_amount
    entry_fee_actual_total = entry_fee_incl_tax_total * entry_fee_discount

    maintenance_fee_tax_amount = maintenance_fee_excl_tax_total * maintenance_fee_tax_rate
    maintenance_fee_incl_tax_total = maintenance_fee_excl_tax_total + maintenance_fee_tax_amount
    maintenance_fee_actual_total = maintenance_fee_incl_tax_total * maintenance_fee_discount

    return templates.TemplateResponse(
        'pipeline_entries/detail.html',
        {
            'request': request,
            'entry': entry,
            'entry_fee_excl_tax_total': entry_fee_excl_tax_total,
            'entry_fee_tax_rate': entry_fee_tax_rate,
            'entry_fee_tax_amount': entry_fee_tax_amount,
            'entry_fee_incl_tax_total': entry_fee_incl_tax_total,
            'entry_fee_discount': entry_fee_discount,
            'entry_fee_actual_total': entry_fee_actual_total,
            'maintenance_fee_excl_tax_total': maintenance_fee_excl_tax_total,
            'maintenance_fee_tax_rate': maintenance_fee_tax_rate,
            'maintenance_fee_tax_amount': maintenance_fee_tax_amount,
            'maintenance_fee_incl_tax_total': maintenance_fee_incl_tax_total,
            'maintenance_fee_discount': maintenance_fee_discount,
            'maintenance_fee_actual_total': maintenance_fee_actual_total,
            'title': f'项目详情 - {entry.project_name or ""}'
        }
    )


@router.get('/{entry_id}/edit', response_class=HTMLResponse)
def edit_entry(entry_id: int, request: Request, db: Session = Depends(get_db)):
    entry = db.query(PipelineEntry).filter(PipelineEntry.id == entry_id).first()
    if not entry:
        return RedirectResponse(url='/pipeline-entries/', status_code=303)

    companies = db.query(Company).order_by(Company.company_name).all()
    return templates.TemplateResponse(
        'pipeline_entries/form.html',
        {
            'request': request,
            'entry': entry,
            'companies': companies,
            'title': f'编辑项目 - {entry.project_name or ""}'
        }
    )


@router.post('/{entry_id}/edit')
def update_entry(
    entry_id: int,
    company_id: int = Form(...),
    cabin_type: str = Form(''),
    project_name: str = Form(''),
    pipeline_type: str = Form(''),
    specification: str = Form(''),
    actual_length: float = Form(0),
    quantity_or_hole_count: float = Form(0),
    entry_date: str = Form(''),
    contract_sign_date_entry: str = Form(''),
    contract_sign_date_maintenance: str = Form(''),
    has_entry_application: str = Form(''),
    remark: str = Form(''),
    entry_fee_tax_rate: float = Form(0),
    maintenance_fee_tax_rate: float = Form(0),
    entry_fee_discount: float = Form(1),
    maintenance_fee_discount: float = Form(1),
    db: Session = Depends(get_db),
):
    entry = db.query(PipelineEntry).filter(PipelineEntry.id == entry_id).first()
    if not entry:
        return RedirectResponse(url='/pipeline-entries/', status_code=303)

    entry.company_id = company_id
    entry.cabin_type = cabin_type
    entry.project_name = project_name
    entry.pipeline_type = pipeline_type
    entry.specification = specification
    entry.actual_length = actual_length
    entry.quantity_or_hole_count = quantity_or_hole_count
    entry.entry_date = parse_date(entry_date)
    entry.contract_sign_date_entry = parse_date(contract_sign_date_entry)
    entry.contract_sign_date_maintenance = parse_date(contract_sign_date_maintenance)
    entry.has_entry_application = has_entry_application
    entry.remark = remark
    entry.entry_fee_tax_rate = entry_fee_tax_rate
    entry.maintenance_fee_tax_rate = maintenance_fee_tax_rate
    entry.entry_fee_discount = entry_fee_discount
    entry.maintenance_fee_discount = maintenance_fee_discount

    db.commit()
    return RedirectResponse(url=f'/pipeline-entries/{entry_id}', status_code=303)


@router.get('/{entry_id}/details/new', response_class=HTMLResponse)
def new_detail(entry_id: int, request: Request, db: Session = Depends(get_db)):
    entry = db.query(PipelineEntry).filter(PipelineEntry.id == entry_id).first()
    if not entry:
        return RedirectResponse(url='/pipeline-entries/', status_code=303)

    return templates.TemplateResponse(
        'pipeline_entries/detail_form.html',
        {
            'request': request,
            'entry': entry,
            'detail': None,
            'title': f'新增收费明细 - {entry.project_name or ""}'
        }
    )


@router.post('/{entry_id}/details/new')
def create_detail(
    entry_id: int,
    pipeline_type: str = Form(''),
    specification: str = Form(''),
    engineering_quantity: float = Form(0),
    entry_unit_price_excl_tax: float = Form(0),
    entry_amount_excl_tax: float = Form(0),
    maintenance_unit_price_excl_tax: float = Form(0),
    maintenance_amount_excl_tax: float = Form(0),
    remark: str = Form(''),
    db: Session = Depends(get_db),
):
    entry = db.query(PipelineEntry).filter(PipelineEntry.id == entry_id).first()
    if not entry:
        return RedirectResponse(url='/pipeline-entries/', status_code=303)

    db.add(PipelineEntryDetail(
        pipeline_entry_id=entry_id,
        pipeline_type=pipeline_type,
        specification=specification,
        engineering_quantity=engineering_quantity,
        entry_unit_price_excl_tax=entry_unit_price_excl_tax,
        entry_amount_excl_tax=entry_amount_excl_tax,
        maintenance_unit_price_excl_tax=maintenance_unit_price_excl_tax,
        maintenance_amount_excl_tax=maintenance_amount_excl_tax,
        remark=remark,
    ))
    db.commit()
    return RedirectResponse(url=f'/pipeline-entries/{entry_id}', status_code=303)


@router.get('/details/{detail_id}/edit', response_class=HTMLResponse)
def edit_detail(detail_id: int, request: Request, db: Session = Depends(get_db)):
    detail = db.query(PipelineEntryDetail).filter(PipelineEntryDetail.id == detail_id).first()
    if not detail:
        return RedirectResponse(url='/pipeline-entries/', status_code=303)

    entry = db.query(PipelineEntry).filter(PipelineEntry.id == detail.pipeline_entry_id).first()
    if not entry:
        return RedirectResponse(url='/pipeline-entries/', status_code=303)

    return templates.TemplateResponse(
        'pipeline_entries/detail_form.html',
        {
            'request': request,
            'entry': entry,
            'detail': detail,
            'title': f'编辑收费明细 - {entry.project_name or ""}'
        }
    )


@router.post('/details/{detail_id}/edit')
def update_detail(
    detail_id: int,
    pipeline_type: str = Form(''),
    specification: str = Form(''),
    engineering_quantity: float = Form(0),
    entry_unit_price_excl_tax: float = Form(0),
    entry_amount_excl_tax: float = Form(0),
    maintenance_unit_price_excl_tax: float = Form(0),
    maintenance_amount_excl_tax: float = Form(0),
    remark: str = Form(''),
    db: Session = Depends(get_db),
):
    detail = db.query(PipelineEntryDetail).filter(PipelineEntryDetail.id == detail_id).first()
    if not detail:
        return RedirectResponse(url='/pipeline-entries/', status_code=303)

    detail.pipeline_type = pipeline_type
    detail.specification = specification
    detail.engineering_quantity = engineering_quantity
    detail.entry_unit_price_excl_tax = entry_unit_price_excl_tax
    detail.entry_amount_excl_tax = entry_amount_excl_tax
    detail.maintenance_unit_price_excl_tax = maintenance_unit_price_excl_tax
    detail.maintenance_amount_excl_tax = maintenance_amount_excl_tax
    detail.remark = remark

    db.commit()
    return RedirectResponse(url=f'/pipeline-entries/{detail.pipeline_entry_id}', status_code=303)


@router.post('/details/{detail_id}/delete')
def delete_detail(detail_id: int, db: Session = Depends(get_db)):
    detail = db.query(PipelineEntryDetail).filter(PipelineEntryDetail.id == detail_id).first()
    if not detail:
        return RedirectResponse(url='/pipeline-entries/', status_code=303)

    entry_id = detail.pipeline_entry_id
    db.delete(detail)
    db.commit()
    return RedirectResponse(url=f'/pipeline-entries/{entry_id}', status_code=303)
