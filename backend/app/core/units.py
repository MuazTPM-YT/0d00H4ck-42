from decimal import ROUND_HALF_UP, Decimal

KG = Decimal("0.001")


def qty(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(KG, rounding=ROUND_HALF_UP)


def rupees_to_paise(rupees: Decimal | str | int) -> int:
    return int((Decimal(str(rupees)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# money x quantity, rounded once at the end to whole paise
def line_amount_paise(rate_paise: int, quantity: Decimal) -> int:
    return int((Decimal(rate_paise) * quantity).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# fabric kg = metres x width_m x gsm / 1000; yarn kg = fabric kg / (1 - loss%)
def yarn_kg_for_fabric(
    metres: Decimal, width_cm: Decimal, gsm: Decimal, loss_pct: Decimal
) -> Decimal:
    fabric_kg = Decimal(metres) * (Decimal(width_cm) / 100) * Decimal(gsm) / 1000
    return qty(fabric_kg / (1 - Decimal(loss_pct) / 100))
