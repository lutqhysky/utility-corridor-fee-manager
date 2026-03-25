from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import (
    get_admin_username,
    is_auth_configured,
    is_authenticated,
    login_user,
    logout_user,
    normalize_next_url,
    verify_password,
)
from app.paths import TEMPLATES_DIR

router = APIRouter(tags=['auth'])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get('/login', response_class=HTMLResponse)
def login_page(request: Request, next: str = '/'):
    safe_next = normalize_next_url(next)

    if is_authenticated(request):
        return RedirectResponse(url=safe_next, status_code=303)

    return templates.TemplateResponse(
        'auth/login.html',
        {
            'request': request,
            'title': '管理员登录',
            'error': '',
            'next_url': safe_next,
            'auth_configured': is_auth_configured(),
            'admin_username': get_admin_username(),
        },
    )


@router.post('/login', response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next_url: str = Form('/'),
):
    safe_next = normalize_next_url(next_url)

    context = {
        'request': request,
        'title': '管理员登录',
        'next_url': safe_next,
        'auth_configured': is_auth_configured(),
        'admin_username': get_admin_username(),
        'error': '',
    }

    if not is_auth_configured():
        context['error'] = '系统尚未配置管理员密码，请先配置环境变量。'
        return templates.TemplateResponse('auth/login.html', context, status_code=503)

    if username != get_admin_username() or not verify_password(password):
        context['error'] = '用户名或密码错误。'
        return templates.TemplateResponse('auth/login.html', context, status_code=401)

    login_user(request, get_admin_username())
    return RedirectResponse(url=safe_next, status_code=303)


@router.get('/logout')
def logout(request: Request):
    logout_user(request)
    return RedirectResponse(url='/login', status_code=303)
