from datetime import date
from app.models import Company, PipelineEntry, FeeRecord, Contract, FeeStandard
from app.services.fee_calc_service import calc_tax


def seed_data(db):
    if db.query(Company).count() > 0:
        return

    companies = [
        Company(company_name='山西转型综改区水务有限公司', short_name='综改水务', company_type='水务'),
        Company(company_name='山西汾飞能源动力有限公司', short_name='汾飞能源', company_type='能源'),
        Company(company_name='国网山西省电力有限公司太原供电分公司', short_name='国网太供', company_type='电力'),
        Company(company_name='山西转型综合改革示范区潇河新兴产业园区服务中心', short_name='潇河园区', company_type='园区管理'),
    ]
    db.add_all(companies)
    db.flush()

    standards = [
        FeeStandard(fee_type='入廊费', pipeline_type='电力', specification='默认', unit_price_excl_tax=105.32, billing_unit='元/米·孔', tax_rate=0.09, price_period='一次性', remark='示例默认税率'),
        FeeStandard(fee_type='运维费', pipeline_type='电力', specification='默认', unit_price_excl_tax=4.68, billing_unit='元/米·孔·年', tax_rate=0.06, price_period='年度', remark='示例默认税率'),
    ]
    db.add_all(standards)

    pipeline_entries = [
        PipelineEntry(company_id=companies[0].id, cabin_type='水信舱', project_name='综改水务项目', pipeline_type='给水', specification='给水管线', actual_length=2727, quantity_or_hole_count=2, entry_date=date(2024, 11, 25), contract_sign_date_entry=date(2024, 11, 25), contract_sign_date_maintenance=date(2025, 1, 1), has_entry_application='是'),
        PipelineEntry(company_id=companies[1].id, cabin_type='电力舱', project_name='汾飞能源项目', pipeline_type='电力', specification='YJLW-220KW-1*2500mm2', actual_length=1352, quantity_or_hole_count=6, entry_date=date(2024, 12, 31), contract_sign_date_entry=date(2024, 12, 31), contract_sign_date_maintenance=date(2025, 1, 11), has_entry_application='是'),
        PipelineEntry(company_id=companies[2].id, cabin_type='电力舱', project_name='潇北污水处理厂', pipeline_type='电力', specification='电力管线', actual_length=2727, quantity_or_hole_count=2, entry_date=date(2025, 3, 31), contract_sign_date_entry=date(2025, 3, 31), contract_sign_date_maintenance=date(2025, 1, 1), has_entry_application='是'),
        PipelineEntry(company_id=companies[3].id, cabin_type='电力舱', project_name='华芯二标段', pipeline_type='电力', specification='电力管线', actual_length=1800, quantity_or_hole_count=2, entry_date=date(2026, 3, 1), contract_sign_date_entry=date(2026, 3, 1), contract_sign_date_maintenance=date(2026, 3, 1), has_entry_application='是'),
    ]
    db.add_all(pipeline_entries)
    db.flush()

    fee_rows = [
        (companies[0].id, pipeline_entries[0].id, '入廊费', '入廊费（一次性）', 4859424.92, 0.09, date(2024, 11, 25), date(2024, 11, 25), date(2024, 12, 10), 4859424.92, date(2024, 12, 2), '已收缴', '首笔一次性收取'),
        (companies[0].id, pipeline_entries[0].id, '运维费', '2025年度', 419515.10, 0.06, date(2025, 1, 1), date(2025, 1, 1), date(2025, 3, 31), 0, None, '待收缴', '按年度收取'),
        (companies[1].id, pipeline_entries[1].id, '入廊费', '入廊费（一次性）', 806646.15, 0.09, date(2024, 12, 31), date(2024, 12, 31), date(2025, 1, 30), 806646.15, date(2025, 1, 11), '已收缴', ''),
        (companies[1].id, pipeline_entries[1].id, '运维费', '2026年度', 69674.44, 0.06, date(2026, 1, 11), date(2025, 12, 12), date(2026, 1, 11), 69674.44, date(2026, 1, 11), '已收缴', ''),
        (companies[2].id, pipeline_entries[2].id, '运维费', '2026年第1季度', 8267.17, 0.06, date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 10), 0, None, '已逾期', '示例逾期数据'),
        (companies[3].id, pipeline_entries[3].id, '入廊费', '入廊费（一次性）', 300000.00, 0.09, date(2026, 3, 1), date(2026, 2, 20), date(2026, 3, 1), 0, None, '待收缴', '华芯二标段示例'),
    ]

    fee_records = []
    for company_id, pipeline_entry_id, fee_type, charge_period, amount_excl_tax, tax_rate, planned_date, remind_date, latest_date, actual_amount, actual_date, status, remark in fee_rows:
        tax_amount, amount_incl_tax = calc_tax(amount_excl_tax, tax_rate)
        fee_records.append(
            FeeRecord(
                company_id=company_id,
                pipeline_entry_id=pipeline_entry_id,
                fee_type=fee_type,
                charge_period=charge_period,
                period_year=planned_date.year if planned_date else None,
                period_quarter=((planned_date.month - 1) // 3 + 1) if planned_date and fee_type == '运维费' else None,
                amount_excl_tax=amount_excl_tax,
                tax_rate=tax_rate,
                tax_amount=tax_amount,
                amount_incl_tax=amount_incl_tax,
                planned_receivable_date=planned_date,
                remind_date=remind_date,
                latest_payment_date=latest_date,
                actual_received_amount=actual_amount,
                actual_received_date=actual_date,
                payment_status=status,
                is_invoiced='是' if actual_amount else '否',
                remark=remark,
            )
        )
    db.add_all(fee_records)

    contracts = [
        Contract(company_id=companies[0].id, contract_type='入廊合同', contract_name='综改水务入廊合同', filing_department='管委会建管部公共事业科', filing_status='已备案', sign_date=date(2024, 11, 25)),
        Contract(company_id=companies[2].id, contract_type='入廊合同', contract_name='潇北污水处理厂入廊合同', filing_department='管委会建管部公共事业科', filing_status='已备案', sign_date=date(2025, 3, 31)),
    ]
    db.add_all(contracts)
    db.commit()
