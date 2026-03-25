import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import FeeRecord


SUPPORTED_CHANNELS = {'dingtalk', 'wecom'}
ACTIVE_PAYMENT_STATUSES = {'未开始', '待收缴', '部分收缴', '已逾期'}


@dataclass
class ReminderSettings:
    enabled: bool
    channel: str
    webhook_url: str
    days_ahead: int
    check_interval_seconds: int
    repeat_days: int


@dataclass
class ReminderRunResult:
    enabled: bool
    sent_count: int
    skipped_count: int
    message: str


def get_reminder_settings() -> ReminderSettings:
    channel = os.getenv('FEE_REMINDER_CHANNEL', '').strip().lower()
    webhook_url = os.getenv('FEE_REMINDER_WEBHOOK', '').strip()
    days_ahead = int(os.getenv('FEE_REMINDER_DAYS_AHEAD', '30'))
    check_interval_seconds = int(os.getenv('FEE_REMINDER_CHECK_INTERVAL_SECONDS', '3600'))
    repeat_days = int(os.getenv('FEE_REMINDER_REPEAT_DAYS', '2'))
    enabled = channel in SUPPORTED_CHANNELS and bool(webhook_url)

    return ReminderSettings(
        enabled=enabled,
        channel=channel,
        webhook_url=webhook_url,
        days_ahead=max(days_ahead, 0),
        check_interval_seconds=max(check_interval_seconds, 60),
        repeat_days=max(repeat_days, 1),
    )


def build_fee_reminder_message(record: FeeRecord, today: date, days_ahead: int) -> str:
    company_name = record.company.short_name or record.company.company_name
    project_name = record.pipeline_entry.project_name if record.pipeline_entry else '未关联入廊项目'
    due_date = record.planned_receivable_date.isoformat() if record.planned_receivable_date else '未设置'
    amount = f'{record.amount_incl_tax or 0:.2f}'
    remaining_days = (record.planned_receivable_date - today).days if record.planned_receivable_date else None

    if remaining_days is None:
        remaining_text = '应收时间未设置'
    elif remaining_days > 0:
        remaining_text = f'距应收时间还有 {remaining_days} 天'
    elif remaining_days == 0:
        remaining_text = '今天就是应收时间'
    else:
        remaining_text = f'已逾期 {abs(remaining_days)} 天'

    return (
        f'【收费提醒】\n'
        f'单位：{company_name}\n'
        f'项目：{project_name}\n'
        f'收费类型：{record.fee_type}\n'
        f'收费期间：{record.charge_period or "未填写"}\n'
        f'状态：{record.payment_status}\n'
        f'应收时间：{due_date}\n'
        f'含税金额：{amount} 元\n'
        f'{remaining_text}（提醒窗口：提前 {days_ahead} 天）\n'
        f'备注：{record.remark or "无"}'
    )


def build_robot_payload(channel: str, content: str) -> dict:
    if channel == 'dingtalk':
        return {
            'msgtype': 'text',
            'text': {'content': content},
        }
    if channel == 'wecom':
        return {
            'msgtype': 'text',
            'text': {'content': content},
        }
    raise ValueError(f'不支持的提醒渠道: {channel}')


def send_robot_message(channel: str, webhook_url: str, content: str):
    payload = json.dumps(build_robot_payload(channel, content)).encode('utf-8')
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read().decode('utf-8') or '{}'

    try:
        parsed_body = json.loads(body)
    except json.JSONDecodeError:
        return

    if channel == 'dingtalk' and parsed_body.get('errcode') not in (None, 0):
        raise ValueError(f"钉钉机器人返回错误：{parsed_body.get('errmsg', body)}")
    if channel == 'wecom' and parsed_body.get('errcode') not in (None, 0):
        raise ValueError(f"企业微信机器人返回错误：{parsed_body.get('errmsg', body)}")


def should_send_reminder(record: FeeRecord, current_date: date, repeat_days: int) -> bool:
    if record.payment_status not in ACTIVE_PAYMENT_STATUSES:
        return False

    if not record.planned_receivable_date:
        return False

    if record.last_reminder_sent_at is None:
        return True

    last_sent_date = record.last_reminder_sent_at.date()
    return (current_date - last_sent_date).days >= repeat_days


def run_fee_reminders(db: Session | None = None, today: date | None = None) -> ReminderRunResult:
    settings = get_reminder_settings()
    if not settings.enabled:
        return ReminderRunResult(False, 0, 0, '未启用提醒：请配置 FEE_REMINDER_CHANNEL 和 FEE_REMINDER_WEBHOOK。')

    owns_session = db is None
    session = db or SessionLocal()
    current_date = today or date.today()
    deadline = current_date + timedelta(days=settings.days_ahead)
    sent_count = 0
    skipped_count = 0

    try:
        records = (
            session.query(FeeRecord)
            .filter(FeeRecord.payment_status.in_(list(ACTIVE_PAYMENT_STATUSES)))
            .filter(FeeRecord.planned_receivable_date.isnot(None))
            .filter(FeeRecord.planned_receivable_date >= current_date)
            .filter(FeeRecord.planned_receivable_date <= deadline)
            .order_by(FeeRecord.planned_receivable_date.asc())
            .all()
        )

        for record in records:
            if not should_send_reminder(record, current_date, settings.repeat_days):
                skipped_count += 1
                continue

            content = build_fee_reminder_message(record, current_date, settings.days_ahead)
            send_robot_message(settings.channel, settings.webhook_url, content)

            record.last_reminder_sent_at = datetime.now()
            record.last_reminder_for_date = record.planned_receivable_date
            record.last_reminder_channel = settings.channel
            session.commit()
            sent_count += 1

        if sent_count == 0 and skipped_count == 0:
            message = f'没有待提醒数据：未来 {settings.days_ahead} 天内没有符合条件的收费记录。'
        else:
            message = f'提醒检查完成：已发送 {sent_count} 条，跳过 {skipped_count} 条。'
        return ReminderRunResult(True, sent_count, skipped_count, message)

    except (urllib.error.URLError, ValueError) as exc:
        if owns_session:
            session.rollback()
        return ReminderRunResult(True, sent_count, skipped_count, f'提醒发送失败：{exc}')
    except Exception as exc:
        if owns_session:
            session.rollback()
        return ReminderRunResult(True, sent_count, skipped_count, f'提醒发送失败：{exc}')
    finally:
        if owns_session:
            session.close()


class FeeReminderScheduler:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self):
        settings = get_reminder_settings()
        if not settings.enabled:
            return
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name='fee-reminder-scheduler',
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)

    def _run_loop(self):
        while not self._stop_event.is_set():
            settings = get_reminder_settings()
            run_fee_reminders()
            self._stop_event.wait(settings.check_interval_seconds)


fee_reminder_scheduler = FeeReminderScheduler()
