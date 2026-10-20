"""收费提醒服务。

渠道：钉钉 / 企业微信（机器人 webhook）、Bark（iPhone 推送）、Gotify（自建推送服务）。
配置：优先读数据库 app_settings（提醒设置页可改，实时生效），环境变量作兜底。
可见性：每次发送记 ReminderLog；每次检查记 last_run；每日 09:00（可配）推送汇总。
"""
import json
import logging
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.database import SessionLocal
from app.models import AppSetting, FeeRecord, FeasibilitySubsidyDetail, ReminderLog

logger = logging.getLogger(__name__)

SUPPORTED_CHANNELS = {'dingtalk', 'wecom', 'bark', 'gotify'}
ACTIVE_PAYMENT_STATUSES = {'未开始', '待收缴', '部分收缴', '已逾期'}
MAINTENANCE_FEE_TYPES = {'运维费', '日常维护费', '维护费'}


# ---------------- 配置读写（数据库优先，环境变量兜底） ----------------

def get_setting(db: Session, key: str, default=None):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is None or row.value is None or row.value == '':
        return default
    return row.value


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def _with_own_session(func):
    """用独立会话执行业务，避免与主流程的事务互相影响。"""

    def wrapper(*args, **kwargs):
        session = SessionLocal()
        try:
            result = func(session, *args, **kwargs)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return wrapper


@_with_own_session
def _save_last_run(session: Session, message: str) -> None:
    set_setting(session, 'reminder.last_run_at', datetime.now().isoformat(timespec='seconds'))
    set_setting(session, 'reminder.last_run_summary', message)


@_with_own_session
def _write_log(session: Session, channel: str, target_desc: str, title: str,
               content: str, status: str, error: str, kind: str) -> None:
    session.add(ReminderLog(
        channel=channel,
        target=target_desc,
        title=title,
        content=(content or '')[:2000],
        status=status,
        error=(error or '')[:2000] or None,
        kind=kind,
    ))
    # 只保留最近 500 条日志，避免无限增长
    old_ids = [
        row.id for row in
        session.query(ReminderLog.id).order_by(ReminderLog.id.desc()).offset(500).all()
    ]
    if old_ids:
        session.query(ReminderLog).filter(ReminderLog.id.in_(old_ids)).delete(synchronize_session=False)


def mask_target(channel: str, target) -> str:
    """目标脱敏描述（日志里不出现完整 webhook/密钥）。"""
    if channel in ('dingtalk', 'wecom'):
        try:
            host = urllib.parse.urlparse(target.webhook_url).netloc or target.webhook_url[:24]
        except Exception:
            host = '***'
        return '%s:%s' % (channel, host)
    if channel == 'bark':
        key = target.webhook_url
        if key.startswith('http'):
            return 'bark:%s' % urllib.parse.urlparse(key).netloc
        return 'bark:%s***' % key[:4] if len(key) > 4 else 'bark:***'
    if channel == 'gotify':
        try:
            host = urllib.parse.urlparse(target.webhook_url).netloc or '***'
        except Exception:
            host = '***'
        return 'gotify:%s' % host
    return '%s:***' % channel


# ---------------- 目标与配置 ----------------

@dataclass
class ReminderTarget:
    channel: str
    webhook_url: str  # dingtalk/wecom: webhook；bark: key 或自建 URL；gotify: 服务器地址
    extra: str = ''   # gotify: app token


@dataclass
class ReminderSettings:
    enabled: bool
    targets: list
    days_ahead: int
    check_interval_seconds: int
    repeat_days: int
    daily_digest_enabled: bool = True
    daily_digest_time: str = '09:00'


@dataclass
class ReminderRunResult:
    enabled: bool
    sent_count: int
    skipped_count: int
    message: str


def _append_target_if_valid(targets: list, seen: set, channel: str,
                            webhook_url: str, extra: str = '') -> None:
    normalized_channel = (channel or '').strip().lower()
    normalized_webhook = (webhook_url or '').strip()
    if normalized_channel not in SUPPORTED_CHANNELS or not normalized_webhook:
        return
    key = (normalized_channel, normalized_webhook, (extra or '').strip())
    if key in seen:
        return
    seen.add(key)
    targets.append(ReminderTarget(
        channel=normalized_channel,
        webhook_url=normalized_webhook,
        extra=(extra or '').strip(),
    ))


