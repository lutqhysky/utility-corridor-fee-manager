from datetime import datetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Company, Contract

router = APIRouter(prefix='/contracts', tags=['contracts'])
templates = Jinja2Templates(directory='app/templates')


def parse_date(value: str):
    return datetime.strptime(value, '%Y-%m-%d').date() if value else None


@router.get('/', response_class=HTMLResponse)
def list_contracts(request: Request, db: Session = Depends(get_db)):
    contracts = db.query(Contract).order_by(Contract.id.desc()).all()
    return templates.TemplateResponse('contracts/list.html', {'request': request, 'contracts': contracts, 'title': '合同备案'})


@router.get('/new', response_class=HTMLResponse)
def new_contract(request: Request, db: Session = Depends(get_db)):
    companies = db.query(Company).order_by(Company.company_name).all()
    return templates.TemplateResponse('contracts/form.html', {'request': request, 'companies': companies, 'title': '新增合同备案'})


@router.post('/new')
def create_contract(
    company_id: int = Form(...),
    contract_type: str = Form(''),
    contract_name: str = Form(...),
    filing_department: str = Form(''),
    filing_status: str = Form(''),
    sign_date: str = Form(''),
    file_path: str = Form(''),
    remark: str = Form(''),
    db: Session = Depends(get_db),
):
    db.add(Contract(
        company_id=company_id,
        contract_type=contract_type,
        contract_name=contract_name,
        filing_department=filing_department,
        filing_status=filing_status,
        sign_date=parse_date(sign_date),
        file_path=file_path,
        remark=remark,
    ))
    db.commit()
    return RedirectResponse(url='/contracts/', status_code=303)
