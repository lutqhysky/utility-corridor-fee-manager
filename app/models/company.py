from sqlalchemy import Column, DateTime, Integer, String, Text, func
from sqlalchemy.orm import relationship
from app.database import Base


class Company(Base):
    __tablename__ = 'companies'

    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String(255), nullable=False, unique=True)
    short_name = Column(String(100), nullable=True)
    company_type = Column(String(100), nullable=True)
    contact_person = Column(String(100), nullable=True)
    contact_phone = Column(String(100), nullable=True)
    remark = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    pipeline_entries = relationship('PipelineEntry', back_populates='company', cascade='all, delete-orphan')
    fee_records = relationship('FeeRecord', back_populates='company', cascade='all, delete-orphan')
    contracts = relationship('Contract', back_populates='company', cascade='all, delete-orphan')
