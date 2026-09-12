"""First-run setup: build the archive, fit both models, cache the artefacts."""

from __future__ import annotations

import time

from . import backends
from .config import MODEL_BACKEND, model_path
from .datagen import build_corpus
from .model import Bundle, get_bundle, reset_cache


def ensure_ready(backend: str | None = None, log=print) -> dict:
    key = backend or MODEL_BACKEND
    started = time.perf_counter()

    if not model_path(key).exists():
        log(f"[mcwp] fitting {backends.BACKENDS[key].label} on a fresh archive...")

    bundle = get_bundle(key)
    metrics = bundle.metrics
    log(f"[mcwp] ready in {time.perf_counter() - started:.2f}s "
        f"[{metrics.get('backend_label', key)}] - "
        f"waste R2={metrics['waste']['r2']:.3f} "
        f"MAE={metrics['waste']['mae_pp']:.2f}pp | "
        f"overrun AUC={metrics['overrun']['auc']:.3f}")
    return metrics


def rebuild(backend: str | None = None, log=print) -> dict:
    """Regenerate the archive and refit from scratch."""
    key = backend or MODEL_BACKEND
    model_path(key).unlink(missing_ok=True)
    reset_cache()
    projects, lines = build_corpus()
    bundle = Bundle.fit(projects, lines, backend=key)
    bundle.save()
    reset_cache()
    log(f"[mcwp] refitted {key}")
    return get_bundle(key).metrics
