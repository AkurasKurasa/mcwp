"""Worked example projects, for the Load sample button.

Each sample states a budget as a ratio of its own benchmark cost rather than an
absolute figure, so the scenario stays meaningful no matter how the price book
or the quantities are edited.
"""

from __future__ import annotations

from . import catalog, costing

SAMPLES = [
    {
        "project_name": "Harbour Point Tower",
        "project_type": "res_multi",
        "region": "ne_metro",
        "project_area": 14000,
        "duration_weeks": 72,
        "budget_ratio": 0.96,          # priced a little under benchmark
        "lines": [
            ("ready_mix_concrete", 4340),
            ("gypsum_drywall", 17500),
            ("glazing_unit", 2660),
            ("copper_piping", 14000),
            ("interior_paint", 6300),
        ],
    },
    {
        "project_name": "Northgate Logistics Hub",
        "project_type": "com_industrial",
        "region": "midwest",
        "project_area": 21000,
        "duration_weeks": 52,
        "budget_ratio": 1.07,          # comfortable, simple envelope
        "lines": [
            ("structural_steel", 924),
            ("ready_mix_concrete", 6510),
            ("membrane_roofing", 13020),
            ("cmu_block", 88200),
            ("electrical_conduit", 52500),
        ],
    },
    {
        "project_name": "Vessel Street Retail Fit-Out",
        "project_type": "com_retail",
        "region": "west_coast",
        "project_area": 1400,
        "duration_weeks": 18,
        "budget_ratio": 0.89,          # tight money, fast programme, fragile mix
        "lines": [
            ("gypsum_drywall", 1750),
            ("ceramic_tile", 770),
            ("glazing_unit", 266),
            ("interior_paint", 630),
            ("electrical_conduit", 3500),
            ("mineral_wool", 2100),
        ],
    },
    {
        "project_name": "Elmsworth Academy Extension",
        "project_type": "institutional",
        "region": "mid_atlantic",
        "project_area": 6200,
        "duration_weeks": 60,
        "budget_ratio": 1.01,
        "lines": [
            ("ready_mix_concrete", 1922),
            ("clay_brick", 124),
            ("rebar_steel", 174),
            ("gypsum_drywall", 7750),
            ("mineral_wool", 9300),
            ("membrane_roofing", 3844),
        ],
    },
]


def sample(index: int = 0) -> dict:
    """Return one sample with its budget resolved into real money."""
    spec = SAMPLES[index % len(SAMPLES)]
    region = catalog.REGION_INDEX[spec["region"]]

    priced = [(catalog.MATERIAL_INDEX[key], float(quantity),
               catalog.MATERIAL_INDEX[key].unit_cost * region.cost_index)
              for key, quantity in spec["lines"]]
    benchmark = costing.benchmark_cost(priced, region)

    return {
        "project_name": spec["project_name"],
        "project_type": spec["project_type"],
        "region": spec["region"],
        "project_area": spec["project_area"],
        "duration_weeks": spec["duration_weeks"],
        "budget": round(benchmark * spec["budget_ratio"] / 1000) * 1000,
        "lines": [{"material": key, "quantity": quantity} for key, quantity in spec["lines"]],
        "index": index % len(SAMPLES),
        "count": len(SAMPLES),
    }
