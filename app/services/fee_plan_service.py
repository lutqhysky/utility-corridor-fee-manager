"""收费计划生成：从入廊清单按业务规则推导应收节点（计划层）。

规则（见《收费生成规则梳理》）：
- 入廊费：一次性节点，金额 = 清单实际入廊费，应收日 = 入廊时间。
- 运维费（统一名「日常维护费」）：计费起始 = 计费起始日（默认入廊时间，例外项目单独设）；
  季度/年度按自然季度/自然年对齐逐期展开；首期不满整期按天折算，第二期起满额；
  季度金额 = 年度运维费 ÷ 4；季度应收日 = 次季首日，年度应收日 = 期次起始日。
- 展开范围：从计费起始期到「当前期 + 下一期」。
- 去重：已有收费记录（同项目+类型+期次）或已有计划节点（含已取消）的期次不再生成。
- 刷新语义：状态为「待到期」的旧节点先删后重建（跟随清单金额/锚点变化）；
  「已转记录」「已取消」节点保留不动。
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.models.fee_plan_node import FeePlanNode
from app.models.fee_record import FeeRecord
from app.models.pipeline_entry import PipelineEntry

MAINTENANCE_FEE_TYPES = {'运维费', '日常维护费', '维护费'}
MAINTENANCE_NAME = '日常维护费'
ENTRY_FEE_NAME = '入廊费'
ENTRY_FEE_PERIOD = '入廊费（一次性）'


def _q2(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal('0.00'), rounding=ROUND_HALF_UP)


def _quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    start_month = 3 * (quarter - 1) + 1
    start = date(year, start_month, 1)
    end = date(year, start_month + 2, calendar.monthrange(year, start_month + 2)[1])
    return start, end


def _periods_for_entry(entry: PipelineEntry, annual_maintenance: Decimal,
                       entry_actual_fee: Decimal, today: date) -> list[dict]:
    """推导一个项目应有的全部节点（不含去重）。"""
    nodes: list[dict] = []
    entry_date = entry.entry_date
    if entry_date is None:
        return nodes

    # 入廊费：一次性
    if entry_actual_fee > 0:
        nodes.append({
            'fee_type': ENTRY_FEE_NAME,
            'charge_period': ENTRY_FEE_PERIOD,
            'period_year': entry_date.year,
            'period_quarter': None,
            'period_start': entry_date,
            'period_end': entry_date,
            'amount_incl_tax': float(entry_actual_fee),
            'planned_receivable_date': entry_date,
            'is_prorated': 0,
        })

    # 运维费
    anchor = entry.billing_start_date or entry_date
    if annual_maintenance <= 0 or anchor is None:
        return nodes

    cycle = (entry.charge_cycle or '年度').strip()
    if cycle == '季度':
        quarterly_amount = _q2(annual_maintenance / Decimal(4))
        year, quarter = anchor.year, (anchor.month - 1) // 3 + 1
        cur_year, cur_quarter = today.year, (today.month - 1) // 3 + 1
        # 展开到当前季度的下一季度为止
        end_key = (cur_year * 4 + cur_quarter) + 1
        first = True
        while year * 4 + quarter <= end_key:
            q_start, q_end = _quarter_bounds(year, quarter)
            p_start = anchor if first else q_start
            days = (q_end - p_start).days + 1
            full_days = (q_end - q_start).days + 1
            if days >= full_days:
                amount, prorated = quarterly_amount, 0
            else:
                amount = _q2(quarterly_amount * Decimal(days) / Decimal(full_days))
                prorated = 1
            nodes.append({
                'fee_type': MAINTENANCE_NAME,
                'charge_period': f'{year}年第{quarter}季度',
                'period_year': year,
                'period_quarter': quarter,
                'period_start': p_start,
                'period_end': q_end,
                'amount_incl_tax': float(amount),
                'planned_receivable_date': q_end + timedelta(days=1),
                'is_prorated': prorated,
            })
            first = False
            quarter += 1
            if quarter > 4:
                quarter, year = 1, year + 1
    else:  # 年度
        year = anchor.year
        last_year = today.year + 1
        first = True
        while year <= last_year:
            y_start, y_end = date(year, 1, 1), date(year, 12, 31)
            p_start = anchor if first else y_start
            days = (y_end - p_start).days + 1
            full_days = (y_end - y_start).days + 1
            if days >= full_days:
                amount, prorated = _q2(annual_maintenance), 0
            else:
                amount = _q2(annual_maintenance * Decimal(days) / Decimal(full_days))
                prorated = 1
            nodes.append({
                'fee_type': MAINTENANCE_NAME,
                'charge_period': f'{year}年度',
                'period_year': year,
                'period_quarter': None,
                'period_start': p_start,
                'period_end': y_end,
                'amount_incl_tax': float(amount),
                'planned_receivable_date': p_start,
                'is_prorated': prorated,
            })
            first = False
            year += 1
    return nodes


def _existing_record_keys(db: Session, entry_id: int):
    """已有收费记录的去重信息，返回 (标签键, 年度键, 是否已有入廊费记录)。

    生产数据实证（2026-10-22 核对）：
    - 入廊费记录的 charge_period 写法不统一（有条写成「2025年度」），
      入廊费是一次性收费 → 该项目只要有任意入廊费记录即视为已收，不再生成节点；
    - 综改水务年度记录写跨年标签（「2024年度-2025年度」），与生成器自然年标签对不上，
      但 period_year 都对得上 → 年度期次再按 (类型, period_year) 兜底匹配；
    - 季度记录标签是规范的「YYYY年第N季度」，period_quarter 普遍为空，靠标签匹配。
    """
    keys: set[tuple[str, str]] = set()
    year_keys: set[tuple[str, int]] = set()
    has_entry_fee = False
    rows = (db.query(FeeRecord.fee_type, FeeRecord.charge_period, FeeRecord.period_year)
            .filter(FeeRecord.pipeline_entry_id == entry_id).all())
    for fee_type, charge_period, period_year in rows:
        name = MAINTENANCE_NAME if fee_type in MAINTENANCE_FEE_TYPES else fee_type
        keys.add((name, charge_period or ''))
        if period_year:
            year_keys.add((name, int(period_year)))
        if name == ENTRY_FEE_NAME:
            has_entry_fee = True
    return keys, year_keys, has_entry_fee


def generate_plans(db: Session, today: date | None = None) -> dict:
    """为全部入廊项目刷新收费计划，返回统计。"""
    from app.routes.fee_records import calculate_entry_actual_fees

    today = today or date.today()
    stats = {'created': 0, 'skipped_existing': 0, 'skipped_paused': 0,
             'skipped_no_date': 0, 'refreshed': 0}
    entries = db.query(PipelineEntry).order_by(PipelineEntry.id).all()
    for entry in entries:
        if entry.plan_paused:
            stats['skipped_paused'] += 1
            continue
        if entry.entry_date is None:
            stats['skipped_no_date'] += 1
            continue

        entry_actual, maintenance_actual = calculate_entry_actual_fees(entry)
        desired = _periods_for_entry(
            entry, Decimal(str(maintenance_actual)), Decimal(str(entry_actual)), today)
        record_keys, record_year_keys, has_entry_fee = _existing_record_keys(db, entry.id)

        # 刷新：删掉未转记录的「待到期」节点后按最新规则重建
        stale = (db.query(FeePlanNode)
                 .filter(FeePlanNode.pipeline_entry_id == entry.id,
                         FeePlanNode.status == '待到期').all())
        for node in stale:
            db.delete(node)
            stats['refreshed'] += 1
        db.flush()
        kept_keys = {
            (MAINTENANCE_NAME if n.fee_type in MAINTENANCE_FEE_TYPES else n.fee_type,
             n.charge_period or '')
            for n in db.query(FeePlanNode).filter(
                FeePlanNode.pipeline_entry_id == entry.id).all()
        }

        for spec in desired:
            key = (spec['fee_type'], spec['charge_period'])
            if key in kept_keys:
                stats['skipped_existing'] += 1
                continue
            if key in record_keys:
                stats['skipped_existing'] += 1
                continue
            # 入廊费一次性：已有任意入廊费记录即跳过（历史标签写法不统一）
            if spec['fee_type'] == ENTRY_FEE_NAME and has_entry_fee:
                stats['skipped_existing'] += 1
                continue
            # 年度期次按年份兜底（跨年标签的历史记录靠 period_year 命中）
            if (spec['period_quarter'] is None and spec['period_year'] is not None
                    and (spec['fee_type'], int(spec['period_year'])) in record_year_keys):
                stats['skipped_existing'] += 1
                continue
            db.add(FeePlanNode(
                pipeline_entry_id=entry.id,
                company_id=entry.company_id,
                status='待到期',
                **spec,
            ))
            stats['created'] += 1
    db.commit()
    return stats
