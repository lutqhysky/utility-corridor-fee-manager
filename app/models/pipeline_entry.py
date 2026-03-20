from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.database import Base


class PipelineEntryDetail(Base):
    __tablename__ = "pipeline_entry_details"

    id = Column(Integer, primary_key=True, index=True)
    pipeline_entry_id = Column(Integer, ForeignKey("pipeline_entries.id"), nullable=False)

    pipeline_type = Column(String, default="")
    specification = Column(String, default="")
    engineering_quantity = Column(Float, default=0)
    entry_unit_price_excl_tax = Column(Float, default=0)
    entry_amount_excl_tax = Column(Float, default=0)
    maintenance_unit_price_excl_tax = Column(Float, default=0)
    maintenance_amount_excl_tax = Column(Float, default=0)
    remark = Column(String, default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    pipeline_entry = relationship("PipelineEntry", back_populates="details")
