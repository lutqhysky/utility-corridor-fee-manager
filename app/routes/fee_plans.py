from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.fee_plan_node import FeePlanNode
from app.models.fee_record import FeeRecord
from app.models.pipeline_entry import PipelineEntry
from app.paths import TEMPLATES_DIR
from app.services.fee_plan_service import generate_plans

router = APIRouter(prefix='/fee-plans', tags=['fee-plans'])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get('/', response_class=HTMLResponse)
def list_plans(request: Request, db: Session = Depends(get_db),
               created: int = -1, skipped_existing: int = -1,
               skipped_paused: int = -1, skipped_no_date: int = -1,
               converted: int = -1, convert_failed: int = -1):
    today = date.today()
    entries = db.query(PipelineEntry).order_by(PipelineEntry.id).all()
    nodes = (db.query(FeePlanNode)
             .order_by(FeePlanNode.planned_receivable_date.asc(), FeePlanNode.id.asc())
             .all())
    by_entry: dict[int, list] = {}
    for node in nodes:
        by_entry.setdefault(node.pipeline_entry_id, []).append(node)

    pending = [n for n in nodes if n.status == '待到期']
    overdue_pending = [n for n in pending
                       if n.planned_receivable_date and n.planned_receivable_date < today]
    summary = {
        'pending_count': len(pending),
        'pending_amount': sum(n.amount_incl_tax or 0 for n in pending),
        'overdue_count': len(overdue_pending),
        'overdue_amount': sum(n.amount_incl_tax or 0 for n in overdue_pending),
        'converted_count': sum(1 for n in nodes if n.status == '已转记录'),
    }
    generate_msg = None
    if converted >= 0:
        generate_msg = f'批量转记录完成：成功 {converted} 个，失败 {convert_failed} 个。'
    if created >= 0:
        generate_msg = (f'计划已生成/刷新：新建 {created} 个节点，'
                        f'跳过已有记录/节点 {skipped_existing} 个，'
                        f'暂停项目 {skipped_paused} 个，未填入廊时间 {skipped_no_date} 个。')
    return templates.TemplateResponse('fee_plans/list.html', {
        'request': request,
        'title': '收费计划',
        'entries': entries,
        'by_entry': by_entry,
        'summary': summary,
        'today': today,
        'generate_msg': generate_msg,
    })


@router.post('/generate')
def generate(request: Request, db: Session = Depends(get_db)):
    stats = generate_plans(db)
    return RedirectResponse(
        url=(f"/fee-plans/?created={stats['created']}"
             f"&skipped_existing={stats['skipped_existing']}"
             f"&skipped_paused={stats['skipped_paused']}"
             f"&skipped_no_date={stats['skipped_no_date']}"),
        status_code=303)


def _convert_node(db: Session, node: FeePlanNode):
    """把一个待到期节点转成收费记录（不提交，调用方统一 commit）。失败返回 None。"""
    from app.routes.fee_records import calc_excl_tax_from_incl_tax, get_standard_tax_rate

    if node.status != '待到期':
        return None
    entry = node.pipeline_entry
    if not entry:
        return None

    tax_rate = get_standard_tax_rate(db, node.fee_type)
    if tax_rate is None:
        tax_rate = (entry.entry_fee_tax_rate if node.fee_type == '入廊费'
                    else entry.maintenance_fee_tax_rate) or 0
    amount_excl_tax, tax_amount = calc_excl_tax_from_incl_tax(
        node.amount_incl_tax or 0, float(tax_rate))
    record = FeeRecord(
        company_id=node.company_id,
        pipeline_entry_id=node.pipeline_entry_id,
        project_name=entry.project_name,
        fee_type=node.fee_type,
        charge_period=node.charge_period,
        period_year=node.period_year,
        period_quarter=node.period_quarter,
        amount_excl_tax=amount_excl_tax,
        tax_rate=float(tax_rate),
        tax_amount=tax_amount,
        amount_incl_tax=node.amount_incl_tax or 0,
        planned_receivable_date=node.planned_receivable_date,
        actual_received_amount=0,
        actual_received_date=None,
        payment_status='待收缴',
        is_invoiced='否',
        remark='由收费计划生成',
    )
    db.add(record)
    db.flush()
    node.status = '已转记录'
    node.fee_record_id = record.id
    return record


@router.post('/{node_id}/convert')
def convert_node(node_id: int, db: Session = Depends(get_db)):
    node = db.query(FeePlanNode).filter(FeePlanNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail='计划节点不存在')
    if node.status == '已转记录':
        return RedirectResponse(url='/fee-plans/', status_code=303)
    if _convert_node(db, node) is None:
        raise HTTPException(status_code=422, detail='节点无法转换（关联入廊记录不存在）')
    db.commit()
    return RedirectResponse(url='/fee-plans/', status_code=303)


@router.post('/convert-batch')
def convert_batch(db: Session = Depends(get_db), node_ids: list[int] = Form([])):
    """批量转记录：逐条转换，单条失败不影响其他条，汇总回报。"""
    ok, failed = 0, 0
    for node_id in dict.fromkeys(node_ids):
        node = db.query(FeePlanNode).filter(FeePlanNode.id == node_id).first()
        if node is None:
            failed += 1
            continue
        try:
            if _convert_node(db, node) is None:
                failed += 1
            else:
                ok += 1
        except Exception:
            db.rollback()
            failed += 1
    db.commit()
    return RedirectResponse(url=f'/fee-plans/?converted={ok}&convert_failed={failed}',
                            status_code=303)


@router.post('/{node_id}/cancel')
def cancel_node(node_id: int, db: Session = Depends(get_db)):
    node = db.query(FeePlanNode).filter(FeePlanNode.id == node_id).first()
    if node and node.status == '待到期':
        node.status = '已取消'
        db.commit()
    return RedirectResponse(url='/fee-plans/', status_code=303)


@router.post('/{node_id}/restore')
def restore_node(node_id: int, db: Session = Depends(get_db)):
    node = db.query(FeePlanNode).filter(FeePlanNode.id == node_id).first()
    if node and node.status == '已取消':
        node.status = '待到期'
        db.commit()
    return RedirectResponse(url='/fee-plans/', status_code=303)
