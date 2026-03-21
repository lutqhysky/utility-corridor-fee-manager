from datetime import datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Company, Contract

router = APIRouter(prefix='/contracts', tags=['contracts'])
templates = Jinja2Templates(directory='app/templates')


def parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f'日期格式错误: {value}，正确格式应为 YYYY-MM-DD') from exc


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
        file_path=file_path,
        remark=remark,
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail='合同备案保存失败，请确认关联单位有效') from exc
    return RedirectResponse(url='/contracts/', status_code=303)
