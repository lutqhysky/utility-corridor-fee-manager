import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.utils import safe_json_dumps
from app.models import Company, FeeStandard, PipelineEntry, PipelineEntryDetail
from app.paths import TEMPLATES_DIR

router = APIRouter(prefix='/pipeline-entries', tags=['pipeline_entries'])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f'日期格式错误: {value}，正确格式应为 YYYY-MM-DD') from exc


def get_discount_or_default(value: float | None):
    return value if value is not None else 1


def calc_detail_amount(quantity: float | None, unit_price: float | None) -> float:
    return q2(Decimal(str(quantity or 0)) * Decimal(str(unit_price or 0)))


def infer_detail_unit(pipeline_type: str | None) -> str:
    """按管线类型推断计费单位：电力/通信按孔，其余按米。"""
    pt = (pipeline_type or '')
    if '电力' in pt or '通信' in pt or '通讯' in pt:
        return '孔'
    return '米'


def q2(value) -> float:
    """四舍五入到分（Decimal），避免浮点 0.015 舍入错误。"""
    return float(Decimal(str(value or 0)).quantize(Decimal('0.00'), rounding=ROUND_HALF_UP))


def _validate_entry_rates(entry_tax: float, maint_tax: float,
                            entry_disc: float, maint_disc: float) -> None:
    """入廊记录税率/折扣范围校验：税率 0~1，折扣 0~1。"""
    for name, val in (('入廊费税率', entry_tax), ('运维费税率', maint_tax)):
        if not 0 <= val < 1:
            raise HTTPException(status_code=422, detail=f'{name}需在 0~1 之间')
    for name, val in (('入廊费折扣', entry_disc), ('运维费折扣', maint_disc)):
        if not 0 <= val <= 1:
            raise HTTPException(status_code=422, detail=f'{name}需在 0~1 之间')


def parse_float_or(value: str | None, default: float = 0.0) -> float:
    """数字框留空（""）时用默认值，避免 422。"""
    if value is None:
        return default
    stripped = value.strip()
    if not stripped:
        return default
    try:
        return float(stripped)
    except (ValueError, TypeError):
        return default


def get_fee_standards_json(db: Session) -> str:
    """按(管线类型, 规格)聚合启用的收费标准，供明细表单引用自动填价。"""
    standards = db.query(FeeStandard).filter(FeeStandard.is_active.is_(True)).all()
    grouped: dict[str, dict] = {}
    for std in standards:
        key = f"{std.pipeline_type or ''}|{std.specification or ''}"
        item = grouped.setdefault(key, {
            'pipeline_type': std.pipeline_type or '',
            'specification': std.specification or '',
            'entry_price': None,
            'maintenance_price': None,
        })
        fee_type = std.fee_type or ''
        if '入廊' in fee_type:
            item['entry_price'] = std.unit_price_excl_tax
        elif '维护' in fee_type or '运维' in fee_type:
            item['maintenance_price'] = std.unit_price_excl_tax
    result = {k: v for k, v in grouped.items() if v['entry_price'] is not None or v['maintenance_price'] is not None}
    return safe_json_dumps(result)


