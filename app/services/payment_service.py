"""收款流水服务：流水是事实来源，FeeRecord 上的实收总额/日期/状态是缓存。"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.fee_payment import FeePayment
from app.models.fee_record import FeeRecord

EPS = Decimal('0.005')


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


def sync_record_from_payments(db: Session, record: FeeRecord) -> None:
    """按流水重算记录的实收缓存：总额、最近到账日、收缴状态。"""
    payments = (db.query(FeePayment)
                .filter(FeePayment.fee_record_id == record.id)
                .order_by(FeePayment.received_date.asc().nullsfirst(), FeePayment.id.asc())
                .all())
    total = sum((_dec(p.amount) for p in payments), Decimal('0'))
    record.actual_received_amount = total
    dates = [p.received_date for p in payments if p.received_date]
    last_date = max(dates) if dates else None
    record.actual_received_date = last_date
    record.latest_payment_date = last_date
    incl = _dec(record.amount_incl_tax)
    if total >= incl - EPS and incl > 0:
        record.payment_status = '已收缴'
    elif total > 0:
        record.payment_status = '部分收缴'
    elif record.payment_status in ('已收缴', '部分收缴', '已逾期'):
        record.payment_status = '待收缴'


def add_payment(db: Session, record: FeeRecord, amount, received_date: date | None,
                remark: str = '') -> FeePayment:
    payment = FeePayment(fee_record_id=record.id, amount=_dec(amount),
                         received_date=received_date, remark=(remark or '').strip() or None)
    db.add(payment)
    db.flush()
    sync_record_from_payments(db, record)
    db.commit()
    db.refresh(payment)
    return payment


def delete_payment(db: Session, payment: FeePayment) -> FeeRecord:
    record = payment.fee_record
    db.delete(payment)
    db.flush()
    if record is not None:
        sync_record_from_payments(db, record)
    db.commit()
    return record


def backfill_historical_payments(db: Session) -> int:
    """把存量实收总额补登为一条流水（幂等：已有流水的记录跳过）。"""
    created = 0
    records = db.query(FeeRecord).filter(FeeRecord.actual_received_amount.isnot(None)).all()
    for record in records:
        if _dec(record.actual_received_amount) <= 0:
            continue
        exists = (db.query(FeePayment.id)
                  .filter(FeePayment.fee_record_id == record.id).first())
        if exists:
            continue
        fallback_date = record.actual_received_date or record.latest_payment_date
        db.add(FeePayment(
            fee_record_id=record.id,
            amount=_dec(record.actual_received_amount),
            received_date=fallback_date,
            remark='历史实收补登（系统启用流水时一次性导入）'))
        created += 1
    if created:
        db.commit()
    return created
