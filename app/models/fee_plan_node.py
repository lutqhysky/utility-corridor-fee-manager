from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey, DateTime, UniqueConstraint, func
from sqlalchemy.orm import relationship
from app.database import Base


class FeePlanNode(Base):
    """收费计划节点：由入廊清单按收费规则推导的一次应收事件（计划层，非台账）。"""

    __tablename__ = 'fee_plan_nodes'
    __table_args__ = (
        UniqueConstraint('pipeline_entry_id', 'fee_type', 'charge_period', name='uq_plan_node_period'),
    )

    id = Column(Integer, primary_key=True, index=True)
    pipeline_entry_id = Column(Integer, ForeignKey('pipeline_entries.id'), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False)

    fee_type = Column(String(50), default='')            # 入廊费 / 日常维护费
    charge_period = Column(String(100), default='')      # 2026年第3季度 / 2026年度 / 入廊费（一次性）
    period_year = Column(Integer, nullable=True)
    period_quarter = Column(Integer, nullable=True)

    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    amount_incl_tax = Column(Float, default=0)           # 应收金额（含税，元）
    planned_receivable_date = Column(Date, nullable=True)
    is_prorated = Column(Integer, default=0)             # 首期按天折算标记

    # 待到期 / 已转记录 / 已取消
    status = Column(String(20), default='待到期')
    fee_record_id = Column(Integer, ForeignKey('fee_records.id'), nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    pipeline_entry = relationship('PipelineEntry', back_populates='fee_plan_nodes')
    company = relationship('Company')
    fee_record = relationship('FeeRecord')
