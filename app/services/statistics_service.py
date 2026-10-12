from datetime import date

from sqlalchemy import func

from app.models import Company, Contract, FeeRecord, PipelineEntry


class StatisticsService:
    @staticmethod
    def dashboard(db):
        today = date.today()
        company_count = db.query(func.count(Company.id)).scalar() or 0
        pipeline_count = db.query(func.count(PipelineEntry.id)).scalar() or 0
        fee_record_count = db.query(func.count(FeeRecord.id)).scalar() or 0
        total_receivable = db.query(func.coalesce(func.sum(FeeRecord.amount_incl_tax), 0)).scalar() or 0
        total_received = db.query(func.coalesce(func.sum(FeeRecord.actual_received_amount), 0)).scalar() or 0

        # 逾期动态判定：应收时间早于今天、且仍有未收余额的记录即为逾期。
        # 不依赖 payment_status 字段里是否有人手工标记为“已逾期”，避免状态无人维护导致逾期金额恒为 0。
        outstanding = FeeRecord.amount_incl_tax - func.coalesce(FeeRecord.actual_received_amount, 0)
        overdue_filter = (
            FeeRecord.planned_receivable_date.isnot(None),
            FeeRecord.planned_receivable_date < today,
            outstanding > 0,
        )
        overdue_amount = db.query(
            func.coalesce(func.sum(outstanding), 0)
        ).filter(*overdue_filter).scalar() or 0
        overdue_count = db.query(func.count(FeeRecord.id)).filter(*overdue_filter).scalar() or 0

        # 合同待办：备案状态不是“已备案”的全部计入（未签订 / 未备案 / 空）
        pending_contract_count = db.query(func.count(Contract.id)).filter(
            func.coalesce(Contract.filing_status, '') != '已备案'
        ).scalar() or 0

        return {
            'company_count': company_count,
            'pipeline_count': pipeline_count,
            'fee_record_count': fee_record_count,
            'total_receivable': total_receivable,
            'total_received': total_received,
            'total_unreceived': total_receivable - total_received,
            'overdue_amount': overdue_amount,
            'overdue_count': overdue_count,
            'pending_contract_count': pending_contract_count,
        }
