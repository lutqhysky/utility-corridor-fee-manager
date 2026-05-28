from decimal import Decimal, ROUND_HALF_UP

def calc_tax(amount_excl_tax: float | Decimal | None, tax_rate: float | Decimal | None) -> tuple[Decimal, Decimal]:
    """
    使用 Decimal 进行金融级精确计算，采用四舍五入
    """
    # 将输入统一转为字符串再转 Decimal，避免浮点精度丢失
    amount = Decimal(str(amount_excl_tax or 0))
    rate = Decimal(str(tax_rate or 0))
    
    # 计算税金并保留两位小数（四舍五入）
    tax_amount = (amount * rate).quantize(Decimal('0.00'), rounding=ROUND_HALF_UP)
    
    # 含税总额
    amount_incl_tax = amount + tax_amount
    
    return tax_amount, amount_incl_tax