def _cfg(db: Session, key: str, env_name: str, default: str) -> str:
    value = get_setting(db, key, None)
    if value is not None:
        return value
    return os.getenv(env_name, default)


def _cfg_int(db: Session, key: str, env_name: str, default: int, minimum: int) -> int:
    raw = _cfg(db, key, env_name, str(default))
    try:
        return max(int(raw), minimum)
    except (TypeError, ValueError):
        return default


def get_reminder_settings(db: Session = None):
    """读取提醒配置。db 为空时用独立短会话读取。"""
    owns_session = db is None
    session = db or SessionLocal()
    try:
        targets: list = []
        seen: set = set()

        _append_target_if_valid(targets, seen, 'wecom',
                                _cfg(session, 'reminder.wecom.webhook', 'FEE_REMINDER_WECOM_WEBHOOK', ''))
        # 兼容旧版单通道配置
        _append_target_if_valid(targets, seen,
                                os.getenv('FEE_REMINDER_CHANNEL', ''),
                                os.getenv('FEE_REMINDER_WEBHOOK', ''))
        _append_target_if_valid(targets, seen, 'bark',
                                _cfg(session, 'reminder.bark.key', 'FEE_REMINDER_BARK_KEY', ''))
        _append_target_if_valid(
            targets, seen, 'gotify',
            _cfg(session, 'reminder.gotify.server', 'FEE_REMINDER_GOTIFY_SERVER', ''),
            _cfg(session, 'reminder.gotify.token', 'FEE_REMINDER_GOTIFY_TOKEN', ''),
        )

        days_ahead = _cfg_int(session, 'reminder.days_ahead', 'FEE_REMINDER_DAYS_AHEAD', 30, 0)
        check_interval = _cfg_int(session, 'reminder.check_interval_seconds',
                                  'FEE_REMINDER_CHECK_INTERVAL_SECONDS', 3600, 60)
        repeat_days = _cfg_int(session, 'reminder.repeat_days', 'FEE_REMINDER_REPEAT_DAYS', 2, 1)
        digest_enabled = _cfg(session, 'reminder.daily_digest_enabled',
                              'FEE_REMINDER_DAILY_DIGEST_ENABLED', '1') == '1'
        digest_time = _cfg(session, 'reminder.daily_digest_time',
                           'FEE_REMINDER_DAILY_DIGEST_TIME', '09:00') or '09:00'

        return ReminderSettings(
            enabled=bool(targets),
            targets=targets,
            days_ahead=days_ahead,
            check_interval_seconds=check_interval,
            repeat_days=repeat_days,
            daily_digest_enabled=digest_enabled,
            daily_digest_time=digest_time,
        )
    finally:
        if owns_session:
            session.close()


# ---------------- 消息构造 ----------------

def build_fee_reminder_title(record: FeeRecord, today: date) -> str:
    if record.planned_receivable_date and record.planned_receivable_date < today:
        days = (today - record.planned_receivable_date).days
        return '收费催缴：已逾期%d天' % days
    return '收费提醒'


def build_fee_reminder_message(record: FeeRecord, today: date, days_ahead: int) -> str:
    company_name = record.company.short_name or record.company.company_name
    if record.project_name:
        project_name = record.project_name
    elif record.pipeline_entry and record.pipeline_entry.project_name:
        project_name = record.pipeline_entry.project_name
    else:
        project_name = '未关联入廊项目'
    due_date = record.planned_receivable_date.isoformat() if record.planned_receivable_date else '未设置'
    amount = '%.2f' % float(record.amount_incl_tax or 0)
    unreceived = float(record.amount_incl_tax or 0) - float(record.actual_received_amount or 0)
    remaining_days = (record.planned_receivable_date - today).days if record.planned_receivable_date else None

    if remaining_days is None:
        remaining_text = '应收时间未设置'
    elif remaining_days > 0:
        remaining_text = '距应收时间还有 %d 天' % remaining_days
    elif remaining_days == 0:
        remaining_text = '今天就是应收时间'
    else:
        remaining_text = '已逾期 %d 天' % abs(remaining_days)

    return (
        '【收费提醒】\n'
        '单位：%s\n'
        '项目：%s\n'
        '收费类型：%s\n'
        '收费期间：%s\n'
        '状态：%s\n'
        '应收时间：%s\n'
        '含税金额：%s 元\n'
        '未收金额：%s 元\n'
        '%s（提醒窗口：提前 %d 天）\n'
        '备注：%s' % (
            company_name, project_name, record.fee_type,
            record.charge_period or '未填写', record.payment_status,
            due_date, amount, '%.2f' % unreceived, remaining_text, days_ahead,
            record.remark or '无',
        )
    )


