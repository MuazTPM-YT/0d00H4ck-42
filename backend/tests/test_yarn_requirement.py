from decimal import Decimal
from types import SimpleNamespace

from app.core.enums import Stage
from app.core.units import yarn_kg_for_fabric
from app.modules.orders.service import RAW_WHITE, yarn_components


def fabric(stages, recipe):
    return SimpleNamespace(
        width_cm=Decimal(150),
        gsm=Decimal(120),
        process_loss_pct=Decimal(10),
        stages=[SimpleNamespace(stage=s) for s in stages],
        recipe=[SimpleNamespace(fibre="Cotton", count=c, share_pct=Decimal(p)) for c, p in recipe],
    )


def test_formula_worked_example():
    # 1000 m x 1.5 m x 120 g/m2 / 1000 = 180 kg fabric; / (1 - 0.10) = 200 kg yarn
    assert yarn_kg_for_fabric(Decimal(1000), Decimal(150), Decimal(120), Decimal(10)) == Decimal(
        "200.000"
    )


def test_split_by_recipe_share_keeps_order_colour_without_dyeing():
    lines = yarn_components(
        Decimal(1000), fabric([Stage.weaving], [("Ne 40/1", 60), ("Ne 30/1", 40)]), "Navy"
    )
    assert [(x["count"], x["kg_needed"], x["colour"]) for x in lines] == [
        ("Ne 40/1", Decimal("120.000"), "Navy"),
        ("Ne 30/1", Decimal("80.000"), "Navy"),
    ]


def test_dyed_route_needs_raw_white_yarn():
    lines = yarn_components(
        Decimal(1000), fabric([Stage.weaving, Stage.dyeing], [("Ne 40/1", 100)]), "Maroon"
    )
    assert lines[0]["colour"] == RAW_WHITE
    assert lines[0]["kg_needed"] == Decimal("200.000")


def test_rounds_to_grams():
    # 333 m x 1.47 x 115 / 1000 / 0.95 = 59.25647 kg, kept to the gram
    assert yarn_kg_for_fabric(Decimal(333), Decimal(147), Decimal(115), Decimal(5)) == Decimal(
        "59.256"
    )