@router.get('/', response_class=HTMLResponse)
def list_entries(request: Request, db: Session = Depends(get_db), company_id: int | None = None,
                 project_name: str | None = None, cabin_type: str | None = None):
    query = db.query(PipelineEntry)
    if company_id:
        query = query.filter(PipelineEntry.company_id == company_id)
    if project_name:
        query = query.filter(PipelineEntry.project_name == project_name)
    if cabin_type:
        query = query.filter(PipelineEntry.cabin_type == cabin_type)

    entries = query.order_by(PipelineEntry.id.desc()).all()

    for entry in entries:
        entry_fee_excl_tax_total = sum((item.entry_amount_excl_tax or 0) for item in entry.details)
        maintenance_fee_excl_tax_total = sum((item.maintenance_amount_excl_tax or 0) for item in entry.details)

        entry_fee_tax_rate = entry.entry_fee_tax_rate or 0
        maintenance_fee_tax_rate = entry.maintenance_fee_tax_rate or 0

        entry_fee_discount = get_discount_or_default(entry.entry_fee_discount)
        maintenance_fee_discount = get_discount_or_default(entry.maintenance_fee_discount)

        entry_fee_tax_amount = q2(Decimal(str(entry_fee_excl_tax_total)) * Decimal(str(entry_fee_tax_rate)))
        entry_fee_incl_tax_total = q2(Decimal(str(entry_fee_excl_tax_total)) + Decimal(str(entry_fee_tax_amount)))
        entry.actual_entry_fee = q2(Decimal(str(entry_fee_incl_tax_total)) * Decimal(str(entry_fee_discount)))
        # 入廊费为 0 多半是收费明细/税率/折扣没填对，打标提醒核实
        entry.zero_fee_warning = (entry.actual_entry_fee or 0) == 0

        maintenance_fee_tax_amount = q2(Decimal(str(maintenance_fee_excl_tax_total)) * Decimal(str(maintenance_fee_tax_rate)))
        maintenance_fee_incl_tax_total = q2(Decimal(str(maintenance_fee_excl_tax_total)) + Decimal(str(maintenance_fee_tax_amount)))
        entry.actual_maintenance_fee = q2(Decimal(str(maintenance_fee_incl_tax_total)) * Decimal(str(maintenance_fee_discount)))
        # 按收费周期拆分年度/季度：季度->年度为4倍，年度->季度为1/4
        if (entry.charge_cycle or '年度') == '季度':
            entry.maintenance_fee_quarterly = entry.actual_maintenance_fee
            entry.maintenance_fee_annual = q2(Decimal(str(entry.actual_maintenance_fee or 0)) * 4)
        else:
            entry.maintenance_fee_annual = entry.actual_maintenance_fee
            entry.maintenance_fee_quarterly = q2(Decimal(str(entry.actual_maintenance_fee or 0)) / 4)

    companies = db.query(Company).order_by(Company.company_name).all()
    project_names = [r[0] for r in db.query(PipelineEntry.project_name)
                     .filter(PipelineEntry.project_name.isnot(None))
                     .filter(PipelineEntry.project_name != '')
                     .distinct().order_by(PipelineEntry.project_name).all()]
    cabin_types = [r[0] for r in db.query(PipelineEntry.cabin_type)
                   .filter(PipelineEntry.cabin_type.isnot(None))
                   .filter(PipelineEntry.cabin_type != '')
                   .distinct().order_by(PipelineEntry.cabin_type).all()]
    total_entry_fee = sum(float(e.actual_entry_fee or 0) for e in entries)
    total_maintenance_annual = sum(float(e.maintenance_fee_annual or 0) for e in entries)
    return templates.TemplateResponse(
        'pipeline_entries/list.html',
        {
            'request': request,
            'entries': entries,
            'companies': companies,
            'selected_company_id': company_id,
            'project_names': project_names,
            'selected_project_name': project_name or '',
            'cabin_types': cabin_types,
            'selected_cabin_type': cabin_type or '',
            'total_entry_fee': total_entry_fee,
            'total_maintenance_annual': total_maintenance_annual,
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

    entry_date: str = Form(''),
    contract_sign_date_entry: str = Form(''),
    contract_sign_date_maintenance: str = Form(''),
    has_entry_application: str = Form(''),
    remark: str = Form(''),
    entry_fee_tax_rate: str | None = Form(None),
    maintenance_fee_tax_rate: str | None = Form(None),
    entry_fee_discount: str | None = Form(None),
    maintenance_fee_discount: str | None = Form(None),
    charge_cycle: str = Form('年度'),
    db: Session = Depends(get_db),
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail='单位不存在')

    if not entry_date or not entry_date.strip():
        raise HTTPException(status_code=422, detail='入廊时间不能为空，请填写')

    entry_fee_tax_rate = parse_float_or(entry_fee_tax_rate, 0.0)
    maintenance_fee_tax_rate = parse_float_or(maintenance_fee_tax_rate, 0.0)
    entry_fee_discount = parse_float_or(entry_fee_discount, 1.0)
    maintenance_fee_discount = parse_float_or(maintenance_fee_discount, 1.0)
    _validate_entry_rates(entry_fee_tax_rate, maintenance_fee_tax_rate,
                          entry_fee_discount, maintenance_fee_discount)

    db.add(PipelineEntry(
        company_id=company_id,
        cabin_type=cabin_type,
        project_name=project_name,
        pipeline_type=pipeline_type,

        entry_date=parse_date(entry_date),
        contract_sign_date_entry=parse_date(contract_sign_date_entry),
        contract_sign_date_maintenance=parse_date(contract_sign_date_maintenance),
        has_entry_application=has_entry_application,
        remark=remark,
        entry_fee_tax_rate=entry_fee_tax_rate,
        maintenance_fee_tax_rate=maintenance_fee_tax_rate,
        entry_fee_discount=entry_fee_discount,
        maintenance_fee_discount=maintenance_fee_discount,
        charge_cycle=charge_cycle,
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail='入廊记录保存失败，请确认关联单位有效') from exc
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

    entry_fee_discount = get_discount_or_default(entry.entry_fee_discount)
    maintenance_fee_discount = get_discount_or_default(entry.maintenance_fee_discount)

    entry_fee_tax_amount = q2(Decimal(str(entry_fee_excl_tax_total)) * Decimal(str(entry_fee_tax_rate)))
    entry_fee_incl_tax_total = q2(Decimal(str(entry_fee_excl_tax_total)) + Decimal(str(entry_fee_tax_amount)))
    entry_fee_actual_total = q2(Decimal(str(entry_fee_incl_tax_total)) * Decimal(str(entry_fee_discount)))

    maintenance_fee_tax_amount = q2(Decimal(str(maintenance_fee_excl_tax_total)) * Decimal(str(maintenance_fee_tax_rate)))
    maintenance_fee_incl_tax_total = q2(Decimal(str(maintenance_fee_excl_tax_total)) + Decimal(str(maintenance_fee_tax_amount)))
    maintenance_fee_actual_total = q2(Decimal(str(maintenance_fee_incl_tax_total)) * Decimal(str(maintenance_fee_discount)))

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

    entry_date: str = Form(''),
    contract_sign_date_entry: str = Form(''),
    contract_sign_date_maintenance: str = Form(''),
    has_entry_application: str = Form(''),
    remark: str = Form(''),
    entry_fee_tax_rate: str | None = Form(None),
    maintenance_fee_tax_rate: str | None = Form(None),
    entry_fee_discount: str | None = Form(None),
    maintenance_fee_discount: str | None = Form(None),
    charge_cycle: str = Form('年度'),
    db: Session = Depends(get_db),
):
    entry = db.query(PipelineEntry).filter(PipelineEntry.id == entry_id).first()
    if not entry:
        return RedirectResponse(url='/pipeline-entries/', status_code=303)

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail='单位不存在')

    if not entry_date or not entry_date.strip():
        raise HTTPException(status_code=422, detail='入廊时间不能为空，请填写')

    entry_fee_tax_rate = parse_float_or(entry_fee_tax_rate, 0.0)
    maintenance_fee_tax_rate = parse_float_or(maintenance_fee_tax_rate, 0.0)
    entry_fee_discount = parse_float_or(entry_fee_discount, 1.0)
    maintenance_fee_discount = parse_float_or(maintenance_fee_discount, 1.0)
    _validate_entry_rates(entry_fee_tax_rate, maintenance_fee_tax_rate,
                          entry_fee_discount, maintenance_fee_discount)

    entry.company_id = company_id
    entry.cabin_type = cabin_type
    entry.project_name = project_name
    entry.pipeline_type = pipeline_type

    entry.entry_date = parse_date(entry_date)
    entry.contract_sign_date_entry = parse_date(contract_sign_date_entry)
    entry.contract_sign_date_maintenance = parse_date(contract_sign_date_maintenance)
    entry.has_entry_application = has_entry_application
    entry.remark = remark
    entry.entry_fee_tax_rate = entry_fee_tax_rate
    entry.maintenance_fee_tax_rate = maintenance_fee_tax_rate
    entry.entry_fee_discount = entry_fee_discount
    entry.maintenance_fee_discount = maintenance_fee_discount
    entry.charge_cycle = charge_cycle

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail='入廊记录更新失败，请确认关联单位有效') from exc
    return RedirectResponse(url=f'/pipeline-entries/{entry_id}', status_code=303)
    
