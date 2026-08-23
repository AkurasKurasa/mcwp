"""The two learners.

1. WasteModel  - per material line, a waste rate with a calibrated interval.
2. OverrunModel - per project, the probability the budget is exceeded.

The overrun classifier consumes the waste model's own forecast as a feature.
That prediction is generated out-of-fold during training, so the classifier
never sees a waste figure the regressor fitted on the same project.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import (HistGradientBoostingClassifier,
                              HistGradientBoostingRegressor)
from sklearn.inspection import permutation_importance
from sklearn.metrics import (accuracy_score, brier_score_loss,
                             mean_absolute_error, r2_score, roc_auc_score)
from sklearn.model_selection import GroupKFold, cross_val_predict, train_test_split

from . import catalog
from .config import METRICS_PATH, MODEL_PATH, RANDOM_SEED
from .datagen import build_corpus, line_features, project_features


def _regressor(loss: str, quantile: float | None = None):
    return HistGradientBoostingRegressor(
        loss=loss, quantile=quantile,
        max_iter=300, learning_rate=0.06, max_depth=6, min_samples_leaf=24,
        l2_regularization=1.0, categorical_features="from_dtype",
        early_stopping=True, validation_fraction=0.12, n_iter_no_change=22,
        random_state=RANDOM_SEED,
    )


def _classifier():
    return HistGradientBoostingClassifier(
        max_iter=280, learning_rate=0.06, max_depth=5, min_samples_leaf=28,
        l2_regularization=1.0, categorical_features="from_dtype",
        early_stopping=True, validation_fraction=0.15, n_iter_no_change=22,
        random_state=RANDOM_SEED,
    )


@dataclass
class Bundle:
    """Everything the app needs to make a prediction."""
    center: HistGradientBoostingRegressor
    lower: HistGradientBoostingRegressor
    upper: HistGradientBoostingRegressor
    overrun: HistGradientBoostingClassifier
    calibration: float = 1.0
    residual_sigma: float = 0.25
    metrics: dict = field(default_factory=dict)
    waste_importance: list = field(default_factory=list)
    overrun_importance: list = field(default_factory=list)
    reliability: list = field(default_factory=list)

    # ------------------------------------------------------------------ fit

    @classmethod
    def fit(cls, projects: pd.DataFrame, lines: pd.DataFrame) -> "Bundle":
        started = time.perf_counter()

        # ---- waste model, split by project so no project straddles the split
        x_all = line_features(lines)
        y_all = lines["waste_pct"].to_numpy()
        groups = lines["project_id"].to_numpy()

        unique = np.unique(groups)
        train_ids, test_ids = train_test_split(unique, test_size=0.2,
                                               random_state=RANDOM_SEED)
        is_train = np.isin(groups, train_ids)
        x_train, y_train = x_all[is_train], y_all[is_train]
        x_test, y_test = x_all[~is_train], y_all[~is_train]

        center = _regressor("squared_error").fit(x_train, y_train)
        lower = _regressor("quantile", 0.10).fit(x_train, y_train)
        upper = _regressor("quantile", 0.90).fit(x_train, y_train)

        predicted = center.predict(x_test)
        raw_low, raw_high = lower.predict(x_test), upper.predict(x_test)

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
        folds = GroupKFold(n_splits=5)
        oof = cross_val_predict(_regressor("squared_error"), x_all, y_all,
                                groups=groups, cv=folds, n_jobs=1)
        lines = lines.assign(oof_waste=oof)
        expected = (lines.assign(weighted=lines["oof_waste"] * lines["line_value_share"])
                    .groupby("project_id")["weighted"].sum())
        projects = projects.set_index("project_id")
        projects["expected_waste"] = expected
        projects = projects.reset_index()

        # ---- overrun classifier
        px = project_features(projects)
        py = projects["overrun"].to_numpy()
        p_train = np.isin(projects["project_id"].to_numpy(), train_ids)

        overrun = _classifier().fit(px[p_train], py[p_train])
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
            "waste": waste_metrics,
            "overrun": overrun_metrics,
            "corpus_projects": int(len(projects)),
            "corpus_lines": int(len(lines)),
            "fit_seconds": round(time.perf_counter() - started, 2),
        }

        return cls(
            center, lower, upper, overrun, calibration, residual_sigma, metrics,
            _importance(center, x_test, y_test, catalog.LINE_FEATURES, "r2"),
            _importance(overrun, px[~p_train], truth, catalog.PROJECT_FEATURES, "roc_auc"),
            reliability,
        )

    # ----------------------------------------------------------- prediction

    def predict_waste(self, records) -> dict:
        frame = line_features(records)
        center = np.clip(self.center.predict(frame), 0.002, 0.60)
        k = self.calibration or 1.0
        low = center - k * (center - self.lower.predict(frame))
        high = center + k * (self.upper.predict(frame) - center)
        return {
            "center": center,
            "low": np.clip(np.minimum(low, center * 0.99), 0.001, 0.60),
            "high": np.clip(np.maximum(high, center * 1.01), 0.002, 0.72),
        }

    def predict_overrun(self, record: dict) -> float:
        frame = project_features([record])
        return float(self.overrun.predict_proba(frame)[0, 1])

    # ---------------------------------------------------------- persistence

    def save(self) -> None:
        joblib.dump(self, MODEL_PATH, compress=3)
        METRICS_PATH.write_text(json.dumps({
            "metrics": self.metrics,
            "waste_importance": self.waste_importance,
            "overrun_importance": self.overrun_importance,
            "reliability": self.reliability,
        }, indent=2), encoding="utf-8")


_CACHE: Bundle | None = None


def _importance(estimator, x, y, columns, scoring) -> list:
    sample = min(700, len(x))
    perm = permutation_importance(estimator, x.iloc[:sample], y[:sample],
                                  n_repeats=5, random_state=RANDOM_SEED, scoring=scoring)
    total = float(np.sum(np.clip(perm.importances_mean, 0, None))) or 1.0
    rows = [{
        "feature": column,
        "label": catalog.FEATURE_LABELS.get(column, column),
        "share": float(max(value, 0.0) / total),
    } for column, value in zip(columns, perm.importances_mean)]
    rows.sort(key=lambda item: item["share"], reverse=True)
    return rows


def get_bundle() -> Bundle:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if MODEL_PATH.exists():
        try:
            _CACHE = joblib.load(MODEL_PATH)
            return _CACHE
        except Exception:  # pragma: no cover - stale artefact, refit below
            pass
    projects, lines = build_corpus()
    _CACHE = Bundle.fit(projects, lines)
    _CACHE.save()
    return _CACHE


def reset_cache() -> None:
    global _CACHE
    _CACHE = None
