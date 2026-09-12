"""Application-wide paths and tunable constants."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTANCE = ROOT / "instance"
DB_PATH = INSTANCE / "mcwp.db"

# Which learner backs the predictions. See mcwp/backends.py for the choices;
# MCWP_BACKEND overrides it without touching code.
MODEL_BACKEND = os.environ.get("MCWP_BACKEND", "random_forest")

# The browser build in site/ can only evaluate this one, so it stays pinned
# regardless of what the app itself is running.
EXPORT_BACKEND = "hist_gradient_boosting"


def model_path(backend: str) -> Path:
    return INSTANCE / f"models_{backend}.joblib"


def metrics_path(backend: str) -> Path:
    return INSTANCE / f"model_metrics_{backend}.json"


MODEL_PATH = model_path(MODEL_BACKEND)
METRICS_PATH = metrics_path(MODEL_BACKEND)

CORPUS_PROJECTS = 2600          # whole projects; each carries 3-8 material lines
RANDOM_SEED = 20260819

CURRENCY = "USD"
CURRENCY_SYMBOL = "$"

# Landfill tipping fee and haulage, per tonne discarded.
DISPOSAL_COST_PER_TONNE = 96.0
# Rework labour, as a share of the value of the material that was wasted.
REWORK_LABOUR_RATIO = 0.42
# What a recycler pays back for clean, sorted offcuts.
SALVAGE_RATIO = 0.14

# Monte Carlo draws behind the cost distribution and buffer sizing.
SIMULATIONS = 4000
# The overrun probability the recommended buffer is sized to achieve.
TARGET_OVERRUN_RISK = 0.10

INSTANCE.mkdir(parents=True, exist_ok=True)
