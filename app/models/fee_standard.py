from sqlalchemy import Boolean, Column, Date, DateTime, Float, Integer, String, Text, func
from app.database import Base


class FeeStandard(Base):
    __tablename__ = 'fee_standards'

    id = Column(Integer, primary_key=True, index=True)
    fee_type = Column(String(50), nullable=False)
    pipeline_type = Column(String(100), nullable=True)
    specification = Column(String(255), nullable=True)
    unit_price_excl_tax = Column(Float, nullable=True)
    billing_unit = Column(String(100), nullable=True)
    tax_rate = Column(Float, nullable=True)
    price_period = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    effective_date = Column(Date, nullable=True)
    remark = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
