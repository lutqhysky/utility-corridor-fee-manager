from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text, Numeric, func
from sqlalchemy.orm import relationship
from app.database import Base

class FeeRecord(Base):
    __tablename__ = 'fee_records'

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False)
    pipeline_entry_id = Column(Integer, ForeignKey('pipeline_entries.id'), nullable=True)
    project_name = Column(String(200), nullable=True)
    fee_type = Column(String(50), nullable=False)
    charge_period = Column(String(100), nullable=True)
    period_year = Column(Integer, nullable=True)
    period_quarter = Column(Integer, nullable=True)
    
    # 核心修改：将 Float 替换为 Numeric(18, 2) 代表 18位数，保留2位小数
    amount_excl_tax = Column(Numeric(18, 2), nullable=True)
    tax_rate = Column(Numeric(6, 4), nullable=True) # 税率保留4位小数，如 0.0900
    tax_amount = Column(Numeric(18, 2), nullable=True)
    amount_incl_tax = Column(Numeric(18, 2), nullable=True)
    actual_received_amount = Column(Numeric(18, 2), nullable=True)
    
    planned_receivable_date = Column(Date, nullable=True)
    remind_date = Column(Date, nullable=True)
    latest_payment_date = Column(Date, nullable=True)
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
