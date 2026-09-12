"""Fit every available backend and put the numbers side by side.

    python tools/compare_models.py            # use cached fits where present
    python tools/compare_models.py --refit     # retrain everything
    python tools/compare_models.py --only xgboost,random_forest

Writes instance/model_comparison.json and prints a table. Nothing here picks a
winner for you: the waste models land within noise of each other on this
corpus, so the choice turns on interval calibration, speed and whether the
browser build needs to evaluate it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcwp import backends  # noqa: E402
from mcwp.config import INSTANCE, model_path  # noqa: E402
from mcwp.datagen import build_corpus  # noqa: E402
from mcwp.model import Bundle, get_bundle, reset_cache  # noqa: E402

OUT = INSTANCE / "model_comparison.json"


def run(keys, refit: bool) -> list:
    corpus = None
    rows = []

    for key in keys:
        spec = backends.BACKENDS[key]
        if not spec.available:
            print(f"  {spec.label:24s} skipped - package not installed")
            continue

        started = time.perf_counter()
        if refit or not model_path(key).exists():
            if corpus is None:
                corpus = build_corpus()
            reset_cache()
            bundle = Bundle.fit(*corpus, backend=key)
            bundle.save()
            source = "fitted"
        else:
            bundle = get_bundle(key)
            source = "cached"
        elapsed = time.perf_counter() - started

        m = bundle.metrics
        rows.append({
            "key": key,
            "label": spec.label,
            "source": source,
            "wall_seconds": round(elapsed, 1),
            "fit_seconds": m["fit_seconds"],
            "exportable": spec.supports_export,
            "calibration": m["waste"]["calibration"],
            "waste": m["waste"],
            "overrun": m["overrun"],
            "top_waste_feature": bundle.waste_importance[0]["label"],
            "top_overrun_feature": bundle.overrun_importance[0]["label"],
        })
        print(f"  {spec.label:24s} {source:7s} R2={m['waste']['r2']:.3f} "
              f"AUC={m['overrun']['auc']:.3f}  ({elapsed:.0f}s)")

    return rows


def table(rows) -> str:
    head = (f"{'Backend':<24}{'R²':>8}{'MAE pp':>9}{'Cover%':>9}{'Calib':>7}"
            f"{'AUC':>8}{'Brier':>8}{'Fit s':>8}  Browser")
    lines = [head, "-" * len(head)]
    for r in rows:
        w, o = r["waste"], r["overrun"]
        lines.append(
            f"{r['label']:<24}{w['r2']:>8.3f}{w['mae_pp']:>9.2f}"
            f"{w['coverage_80']:>9.1f}{r['calibration']:>7.2f}"
            f"{o['auc']:>8.3f}{o['brier']:>8.3f}{r['fit_seconds']:>8.1f}"
            f"  {'yes' if r['exportable'] else 'no'}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refit", action="store_true", help="retrain even if cached")
    ap.add_argument("--only", default="", help="comma-separated backend keys")
    args = ap.parse_args()

    keys = [k.strip() for k in args.only.split(",") if k.strip()] or list(backends.BACKENDS)
    unknown = [k for k in keys if k not in backends.BACKENDS]
    if unknown:
        raise SystemExit(f"unknown backend(s): {unknown}; "
                         f"choose from {sorted(backends.BACKENDS)}")

    print(f"comparing {len(keys)} backend(s)"
          f"{' with a full refit' if args.refit else ''}\n")
    rows = run(keys, args.refit)
    if not rows:
        raise SystemExit("nothing to compare")

    print("\n" + table(rows))
    print(f"\ndefault backend: {backends.DEFAULT_BACKEND}"
          f"   (override with MCWP_BACKEND=<key>)")

    OUT.write_text(json.dumps({"compared_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                               "default": backends.DEFAULT_BACKEND,
                               "rows": rows}, indent=2), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
