import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import AppSetting, FeeRecord


SUPPORTED_CHANNELS = {'dingtalk', 'wecom'}
REMINDER_SETTING_KEYS = {
    'channel': 'fee_reminder_channel',
    'webhook_url': 'fee_reminder_webhook',
    'days_ahead': 'fee_reminder_days_ahead',
    'check_interval_seconds': 'fee_reminder_check_interval_seconds',
}


@dataclass
class ReminderSettings:
    enabled: bool
    channel: str
    webhook_url: str
    days_ahead: int
    check_interval_seconds: int


@dataclass
class ReminderRunResult:
    enabled: bool
    sent_count: int
    skipped_count: int
    message: str


def get_int_env(name: str, default: int, minimum: int) -> int:
    raw_value = os.getenv(name, '').strip()
    if not raw_value:
        return max(default, minimum)

    try:
        return max(int(raw_value), minimum)
    except ValueError:
        return max(default, minimum)


def get_int_value(raw_value: str, default: int, minimum: int) -> int:
    if not raw_value:
        return max(default, minimum)

    try:
        return max(int(raw_value), minimum)
    except ValueError:
        return max(default, minimum)


def get_reminder_setting_values(db: Session) -> dict[str, str]:
    rows = (
        db.query(AppSetting)
        .filter(AppSetting.key.in_(REMINDER_SETTING_KEYS.values()))
        .all()
    )
    return {row.key: row.value or '' for row in rows}


def get_reminder_settings(db: Session | None = None) -> ReminderSettings:
    owns_session = db is None
    session = db or SessionLocal()
    setting_values = get_reminder_setting_values(session)

    channel = (
        setting_values.get(REMINDER_SETTING_KEYS['channel'])
        or os.getenv('FEE_REMINDER_CHANNEL', '')
    ).strip().lower()
    webhook_url = (
        setting_values.get(REMINDER_SETTING_KEYS['webhook_url'])
        or os.getenv('FEE_REMINDER_WEBHOOK', '')
    ).strip()
    days_ahead = get_int_value(
        setting_values.get(REMINDER_SETTING_KEYS['days_ahead'], ''),
        default=get_int_env('FEE_REMINDER_DAYS_AHEAD', default=3, minimum=0),
        minimum=0,
    )
    check_interval_seconds = get_int_value(
        setting_values.get(REMINDER_SETTING_KEYS['check_interval_seconds'], ''),
        default=get_int_env('FEE_REMINDER_CHECK_INTERVAL_SECONDS', default=300, minimum=60),
        minimum=60,
    )
    enabled = channel in SUPPORTED_CHANNELS and bool(webhook_url)
    settings = ReminderSettings(
        enabled=enabled,
        channel=channel,
        webhook_url=webhook_url,
        days_ahead=days_ahead,
        check_interval_seconds=check_interval_seconds,
    )
    if owns_session:
        session.close()
    return settings


def save_reminder_settings(
    db: Session,
    channel: str,
    webhook_url: str,
    days_ahead: int,
    check_interval_seconds: int,
):
    values = {
        REMINDER_SETTING_KEYS['channel']: channel.strip().lower(),
        REMINDER_SETTING_KEYS['webhook_url']: webhook_url.strip(),
        REMINDER_SETTING_KEYS['days_ahead']: str(max(days_ahead, 0)),
        REMINDER_SETTING_KEYS['check_interval_seconds']: str(max(check_interval_seconds, 60)),
    }

    existing_rows = (
        db.query(AppSetting)
        .filter(AppSetting.key.in_(values.keys()))
        .all()
    )
    existing_by_key = {row.key: row for row in existing_rows}

    for key, value in values.items():
        row = existing_by_key.get(key)
        if row:
            row.value = value
            continue
        db.add(AppSetting(key=key, value=value))

    db.commit()
    return get_reminder_settings(db)


def build_fee_reminder_message(record: FeeRecord, today: date, days_ahead: int) -> str:
    company_name = record.company.short_name or record.company.company_name
    project_name = record.pipeline_entry.project_name if record.pipeline_entry else '未关联入廊项目'
    due_date = record.planned_receivable_date.isoformat() if record.planned_receivable_date else '未设置'
    amount = f'{record.amount_incl_tax or 0:.2f}'
    remaining_days = (record.planned_receivable_date - today).days if record.planned_receivable_date else None
    remaining_text = f'距应收时间还有 {remaining_days} 天' if remaining_days is not None else '应收时间未设置'

    return (
        f'【收费提醒】\n'
        f'单位：{company_name}\n'
        f'项目：{project_name}\n'
        f'收费类型：{record.fee_type}\n'
        f'收费期间：{record.charge_period or "未填写"}\n'
        f'状态：{record.payment_status}\n'
        f'应收时间：{due_date}\n'
        f'含税金额：{amount} 元\n'
        f'{remaining_text}（提醒阈值：提前 {days_ahead} 天）\n'
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


def run_fee_reminders(db: Session | None = None, today: date | None = None) -> ReminderRunResult:
    owns_session = db is None
    session = db or SessionLocal()
    settings = get_reminder_settings(session)
    if not settings.enabled:
        if owns_session:
            session.close()
        return ReminderRunResult(False, 0, 0, '未启用提醒：请先在网页端或环境变量中配置提醒渠道和 Webhook。')

    current_date = today or date.today()
    deadline = current_date + timedelta(days=settings.days_ahead)
    sent_count = 0
    skipped_count = 0

    try:
        records = (
            session.query(FeeRecord)
            .filter(FeeRecord.payment_status == '未开始')
            .filter(FeeRecord.planned_receivable_date.isnot(None))
            .filter(FeeRecord.planned_receivable_date >= current_date)
            .filter(FeeRecord.planned_receivable_date <= deadline)
            .order_by(FeeRecord.planned_receivable_date.asc())
            .all()
        )

        for record in records:
            if record.last_reminder_for_date == record.planned_receivable_date:
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
            message = f'没有待提醒数据：未来 {settings.days_ahead} 天内没有符合条件的“未开始”收费记录。'
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
        settings = get_reminder_settings()
        while not self._stop_event.is_set():
            run_fee_reminders()
            self._stop_event.wait(settings.check_interval_seconds)


fee_reminder_scheduler = FeeReminderScheduler()
