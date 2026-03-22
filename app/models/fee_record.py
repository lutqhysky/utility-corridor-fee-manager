from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship
from app.database import Base


class FeeRecord(Base):
    __tablename__ = 'fee_records'

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False)
    pipeline_entry_id = Column(Integer, ForeignKey('pipeline_entries.id'), nullable=True)
    fee_type = Column(String(50), nullable=False)
    charge_period = Column(String(100), nullable=True)
    period_year = Column(Integer, nullable=True)
    period_quarter = Column(Integer, nullable=True)
    amount_excl_tax = Column(Float, nullable=True)
    tax_rate = Column(Float, nullable=True)
    tax_amount = Column(Float, nullable=True)
    amount_incl_tax = Column(Float, nullable=True)
    planned_receivable_date = Column(Date, nullable=True)
    remind_date = Column(Date, nullable=True)
    latest_payment_date = Column(Date, nullable=True)
    actual_received_amount = Column(Float, nullable=True)
    actual_received_date = Column(Date, nullable=True)
    payment_status = Column(String(50), nullable=False, default='待收缴')
    is_invoiced = Column(String(50), nullable=True)
    remark = Column(Text, nullable=True)
    last_reminder_sent_at = Column(DateTime, nullable=True)
    last_reminder_for_date = Column(Date, nullable=True)
    last_reminder_channel = Column(String(50), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    company = relationship('Company', back_populates='fee_records')
    pipeline_entry = relationship('PipelineEntry', back_populates='fee_records')