@router.post('/{entry_id}/delete')
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    entry = db.query(PipelineEntry).filter(PipelineEntry.id == entry_id).first()
    if not entry:
        return RedirectResponse(url='/pipeline-entries/', status_code=303)

    # 有关联收费记录时阻断删除，避免静默断开关联
    related_count = len(entry.fee_records or [])
    if related_count:
        raise HTTPException(
            status_code=422,
            detail=f'该项目有关联的收费记录 {related_count} 条，不能直接删除。请先处理这些收费记录（删除或取消关联）后再试。',
        )

    db.delete(entry)
    db.commit()
    return RedirectResponse(url='/pipeline-entries/', status_code=303)

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
            'fee_standards_json': get_fee_standards_json(db),
            'title': f'新增收费明细 - {entry.project_name or ""}'
        }
    )


@router.post('/{entry_id}/details/new')
def create_detail(
    entry_id: int,
    pipeline_type: str = Form(''),
    specification: str = Form(''),
    engineering_quantity: str | None = Form(None),
    entry_unit_price_excl_tax: str | None = Form(None),
    maintenance_unit_price_excl_tax: str | None = Form(None),
    remark: str = Form(''),
    db: Session = Depends(get_db),
):
    engineering_quantity = parse_float_or(engineering_quantity, 0.0)
    entry_unit_price_excl_tax = parse_float_or(entry_unit_price_excl_tax, 0.0)
    maintenance_unit_price_excl_tax = parse_float_or(maintenance_unit_price_excl_tax, 0.0)
    entry = db.query(PipelineEntry).filter(PipelineEntry.id == entry_id).first()
    if not entry:
        return RedirectResponse(url='/pipeline-entries/', status_code=303)

    entry_amount_excl_tax = calc_detail_amount(engineering_quantity, entry_unit_price_excl_tax)
    maintenance_amount_excl_tax = calc_detail_amount(engineering_quantity, maintenance_unit_price_excl_tax)

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
            'fee_standards_json': get_fee_standards_json(db),
            'title': f'编辑收费明细 - {entry.project_name or ""}'
        }
    )