# ---------------- 各渠道发送 ----------------

def send_robot_message(channel: str, webhook_url: str, content: str) -> None:
    """钉钉 / 企业微信机器人：POST JSON 文本消息。"""
    payload = json.dumps({'msgtype': 'text', 'text': {'content': content}}).encode('utf-8')
    request = urllib.request.Request(
        webhook_url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read().decode('utf-8') or '{}'
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        raise ValueError('%s 返回非 JSON 响应（可能是错误页）：%s' % (channel, body[:200]))
    if parsed.get('errcode') not in (None, 0):
        raise ValueError('机器人返回错误：%s' % parsed.get('errmsg', body))


def send_bark_message(key_or_url: str, title: str, content: str) -> None:
    """Bark：GET 推送。key_or_url 可为设备 key（走 api.day.app）或自建服务器完整 URL。"""
    key_or_url = (key_or_url or '').strip().rstrip('/')
    if key_or_url.startswith('http'):
        if key_or_url.count('/') <= 2:
            raise ValueError('Bark 自建地址需包含设备 key')
        url = '%s/%s/%s' % (key_or_url, urllib.parse.quote(title, safe=''),
                            urllib.parse.quote(content[:500], safe=''))
    else:
        if not key_or_url:
            raise ValueError('Bark key 为空')
        url = 'https://api.day.app/%s/%s/%s' % (
            key_or_url, urllib.parse.quote(title, safe=''), urllib.parse.quote(content[:500], safe=''))
    with urllib.request.urlopen(url, timeout=10) as response:
        body = response.read().decode('utf-8') or '{}'
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        raise ValueError('Bark 返回非 JSON 响应（可能是错误页）：%s' % body[:200])
    if parsed.get('code') != 200:
        raise ValueError('Bark 返回错误：%s' % parsed.get('message', body))


def send_gotify_message(server: str, token: str, title: str, content: str,
                        priority: int = 5) -> None:
    """Gotify：POST /message?token=xxx。"""
    server = (server or '').rstrip('/')
    if not server or not token:
        raise ValueError('Gotify 服务器地址或 Token 为空')
    payload = json.dumps({'title': title, 'message': content, 'priority': priority}).encode('utf-8')
    url = '%s/message?token=%s' % (server, urllib.parse.quote(token))
    request = urllib.request.Request(
        url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status not in (200, 201):
            raise ValueError('Gotify 返回 HTTP %s' % response.status)


def send_to_target(target: ReminderTarget, title: str, content: str) -> None:
    if target.channel in ('dingtalk', 'wecom'):
        send_robot_message(target.channel, target.webhook_url, content)
    elif target.channel == 'bark':
        send_bark_message(target.webhook_url, title, content)
    elif target.channel == 'gotify':
        send_gotify_message(target.webhook_url, target.extra, title, content)
    else:
        raise ValueError('不支持的提醒渠道: %s' % target.channel)


# ---------------- 单条提醒 ----------------

def should_send_reminder(record: FeeRecord, current_date: date, repeat_days: int) -> bool:
    if record.payment_status not in ACTIVE_PAYMENT_STATUSES:
        return False
    if not record.planned_receivable_date:
        return False
    if record.last_reminder_sent_at is None:
        return True
    last_sent_date = record.last_reminder_sent_at.date()
    return (current_date - last_sent_date).days >= repeat_days


def get_retry_targets(record, targets):
    """上次发送失败、本轮需要补发的渠道（不含已成功的，也不含已移除的）。"""
    if not record.last_reminder_sent_at:
        return []
    last_success = set((record.last_reminder_channel or '').split(',')) - {''}
    return [t for t in targets if t.channel not in last_success]


def run_fee_reminders(db: Session = None, today: date = None):
    if not _reminder_lock.acquire(blocking=False):
        return ReminderRunResult(False, 0, 0, '已有提醒任务在执行，本次跳过。')
    owns_session = db is None
    session = db or SessionLocal()
    try:
        settings = get_reminder_settings(session)
        if not settings.enabled:
            result = ReminderRunResult(False, 0, 0, '未启用提醒：请在“提醒设置”页配置至少一个推送渠道。')
            _save_last_run(result.message)
            return result

        current_date = today or date.today()
        deadline = current_date + timedelta(days=settings.days_ahead)
        sent_count = 0
        skipped_count = 0
        overdue_sent_count = 0

        # 提醒范围：应收时间落在 (-∞, 今天 + days_ahead] 的未结清记录。
        # 不要加 planned_receivable_date >= today 的下限，否则已逾期记录会被排除、收不到催缴。
        # 只提醒仍有未收余额的：已全额收清但状态未改的不再推送
        outstanding = FeeRecord.amount_incl_tax - func.coalesce(FeeRecord.actual_received_amount, 0)
        records = (
            session.query(FeeRecord)
            .filter(FeeRecord.payment_status.in_(list(ACTIVE_PAYMENT_STATUSES)))
            .filter(FeeRecord.planned_receivable_date.isnot(None))
            .filter(FeeRecord.planned_receivable_date <= deadline)
            .filter(outstanding > 0)
            .order_by(FeeRecord.planned_receivable_date.asc())
            .all()
        )

        for record in records:
            normal_due = should_send_reminder(record, current_date, settings.repeat_days)
            retry_targets = [] if normal_due else get_retry_targets(record, settings.targets)
            if normal_due:
                targets_to_send = settings.targets
            elif retry_targets:
                targets_to_send = retry_targets
            else:
                skipped_count += 1
                continue

            title = build_fee_reminder_title(record, current_date)
            content = build_fee_reminder_message(record, current_date, settings.days_ahead)

            successful_channels: list = []
            for target in targets_to_send:
                desc = mask_target(target.channel, target)
                try:
                    send_to_target(target, title, content)
                    successful_channels.append(target.channel)
                    _write_log(target.channel, desc, title, content, 'success', '',
                               ReminderLog.KIND_SINGLE)
                except Exception as exc:
                    logger.warning('提醒发送失败 channel=%s: %s', target.channel, exc)
                    _write_log(target.channel, desc, title, content, 'failed', str(exc),
                               ReminderLog.KIND_SINGLE)

            if successful_channels:
                if normal_due:
                    record.last_reminder_sent_at = datetime.now()
                    record.last_reminder_for_date = record.planned_receivable_date
                    record.last_reminder_channel = ','.join(successful_channels)
                    sent_count += 1
                    if record.planned_receivable_date < current_date:
                        overdue_sent_count += 1
                else:
                    # 补发：合并成功渠道，不推进时间戳，下轮继续补发剩余失败渠道
                    prev = set((record.last_reminder_channel or '').split(',')) - {''}
                    record.last_reminder_channel = ','.join(sorted(prev | set(successful_channels)))
                    sent_count += 1
                session.commit()

        if sent_count == 0 and skipped_count == 0:
            message = '没有待提醒数据：未来 %d 天内（含已逾期）没有符合条件的收费记录。' % settings.days_ahead
        else:
            message = ('提醒检查完成：已发送 %d 条（其中逾期催缴 %d 条），跳过 %d 条。'
                       % (sent_count, overdue_sent_count, skipped_count))
        result = ReminderRunResult(True, sent_count, skipped_count, message)
        _save_last_run(message)
        return result
    except Exception as exc:
        logger.exception('提醒检查异常')
        if owns_session:
            session.rollback()
        result = ReminderRunResult(True, 0, 0, '提醒发送失败：%s' % exc)
        try:
            _save_last_run(result.message)
        except Exception:
            pass
        return result
    finally:
        _reminder_lock.release()
        if owns_session:
            session.close()


# ---------------- 每日汇总 ----------------

def build_daily_digest(db: Session, today: date):
    """构造每日汇总：已收情况 + 今日到期 / 已逾期 / 未来7天到期。返回 (标题, 正文, 统计)。"""
    outstanding = FeeRecord.amount_incl_tax - func.coalesce(FeeRecord.actual_received_amount, 0)
    base = (
        db.query(FeeRecord)
        .options(joinedload(FeeRecord.company), joinedload(FeeRecord.pipeline_entry))
        .filter(FeeRecord.payment_status.in_(list(ACTIVE_PAYMENT_STATUSES)))
        .filter(FeeRecord.planned_receivable_date.isnot(None))
        .filter(outstanding > 0)
    )
    due_today = base.filter(FeeRecord.planned_receivable_date == today).order_by(
        FeeRecord.amount_incl_tax.desc()).all()
    overdue = base.filter(FeeRecord.planned_receivable_date < today).order_by(
        FeeRecord.planned_receivable_date.asc()).all()
    upcoming = base.filter(
        FeeRecord.planned_receivable_date > today,
        FeeRecord.planned_receivable_date <= today + timedelta(days=7),
    ).order_by(FeeRecord.planned_receivable_date.asc()).all()

    # 到目前为止的实收：按入廊费 / 日常维护费（含别名）拆分
    received_rows = (
        db.query(FeeRecord.fee_type,
                 func.coalesce(func.sum(FeeRecord.actual_received_amount), 0).label('total'))
        .filter(FeeRecord.actual_received_amount.isnot(None))
        .filter(FeeRecord.actual_received_amount > 0)
        .group_by(FeeRecord.fee_type)
        .all()
    )
    entry_received = sum(float(r.total) for r in received_rows
                         if (r.fee_type or '').strip() == '入廊费')
    maint_received = sum(float(r.total) for r in received_rows
                         if (r.fee_type or '').strip() in MAINTENANCE_FEE_TYPES)
    total_received = sum(float(r.total) for r in received_rows)

    def amount_sum(rows) -> float:
        return float(sum(float(r.amount_incl_tax or 0) - float(r.actual_received_amount or 0)
                         for r in rows))

    def line(r: FeeRecord) -> str:
        company_name = r.company.short_name or r.company.company_name if r.company else ''
        project_name = r.project_name or (r.pipeline_entry.project_name if r.pipeline_entry else '')
        name = '%s-%s' % (company_name, project_name) if project_name else company_name
        remain = float(r.amount_incl_tax or 0) - float(r.actual_received_amount or 0)
        due = r.planned_receivable_date.isoformat()
        overdue_days = (today - r.planned_receivable_date).days if r.planned_receivable_date < today else 0
        suffix = '（已逾期%d天）' % overdue_days if overdue_days > 0 else ''
        return '- %s｜%s｜应收%s｜未收¥%s%s' % (name, r.fee_type, due, '%.2f' % remain, suffix)

    # 待收缴明细：逾期优先，其次今日到期，再次未来7天
    all_pending = overdue + due_today + upcoming
    pending_total = amount_sum(all_pending)

    parts = ['1、到目前为止，已收到管廊有偿使用费 ¥%.2f，其中入廊费 ¥%.2f，日常维护费 ¥%.2f。'
             % (total_received, entry_received, maint_received),
             '2、待收缴情况【共%d笔，共计¥%.2f元】' % (len(all_pending), pending_total),
             '具体明细如下：']
    parts += [line(r) for r in all_pending]

    counts = {'due_today': len(due_today), 'overdue': len(overdue),
              'upcoming': len(upcoming),
              'total': len(due_today) + len(overdue) + len(upcoming)}
    title = '小牛管廊项目公司管廊有偿使用费收缴情况【%s】' % today.isoformat()
    return title, '\n'.join(parts), counts


def run_daily_digest(db: Session = None, today: date = None, force: bool = False) -> str:
    """执行每日汇总推送。force=True 时忽略时间/去重检查（用于手动触发和测试）。"""
    if not _reminder_lock.acquire(blocking=False):
        return '已有提醒任务在执行，本次跳过。'
    owns_session = db is None
    session = db or SessionLocal()
    try:
        settings = get_reminder_settings(session)
        if not settings.enabled:
            return '未启用提醒：请先在“提醒设置”页配置推送渠道。'
        if not settings.daily_digest_enabled and not force:
            return '每日汇总未启用。'

        current_date = today or date.today()
        if not force:
            last_date = get_setting(session, 'reminder.last_digest_date', '')
            if last_date == current_date.isoformat():
                return '今日汇总已推送过，不重复发送。'
            try:
                hh, mm = settings.daily_digest_time.split(':')
                if datetime.now().time() < time(int(hh), int(mm)):
                    return '未到推送时间（设定 %s）。' % settings.daily_digest_time
            except (ValueError, AttributeError):
                logger.warning('每日汇总时间配置无效: %s', settings.daily_digest_time)

        title, content, counts = build_daily_digest(session, current_date)
        if counts['total'] == 0:
            # 无数据不写去重标记：当天稍后有数据时仍可推送
            return '今日无到期/逾期数据，汇总已跳过。'

        ok, failed = [], []
        for target in settings.targets:
            desc = mask_target(target.channel, target)
            try:
                send_to_target(target, title, content)
                ok.append(target.channel)
                _write_log(target.channel, desc, title, content, 'success', '',
                           ReminderLog.KIND_DIGEST)
            except Exception as exc:
                failed.append('%s: %s' % (target.channel, exc))
                _write_log(target.channel, desc, title, content, 'failed', str(exc),
                           ReminderLog.KIND_DIGEST)

        # 手动 force 触发不占用正常日报的去重标记；
        # 全部渠道失败时也不写，等调度器下一轮自动重试，避免日报静默丢失
        if not force and ok:
            _mark_digest_done(session, current_date)
        if ok and not failed:
            return '今日汇总已推送（%d 个渠道）：到期 %d 笔、逾期 %d 笔。' % (
                len(ok), counts['due_today'], counts['overdue'])
        if ok:
            return '汇总部分推送成功（%s），失败：%s' % (','.join(ok), '；'.join(failed))
        return '汇总推送失败：%s' % '；'.join(failed)
    finally:
        _reminder_lock.release()
        if owns_session:
            session.close()


def _mark_digest_done(session: Session, today: date) -> None:
    set_setting(session, 'reminder.last_digest_date', today.isoformat())
    session.commit()


# ---------------- 可行性缺口补助汇总 ----------------

def build_subsidy_digest(db: Session):
    """构造可行性缺口补助收款汇总。返回 (标题, 正文)。金额单位：万元。"""
    details = (
        db.query(FeasibilitySubsidyDetail)
        .filter(FeasibilitySubsidyDetail.amount.isnot(None))
        .filter(FeasibilitySubsidyDetail.amount > 0)
        .order_by(FeasibilitySubsidyDetail.received_date.isnot(None).desc(),
                  FeasibilitySubsidyDetail.received_date.asc(),
                  FeasibilitySubsidyDetail.id.asc())
        .all()
    )

    total = sum(float(d.amount or 0) for d in details)
    count = len(details)

    # 按年分组
    by_year: dict[int, list] = {}
    for d in details:
        if d.received_date:
            by_year.setdefault(d.received_date.year, []).append(d)
    year_parts = []
    for year in sorted(by_year):
        y_total = sum(float(d.amount or 0) for d in by_year[year])
        year_parts.append('%d年收到%.2f万/%d笔' % (year, y_total / 10000, len(by_year[year])))

    # 明细表（累计，单位：万元）
    running = 0.0
    lines = []
    for i, d in enumerate(details, 1):
        amt_wan = float(d.amount or 0) / 10000
        running += amt_wan
        date_str = d.received_date.strftime('%Y年%m月%d日') if d.received_date else '未设置'
        lines.append('%d｜%s｜%.2f｜%.2f' % (i, date_str, amt_wan, running))

    parts = ['1、截止目前共收到政府【可行性缺口补助】%.2f万/%d笔。' % (total / 10000, count)]
    if year_parts:
        parts.append('其中' + '，'.join(year_parts) + '。')
    parts += ['明细如下：',
              '序号｜收款日期｜金额(万元)｜累计(万元)'] + lines

    title = '小牛管廊项目公司管廊【可行性缺口补助】收款情况汇总【%s】' % date.today().isoformat()
    return title, '\n'.join(parts), count


def run_subsidy_digest(db: Session = None, today: date = None, force: bool = False) -> str:
    """执行可行性缺口补助汇总推送，每天一次（与收费日报同一时间）。"""
    if not _reminder_lock.acquire(blocking=False):
        return '已有提醒任务在执行，本次跳过。'
    owns_session = db is None
    session = db or SessionLocal()
    try:
        settings = get_reminder_settings(session)
        if not settings.enabled:
            return '未启用提醒：请先在"提醒设置"页配置推送渠道。'

        current_date = today or date.today()
        if not force:
            last_date = get_setting(session, 'reminder.last_subsidy_digest_date', '')
            if last_date == current_date.isoformat():
                return '今日补助汇总已推送过，不重复发送。'
            try:
                hh, mm = settings.daily_digest_time.split(':')
                if datetime.now().time() < time(int(hh), int(mm)):
                    return '未到推送时间（设定 %s）。' % settings.daily_digest_time
            except (ValueError, AttributeError):
                logger.warning('每日汇总时间配置无效: %s', settings.daily_digest_time)

        title, content, count = build_subsidy_digest(session)
        # 无数据时跳过，不写去重标记
        if count == 0:
            return '暂无可行性缺口补助收款数据，汇总已跳过。'

        ok, failed = [], []
        for target in settings.targets:
            desc = mask_target(target.channel, target)
            try:
                send_to_target(target, title, content)
                ok.append(target.channel)
                _write_log(target.channel, desc, title, content, 'success', '',
                           ReminderLog.KIND_DIGEST)
            except Exception as exc:
                failed.append('%s: %s' % (target.channel, exc))
                _write_log(target.channel, desc, title, content, 'failed', str(exc),
                           ReminderLog.KIND_DIGEST)

        # 全部渠道失败时不写去重标记，等调度器下一轮自动重试
        if not force and ok:
            set_setting(session, 'reminder.last_subsidy_digest_date', current_date.isoformat())
            session.commit()
        if ok and not failed:
            return '补助汇总已推送（%d 个渠道）。' % len(ok)
        if ok:
            return '补助汇总部分推送成功（%s），失败：%s' % (','.join(ok), '；'.join(failed))
        return '补助汇总推送失败：%s' % '；'.join(failed)
    finally:
        _reminder_lock.release()
        if owns_session:
            session.close()


# ---------------- 调度器 ----------------

# 提醒互斥锁：手动触发与定时线程互斥，避免并发重复发送
_reminder_lock = threading.Lock()


class FeeReminderScheduler:
    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()

    def start(self):
        # 无条件启动：run_fee_reminders / run_daily_digest 内部已有 enabled 短路检查，
        # 用户后续在设置页补配渠道无需重启进程即可生效。
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name='fee-reminder-scheduler',
            daemon=True,
        )
        self._thread.start()
        logger.info('收费提醒调度器已启动。')

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                run_fee_reminders()
            except Exception:
                logger.exception('定时提醒检查异常')
            try:
                run_daily_digest()
            except Exception:
                logger.exception('每日汇总推送异常')
            try:
                run_subsidy_digest()
            except Exception:
                logger.exception('补助汇总推送异常')
            try:
                interval = get_reminder_settings().check_interval_seconds
            except Exception:
                interval = 3600
            self._stop_event.wait(interval)

    def check_daily_digest_now(self):
        """供外部手动触发一次汇总时间检查（测试用）。"""
        run_daily_digest()


fee_reminder_scheduler = FeeReminderScheduler()
