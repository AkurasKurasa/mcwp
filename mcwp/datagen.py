"""The synthetic project archive.

Each record is a whole project: a materials list, a budget, a location, a size
and a duration, plus what it actually cost when it finished.

The generator knows things the model never sees - crew quality, storage
discipline, design churn, coordination maturity. Those latent factors move the
outcome, so two projects with identical stated inputs finish differently. That
gap is the irreducible uncertainty the interval and the buffer exist to cover.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import catalog, costing
from .config import (CORPUS_PROJECTS, DISPOSAL_COST_PER_TONNE, RANDOM_SEED,
                     REWORK_LABOUR_RATIO, SALVAGE_RATIO)

# Materials that plausibly appear together, by project family.
PALETTES = {
    "Residential": ["ready_mix_concrete", "dimensional_lumber", "plywood_sheathing",
                    "gypsum_drywall", "mineral_wool", "interior_paint", "ceramic_tile",
                    "copper_piping", "electrical_conduit", "clay_brick", "membrane_roofing"],
    "Commercial": ["ready_mix_concrete", "rebar_steel", "structural_steel", "cmu_block",
                   "glazing_unit", "gypsum_drywall", "mineral_wool", "membrane_roofing",
                   "ceramic_tile", "electrical_conduit", "copper_piping", "interior_paint"],
    "Other": ["ready_mix_concrete", "rebar_steel", "structural_steel", "asphalt_mix",
              "cmu_block", "glazing_unit", "gypsum_drywall", "membrane_roofing",
              "electrical_conduit", "copper_piping", "mineral_wool", "interior_paint"],
}


def _clip(v, lo, hi):
    return float(np.clip(v, lo, hi))


def latent_waste(material, ptype, region, quantity, area, duration,
                 line_count, budget_ratio, site, hidden) -> float:
    """Waste fraction for one material line, given observed and hidden state.

    `site` carries what the engineer can state at bid time about conditions:
    covered storage, how often it rains, and how experienced the contractor is.
    `hidden` keeps what they cannot - design churn, coordination maturity,
    prefabrication - which is what the interval and the buffer exist to cover.
    """
    w = material.base_waste * ptype.waste_multiplier

    # Observable structure ---------------------------------------------------
    # Bigger orders waste proportionally less.
    scale = np.log10(max(quantity, 1.0) / max(_typical(material.key, area), 1.0))
    w *= 1.0 - 0.045 * scale
    # A compressed programme for the area being built raises pressure.
    intensity = area / max(duration, 1.0)
    w *= 1.0 + 0.055 * np.tanh((intensity - _typical_intensity(ptype)) / 220.0)
    # Long jobs drift; short ones are tightly controlled.
    w *= 1.0 + 0.0014 * max(duration - 45, 0)
    # More trades on one package means more interfaces to get wrong.
    w *= 1.0 + 0.012 * max(line_count - 3, 0)
    # A budget squeezed below benchmark buys cheaper crews and thinner supervision.
    w *= 1.0 + 0.28 * max(1.0 - budget_ratio, -0.15)
    # Regional labour markets: expensive labour is usually more productive.
    w *= 1.0 - 0.035 * (region.labor_index - 1.0)

    # Stated site conditions -------------------------------------------------
    # An experienced contractor wastes less, with diminishing returns.
    w *= 1.0 - 0.10 * np.tanh((site["experience_years"] - 12.0) / 12.0)
    # Covered storage, against what a job this size needs. Too little and
    # material sits in the weather and gets damaged, double-handled, lost.
    w *= 1.0 - 0.09 * np.tanh(site["storage_ratio"] - 1.0)
    # Rain costs most on the materials that mind it: boards swell, renders
    # wash, insulation wets out. Structural steel barely notices.
    w *= 1.0 + 0.0075 * site["rain_days"] * (0.35 + material.fragility)

    # Hidden state the engineer cannot state at bid time ---------------------
    w *= 1.0 + 0.0150 * hidden["design_changes"] ** 0.9
    w *= 0.90 if hidden["bim"] else 1.0
    w *= 0.87 if hidden["waste_program"] else 1.0
    w *= 1.0 - 0.0032 * hidden["prefab"]
    w *= 1.0 + 0.00040 * hidden["transport_km"] * (0.4 + material.fragility)

    return _clip(w, 0.004, 0.48)


def _typical(material_key: str, area: float) -> float:
    return catalog.QUANTITY_PER_1000M2[material_key] * area / 1000.0


def _typical_intensity(ptype) -> float:
    return max(ptype.typical_area / 48.0, 12.0)


def benchmark_cost(lines, region, escalation: float = 1.0) -> float:
    """What the materials should cost at the prices of the day, baseline waste.

    A budget is set in the money of its own moment, so the benchmark is
    escalated to the project's completion date exactly as the actuals are.
    """
    priced = [(catalog.MATERIAL_INDEX[key], quantity,
               catalog.MATERIAL_INDEX[key].unit_cost * region.cost_index * escalation)
              for key, quantity in lines]
    return costing.benchmark_cost(priced, region)


def build_corpus(n_projects: int = CORPUS_PROJECTS, seed: int = RANDOM_SEED):
    """Return (project_frame, line_frame) for training."""
    rng = np.random.default_rng(seed)

    project_rows, line_rows = [], []
    start = date(2023, 1, 1)

    for pid in range(1, n_projects + 1):
        ptype = catalog.PROJECT_TYPES[rng.integers(len(catalog.PROJECT_TYPES))]
        region = catalog.REGIONS[rng.integers(len(catalog.REGIONS))]
        completed = start + timedelta(days=int(rng.integers(0, 1150)))

        area = _clip(ptype.typical_area * rng.lognormal(0.0, 0.60), 80, 90000)
        duration = _clip(8 + 0.0030 * area + rng.normal(0, 8), 4, 190)

        palette = PALETTES[ptype.family]
        line_count = int(rng.integers(3, min(8, len(palette)) + 1))
        chosen = list(rng.choice(palette, size=line_count, replace=False))

        lines = []
        for key in chosen:
            quantity = _clip(_typical(key, area) * rng.lognormal(0.0, 0.30), 1.0, 5_000_000)
            lines.append((key, quantity))

        # Prices of the day, applied to both the benchmark and the actuals.
        months = (completed.year - 2023) * 12 + completed.month
        escalation = 1.0 + 0.0030 * months

        benchmark = benchmark_cost(lines, region, escalation)
        # Budgets are set by people: some are tight, most are about right.
        budget_ratio_true = float(_clip(rng.normal(1.02, 0.13), 0.68, 1.55))
        budget = benchmark * budget_ratio_true

        # What the engineer can state about the site.
        storage_need = max(0.02 * area, 12.0)
        storage_m2 = _clip(storage_need * rng.lognormal(0.0, 0.55), 10, 8000)
        site = {
            "storage_m2": storage_m2,
            "storage_ratio": storage_m2 / storage_need,
            "rain_days": _clip(rng.normal(8.0, 4.5), 0, 28),
            "experience_years": _clip(rng.gamma(3.0, 5.0), 1, 40),
        }

        hidden = {
            "design_changes": float(rng.poisson(6 + 0.06 * duration)),
            "bim": int(rng.random() < 0.42),
            "waste_program": int(rng.random() < 0.30),
            "prefab": _clip(rng.gamma(2.0, 9.0), 0, 85),
            "transport_km": _clip(rng.gamma(2.0, 70.0), 3, 2000),
        }

        gross_values = []
        for key, quantity in lines:
            material = catalog.MATERIAL_INDEX[key]
            gross_values.append(quantity * material.unit_cost * region.cost_index)
        total_gross = sum(gross_values) or 1.0

        actual_cost = 0.0
        pending = []
        for (key, quantity), gross in zip(lines, gross_values):
            material = catalog.MATERIAL_INDEX[key]
            share = gross / total_gross

            true_waste = latent_waste(material, ptype, region, quantity, area,
                                      duration, line_count, budget_ratio_true,
                                      site, hidden)
            # Heteroscedastic noise: green crews and cramped sites are also
            # less predictable, not just worse on average.
            sigma = (0.14
                     + 0.10 * max(1.0 - site["experience_years"] / 14.0, 0.0)
                     + 0.07 * max(1.0 - site["storage_ratio"], 0.0))
            realised_waste = _clip(true_waste * rng.lognormal(-0.5 * sigma ** 2, sigma),
                                   0.002, 0.60)

            # Mean-corrected, so price dispersion adds spread without adding drift.
            price_sigma = float(np.hypot(region.volatility, material.volatility))
            unit_price = (material.unit_cost * region.cost_index * escalation
                          * rng.lognormal(-0.5 * price_sigma ** 2, price_sigma))
            stack = costing.line_cost(material, quantity, realised_waste,
                                      unit_price, region.labor_index)
            actual_cost += stack["total"]

            pending.append({
                "project_id": pid,
                "material": key,
                "project_type": ptype.key,
                "region": region.key,
                "quantity": quantity,
                "quantity_log": float(np.log1p(quantity)),
                "project_area": area,
                "project_area_log": float(np.log1p(area)),
                "duration_weeks": duration,
                "line_count": float(line_count),
                "line_value_share": share,
                "budget_ratio": budget_ratio_true,
                "schedule_intensity": area / max(duration, 1.0),
                "storage_ratio": site["storage_ratio"],
                "storage_m2": site["storage_m2"],
                "rain_days": site["rain_days"],
                "experience_years": site["experience_years"],
                "waste_pct": realised_waste,
                "unit_price": unit_price,
                "line_cost": stack["total"],
                "waste_cost": stack["wasted_value"],
            })

        line_rows.extend(pending)

        shares = np.array([row["line_value_share"] for row in pending])
        fragile = sum(row["line_value_share"] for row in pending
                      if catalog.MATERIAL_INDEX[row["material"]].fragility > 0.35)
        vol = sum(row["line_value_share"] * catalog.MATERIAL_INDEX[row["material"]].volatility
                  for row in pending)
        value_weighted_waste = sum(row["line_value_share"] * row["waste_pct"] for row in pending)

        project_rows.append({
            "project_id": pid,
            "project_type": ptype.key,
            "region": region.key,
            "project_area": area,
            "project_area_log": float(np.log1p(area)),
            "duration_weeks": duration,
            "line_count": float(line_count),
            "budget": budget,
            "benchmark_cost": benchmark,
            "budget_ratio": budget_ratio_true,
            "budget_per_m2": budget / max(area, 1.0),
            "schedule_intensity": area / max(duration, 1.0),
            "storage_ratio": site["storage_ratio"],
            "storage_m2": site["storage_m2"],
            "rain_days": site["rain_days"],
            "experience_years": site["experience_years"],
            "mix_concentration": float(np.sum(shares ** 2)),
            "fragile_share": float(fragile),
            "volatility_weighted": float(vol),
            "realised_waste": float(value_weighted_waste),
            "actual_cost": actual_cost,
            "overrun": int(actual_cost > budget),
            "overrun_pct": (actual_cost - budget) / max(budget, 1.0),
            "completed_on": completed.isoformat(),
        })

    return pd.DataFrame(project_rows), pd.DataFrame(line_rows)


# ------------------------------------------------------------ frame coercion

def _categorise(frame: pd.DataFrame, columns) -> pd.DataFrame:
    for column in columns:
        frame[column] = pd.Categorical(frame[column],
                                       categories=catalog.CATEGORY_LEVELS[column])
    return frame


def line_features(records) -> pd.DataFrame:
    frame = pd.DataFrame(records) if not isinstance(records, pd.DataFrame) else records.copy()
    frame = frame[catalog.LINE_FEATURES].copy()
    frame = _categorise(frame, catalog.LINE_CATEGORICALS)
    for column in catalog.LINE_FEATURES:
        if column not in catalog.LINE_CATEGORICALS:
            frame[column] = frame[column].astype(float)
    return frame


def project_features(records) -> pd.DataFrame:
    frame = pd.DataFrame(records) if not isinstance(records, pd.DataFrame) else records.copy()
    frame = frame[catalog.PROJECT_FEATURES].copy()
    frame = _categorise(frame, catalog.PROJECT_CATEGORICALS)
    for column in catalog.PROJECT_FEATURES:
        if column not in catalog.PROJECT_CATEGORICALS:
            frame[column] = frame[column].astype(float)
    return frame