@router.post('/details/{detail_id}/edit')
def update_detail(
    detail_id: int,
    pipeline_type: str = Form(''),
    specification: str = Form(''),
    engineering_quantity: str | None = Form(None),
    entry_unit_price_excl_tax: str | None = Form(None),
    maintenance_unit_price_excl_tax: str | None = Form(None),
    remark: str = Form(''),
    db: Session = Depends(get_db),
):
    engineering_quantity = parse_float_or(engineering_quantity, 0.0)
    entry_unit_price_excl_tax = parse_float_or(entry_unit_price_excl_tax, 0.0)
    maintenance_unit_price_excl_tax = parse_float_or(maintenance_unit_price_excl_tax, 0.0)
    detail = db.query(PipelineEntryDetail).filter(PipelineEntryDetail.id == detail_id).first()
    if not detail:
        return RedirectResponse(url='/pipeline-entries/', status_code=303)

    detail.pipeline_type = pipeline_type
    detail.specification = specification
    detail.engineering_quantity = engineering_quantity
    detail.entry_unit_price_excl_tax = entry_unit_price_excl_tax
    detail.entry_amount_excl_tax = calc_detail_amount(engineering_quantity, entry_unit_price_excl_tax)
    detail.maintenance_unit_price_excl_tax = maintenance_unit_price_excl_tax
    detail.maintenance_amount_excl_tax = calc_detail_amount(engineering_quantity, maintenance_unit_price_excl_tax)
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


PRINT_REGION_TITLE = '山西转型综合改革示范区潇河产业园区太原起步区'
PRINT_TARGET_ROWS = 24  # 表格目标总行数（含表头），不足时用空白行补齐以撑满 A4


def _fmt_money(value) -> str:
    return '%.2f' % float(value or 0)


def _fmt_qty(value) -> str:
    return '%g' % float(value or 0)


def _fmt_pct(value) -> str:
    return '%g%%' % (float(value or 0) * 100)


