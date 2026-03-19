def calc_tax(amount_excl_tax: float | None, tax_rate: float | None) -> tuple[float, float]:
    amount = float(amount_excl_tax or 0)
    rate = float(tax_rate or 0)
    tax_amount = round(amount * rate, 2)
    amount_incl_tax = round(amount + tax_amount, 2)
    return tax_amount, amount_incl_tax
