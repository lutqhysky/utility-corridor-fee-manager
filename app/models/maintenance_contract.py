from sqlalchemy import Column, Integer, String, Date, Text, DateTime, func
from app.database import Base

class MaintenanceContract(Base):
    __tablename__ = 'maintenance_contracts'

    id = Column(Integer, primary_key=True, index=True)
    contract_name = Column(String(255), nullable=False)     # 合同名称
    party_a = Column(String(255), nullable=False)           # 甲方单位
    party_b = Column(String(255), nullable=False)           # 乙方单位
    sign_date = Column(Date, nullable=True)                 # 合同签订时间
    start_date = Column(Date, nullable=True)                # 开始时间
    end_date = Column(Date, nullable=True)                  # 结束时间
    content = Column(Text, nullable=True)                   # 合同主要内容
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
