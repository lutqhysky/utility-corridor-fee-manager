import json
from datetime import datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from urllib.parse import quote
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
# 核心修改 1：引入 selectinload 用于预加载关联数据
from sqlalchemy.orm import Session, selectinload
from app.database import get_db
from app.models import Company, FeeRecord
from app.paths import TEMPLATES_DIR

router = APIRouter(prefix='/companies', tags=['companies'])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_company_or_404(db: Session, company_id: int):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail='单位不存在')
    return company


@router.get('/', response_class=HTMLResponse)
def list_companies(request: Request, db: Session = Depends(get_db), keyword: str = '', sort: str = ''):
    query = db.query(Company)
    if keyword:
        query = query.filter(Company.company_name.contains(keyword) | Company.short_name.contains(keyword))
    sort_order = sort if sort in ('id_asc', 'id_desc') else 'id_asc'
    if sort_order == 'id_asc':
        companies = query.order_by(Company.id.asc()).all()
    else:
        companies = query.order_by(Company.id.desc()).all()

    received_amount_rows = (
        db.query(
            FeeRecord.company_id,
            func.coalesce(func.sum(FeeRecord.actual_received_amount), 0).label('total_received_amount')
        )
        .group_by(FeeRecord.company_id)
        .all()
    )
    received_amount_map = {row.company_id: row.total_received_amount for row in received_amount_rows}
    for company in companies:
        company.total_received_amount = received_amount_map.get(company.id, 0)

    return templates.TemplateResponse('companies/list.html', {'request': request, 'companies': companies, 'keyword': keyword, 'sort_order': sort_order, 'title': '单位管理'})


@router.get('/new', response_class=HTMLResponse)
def new_company(request: Request):
    return templates.TemplateResponse('companies/form.html', {'request': request, 'company': None, 'title': '新增单位'})


@router.post('/new')
def create_company(
    company_name: str = Form(...),
    short_name: str = Form(''),
    company_type: str = Form(''),
    construction_contact_person: str = Form(''),
    construction_contact_phone: str = Form(''),
    maintenance_contact_person: str = Form(''),
    maintenance_contact_phone: str = Form(''),
    remark: str = Form(''),
    db: Session = Depends(get_db),
):
    existing_company = db.query(Company).filter(Company.company_name == company_name).first()
    if existing_company:
        raise HTTPException(status_code=422, detail='单位名称已存在，请勿重复创建')

    db.add(Company(company_name=company_name, short_name=short_name, company_type=company_type,
                   construction_contact_person=construction_contact_person,
                   construction_contact_phone=construction_contact_phone,
                   maintenance_contact_person=maintenance_contact_person,
                   maintenance_contact_phone=maintenance_contact_phone,
                   remark=remark))
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
    construction_contact_person: str = Form(''),
    construction_contact_phone: str = Form(''),
    maintenance_contact_person: str = Form(''),
    maintenance_contact_phone: str = Form(''),
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
    company.construction_contact_person = construction_contact_person
    company.construction_contact_phone = construction_contact_phone
    company.maintenance_contact_person = maintenance_contact_person
    company.maintenance_contact_phone = maintenance_contact_phone
    company.remark = remark

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail='单位更新失败，请检查名称是否重复') from exc
    return RedirectResponse(url=f'/companies/{company_id}', status_code=303)


@router.get('/{company_id}', response_class=HTMLResponse)
def company_detail(company_id: int, request: Request, db: Session = Depends(get_db)):
    # 核心修改 2：使用 selectinload 提前加载该单位的 入廊记录、收费记录、合同 数据。
    # 这样在渲染模板的 for 循环时，就不会再向数据库发送额外的查询请求（解决 N+1 导致页面卡顿的问题）。
    company = (
        db.query(Company)
        .options(
            selectinload(Company.pipeline_entries),
            selectinload(Company.fee_records),
            selectinload(Company.contracts)
        )
        .filter(Company.id == company_id)
        .first()
    )
    
    if not company:
        raise HTTPException(status_code=404, detail='单位不存在')
        
    return templates.TemplateResponse('companies/detail.html', {'request': request, 'company': company, 'title': '单位详情'})


def _model_to_dict(obj) -> dict:
    """SQLAlchemy 对象转可 JSON 序列化的 dict。"""
    result = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        if hasattr(value, 'isoformat'):
            value = value.isoformat()
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            value = str(value)
        result[column.name] = value
    return result


def backup_company_data(db: Session, company) -> str:
    """删除单位前自动备份其全部关联数据为 JSON，返回备份文件路径。"""
    from app.database import DATABASE_PATH
    backup_dir = DATABASE_PATH.parent / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    data = {
        'backup_at': timestamp,
        'company': _model_to_dict(company),
        'pipeline_entries': [],
        'fee_records': [_model_to_dict(r) for r in company.fee_records],
        'contracts': [_model_to_dict(c) for c in company.contracts],
    }
    for entry in company.pipeline_entries:
        entry_dict = _model_to_dict(entry)
        entry_dict['details'] = [_model_to_dict(d) for d in entry.details]
        data['pipeline_entries'].append(entry_dict)
    backup_path = backup_dir / f"company_{company.id}_{timestamp}.json"
    backup_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(backup_path)


@router.post('/{company_id}/delete')
def delete_company(company_id: int, confirm_name: str = Form(''), db: Session = Depends(get_db)):
    company = get_company_or_404(db, company_id)
    # 二次确认：必须输入单位简称（或全称）才能删除
    expected = (company.short_name or company.company_name or '').strip()
    if not expected or (confirm_name or '').strip() != expected:
        raise HTTPException(status_code=422, detail='单位名称确认不匹配，删除已取消')
    # 有关联业务数据时阻断删除（避免级联删掉入廊/收费/合同）
    related = []
    if company.pipeline_entries:
        related.append(f'入廊记录 {len(company.pipeline_entries)} 条')
    if company.fee_records:
        related.append(f'收费记录 {len(company.fee_records)} 条')
    if company.contracts:
        related.append(f'合同 {len(company.contracts)} 条')
    if related:
        raise HTTPException(
            status_code=422,
            detail='该单位存在关联业务数据（' + '、'.join(related) + '），不可删除。如需停用请联系管理员。')
    # 先自动备份，再删除
    backup_path = backup_company_data(db, company)
    db.delete(company)
    db.commit()
    return RedirectResponse(url='/companies/?notice=' + quote(f'单位已删除，数据已备份至 {backup_path}'), status_code=303)
