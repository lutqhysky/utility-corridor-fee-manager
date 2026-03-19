from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship
from app.database import Base


class PipelineEntry(Base):
    __tablename__ = 'pipeline_entries'

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False)
    cabin_type = Column(String(100), nullable=True)
    project_name = Column(String(255), nullable=True)
    pipeline_type = Column(String(100), nullable=True)
    specification = Column(String(255), nullable=True)
    actual_length = Column(Float, nullable=True)
    quantity_or_hole_count = Column(Float, nullable=True)
    entry_date = Column(Date, nullable=True)
    contract_sign_date_entry = Column(Date, nullable=True)
    contract_sign_date_maintenance = Column(Date, nullable=True)
    has_entry_application = Column(String(50), nullable=True)
    remark = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    company = relationship('Company', back_populates='pipeline_entries')
    fee_records = relationship('FeeRecord', back_populates='pipeline_entry')
