from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.database import Base


class ReminderLog(Base):
    """提醒发送日志：每次推送（成功/失败）记一条，方便在页面上查看发送历史。"""

    __tablename__ = 'reminder_logs'

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    channel = Column(String(50), nullable=True)      # dingtalk / wecom / bark / gotify
    target = Column(String(255), nullable=True)      # 脱敏后的目标描述
    title = Column(String(255), nullable=True)
    content = Column(Text, nullable=True)
    status = Column(String(20), nullable=True)       # success / failed
    error = Column(Text, nullable=True)

    KIND_SINGLE = 'single'   # 单条到期/逾期提醒
    KIND_DIGEST = 'digest'    # 每日汇总
    KIND_TEST = 'test'        # 测试推送
    kind = Column(String(20), nullable=True, default=KIND_SINGLE)
