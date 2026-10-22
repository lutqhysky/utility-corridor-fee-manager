from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class PipelineEntry(Base):
    __tablename__ = "pipeline_entries"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    cabin_type = Column(String, default="")
    project_name = Column(String, default="")
    pipeline_type = Column(String, default="")
    specification = Column(String, default="")
    actual_length = Column(Float, default=0)
    quantity_or_hole_count = Column(Float, default=0)

    entry_date = Column(Date, nullable=True)
    contract_sign_date_entry = Column(Date, nullable=True)
    contract_sign_date_maintenance = Column(Date, nullable=True)

    has_entry_application = Column(String, default="")
    remark = Column(String, default="")

    entry_fee_tax_rate = Column(Float, default=0)
    maintenance_fee_tax_rate = Column(Float, default=0)

    entry_fee_discount = Column(Float, default=1)
    maintenance_fee_discount = Column(Float, default=1)
    charge_cycle = Column(String(20), default="年度")

    # 收费计划：运维计费起始日（为空则用入廊时间；综改水务等例外单独设）；暂停生成开关
    billing_start_date = Column(Date, nullable=True)
    plan_paused = Column(Integer, default=0)

    company = relationship("Company", back_populates="pipeline_entries")
    fee_records = relationship("FeeRecord", back_populates="pipeline_entry")
    fee_plan_nodes = relationship("FeePlanNode", back_populates="pipeline_entry", cascade="all, delete-orphan")
    details = relationship("PipelineEntryDetail", back_populates="pipeline_entry", cascade="all, delete-orphan")
