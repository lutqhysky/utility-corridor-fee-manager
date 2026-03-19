from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship
from app.database import Base


class Contract(Base):
    __tablename__ = 'contracts'

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False)
    contract_type = Column(String(100), nullable=True)
    contract_name = Column(String(255), nullable=False)
    filing_department = Column(String(255), nullable=True)
    filing_status = Column(String(100), nullable=True)
    sign_date = Column(Date, nullable=True)
    file_path = Column(String(255), nullable=True)
    remark = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    company = relationship('Company', back_populates='contracts')
