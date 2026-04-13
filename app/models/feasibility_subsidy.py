from sqlalchemy import Column, Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class FeasibilitySubsidyPeriod(Base):
    __tablename__ = 'feasibility_subsidy_periods'

    id = Column(Integer, primary_key=True, index=True)
    operating_period = Column(String(100), nullable=False, default='')
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    current_receivable = Column(Float, nullable=False, default=0)
    cumulative_payable = Column(Float, nullable=False, default=0)

    details = relationship(
        'FeasibilitySubsidyDetail',
        back_populates='period',
        cascade='all, delete-orphan',
    )


class FeasibilitySubsidyDetail(Base):
    __tablename__ = 'feasibility_subsidy_details'

    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey('feasibility_subsidy_periods.id'), nullable=False)
    received_date = Column(Date, nullable=True)
    amount = Column(Float, nullable=False, default=0)
    remark = Column(String, nullable=False, default='')

    period = relationship('FeasibilitySubsidyPeriod', back_populates='details')
