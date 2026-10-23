from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.paths import TEMPLATES_DIR
from app.services.reconciliation_service import get_reconciliation

router = APIRouter(prefix='/reconciliation')
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get('/export')
def export_reconciliation(db: Session = Depends(get_db)):
    """导出勾稽预警清单为 Excel。"""
    from app.utils import xlsx_response
    data = get_reconciliation(db)
    rows = []
    for g in data['groups']:
        for r in g['rows']:
            rows.append([g['title'], r['company_name'], r['entry'].project_name or '',
                         r['entry_date'], r['contract_name'], r['contract_type'],
                         r['status_text']])
    for item in data['unlinked_contracts']:
        c = item['contract']
        rows.append(['合同未关联入廊项目',
                     c.company.short_name or c.company.company_name if c.company else '',
                     '', '', '《%s》' % c.contract_name, c.contract_type or '',
                     c.filing_status or ''])
    return xlsx_response('勾稽预警.xlsx', [(
        '勾稽预警',
        ['问题类型', '单位', '项目', '入廊时间', '合同名', '合同类型', '状态/说明'],
        [18, 16, 26, 12, 28, 14, 30], rows)])


@router.get('/', response_class=HTMLResponse)
def reconciliation_page(request: Request, db: Session = Depends(get_db)):
    data = get_reconciliation(db)
    return templates.TemplateResponse(request, 'reconciliation/list.html', {'data': data})
