"""First-run setup: build the archive, fit both models, cache the artefacts."""

from __future__ import annotations

import time

from .config import MODEL_PATH
from .datagen import build_corpus
from .model import Bundle, get_bundle, reset_cache


def ensure_ready(log=print) -> dict:
    started = time.perf_counter()

    if not MODEL_PATH.exists():
        log("[mcwp] building project archive and fitting models...")

    bundle = get_bundle()
    metrics = bundle.metrics
    log(f"[mcwp] ready in {time.perf_counter() - started:.2f}s - "
        f"waste R2={metrics['waste']['r2']:.3f} "
        f"MAE={metrics['waste']['mae_pp']:.2f}pp | "
        f"overrun AUC={metrics['overrun']['auc']:.3f}")
    return metrics


def rebuild(log=print) -> dict:
    """Regenerate the archive and refit from scratch."""
    MODEL_PATH.unlink(missing_ok=True)
    reset_cache()
    projects, lines = build_corpus()
    bundle = Bundle.fit(projects, lines)
    bundle.save()
    reset_cache()
    log("[mcwp] refitted")
    return get_bundle().metrics
