"""提醒设置页：渠道配置、推送策略、测试推送、发送日志。"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from urllib.parse import quote

from app.database import get_db
from app.models import ReminderLog
from app.paths import TEMPLATES_DIR
from app.services.reminder_service import (
    ReminderLog as LogKind,
    get_reminder_settings,
    get_setting,
    mask_target,
    send_to_target,
    set_setting,
)

router = APIRouter(prefix='/settings', tags=['settings'])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

SETTING_FIELDS = [
    # (form 字段名, app_settings key, 默认值)
    ('daily_digest_enabled', 'reminder.daily_digest_enabled', '1'),
    ('daily_digest_time', 'reminder.daily_digest_time', '09:00'),
    ('days_ahead', 'reminder.days_ahead', '30'),
    ('check_interval_seconds', 'reminder.check_interval_seconds', '3600'),
    ('repeat_days', 'reminder.repeat_days', '2'),
    ('wecom_webhook', 'reminder.wecom.webhook', ''),
    ('bark_key', 'reminder.bark.key', ''),
    ('gotify_server', 'reminder.gotify.server', ''),
    ('gotify_token', 'reminder.gotify.token', ''),
]

def read_current(db: Session) -> dict:
    values = {}
    for form_name, key, default in SETTING_FIELDS:
        values[form_name] = get_setting(db, key, default) or ''
    return values


@router.get('/reminders', response_class=HTMLResponse)
def reminders_page(request: Request, db: Session = Depends(get_db), notice: str = ''):
    settings = get_reminder_settings(db)
    return templates.TemplateResponse(
        'settings/reminders.html',
        {
            'request': request,
            'values': read_current(db),
            'settings': settings,
            'notice': notice,
            'title': '提醒设置',
        },
    )


@router.post('/reminders/save')
def save_reminders_form(
    db: Session = Depends(get_db),
    daily_digest_enabled: str = Form(''),
    daily_digest_time: str = Form('09:00'),
    days_ahead: str = Form('30'),
    check_interval_seconds: str = Form('3600'),
    repeat_days: str = Form('2'),
    wecom_webhook: str = Form(''),
    bark_key: str = Form(''),
    gotify_server: str = Form(''),
    gotify_token: str = Form(''),
):
    incoming = {
        'daily_digest_enabled': '1' if daily_digest_enabled else '0',
        'daily_digest_time': (daily_digest_time or '09:00').strip(),
        'days_ahead': (days_ahead or '30').strip(),
        'check_interval_seconds': (check_interval_seconds or '3600').strip(),
        'repeat_days': (repeat_days or '2').strip(),
        'wecom_webhook': wecom_webhook.strip(),
        'bark_key': bark_key.strip(),
        'gotify_server': gotify_server.strip().rstrip('/'),
        'gotify_token': gotify_token.strip(),
    }
    for form_name, key, _default in SETTING_FIELDS:
        set_setting(db, key, incoming[form_name])
    db.commit()
    notice = '提醒设置已保存，实时生效（无需重启）。'
    return RedirectResponse(url=f'/settings/reminders?notice={quote(notice)}', status_code=303)


@router.post('/reminders/test')
def test_reminders(db: Session = Depends(get_db)):
    from app.services import reminder_service as rs

    settings = get_reminder_settings(db)
    if not settings.enabled:
        notice = '未配置任何推送渠道，请先填写至少一个渠道。'
        return RedirectResponse(url=f'/settings/reminders?notice={quote(notice)}', status_code=303)

    title = '提醒测试'
    content = '这是一条来自管廊收费系统的测试提醒，收到说明该渠道配置正确。'
    ok, failed = [], []
    for target in settings.targets:
        desc = mask_target(target.channel, target)
        try:
            send_to_target(target, title, content)
            ok.append(target.channel)
            rs._write_log(target.channel, desc, title, content, 'success', '', LogKind.KIND_TEST)
        except Exception as exc:  # noqa: BLE001
            failed.append(f'{target.channel}: {exc}')
            rs._write_log(target.channel, desc, title, content, 'failed', str(exc), LogKind.KIND_TEST)

    if ok and not failed:
        notice = f'测试推送成功（{", ".join(ok)}），请查收。'
    elif ok:
        notice = f'部分成功（{", ".join(ok)}），失败：{"；".join(failed)}'
    else:
        notice = f'测试推送失败：{"；".join(failed)}'
    return RedirectResponse(url=f'/settings/reminders?notice={quote(notice)}', status_code=303)


@router.post('/reminders/test-subsidy')
def test_subsidy_digest(db: Session = Depends(get_db)):
    from app.services import reminder_service as rs
    result = rs.run_subsidy_digest(db=db, force=True)
    notice = '补助汇总手动推送：' + result
    return RedirectResponse(url=f'/settings/reminders?notice={quote(notice)}', status_code=303)


@router.get('/reminders/logs', response_class=HTMLResponse)
def reminder_logs(request: Request, db: Session = Depends(get_db)):
    logs = db.query(ReminderLog).order_by(ReminderLog.id.desc()).limit(100).all()
    return templates.TemplateResponse(
        'settings/reminder_logs.html',
        {'request': request, 'logs': logs, 'title': '提醒发送日志'},
    )
