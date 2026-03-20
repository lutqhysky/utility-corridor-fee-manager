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

    company = relationship("Company", back_populates="pipeline_entries")
    details = relationship("PipelineEntryDetail", back_populates="pipeline_entry", cascade="all, delete-orphan")
