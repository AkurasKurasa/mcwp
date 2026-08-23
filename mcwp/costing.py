"""The cost model, shared by the data generator and the live engine.

Both sides must price a material line identically, otherwise the budgets in the
training archive would not be comparable to the budgets an engineer types in,
and the overrun classifier would be learning an artefact.
"""

from __future__ import annotations

from .config import DISPOSAL_COST_PER_TONNE, REWORK_LABOUR_RATIO, SALVAGE_RATIO


def line_cost(material, quantity: float, waste_pct: float,
              unit_price: float, labor_index: float) -> dict:
    """Everything one material line costs at a given waste rate.

    `quantity` is the installed takeoff; procurement is grossed up from it.
    """
    waste_pct = float(min(max(waste_pct, 0.0), 0.6))
    order_qty = quantity / (1.0 - waste_pct)
    waste_qty = order_qty - quantity

    procurement = order_qty * unit_price
    wasted_value = waste_qty * unit_price
    landfill_t = waste_qty * material.mass_kg_per_unit * (1 - material.recycle_rate) / 1000.0

    disposal = landfill_t * DISPOSAL_COST_PER_TONNE
    rework = wasted_value * REWORK_LABOUR_RATIO * labor_index
    salvage = wasted_value * material.recycle_rate * SALVAGE_RATIO

    return {
        "order_qty": order_qty,
        "waste_qty": waste_qty,
        "procurement": procurement,
        "wasted_value": wasted_value,
        "disposal": disposal,
        "rework": rework,
        "salvage": salvage,
        "total": procurement + disposal + rework - salvage,
        "waste_tonnes": waste_qty * material.mass_kg_per_unit / 1000.0,
        "co2e_tonnes": waste_qty * material.co2e_kg_per_unit / 1000.0,
    }


def benchmark_cost(priced_lines, region) -> float:
    """What this materials list should cost at list price and baseline waste.

    Same cost components as the realised figure - procurement, rework, disposal,
    less salvage - so a budget set against it is a like-for-like comparison.
    """
    total = 0.0
    for material, quantity, unit_price in priced_lines:
        total += line_cost(material, quantity, material.base_waste,
                           unit_price, region.labor_index)["total"]
    return total
