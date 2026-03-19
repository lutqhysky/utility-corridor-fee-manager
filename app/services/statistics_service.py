from sqlalchemy import func
from app.models import Company, FeeRecord, PipelineEntry


class StatisticsService:
    @staticmethod
    def dashboard(db):
        company_count = db.query(func.count(Company.id)).scalar() or 0
        pipeline_count = db.query(func.count(PipelineEntry.id)).scalar() or 0
        fee_record_count = db.query(func.count(FeeRecord.id)).scalar() or 0
        total_receivable = db.query(func.coalesce(func.sum(FeeRecord.amount_incl_tax), 0)).scalar() or 0
        total_received = db.query(func.coalesce(func.sum(FeeRecord.actual_received_amount), 0)).scalar() or 0
        overdue_amount = db.query(
            func.coalesce(func.sum(FeeRecord.amount_incl_tax - func.coalesce(FeeRecord.actual_received_amount, 0)), 0)
        ).filter(FeeRecord.payment_status == '已逾期').scalar() or 0

        return {
            'company_count': company_count,
            'pipeline_count': pipeline_count,
            'fee_record_count': fee_record_count,
            'total_receivable': total_receivable,
            'total_received': total_received,
            'total_unreceived': total_receivable - total_received,
            'overdue_amount': overdue_amount,
        }
