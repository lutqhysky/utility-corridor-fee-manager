"""数据看板服务：汇总有偿使用费收缴情况，供 /data-dashboard/ 页面使用。"""

from datetime import date, timedelta

from sqlalchemy import Integer, cast, func

from app.models import Company, FeeRecord, FeasibilitySubsidyDetail

MAINTENANCE_FEE_TYPES = {'运维费', '日常维护费', '维护费'}


def _outstanding_expr():
    return FeeRecord.amount_incl_tax - func.coalesce(FeeRecord.actual_received_amount, 0)


def get_data_dashboard(db):
    today = date.today()
    outstanding = _outstanding_expr()

    # ---------- KPI ----------
    total_receivable = float(
        db.query(func.coalesce(func.sum(FeeRecord.amount_incl_tax), 0)).scalar() or 0)
    total_received = float(
        db.query(func.coalesce(func.sum(FeeRecord.actual_received_amount), 0)).scalar() or 0)
    total_unreceived = total_receivable - total_received
    collection_rate = (total_received / total_receivable * 100) if total_receivable > 0 else 0

    overdue_q = db.query(FeeRecord).filter(
        FeeRecord.planned_receivable_date.isnot(None),
        FeeRecord.planned_receivable_date < today,
        outstanding > 0,
    )
    overdue_amount = float(
        db.query(func.coalesce(func.sum(outstanding), 0)).filter(
            FeeRecord.planned_receivable_date.isnot(None),
            FeeRecord.planned_receivable_date < today,
            outstanding > 0,
        ).scalar() or 0)
    overdue_count = overdue_q.count()
    max_overdue_days = 0
    if overdue_count:
        earliest = db.query(func.min(FeeRecord.planned_receivable_date)).filter(
            FeeRecord.planned_receivable_date.isnot(None),
            FeeRecord.planned_receivable_date < today,
            outstanding > 0,
        ).scalar()
        if earliest:
            max_overdue_days = (today - earliest).days

    # ---------- 收缴趋势：按年 / 按季度 ----------
    def trend(by_year: bool):
        if by_year:
            period_label = func.strftime('%Y', FeeRecord.planned_receivable_date)
            recv_label = func.strftime('%Y', FeeRecord.actual_received_date)
        else:
            # 季度标签：2026-Q3（SQLite 用 printf 拼字符串，+ 会被当成数字加法）
            period_label = func.printf(
                '%s-Q%s', func.strftime('%Y', FeeRecord.planned_receivable_date),
                cast((cast(func.strftime('%m', FeeRecord.planned_receivable_date), Integer) + 2) / 3, Integer))
            recv_label = func.printf(
                '%s-Q%s', func.strftime('%Y', FeeRecord.actual_received_date),
                cast((cast(func.strftime('%m', FeeRecord.actual_received_date), Integer) + 2) / 3, Integer))
        plan_rows = (
            db.query(period_label.label('p'),
                     func.coalesce(func.sum(FeeRecord.amount_incl_tax), 0).label('amt'))
            .filter(FeeRecord.planned_receivable_date.isnot(None))
            .group_by('p').order_by('p').all()
        )
        recv_rows = (
            db.query(recv_label.label('p'),
                     func.coalesce(func.sum(FeeRecord.actual_received_amount), 0).label('amt'))
            .filter(FeeRecord.actual_received_date.isnot(None))
            .filter(FeeRecord.actual_received_amount > 0)
            .group_by('p').order_by('p').all()
        )
        plan_map = {r.p: float(r.amt or 0) for r in plan_rows}
        recv_map = {r.p: float(r.amt or 0) for r in recv_rows}
        periods = sorted(set(plan_map) | set(recv_map))
        return [{'period': p,
                 'planned': plan_map.get(p, 0),
                 'received': recv_map.get(p, 0)} for p in periods]

    # ---------- 费用类型占比（已收） ----------
    type_rows = (
        db.query(FeeRecord.fee_type,
                 func.coalesce(func.sum(FeeRecord.actual_received_amount), 0).label('amt'))
        .filter(FeeRecord.actual_received_amount > 0)
        .group_by(FeeRecord.fee_type).all()
    )
    entry_received = sum(float(r.amt or 0) for r in type_rows if (r.fee_type or '').strip() == '入廊费')
    maint_received = sum(float(r.amt or 0) for r in type_rows
                         if (r.fee_type or '').strip() in MAINTENANCE_FEE_TYPES)

    # ---------- 单位待收排行 ----------
    pending_by_company = (
        db.query(Company.short_name, Company.company_name,
                 func.coalesce(func.sum(outstanding), 0).label('amt'))
        .join(FeeRecord, FeeRecord.company_id == Company.id)
        .filter(outstanding > 0)
        .group_by(Company.id, Company.short_name, Company.company_name)
        .order_by(func.sum(outstanding).desc())
        .all()
    )
    pending_rank = [{'name': r.short_name or r.company_name or '',
                     'amount': float(r.amt or 0)} for r in pending_by_company]

    # ---------- 各单位已收（入廊费 / 日常维护费堆叠） ----------
    recv_by_company = (
        db.query(Company.short_name, Company.company_name, FeeRecord.fee_type,
                 func.coalesce(func.sum(FeeRecord.actual_received_amount), 0).label('amt'))
        .join(FeeRecord, FeeRecord.company_id == Company.id)
        .filter(FeeRecord.actual_received_amount > 0)
        .group_by(Company.id, Company.short_name, Company.company_name, FeeRecord.fee_type)
        .all()
    )
    company_map: dict = {}
    for r in recv_by_company:
        name = r.short_name or r.company_name or ''
        entry = company_map.setdefault(name, {'name': name, 'entry': 0.0, 'maint': 0.0})
        ft = (r.fee_type or '').strip()
        if ft == '入廊费':
            entry['entry'] += float(r.amt or 0)
        elif ft in MAINTENANCE_FEE_TYPES:
            entry['maint'] += float(r.amt or 0)
    company_received = sorted(
        ({**v, 'total': v['entry'] + v['maint']} for v in company_map.values()),
        key=lambda x: x['total'], reverse=True)

    # ---------- 逾期明细 ----------
    overdue_records = (
        db.query(FeeRecord)
        .filter(FeeRecord.planned_receivable_date.isnot(None),
                FeeRecord.planned_receivable_date < today,
                outstanding > 0)
        .order_by(outstanding.desc())
        .all()
    )
    overdue_list = []
    for r in overdue_records:
        cname = r.company.short_name or r.company.company_name if r.company else ''
        pname = r.project_name or (r.pipeline_entry.project_name if r.pipeline_entry else '')
        overdue_list.append({
            'name': '%s-%s' % (cname, pname) if pname else cname,
            'fee_type': r.fee_type,
            'due_date': r.planned_receivable_date.isoformat() if r.planned_receivable_date else '',
            'amount': float(r.amount_incl_tax or 0) - float(r.actual_received_amount or 0),
            'days': (today - r.planned_receivable_date).days if r.planned_receivable_date else 0,
        })

    # ---------- 可行性缺口补助 ----------
    sub_details = (
        db.query(FeasibilitySubsidyDetail)
        .filter(FeasibilitySubsidyDetail.amount.isnot(None),
                FeasibilitySubsidyDetail.amount > 0)
        .order_by(FeasibilitySubsidyDetail.received_date.asc(),
                  FeasibilitySubsidyDetail.id.asc())
        .all()
    )
    sub_total = sum(float(d.amount or 0) for d in sub_details)
    sub_by_year: dict = {}
    for d in sub_details:
        if d.received_date:
            y = d.received_date.year
            sub_by_year[y] = sub_by_year.get(y, [0.0, 0])
            sub_by_year[y][0] += float(d.amount or 0)
            sub_by_year[y][1] += 1

    # ---------- 收费计划节点 ----------
    from sqlalchemy.orm import joinedload
    from app.models.fee_plan_node import FeePlanNode
    plan_rows = (
        db.query(FeePlanNode)
        .options(joinedload(FeePlanNode.company), joinedload(FeePlanNode.pipeline_entry))
        .filter(FeePlanNode.status == '待到期')
        .filter(FeePlanNode.planned_receivable_date.isnot(None))
        .order_by(FeePlanNode.planned_receivable_date.asc(), FeePlanNode.id.asc())
        .all()
    )
    plan_overdue = [n for n in plan_rows if n.planned_receivable_date < today]
    plan_next30 = [n for n in plan_rows
                   if today <= n.planned_receivable_date <= today + timedelta(days=30)]

    def plan_item(n):
        company_name = n.company.short_name or n.company.company_name if n.company else ''
        project_name = n.pipeline_entry.project_name if n.pipeline_entry else ''
        name = '%s-%s' % (company_name, project_name) if project_name else company_name
        return {'name': name, 'fee_type': n.fee_type, 'period': n.charge_period,
                'amount': float(n.amount_incl_tax or 0),
                'due_date': n.planned_receivable_date.isoformat(),
                'days': (n.planned_receivable_date - today).days}

    plan_info = {
        'overdue_count': len(plan_overdue),
        'overdue_amount': float(sum(float(n.amount_incl_tax or 0) for n in plan_overdue)),
        'next30_count': len(plan_next30),
        'next30_amount': float(sum(float(n.amount_incl_tax or 0) for n in plan_next30)),
        'overdue_list': [plan_item(n) for n in plan_overdue[:5]],
        'next_list': [plan_item(n) for n in plan_next30[:5]],
    }

    return {
        'today': today.isoformat(),
        'kpi': {
            'total_receivable': total_receivable,
            'total_received': total_received,
            'collection_rate': collection_rate,
            'total_unreceived': total_unreceived,
            'overdue_amount': overdue_amount,
            'overdue_count': overdue_count,
            'max_overdue_days': max_overdue_days,
        },
        'trend_year': trend(by_year=True),
        'trend_quarter': trend(by_year=False),
        'entry_received': entry_received,
        'maint_received': maint_received,
        'pending_rank': pending_rank,
        'company_received': company_received,
        'overdue_list': overdue_list,
        'plan': plan_info,
        'subsidy': {
            'total': sub_total,
            'count': len(sub_details),
            'by_year': [{'year': y, 'amount': v[0], 'count': v[1]}
                        for y, v in sorted(sub_by_year.items())],
        },
    }
