"""The two learners, fitted through a selectable backend.

1. a waste model  - per material line, a waste rate with a calibrated interval.
2. a classifier   - per project, the probability the budget is exceeded.

The classifier consumes the waste model's own forecast as a feature. That
prediction is generated out-of-fold during training, so the classifier never
sees a waste figure the regressor fitted on the same project.

Which learner does the work is chosen by backend; see mcwp/backends.py.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import (accuracy_score, brier_score_loss,
                             mean_absolute_error, r2_score, roc_auc_score)
from sklearn.model_selection import GroupKFold, cross_val_predict, train_test_split

from . import backends, catalog
from .config import MODEL_BACKEND, RANDOM_SEED, metrics_path, model_path
from .datagen import build_corpus, line_features, project_features


@dataclass
class Bundle:
    """Everything the app needs to make a prediction."""
    waste: object
    overrun: object
    backend: str = MODEL_BACKEND
    calibration: float = 1.0
    residual_sigma: float = 0.25
    metrics: dict = field(default_factory=dict)
    waste_importance: list = field(default_factory=list)
    overrun_importance: list = field(default_factory=list)
    reliability: list = field(default_factory=list)
    project_columns: list = field(default_factory=list)

    # ------------------------------------------------------------------ fit

    @classmethod
    def fit(cls, projects: pd.DataFrame, lines: pd.DataFrame,
            backend: str | None = None) -> "Bundle":
        spec = backends.get(backend or MODEL_BACKEND)
        started = time.perf_counter()

        # ---- waste model, split by project so no project straddles the split
        x_raw = line_features(lines)
        x_all = spec.prepare(x_raw)
        y_all = lines["waste_pct"].to_numpy()
        groups = lines["project_id"].to_numpy()

        unique = np.unique(groups)
        train_ids, _ = train_test_split(unique, test_size=0.2, random_state=RANDOM_SEED)
        is_train = np.isin(groups, train_ids)
        x_train, y_train = x_all[is_train], y_all[is_train]
        x_test, y_test = x_all[~is_train], y_all[~is_train]

        waste = spec.waste_model().fit(x_train, y_train)
        predicted, raw_low, raw_high = waste.predict_band(x_test)

        calibration, best = 1.0, float("inf")
        for candidate in np.arange(0.8, 3.51, 0.05):
            lo = predicted - candidate * (predicted - raw_low)
            hi = predicted + candidate * (raw_high - predicted)
            gap = abs(float(np.mean((y_test >= lo) & (y_test <= hi))) - 0.80)
            if gap < best:
                best, calibration = gap, float(candidate)
        band_low = predicted - calibration * (predicted - raw_low)
        band_high = predicted + calibration * (raw_high - predicted)

        # Multiplicative residual spread, used by the cost simulation.
        ratios = np.log(np.clip(y_test, 1e-4, None) / np.clip(predicted, 1e-4, None))
        residual_sigma = float(np.clip(np.std(ratios), 0.05, 1.2))

        waste_metrics = {
            "r2": float(r2_score(y_test, predicted)),
            "mae_pp": float(mean_absolute_error(y_test, predicted) * 100),
            "rmse_pp": float(np.sqrt(np.mean((y_test - predicted) ** 2)) * 100),
            "coverage_80": float(np.mean((y_test >= band_low) & (y_test <= band_high)) * 100),
            "calibration": round(calibration, 2),
            "residual_sigma": round(residual_sigma, 3),
            "train_lines": int(is_train.sum()),
            "test_lines": int((~is_train).sum()),
        }

        # ---- out-of-fold waste forecast, so the classifier sees honest input
        oof = cross_val_predict(waste.point_model(), x_all, y_all, groups=groups,
                                cv=GroupKFold(n_splits=5), n_jobs=1)
        lines = lines.assign(oof_waste=oof)
        expected = (lines.assign(weighted=lines["oof_waste"] * lines["line_value_share"])
                    .groupby("project_id")["weighted"].sum())
        projects = projects.set_index("project_id")
        projects["expected_waste"] = expected
        projects = projects.reset_index()

        # ---- overrun classifier
        px = spec.prepare(project_features(projects))
        py = projects["overrun"].to_numpy()
        p_train = np.isin(projects["project_id"].to_numpy(), train_ids)

        overrun = spec.classifier().fit(px[p_train], py[p_train])
        proba = overrun.predict_proba(px[~p_train])[:, 1]
        truth = py[~p_train]

        deciles = np.clip((proba * 10).astype(int), 0, 9)
        reliability = []
        for bucket in range(10):
            mask = deciles == bucket
            if mask.sum() < 8:
                continue
            reliability.append({
                "predicted": round(float(proba[mask].mean()) * 100, 1),
                "observed": round(float(truth[mask].mean()) * 100, 1),
                "n": int(mask.sum()),
            })

        overrun_metrics = {
            "auc": float(roc_auc_score(truth, proba)),
            "brier": float(brier_score_loss(truth, proba)),
            "accuracy": float(accuracy_score(truth, proba >= 0.5)),
            "base_rate": float(truth.mean() * 100),
            "train_projects": int(p_train.sum()),
            "test_projects": int((~p_train).sum()),
        }

        metrics = {
            "backend": spec.key,
            "backend_label": spec.label,
            "waste": waste_metrics,
            "overrun": overrun_metrics,
            "corpus_projects": int(len(projects)),
            "corpus_lines": int(len(lines)),
            "fit_seconds": round(time.perf_counter() - started, 2),
        }

        return cls(
            waste=waste, overrun=overrun, backend=spec.key,
            calibration=calibration, residual_sigma=residual_sigma, metrics=metrics,
            waste_importance=_importance(waste.estimator, x_test, y_test,
                                         catalog.LINE_FEATURES, x_raw.columns, "r2"),
            overrun_importance=_importance(overrun, px[~p_train], truth,
                                           catalog.PROJECT_FEATURES,
                                           project_features(projects).columns, "roc_auc"),
            reliability=reliability,
            project_columns=list(px.columns),
        )

    # ----------------------------------------------------------- prediction

    def _spec(self):
        return backends.BACKENDS[self.backend]

    def predict_waste(self, records) -> dict:
        frame = self._spec().prepare(line_features(records))
        centre, raw_low, raw_high = self.waste.predict_band(frame)
        centre = np.clip(centre, 0.002, 0.60)
        k = self.calibration or 1.0
        low = centre - k * (centre - raw_low)
        high = centre + k * (raw_high - centre)
        return {
            "center": centre,
            "low": np.clip(np.minimum(low, centre * 0.99), 0.001, 0.60),
            "high": np.clip(np.maximum(high, centre * 1.01), 0.002, 0.72),
        }

    def predict_overrun(self, record: dict) -> float:
        frame = self._spec().prepare(project_features([record]))
        if self.project_columns:
            frame = frame.reindex(columns=self.project_columns, fill_value=0)
        return float(self.overrun.predict_proba(frame)[0, 1])

    # ---------------------------------------------------------- persistence

    def save(self) -> None:
        joblib.dump(self, model_path(self.backend), compress=3)
        metrics_path(self.backend).write_text(json.dumps({
            "metrics": self.metrics,
            "waste_importance": self.waste_importance,
            "overrun_importance": self.overrun_importance,
            "reliability": self.reliability,
        }, indent=2), encoding="utf-8")


_CACHE: dict = {}


def _importance(estimator, x, y, logical_features, raw_columns, scoring) -> list:
    """Permutation importance, folded back onto the logical feature names.

    One-hot backends see `material_rebar_steel` and friends; the app talks
    about `material`. Shares of the expanded columns are summed back into the
    feature they came from so every backend reports the same vocabulary.
    """
    sample = min(700, len(x))
    perm = permutation_importance(estimator, x.iloc[:sample], y[:sample],
                                  n_repeats=5, random_state=RANDOM_SEED, scoring=scoring)

    folded = {name: 0.0 for name in logical_features}
    for column, value in zip(x.columns, perm.importances_mean):
        owner = next((f for f in logical_features
                      if column == f or column.startswith(f + "_")), None)
        if owner is not None:
            folded[owner] += max(float(value), 0.0)

    total = sum(folded.values()) or 1.0
    rows = [{"feature": name,
             "label": catalog.FEATURE_LABELS.get(name, name),
             "share": value / total}
            for name, value in folded.items()]
    rows.sort(key=lambda item: item["share"], reverse=True)
    return rows


def get_bundle(backend: str | None = None) -> Bundle:
    key = backend or MODEL_BACKEND
    if key in _CACHE:
        return _CACHE[key]

    path = model_path(key)
    if path.exists():
        try:
            _CACHE[key] = joblib.load(path)
            return _CACHE[key]
        except Exception:  # pragma: no cover - stale artefact, refit below
            pass

    projects, lines = build_corpus()
    bundle = Bundle.fit(projects, lines, backend=key)
    bundle.save()
    _CACHE[key] = bundle
    return bundle


def reset_cache() -> None:
    _CACHE.clear()
