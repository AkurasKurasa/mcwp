"""Export the trained bundle to JSON the browser can evaluate.

HistGradientBoosting predicts from raw feature values at inference time:
numerical splits compare against `num_threshold`, categorical splits test a
bit in `raw_left_cat_bitsets`. Both are portable, so the trees survive the
trip to JavaScript intact — no binning, no sklearn.

Categorical inputs arrive as their index into catalog.CATEGORY_LEVELS,
which is what pandas hands sklearn when the column is a Categorical.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from mcwp import catalog, engine, samples  # noqa: E402
from mcwp.config import (DISPOSAL_COST_PER_TONNE, EXPORT_BACKEND,  # noqa: E402
                         REWORK_LABOUR_RATIO,
                         SALVAGE_RATIO, SIMULATIONS, TARGET_OVERRUN_RISK)
from mcwp.datagen import PALETTES  # noqa: E402
from mcwp.model import get_bundle  # noqa: E402

OUT = ROOT / "site" / "model.js"


def dump_tree(tree) -> dict:
    n = tree.nodes
    bitsets = getattr(tree, "raw_left_cat_bitsets", None)
    return {
        "lf": n["is_leaf"].astype(int).tolist(),
        "v": [float(x) for x in n["value"]],
        "f": n["feature_idx"].astype(int).tolist(),
        "t": [float(x) for x in n["num_threshold"]],
        "l": n["left"].astype(int).tolist(),
        "r": n["right"].astype(int).tolist(),
        "c": n["is_categorical"].astype(int).tolist(),
        "b": n["bitset_idx"].astype(int).tolist(),
        "m": n["missing_go_to_left"].astype(int).tolist(),
        "bs": ([[int(x) for x in row] for row in bitsets]
               if bitsets is not None and len(bitsets) else []),
    }


def dump_model(est) -> dict:
    return {
        "baseline": float(np.ravel(est._baseline_prediction)[0]),
        "trees": [dump_tree(t) for row in est._predictors for t in row],
    }


def encoder_levels(est, feature_names) -> dict:
    """The category order sklearn actually encodes against.

    OrdinalEncoder sorts categories, so a category's code is its index in the
    sorted list - not its position in catalog.CATEGORY_LEVELS. Reading the
    fitted encoder is the only way to be sure.
    """
    for _name, transformer, columns in est._preprocessor.transformers_:
        if not hasattr(transformer, "categories_"):
            continue
        selected = [f for f, keep in zip(feature_names, columns) if keep]
        return {f: [str(c) for c in cats]
                for f, cats in zip(selected, transformer.categories_)}
    return {}


def main() -> None:
    bundle = get_bundle(EXPORT_BACKEND)

    if bundle.backend != EXPORT_BACKEND:
        raise SystemExit(
            f"the browser build can only evaluate {EXPORT_BACKEND!r}, but the "
            f"loaded bundle is {bundle.backend!r}. Re-run with "
            f"MCWP_BACKEND={EXPORT_BACKEND}.")

    payload = {
        "models": {
            "center": dump_model(bundle.waste.center),
            "lower": dump_model(bundle.waste.lower),
            "upper": dump_model(bundle.waste.upper),
            "overrun": dump_model(bundle.overrun),
        },
        "features": {
            "line": catalog.LINE_FEATURES,
            "line_cat": catalog.LINE_CATEGORICALS,
            "project": catalog.PROJECT_FEATURES,
            "project_cat": catalog.PROJECT_CATEGORICALS,
        },
        "levels": catalog.CATEGORY_LEVELS,
        "encoders": {
            "line": encoder_levels(bundle.waste.center, catalog.LINE_FEATURES),
            "project": encoder_levels(bundle.overrun, catalog.PROJECT_FEATURES),
        },
        "calibration": bundle.calibration,
        "residual_sigma": bundle.residual_sigma,
        "metrics": bundle.metrics,
        "materials": [m.as_dict() for m in catalog.MATERIALS],
        "project_types": [
            {"key": p.key, "name": p.name, "family": p.family,
             "typical_area": p.typical_area, "waste_multiplier": p.waste_multiplier}
            for p in catalog.PROJECT_TYPES
        ],
        "regions": [
            {"key": r.key, "name": r.name, "cost_index": r.cost_index,
             "labor_index": r.labor_index, "volatility": r.volatility}
            for r in catalog.REGIONS
        ],
        "quantity_per_1000m2": catalog.QUANTITY_PER_1000M2,
        "palettes": PALETTES,
        "defaults": engine.DEFAULT_PROJECT,
        "bounds": {k: list(v) for k, v in engine._BOUNDS.items()},
        "max_lines": engine.MAX_LINES,
        "samples": [samples.sample(i) for i in range(samples.COUNT)]
                   if hasattr(samples, "COUNT") else
                   [samples.sample(i) for i in range(4)],
        "config": {
            "disposal_cost_per_tonne": DISPOSAL_COST_PER_TONNE,
            "rework_labour_ratio": REWORK_LABOUR_RATIO,
            "salvage_ratio": SALVAGE_RATIO,
            "simulations": SIMULATIONS,
            "target_overrun_risk": TARGET_OVERRUN_RISK,
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        f.write("window.MCWP_MODEL=")
        json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)
        f.write(";\n")

    size = OUT.stat().st_size
    trees = sum(len(m["trees"]) for m in payload["models"].values())
    nodes = sum(len(t["lf"]) for m in payload["models"].values() for t in m["trees"])
    print(f"wrote {OUT.relative_to(ROOT)}  {size/1e6:.2f} MB  "
          f"{trees} trees  {nodes} nodes")


if __name__ == "__main__":
    main()
