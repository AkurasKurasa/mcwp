"""The analysis engine.

Takes what an engineer can state at bid time - project type, materials list,
budget, size, location, duration - and returns:

  * the likely waste rate, per material and for the package
  * the probability the budget is exceeded
  * which materials carry the risk, and why
  * the contingency that brings the overrun risk down to a stated target
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone

import numpy as np

from . import backends, catalog, costing
from .config import (DISPOSAL_COST_PER_TONNE, MODEL_BACKEND, REWORK_LABOUR_RATIO,
                     SALVAGE_RATIO, SIMULATIONS, TARGET_OVERRUN_RISK)
from .model import get_bundle

MAX_LINES = 10

DEFAULT_PROJECT = {
    "project_name": "",
    "project_type": "com_office",
    "region": "midwest",
    "project_area": 9200.0,
    "duration_weeks": 40.0,
    "budget": 0.0,
}

_BOUNDS = {
    "project_area": (50.0, 500_000.0),
    "duration_weeks": (2.0, 260.0),
    "budget": (0.0, 5_000_000_000.0),
}


# ----------------------------------------------------------------- input prep

def _number(raw, fallback=0.0):
    try:
        value = float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return float(fallback)
    return float(value) if math.isfinite(value) else float(fallback)


def suggested_lines(project_type: str, area: float) -> list:
    """A sensible starting materials list for a project of this type and size."""
    from .datagen import PALETTES
    family = catalog.PROJECT_TYPE_INDEX[project_type].family
    return [{"material": key,
             "quantity": round(catalog.QUANTITY_PER_1000M2[key] * area / 1000.0, 1)}
            for key in PALETTES[family][:5]]


def normalise(raw: dict) -> dict:
    """Coerce an arbitrary form or JSON payload into a clean project record."""
    clean = dict(DEFAULT_PROJECT)

    ptype = str(raw.get("project_type") or "").strip()
    clean["project_type"] = ptype if ptype in catalog.PROJECT_TYPE_INDEX \
        else DEFAULT_PROJECT["project_type"]
    region = str(raw.get("region") or "").strip()
    clean["region"] = region if region in catalog.REGION_INDEX else DEFAULT_PROJECT["region"]

    for field in ("project_area", "duration_weeks", "budget"):
        low, high = _BOUNDS[field]
        clean[field] = min(max(_number(raw.get(field), DEFAULT_PROJECT[field]), low), high)

    clean["project_name"] = str(raw.get("project_name", "")).strip()[:120] or "Untitled Project"

    choice = str(raw.get("backend") or "").strip()
    spec = backends.BACKENDS.get(choice)
    clean["backend"] = choice if spec is not None and spec.available else MODEL_BACKEND

    # Materials list: accept a list of dicts, or parallel arrays from a form post.
    lines = raw.get("lines")
    if not isinstance(lines, list):
        keys = raw.get("material[]") or raw.get("material") or []
        quantities = raw.get("quantity[]") or raw.get("quantity") or []
        if isinstance(keys, str):
            keys, quantities = [keys], [quantities]
        lines = [{"material": k, "quantity": q} for k, q in zip(keys, quantities)]

    cleaned, seen = [], set()
    for line in lines[: MAX_LINES * 2]:
        key = str((line or {}).get("material", "")).strip()
        if key not in catalog.MATERIAL_INDEX or key in seen:
            continue
        quantity = _number((line or {}).get("quantity"), 0.0)
        if quantity <= 0:
            continue
        seen.add(key)
        cleaned.append({"material": key, "quantity": min(quantity, 5_000_000.0)})
        if len(cleaned) >= MAX_LINES:
            break

    clean["lines"] = cleaned or suggested_lines(clean["project_type"], clean["project_area"])
    return clean


# --------------------------------------------------------------- cost helpers

_line_cost = costing.line_cost


def _reference() -> str:
    stamp = datetime.now(timezone.utc).strftime("%y%m%d%H%M%S%f")
    digest = hashlib.sha1(stamp.encode()).hexdigest()[:4].upper()
    return f"MC-{stamp[:10]}-{digest}"


def _verdict(probability: float) -> dict:
    """Severity reads as contrast, not hue: the worse it is, the brighter it is."""
    if probability >= 0.65:
        return {"label": "Overrun likely", "tone": "rose", "colour": "var(--tone-1)"}
    if probability >= 0.40:
        return {"label": "Overrun plausible", "tone": "amber", "colour": "var(--tone-2)"}
    if probability >= 0.20:
        return {"label": "Holds, with watch items", "tone": "cyan", "colour": "var(--tone-3)"}
    return {"label": "Budget looks sound", "tone": "mint", "colour": "var(--tone-4)"}


# ---------------------------------------------------------------- the analysis

def analyse(raw: dict) -> dict:
    project = normalise(raw)
    bundle = get_bundle(project["backend"])
    ptype = catalog.PROJECT_TYPE_INDEX[project["project_type"]]
    region = catalog.REGION_INDEX[project["region"]]

    area = project["project_area"]
    duration = project["duration_weeks"]
    line_count = len(project["lines"])

    # ---- benchmark cost sets the scale the budget is judged against
    priced = []
    for line in project["lines"]:
        material = catalog.MATERIAL_INDEX[line["material"]]
        unit_price = material.unit_cost * region.cost_index
        priced.append({
            "material": material,
            "quantity": line["quantity"],
            "unit_price": unit_price,
            "gross": line["quantity"] * unit_price,
        })

    total_gross = sum(item["gross"] for item in priced) or 1.0
    benchmark_cost = costing.benchmark_cost(
        [(item["material"], item["quantity"], item["unit_price"]) for item in priced], region)

    budget = project["budget"]
    auto_budget = budget <= 0
    if auto_budget:
        budget = benchmark_cost      # no budget stated: judge against benchmark
    budget_ratio = budget / max(benchmark_cost, 1.0)
    schedule_intensity = area / max(duration, 1.0)

    # ---- waste forecast, one row per material line
    records = [{
        "material": item["material"].key,
        "project_type": ptype.key,
        "region": region.key,
        "quantity_log": float(np.log1p(item["quantity"])),
        "project_area_log": float(np.log1p(area)),
        "duration_weeks": duration,
        "line_count": float(line_count),
        "line_value_share": item["gross"] / total_gross,
        "budget_ratio": budget_ratio,
        "schedule_intensity": schedule_intensity,
    } for item in priced]

    band = bundle.predict_waste(records)

    results, expected_waste = [], 0.0
    for item, record, centre, low, high in zip(
            priced, records, band["center"], band["low"], band["high"]):
        material = item["material"]
        quantity, price, labour = item["quantity"], item["unit_price"], region.labor_index
        stack = _line_cost(material, quantity, centre, price, labour)
        low_stack = _line_cost(material, quantity, low, price, labour)
        high_stack = _line_cost(material, quantity, high, price, labour)

        share = record["line_value_share"]
        expected_waste += share * float(centre)

        results.append({
            "key": material.key,
            "name": material.name,
            "category": material.category,
            "unit": material.unit,
            "accent": material.accent,
            "quantity": round(item["quantity"], 2),
            "unit_price": round(item["unit_price"], 2),
            "waste_pct": round(float(centre) * 100, 2),
            "waste_low": round(float(low) * 100, 2),
            "waste_high": round(float(high) * 100, 2),
            "benchmark_pct": round(material.base_waste * 100, 2),
            "order_qty": round(stack["order_qty"], 2),
            "waste_qty": round(stack["waste_qty"], 2),
            "wasted_value": round(stack["wasted_value"], 2),
            "procurement": round(stack["procurement"], 2),
            "total": round(stack["total"], 2),
            "total_low": round(low_stack["total"], 2),
            "total_high": round(high_stack["total"], 2),
            "co2e_tonnes": round(stack["co2e_tonnes"], 2),
            "waste_tonnes": round(stack["waste_tonnes"], 2),
            "value_share": round(share * 100, 1),
            "volatility": material.volatility,
            "fragility": material.fragility,
            "lead_time_days": material.lead_time_days,
        })

    expected_cost = sum(row["total"] for row in results)
    wasted_value = sum(row["wasted_value"] for row in results)
    weights = np.array([row["value_share"] / 100 for row in results])

    # ---- learned probability that this budget is exceeded
    project_record = {
        "project_type": ptype.key,
        "region": region.key,
        "project_area_log": float(np.log1p(area)),
        "duration_weeks": duration,
        "line_count": float(line_count),
        "budget_ratio": budget_ratio,
        "budget_per_m2": budget / max(area, 1.0),
        "schedule_intensity": schedule_intensity,
        "expected_waste": expected_waste,
        "mix_concentration": float(np.sum(weights ** 2)),
        "fragile_share": float(sum(w for w, r in zip(weights, results) if r["fragility"] > 0.35)),
        "volatility_weighted": float(sum(w * r["volatility"] for w, r in zip(weights, results))),
    }
    classifier_risk = bundle.predict_overrun(project_record)

    simulation = _simulate(priced, band["center"], bundle.residual_sigma, region, budget)
    risks = _rank_risk(results, simulation["line_sigma"], expected_cost)
    advice = _recommendations(results, risks, schedule_intensity, budget_ratio,
                              simulation, ptype)

    return {
        "reference": _reference(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": {
            **project,
            "budget": round(budget, 2),
            "auto_budget": auto_budget,
            "project_type_name": ptype.name,
            "project_type_family": ptype.family,
            "region_name": region.name,
            "cost_index": region.cost_index,
            "schedule_intensity": round(schedule_intensity, 1),
        },
        "waste": {
            "pct": round(expected_waste * 100, 2),
            "low_pct": round(float(np.average([r["waste_low"] for r in results], weights=weights)), 2),
            "high_pct": round(float(np.average([r["waste_high"] for r in results], weights=weights)), 2),
            "benchmark_pct": round(float(np.average([r["benchmark_pct"] for r in results], weights=weights)), 2),
            "wasted_value": round(wasted_value, 2),
            "tonnes": round(sum(r["waste_tonnes"] for r in results), 2),
            "co2e_tonnes": round(sum(r["co2e_tonnes"] for r in results), 2),
        },
        "cost": {
            "benchmark": round(benchmark_cost, 2),
            "expected": round(expected_cost, 2),
            "budget": round(budget, 2),
            "budget_ratio": round(budget_ratio, 3),
            "variance": round(budget - expected_cost, 2),
            "procurement": round(sum(r["procurement"] for r in results), 2),
        },
        "overrun": {
            "probability": round(classifier_risk * 100, 1),
            "simulated": round(simulation["sim_risk"] * 100, 1),
            "verdict": _verdict(classifier_risk),
            "p10": round(simulation["p10"], 2),
            "p50": round(simulation["p50"], 2),
            "p90": round(simulation["p90"], 2),
            "histogram": simulation["histogram"],
        },
        "buffer": simulation["buffer"],
        "lines": results,
        "risks": risks,
        "advice": advice,
        "model": bundle.metrics,
    }


# ------------------------------------------------------------ cost simulation

def _simulate(priced, centres, residual_sigma, region, budget) -> dict:
    """Monte Carlo over waste uncertainty and price dispersion.

    Waste is drawn around the model's own central forecast using the residual
    spread measured on held-out lines; unit prices are drawn from regional and
    commodity dispersion. The distribution is left at its own level - it is a
    cost forecast, and the buffer is the distance from the budget to its 90th
    percentile. The learned classifier is reported alongside as a second,
    independent read on overrun risk rather than being used to bend this curve.
    """
    rng = np.random.default_rng(4242)
    totals = np.zeros(SIMULATIONS)
    line_sigma = []

    for item, centre in zip(priced, centres):
        material = item["material"]
        quantity = item["quantity"]

        waste = np.clip(
            float(centre) * rng.lognormal(-0.5 * residual_sigma ** 2,
                                          residual_sigma, SIMULATIONS),
            0.002, 0.58)
        price_sigma = float(np.hypot(region.volatility, material.volatility))
        price = item["unit_price"] * rng.lognormal(-0.5 * price_sigma ** 2,
                                                   price_sigma, SIMULATIONS)

        order = quantity / (1.0 - waste)
        wasted = order - quantity
        wasted_value = wasted * price
        landfill_t = wasted * material.mass_kg_per_unit * (1 - material.recycle_rate) / 1000.0

        cost = (order * price
                + landfill_t * DISPOSAL_COST_PER_TONNE
                + wasted_value * REWORK_LABOUR_RATIO * region.labor_index
                - wasted_value * material.recycle_rate * SALVAGE_RATIO)
        totals += cost
        line_sigma.append(float(np.std(cost)))

    p10, p50, p90 = (float(np.quantile(totals, q)) for q in (0.10, 0.50, 0.90))
    sim_risk = float(np.mean(totals > budget))
    safe_budget = float(np.quantile(totals, 1.0 - TARGET_OVERRUN_RISK))
    buffer_amount = max(safe_budget - budget, 0.0)

    counts, edges = np.histogram(totals, bins=26)
    histogram = [{"x": round(float((edges[i] + edges[i + 1]) / 2), 2), "n": int(counts[i])}
                 for i in range(len(counts))]

    return {
        "p10": p10, "p50": p50, "p90": p90,
        "sim_risk": sim_risk,
        "line_sigma": line_sigma,
        "histogram": histogram,
        "buffer": {
            "amount": round(buffer_amount, 2),
            "pct_of_budget": round(buffer_amount / max(budget, 1.0) * 100, 2),
            "recommended_budget": round(budget + buffer_amount, 2),
            "target_risk": round(TARGET_OVERRUN_RISK * 100),
            "adequate": buffer_amount <= 0.5,
        },
    }


# ------------------------------------------------------------ risk attribution

def _rank_risk(lines, line_sigma, expected_cost) -> list:
    """Score each material on money at stake, uncertainty and price exposure.

    Scored relative to the rest of the package, so the ranking means the same
    thing on a three-line fit-out as on a ten-line tower. A share of 40% or more
    of the package's variance or waste value saturates that component.
    """
    total_variance = sum(sigma ** 2 for sigma in line_sigma) or 1.0
    total_wasted = sum(row["wasted_value"] for row in lines) or 1.0

    scored = []
    for row, sigma in zip(lines, line_sigma):
        variance_share = sigma ** 2 / total_variance
        wasted_share = row["wasted_value"] / total_wasted
        waste_penalty = max(row["waste_pct"] - row["benchmark_pct"], 0)

        score = (40 * min(variance_share / 0.40, 1.0)
                 + 25 * min(wasted_share / 0.40, 1.0)
                 + 15 * min(waste_penalty / 4.0, 1.0)
                 + 12 * min(row["volatility"] / 0.20, 1.0)
                 + 8 * row["fragility"])

        reasons = []
        if variance_share > 0.28:
            reasons.append(f"drives {variance_share * 100:.0f}% of the cost variance")
        if row["waste_pct"] > row["benchmark_pct"] + 0.8:
            reasons.append(f"{row['waste_pct']:.1f}% forecast against a "
                           f"{row['benchmark_pct']:.1f}% benchmark")
        if row["volatility"] >= 0.14:
            reasons.append("volatile unit price")
        if row["fragility"] >= 0.5:
            reasons.append("damage-prone in handling")
        if row["value_share"] >= 30:
            reasons.append(f"{row['value_share']:.0f}% of package value")
        if row["lead_time_days"] >= 30:
            reasons.append(f"{row['lead_time_days']}-day lead time")
        if not reasons:
            reasons.append("stable and inside benchmark")

        scored.append({
            "key": row["key"],
            "name": row["name"],
            "accent": row["accent"],
            "unit": row["unit"],
            "score": int(min(round(score), 100)),
            "band": "high" if score >= 55 else "medium" if score >= 32 else "low",
            "variance_share": round(variance_share * 100, 1),
            "wasted_value": row["wasted_value"],
            "waste_pct": row["waste_pct"],
            "benchmark_pct": row["benchmark_pct"],
            "value_share": row["value_share"],
            "cost_low": row["total_low"],
            "cost_high": row["total_high"],
            "reasons": reasons,
        })

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored


def _recommendations(lines, risks, schedule_intensity, budget_ratio,
                     simulation, ptype) -> list:
    """Concrete, ordered actions tied to what the numbers actually say."""
    advice = []
    buffer = simulation["buffer"]

    if not buffer["adequate"]:
        advice.append({
            "title": f"Carry a {buffer['pct_of_budget']:.1f}% contingency",
            "detail": (f"A buffer of ${buffer['amount']:,.0f} takes the working budget to "
                       f"${buffer['recommended_budget']:,.0f} and holds overrun risk at "
                       f"{buffer['target_risk']}%."),
            "tone": "violet",
        })
    else:
        advice.append({
            "title": "The stated budget already carries enough cover",
            "detail": (f"The 90th-percentile outturn is ${simulation['p90']:,.0f}, inside the "
                       "budget. No additional contingency is indicated."),
            "tone": "mint",
        })

    if budget_ratio < 0.92:
        advice.append({
            "title": "The budget sits below benchmark for this scope",
            "detail": (f"At {budget_ratio * 100:.0f}% of benchmark cost this package is priced "
                       "tight. In the archive that correlates with thinner supervision and "
                       "higher waste, which the forecast above already reflects."),
            "tone": "rose",
        })

    top = risks[0] if risks else None
    if top and top["band"] != "low":
        advice.append({
            "title": f"Put {top['name']} under tighter control",
            "detail": (f"It carries {top['variance_share']:.0f}% of the cost variance and "
                       f"${top['wasted_value']:,.0f} of forecast waste. Tighten the takeoff, "
                       "sequence deliveries and fix the price early."),
            "tone": "amber",
        })

    long_lead = [row for row in lines if row["lead_time_days"] >= 30]
    if long_lead:
        names = ", ".join(row["name"] for row in long_lead[:3])
        advice.append({
            "title": "Lock the long-lead items now",
            "detail": (f"{names} run {max(row['lead_time_days'] for row in long_lead)} days or "
                       "more. Ordering these late is the usual route into an overrun."),
            "tone": "cyan",
        })

    over = [row for row in lines if row["waste_pct"] > row["benchmark_pct"] + 1.5]
    if over:
        worst = max(over, key=lambda row: row["waste_pct"] - row["benchmark_pct"])
        advice.append({
            "title": f"{worst['name']} is forecast well above benchmark",
            "detail": (f"{worst['waste_pct']:.1f}% against {worst['benchmark_pct']:.1f}%. "
                       "Cut-list optimisation, offcut reuse and covered storage are the levers "
                       "that close that gap."),
            "tone": "amber",
        })

    if schedule_intensity > max(ptype.typical_area / 30, 40):
        advice.append({
            "title": "The programme is compressed for a job this size",
            "detail": (f"{schedule_intensity:.0f} m² per week is fast for a "
                       f"{ptype.name.lower()}. Compression pushes waste up through rework "
                       "and double-handling."),
            "tone": "rose",
        })

    return advice[:5]
