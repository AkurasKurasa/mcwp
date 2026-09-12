"""MCWP - Material Cost & Waste Prediction.

A single-page Flask tool. An engineer states the project, its materials list,
its budget, size, location and duration; the page returns the likely waste
rate, the probability of a cost overrun, which materials carry the risk, and
the contingency that brings that risk down to target.
"""

from __future__ import annotations

import json
import os
import warnings
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request

warnings.filterwarnings("ignore", category=UserWarning)

from mcwp import backends, catalog, engine, samples
from mcwp.bootstrap import ensure_ready
from mcwp.config import CURRENCY, CURRENCY_SYMBOL, INSTANCE, SIMULATIONS
from mcwp.model import get_bundle

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "mcwp-local-workspace")
app.jinja_env.trim_blocks = True
app.jinja_env.lstrip_blocks = True

METRICS = ensure_ready()


def backend_options() -> list:
    """Every backend, with its measured scores where they have been recorded."""
    measured = {}
    report = INSTANCE / "model_comparison.json"
    if report.exists():
        try:
            for row in json.loads(report.read_text(encoding="utf-8"))["rows"]:
                measured[row["key"]] = row
        except (ValueError, KeyError):
            pass

    options = []
    for item in backends.available():
        row = measured.get(item["key"])
        if row:
            item["r2"] = round(row["waste"]["r2"], 3)
            item["auc"] = round(row["overrun"]["auc"], 3)
            item["mae_pp"] = round(row["waste"]["mae_pp"], 2)
            item["coverage_80"] = round(row["waste"]["coverage_80"], 1)
        options.append(item)
    return options


# --------------------------------------------------------------- jinja filters

@app.template_filter("money")
def money(value, decimals: int = 0) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{'-' if value < 0 else ''}{CURRENCY_SYMBOL}{abs(value):,.{decimals}f}"


@app.template_filter("compact")
def compact(value) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "-"
    sign, value = ("-" if value < 0 else ""), abs(value)
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= limit:
            scaled = value / limit
            return f"{sign}{scaled:.2f}{suffix}" if scaled < 10 else f"{sign}{scaled:.1f}{suffix}"
    return f"{sign}{value:,.0f}"


@app.template_filter("money_compact")
def money_compact(value) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{'-' if value < 0 else ''}{CURRENCY_SYMBOL}{compact(abs(value))}"


@app.template_filter("num")
def num(value, decimals: int = 1) -> str:
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "-"


@app.template_filter("signed")
def signed(value, decimals: int = 2) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{'+' if value >= 0 else ''}{value:.{decimals}f}"


@app.template_filter("tojson_safe")
def tojson_safe(value) -> str:
    return json.dumps(value, default=str)


@app.context_processor
def inject_globals():
    return {
        "CURRENCY": CURRENCY,
        "SYMBOL": CURRENCY_SYMBOL,
        "catalog": catalog,
        "metrics": METRICS,
        "simulations": SIMULATIONS,
        "model_backends": backend_options(),
        "year": datetime.now(timezone.utc).year,
    }


# ---------------------------------------------------------------------- routes

@app.route("/", methods=["GET", "POST"])
def index():
    payload = request.form.to_dict(flat=False) if request.method == "POST" else {}
    if payload:
        payload = {key: (value if key in ("material", "quantity") else value[0])
                   for key, value in payload.items()}

    bundle = get_bundle()
    return render_template(
        "index.html",
        r=engine.analyse(payload),
        submitted=request.method == "POST",
        metrics_importance_waste=bundle.waste_importance,
        metrics_importance_overrun=bundle.overrun_importance,
        reliability=bundle.reliability,
        units={m.key: m.unit for m in catalog.MATERIALS},
    )


@app.post("/api/analyse")
def api_analyse():
    return jsonify(engine.analyse(request.get_json(silent=True) or {}))


@app.get("/api/suggest")
def api_suggest():
    project_type = request.args.get("project_type", "com_office")
    if project_type not in catalog.PROJECT_TYPE_INDEX:
        project_type = "com_office"
    try:
        area = float(request.args.get("area", 9200))
    except ValueError:
        area = 9200.0
    return jsonify(engine.suggested_lines(project_type, max(area, 50.0)))


@app.get("/api/sample")
def api_sample():
    try:
        index = int(request.args.get("i", 0))
    except ValueError:
        index = 0
    return jsonify(samples.sample(index))


@app.get("/api/materials")
def api_materials():
    return jsonify([m.as_dict() for m in catalog.MATERIALS])


@app.get("/api/backends")
def api_backends():
    return jsonify(backend_options())


@app.get("/api/health")
def api_health():
    return jsonify({"status": "ok", "model": METRICS})


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(debug=True, port=5000)
