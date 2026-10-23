"""三勾稽预警：入廊清单 × 合同备案 × 收费记录 交叉核对。

白城管廊 PPP 绩效评价实证教训：管线已入廊占大量空间却未签协议、未缴费，
收费项失分。勾稽的目的就是让"有入廊无合同、有合同无收费、有收费无合同"
这类脱节在系统里自动现形，而不是靠人工记忆。

合同与项目的关联分三级（页面上标注来源，推断结果需人工复核）：
1. 关联字段：contracts.pipeline_entry_id 直接指向；
2. 名称一致：合同名与项目名完全相同；
3. 名称推断：合同名去掉类型词/装饰后与项目名核心一致且唯一命中。
"""

from sqlalchemy.orm import Session, joinedload

from app.models import Contract, FeeRecord, PipelineEntry

ENTRY_TYPES = {'入廊合同', '入廊/运维合同'}
MAINT_TYPES = {'运维合同', '入廊/运维合同'}

ISSUE_DEFS = [
    ('no_contract', '有入廊无合同', 'danger'),
    ('fee_no_contract', '有收费无合同', 'danger'),
    ('no_fee', '有入廊无收费', 'danger'),
    ('contract_unsigned', '合同未签订', 'warn'),
    ('missing_entry_contract', '缺入廊合同', 'warn'),
    ('missing_maint_contract', '缺运维合同', 'warn'),
    ('contract_unfiled', '合同未备案/正在备案', 'info'),
]


def _link_contract(contract: Contract, entries: list[PipelineEntry]):
    """返回 (entry, 关联方式)；关联不上返回 (None, '未关联')。"""
    if contract.pipeline_entry_id:
        for e in entries:
            if e.id == contract.pipeline_entry_id:
                return e, '关联字段'
    name = (contract.contract_name or '').strip()
    for e in entries:
        if name and name == (e.project_name or '').strip():
            return e, '名称一致'
    core = name
    for token in ('入廊/运维合同', '入廊合同', '运维合同', '【', '】'):
        core = core.replace(token, '')
    core = core.strip().removesuffix('管线').strip()
    if core:
        hits = []
        for e in entries:
            pname = (e.project_name or '').strip()
            pcore = pname.removesuffix('项目')
            if core == pcore or core in pname or pcore in core:
                hits.append(e)
        if len(hits) == 1:
            return hits[0], '名称推断'
    return None, '未关联'


def get_reconciliation(db: Session) -> dict:
    entries = (db.query(PipelineEntry)
               .options(joinedload(PipelineEntry.company))
               .order_by(PipelineEntry.id).all())
    contracts = db.query(Contract).order_by(Contract.id).all()
    fee_entry_ids = {row[0] for row in
                     db.query(FeeRecord.pipeline_entry_id)
                     .filter(FeeRecord.pipeline_entry_id.isnot(None))
                     .distinct().all()}

    contracts_by_entry: dict[int, list] = {}
    unlinked_contracts = []
    for c in contracts:
        entry, method = _link_contract(c, entries)
        if entry is None:
            unlinked_contracts.append({'contract': c, 'method': method, 'entry': entry})
        else:
            contracts_by_entry.setdefault(entry.id, []).append(
                {'contract': c, 'method': method, 'entry': entry})

    def company_name(e: PipelineEntry) -> str:
        return e.company.short_name or e.company.company_name if e.company else ''

    groups: dict[str, list] = {key: [] for key, _, _ in ISSUE_DEFS}
    for e in entries:
        linked = contracts_by_entry.get(e.id, [])
        types = {(item['contract'].contract_type or '').strip() for item in linked}
        base = {'entry': e, 'company_name': company_name(e),
                'entry_date': e.entry_date.isoformat() if e.entry_date else '未填',
                'contract_name': '—', 'contract_type': '—', 'status_text': ''}
        if not linked:
            groups['no_contract'].append(
                {**base, 'status_text': '入廊清单中无任何合同与之关联'})
        else:
            if not (types & ENTRY_TYPES):
                groups['missing_entry_contract'].append(
                    {**base, 'contract_type': '入廊合同（缺）',
                     'status_text': '已有合同类型：%s' % '、'.join(sorted(types))})
            if not (types & MAINT_TYPES):
                groups['missing_maint_contract'].append(
                    {**base, 'contract_type': '运维合同（缺）',
                     'status_text': '已有合同类型：%s' % '、'.join(sorted(types))})
            for item in linked:
                c = item['contract']
                status = (c.filing_status or '').strip()
                crow = {**base,
                        'contract_name': '《%s》' % c.contract_name,
                        'contract_type': c.contract_type or '未填类型',
                        'status_text': status or '未填'}
                if status == '未签订':
                    groups['contract_unsigned'].append(crow)
                elif status in ('未备案', '正在备案'):
                    groups['contract_unfiled'].append(crow)
        if e.id not in fee_entry_ids:
            groups['no_fee'].append({**base, 'status_text': '收费记录 0 条'})
        elif not linked:
            groups['fee_no_contract'].append(
                {**base, 'status_text': '已有收费记录但无合同关联'})

    serious_keys = ('no_contract', 'fee_no_contract', 'no_fee', 'contract_unsigned')
    return {
        'groups': [{'key': key, 'title': title, 'level': level, 'rows': groups[key]}
                   for key, title, level in ISSUE_DEFS],
        'counts': {key: len(groups[key]) for key, _, _ in ISSUE_DEFS},
        'serious_total': sum(len(groups[k]) for k in serious_keys),
        'unlinked_contracts': unlinked_contracts,
        'contracts_by_entry': contracts_by_entry,
        'total_entries': len(entries),
        'total_contracts': len(contracts),
    }
