from datetime import datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Company, Contract, PipelineEntry
from app.paths import TEMPLATES_DIR
from app.utils import safe_json_dumps
from sqlalchemy import func

router = APIRouter(prefix='/contracts', tags=['contracts'])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f'日期格式错误: {value}，正确格式应为 YYYY-MM-DD') from exc


def get_contract_or_404(db: Session, contract_id: int):
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail='合同备案不存在')
    return contract


@router.get('/', response_class=HTMLResponse)
def list_contracts(request: Request, db: Session = Depends(get_db), filing: str = '',
                   company_id: str = '', contract_type: str = ''):
    query = db.query(Contract)
    # filing=pending 表示“待办”：未签订、未备案或备案状态为空
    if filing == 'pending':
        query = query.filter(func.coalesce(Contract.filing_status, '') != '已备案')
    elif filing:
        query = query.filter(Contract.filing_status == filing)
    if company_id:
        try:
            query = query.filter(Contract.company_id == int(company_id))
        except ValueError:
            pass
    if contract_type:
        query = query.filter(Contract.contract_type == contract_type)
    contracts = query.order_by(Contract.id.desc()).all()


    companies = db.query(Company).order_by(Company.company_name).all()
    contract_types = [r[0] for r in db.query(Contract.contract_type)
                      .filter(Contract.contract_type.isnot(None))
                      .filter(Contract.contract_type != '')
                      .distinct().order_by(Contract.contract_type).all()]

    total_count = db.query(func.count(Contract.id)).scalar() or 0
    filed_count = db.query(func.count(Contract.id)).filter(Contract.filing_status == '已备案').scalar() or 0
    unsigned_count = db.query(func.count(Contract.id)).filter(Contract.filing_status == '未签订').scalar() or 0
    unfiled_count = db.query(func.count(Contract.id)).filter(Contract.filing_status == '未备案').scalar() or 0
    filing_count = db.query(func.count(Contract.id)).filter(Contract.filing_status == '正在备案').scalar() or 0
    pending_count = total_count - filed_count

    return templates.TemplateResponse(
        'contracts/list.html',
        {
            'request': request,
            'contracts': contracts,
            'selected_filing': filing,
            'companies': companies,
            'selected_company_id': company_id,
            'contract_type_options': contract_types,
            'selected_contract_type': contract_type,
            'total_count': total_count,
            'filed_count': filed_count,
            'unsigned_count': unsigned_count,
            'unfiled_count': unfiled_count,
            'filing_count': filing_count,
            'pending_count': pending_count,
            'title': '合同备案',
        },
    )


@router.get('/new', response_class=HTMLResponse)
def new_contract(request: Request, db: Session = Depends(get_db)):
    companies = db.query(Company).order_by(Company.company_name).all()
    pipeline_entries = db.query(PipelineEntry).filter(PipelineEntry.project_name.isnot(None)).filter(PipelineEntry.project_name != '').order_by(PipelineEntry.id.desc()).all()
    entries_json = safe_json_dumps([{
        'id': e.id,
        'company_id': e.company_id,
        'project_name': e.project_name or '',
        'company_name': (e.company.short_name or e.company.company_name) if e.company else '',
        'sign_date_entry': e.contract_sign_date_entry.isoformat() if e.contract_sign_date_entry else '',
        'sign_date_maintenance': e.contract_sign_date_maintenance.isoformat() if e.contract_sign_date_maintenance else '',
    } for e in pipeline_entries])
    return templates.TemplateResponse('contracts/form.html', {'request': request, 'companies': companies, 'pipeline_entries': pipeline_entries, 'entries_json': entries_json, 'title': '新增合同备案'})


@router.post('/new')
def create_contract(
    company_id: int = Form(...),
    contract_type: str = Form(''),
    contract_name: str = Form(...),
    filing_department: str = Form(''),
    filing_status: str = Form(''),
    sign_date: str = Form(''),
    remark: str = Form(''),
    pipeline_entry_id: str | None = Form(None),
    db: Session = Depends(get_db),
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail='单位不存在')

    db.add(Contract(
        company_id=company_id,
        contract_type=contract_type,
        contract_name=contract_name,
        filing_department=filing_department,
        filing_status=filing_status,
        sign_date=parse_date(sign_date),
        remark=remark,
        pipeline_entry_id=int(pipeline_entry_id) if pipeline_entry_id else None,
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail='合同备案保存失败，请确认关联单位有效') from exc
    return RedirectResponse(url='/contracts/', status_code=303)


@router.get('/{contract_id}/edit', response_class=HTMLResponse)
def edit_contract(contract_id: int, request: Request, db: Session = Depends(get_db)):
    contract = get_contract_or_404(db, contract_id)
    companies = db.query(Company).order_by(Company.company_name).all()
    pipeline_entries = db.query(PipelineEntry).filter(PipelineEntry.project_name.isnot(None)).filter(PipelineEntry.project_name != '').order_by(PipelineEntry.id.desc()).all()
    entries_json = safe_json_dumps([{
        'id': e.id,
        'company_id': e.company_id,
        'project_name': e.project_name or '',
        'company_name': (e.company.short_name or e.company.company_name) if e.company else '',
        'sign_date_entry': e.contract_sign_date_entry.isoformat() if e.contract_sign_date_entry else '',
        'sign_date_maintenance': e.contract_sign_date_maintenance.isoformat() if e.contract_sign_date_maintenance else '',
    } for e in pipeline_entries])
    return templates.TemplateResponse(
        'contracts/form.html',
        {
            'request': request,
            'contract': contract,
            'companies': companies,
            'pipeline_entries': pipeline_entries,
            'entries_json': entries_json,
            'title': '编辑合同备案',
        },
    )


@router.post('/{contract_id}/edit')
def update_contract(
    contract_id: int,
    company_id: int = Form(...),
    contract_type: str = Form(''),
    contract_name: str = Form(...),
    filing_department: str = Form(''),
    filing_status: str = Form(''),
    sign_date: str = Form(''),
    remark: str = Form(''),
    pipeline_entry_id: str | None = Form(None),
    db: Session = Depends(get_db),
):
    contract = get_contract_or_404(db, contract_id)
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail='单位不存在')

    contract.company_id = company_id
    contract.contract_type = contract_type
    contract.contract_name = contract_name
    contract.filing_department = filing_department
    contract.filing_status = filing_status
    contract.sign_date = parse_date(sign_date)
    contract.remark = remark
    contract.pipeline_entry_id = int(pipeline_entry_id) if pipeline_entry_id else None

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail='合同备案更新失败，请确认关联单位有效') from exc
    return RedirectResponse(url='/contracts/', status_code=303)


@router.post('/{contract_id}/delete')
def delete_contract(contract_id: int, db: Session = Depends(get_db)):
    contract = get_contract_or_404(db, contract_id)
    db.delete(contract)
    db.commit()
    return RedirectResponse(url='/contracts/', status_code=303)