@router.get('/{entry_id}/print/{fee_kind}', response_class=HTMLResponse)
def print_fee_sheet(entry_id: int, fee_kind: str, request: Request, db: Session = Depends(get_db)):
    """打印费用单：fee_kind 为 entry（入廊费）或 maintenance（运维费）。"""
    if fee_kind not in ('entry', 'maintenance'):
        return RedirectResponse(url='/pipeline-entries/', status_code=303)
    entry = db.query(PipelineEntry).filter(PipelineEntry.id == entry_id).first()
    if not entry:
        return RedirectResponse(url='/pipeline-entries/', status_code=303)

    is_entry = fee_kind == 'entry'
    fee_label = '入廊费' if is_entry else '运维费'
    if is_entry:
        tax_rate = entry.entry_fee_tax_rate or 0
        discount = get_discount_or_default(entry.entry_fee_discount)
        qty_header = '入廊工程量'
        price_header = '不含税入廊费（元/米·孔）'
        amount_header = '不含税入廊费合计'
    else:
        tax_rate = entry.maintenance_fee_tax_rate or 0
        discount = get_discount_or_default(entry.maintenance_fee_discount)
        qty_header = '运维工程量'
        price_header = '不含税运维费（元/米·年）'
        amount_header = '不含税运维费合计'

    rows = []
    for item in entry.details:
        qty = item.engineering_quantity or 0
        if is_entry:
            unit_price = item.entry_unit_price_excl_tax or 0
            amount = item.entry_amount_excl_tax or 0
        else:
            unit_price = item.maintenance_unit_price_excl_tax or 0
            amount = item.maintenance_amount_excl_tax or 0
        if not amount and qty and unit_price:
            amount = calc_detail_amount(qty, unit_price)
        rows.append({
            'pipeline_type': item.pipeline_type or '',
            'specification': item.specification or '',
            'unit': infer_detail_unit(item.pipeline_type),
            'quantity': _fmt_qty(qty),
            'unit_price': _fmt_money(unit_price),
            'amount': _fmt_money(amount),
            'remark': item.remark or '',
            '_amount_value': float(amount or 0),
        })

    subtotal = sum(row['_amount_value'] for row in rows)
    # 税金先舍到分再参与汇总，避免单据分项加总差 1 分
    tax_amount = q2(Decimal(str(subtotal)) * Decimal(str(tax_rate)))
    total_incl_tax = q2(Decimal(str(subtotal)) + Decimal(str(tax_amount)))

    # 折扣段始终显示：正式费用单据需注明合同约定折扣后的实际应收金额
    actual_subtotal = q2(Decimal(str(subtotal)) * Decimal(str(discount)))
    actual_tax = q2(Decimal(str(actual_subtotal)) * Decimal(str(tax_rate)))
    actual_total = q2(Decimal(str(actual_subtotal)) + Decimal(str(actual_tax)))

    cabin = entry.cabin_type or ''
    note_text = (
        f'根据管线入廊合同约定，本项目{cabin}{fee_label}按照上述金额的{_fmt_pct(discount)}收取。'
        '实际综合管廊有偿使用费如下：'
    )

    fixed_rows = 1 + len(rows) + 3 + 4
    blank_rows = list(range(max(0, PRINT_TARGET_ROWS - fixed_rows)))

    return templates.TemplateResponse(
        'pipeline_entries/print.html',
        {
            'request': request,
            'region_title': PRINT_REGION_TITLE,
            'sheet_title': f'管廊{cabin}有偿使用费（{entry.project_name or ""}-{fee_label}）',
            'qty_header': qty_header,
            'price_header': price_header,
            'amount_header': amount_header,
            'rows': rows,
            'subtotal': _fmt_money(subtotal),
            'tax_rate_text': _fmt_pct(tax_rate),
            'tax_amount': _fmt_money(tax_amount),
            'total_incl_tax': _fmt_money(total_incl_tax),
            'note_text': note_text,
            'actual_subtotal': _fmt_money(actual_subtotal),
            'actual_tax': _fmt_money(actual_tax),
            'actual_total': _fmt_money(actual_total),
            'blank_rows': blank_rows,
            'title': f'打印{fee_label} - {entry.project_name or ""}',
        },
    )
