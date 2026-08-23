"""Application-wide paths and tunable constants."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTANCE = ROOT / "instance"
DB_PATH = INSTANCE / "mcwp.db"
MODEL_PATH = INSTANCE / "models.joblib"
METRICS_PATH = INSTANCE / "model_metrics.json"

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
