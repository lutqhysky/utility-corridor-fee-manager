from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Company

router = APIRouter(prefix='/companies', tags=['companies'])
templates = Jinja2Templates(directory='app/templates')


def get_company_or_404(db: Session, company_id: int):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail='单位不存在')
    return company


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
    existing_company = db.query(Company).filter(Company.company_name == company_name).first()
    if existing_company:
        raise HTTPException(status_code=422, detail='单位名称已存在，请勿重复创建')

    db.add(Company(company_name=company_name, short_name=short_name, company_type=company_type, contact_person=contact_person, contact_phone=contact_phone, remark=remark))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail='单位保存失败，请检查名称是否重复') from exc
    return RedirectResponse(url='/companies/', status_code=303)


@router.get('/{company_id}/edit', response_class=HTMLResponse)
def edit_company(company_id: int, request: Request, db: Session = Depends(get_db)):
    company = get_company_or_404(db, company_id)
    return templates.TemplateResponse('companies/form.html', {'request': request, 'company': company, 'title': '编辑单位'})


@router.post('/{company_id}/edit')
def update_company(
    company_id: int,
    company_name: str = Form(...),
    short_name: str = Form(''),
    company_type: str = Form(''),
    contact_person: str = Form(''),
    contact_phone: str = Form(''),
    remark: str = Form(''),
    db: Session = Depends(get_db),
):
    company = get_company_or_404(db, company_id)

    existing_company = (
        db.query(Company)
        .filter(Company.company_name == company_name, Company.id != company_id)
        .first()
    )
    if existing_company:
        raise HTTPException(status_code=422, detail='单位名称已存在，请使用其他名称')

    company.company_name = company_name
    company.short_name = short_name
    company.company_type = company_type
    company.contact_person = contact_person
    company.contact_phone = contact_phone
    company.remark = remark

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail='单位更新失败，请检查名称是否重复') from exc
    return RedirectResponse(url=f'/companies/{company_id}', status_code=303)


@router.get('/{company_id}', response_class=HTMLResponse)
def company_detail(company_id: int, request: Request, db: Session = Depends(get_db)):
    company = get_company_or_404(db, company_id)
    return templates.TemplateResponse('companies/detail.html', {'request': request, 'company': company, 'title': '单位详情'})


@router.post('/{company_id}/delete')
def delete_company(company_id: int, db: Session = Depends(get_db)):
    company = get_company_or_404(db, company_id)
    db.delete(company)
    db.commit()
    return RedirectResponse(url='/companies/', status_code=303)
