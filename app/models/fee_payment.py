from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.orm import relationship

from app.database import Base


class FeePayment(Base):
    """收费记录的收款流水：一笔收费可分多次到账，每次到账一行。

    FeeRecord.actual_received_amount 是流水合计的冗余缓存（日报/看板/汇总
    等既有口径都读它），由 payment_service 在流水增删时统一回写。
    """
    __tablename__ = 'fee_payments'

    id = Column(Integer, primary_key=True, index=True)
    fee_record_id = Column(Integer, ForeignKey('fee_records.id'), nullable=False, index=True)
    amount = Column(Numeric(18, 2), nullable=False)
    received_date = Column(Date, nullable=True)
    remark = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    fee_record = relationship('FeeRecord', back_populates='payments')
