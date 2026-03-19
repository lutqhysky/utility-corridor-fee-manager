from datetime import datetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Company, PipelineEntry

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
    return templates.TemplateResponse('pipeline_entries/list.html', {'request': request, 'entries': entries, 'companies': companies, 'selected_company_id': company_id, 'title': '入廊管线清单'})


@router.get('/new', response_class=HTMLResponse)
def new_entry(request: Request, db: Session = Depends(get_db)):
    companies = db.query(Company).order_by(Company.company_name).all()
    return templates.TemplateResponse('pipeline_entries/form.html', {'request': request, 'entry': None, 'companies': companies, 'title': '新增入廊记录'})


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
    ))
    db.commit()
    return RedirectResponse(url='/pipeline-entries/', status_code=303)
