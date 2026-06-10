from datetime import datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.maintenance_contract import MaintenanceContract
from app.paths import TEMPLATES_DIR

router = APIRouter(prefix='/maintenance-contracts', tags=['maintenance_contracts'])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

def parse_date(value: str):
    if not value or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), '%Y-%m-%d').date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f'日期格式错误: {value}') from exc

@router.get('/', response_class=HTMLResponse)
def list_contracts(request: Request, db: Session = Depends(get_db)):
    # 按ID倒序排列，最新备案的在最前面
    contracts = db.query(MaintenanceContract).order_by(MaintenanceContract.id.desc()).all()
    return templates.TemplateResponse(
        'maintenance_contracts/list.html', 
        {'request': request, 'contracts': contracts, 'title': '运维合同备案情况'}
    )

@router.get('/new', response_class=HTMLResponse)
def new_contract(request: Request):
    return templates.TemplateResponse(
        'maintenance_contracts/form.html', 
        {'request': request, 'contract': None, 'title': '新增运维合同'}
    )

@router.post('/new')
def create_contract(
    contract_name: str = Form(...),
    party_a: str = Form(...),
    party_b: str = Form(...),
    sign_date: str = Form(''),
    start_date: str = Form(''),
    end_date: str = Form(''),
    content: str = Form(''),
    db: Session = Depends(get_db),
):
    db.add(MaintenanceContract(
        contract_name=contract_name,
        party_a=party_a,
        party_b=party_b,
        sign_date=parse_date(sign_date),
        start_date=parse_date(start_date),
        end_date=parse_date(end_date),
        content=content
    ))
    db.commit()
    return RedirectResponse(url='/maintenance-contracts/', status_code=303)

@router.get('/{contract_id}/edit', response_class=HTMLResponse)
def edit_contract(contract_id: int, request: Request, db: Session = Depends(get_db)):
    contract = db.query(MaintenanceContract).filter(MaintenanceContract.id == contract_id).first()
    if not contract:
        return RedirectResponse(url='/maintenance-contracts/', status_code=303)
    return templates.TemplateResponse(
        'maintenance_contracts/form.html', 
        {'request': request, 'contract': contract, 'title': '编辑运维合同'}
    )

@router.post('/{contract_id}/edit')
def update_contract(
    contract_id: int,
    contract_name: str = Form(...),
    party_a: str = Form(...),
    party_b: str = Form(...),
    sign_date: str = Form(''),
    start_date: str = Form(''),
    end_date: str = Form(''),
    content: str = Form(''),
    db: Session = Depends(get_db),
):
    contract = db.query(MaintenanceContract).filter(MaintenanceContract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail='合同不存在')
        
    contract.contract_name = contract_name
    contract.party_a = party_a
    contract.party_b = party_b
    contract.sign_date = parse_date(sign_date)
    contract.start_date = parse_date(start_date)
    contract.end_date = parse_date(end_date)
    contract.content = content
    
    db.commit()
    return RedirectResponse(url='/maintenance-contracts/', status_code=303)

@router.post('/{contract_id}/delete')
def delete_contract(contract_id: int, db: Session = Depends(get_db)):
    contract = db.query(MaintenanceContract).filter(MaintenanceContract.id == contract_id).first()
    if contract:
        db.delete(contract)
        db.commit()
    return RedirectResponse(url='/maintenance-contracts/', status_code=303)
