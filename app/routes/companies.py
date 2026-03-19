from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Company

router = APIRouter(prefix='/companies', tags=['companies'])
templates = Jinja2Templates(directory='app/templates')


@router.get('/', response_class=HTMLResponse)
def list_companies(request: Request, db: Session = Depends(get_db), keyword: str = ''):
    query = db.query(Company)
    if keyword:
        query = query.filter(Company.company_name.contains(keyword) | Company.short_name.contains(keyword))
    companies = query.order_by(Company.id.desc()).all()
    return templates.TemplateResponse('companies/list.html', {'request': request, 'companies': companies, 'keyword': keyword, 'title': '单位管理'})


@router.get('/new', response_class=HTMLResponse)
def new_company(request: Request):
    return templates.TemplateResponse('companies/form.html', {'request': request, 'company': None, 'title': '新增单位'})


@router.post('/new')
def create_company(
    company_name: str = Form(...),
    short_name: str = Form(''),
    company_type: str = Form(''),
    contact_person: str = Form(''),
    contact_phone: str = Form(''),
    remark: str = Form(''),
    db: Session = Depends(get_db),
):
    db.add(Company(company_name=company_name, short_name=short_name, company_type=company_type, contact_person=contact_person, contact_phone=contact_phone, remark=remark))
    db.commit()
    return RedirectResponse(url='/companies/', status_code=303)


@router.get('/{company_id}', response_class=HTMLResponse)
def company_detail(company_id: int, request: Request, db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail='单位不存在')
    return templates.TemplateResponse('companies/detail.html', {'request': request, 'company': company, 'title': '单位详情'})
