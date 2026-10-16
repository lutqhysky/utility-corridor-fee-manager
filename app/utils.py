"""通用工具函数。"""
import json


def safe_json_dumps(data) -> str:
    """序列化为 JSON 并转义尖括号，防止 </script> 突破 script 块造成存储型 XSS。

    模板中仍需配合 |safe 使用（内容已是合法 JSON，转义后不影响 JSON.parse）。
    """
    return (
        json.dumps(data, ensure_ascii=False)
        .replace('<', '\\u003c')
        .replace('>', '\\u003e')
        .replace('&', '\\u0026')
    )


def parse_float_or(value: str | None, default: float = 0.0) -> float:
    """表单数字框安全解析：空字符串/非法值回退为 default，避免 Pydantic 422。"""
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def parse_optional_int(value: str | None) -> int | None:
    """表单整数框安全解析：空字符串/非法值返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def safe_excel_cell(value):
    """Excel 公式注入防护：以 = + - @ 开头的字符串前加单引号，强制按文本处理。"""
    if isinstance(value, str) and value[:1] in ('=', '+', '-', '@'):
        return "'" + value
    return value
