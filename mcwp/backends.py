"""Selectable model backends.

Each backend supplies a waste model (a central forecast plus an 80% interval)
and an overrun classifier. They differ in more than hyperparameters:

  random_forest   averages trees, so it cannot extrapolate past the training
                  range and has no quantile loss. Its interval comes from a
                  quantile regression forest - the quantiles of the training
                  labels sitting in each leaf, per Meinshausen (2006). Needs
                  categoricals one-hot encoded; sklearn forests have no native
                  categorical support.
  xgboost         boosts residuals, so it can move past the training range.
                  Quantiles come from the pinball objective. Handles pandas
                  categoricals natively with enable_categorical.
  hist_gradient_boosting
                  sklearn's own histogram booster. Native categoricals, native
                  quantile loss, and the only backend the browser build knows
                  how to evaluate.

A backend is picked by name; see config.MODEL_BACKEND.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.ensemble import (HistGradientBoostingClassifier,
                              HistGradientBoostingRegressor,
                              RandomForestClassifier, RandomForestRegressor)

from .config import RANDOM_SEED

try:  # optional
    from xgboost import XGBClassifier, XGBRegressor
    HAS_XGBOOST = True
except ImportError:  # pragma: no cover - xgboost not installed
    HAS_XGBOOST = False


# ----------------------------------------------------------- feature framing

def one_hot(frame: pd.DataFrame) -> pd.DataFrame:
    """Expand categoricals; forests have no native categorical support."""
    cats = [c for c in frame.columns if str(frame[c].dtype) == "category"]
    return pd.get_dummies(frame, columns=cats) if cats else frame


def as_codes(frame: pd.DataFrame) -> pd.DataFrame:
    """Leave pandas categoricals in place for backends that understand them."""
    return frame


def align(frame: pd.DataFrame, columns) -> pd.DataFrame:
    """One-hot frames must carry the same columns at predict time as at fit."""
    return frame.reindex(columns=columns, fill_value=0)


# --------------------------------------------------------------- waste models

class QuantileForest:
    """Random forest with a Meinshausen quantile interval.

    The forest predicts the mean as usual. For the interval, every training
    label is kept against the leaf it landed in; a prediction pools the labels
    from the leaves the row reaches and takes quantiles of that pool. Taking
    quantiles of the per-tree *predictions* instead would measure uncertainty
    of the mean, which is roughly half as wide as it needs to be.
    """

    prepare = staticmethod(one_hot)
    supports_export = False
    name = "random_forest"

    def __init__(self, low: float = 0.10, high: float = 0.90):
        self.low, self.high = low, high
        self.forest = RandomForestRegressor(
            n_estimators=200, min_samples_leaf=20, max_features=0.6,
            n_jobs=-1, random_state=RANDOM_SEED)
        self.columns_ = None
        self._leaves = None

    def fit(self, x, y):
        self.columns_ = list(x.columns)
        self.forest.fit(x, y)
        leaves = self.forest.apply(x)
        y = np.asarray(y)
        self._leaves = []
        for t in range(leaves.shape[1]):
            bucket = defaultdict(list)
            for row, leaf in enumerate(leaves[:, t]):
                bucket[leaf].append(y[row])
            self._leaves.append({k: np.sort(np.asarray(v)) for k, v in bucket.items()})
        return self

    def predict(self, x):
        return self.forest.predict(align(x, self.columns_))

    def predict_band(self, x):
        x = align(x, self.columns_)
        centre = self.forest.predict(x)
        leaves = self.forest.apply(x)
        low = np.empty(len(x))
        high = np.empty(len(x))
        for i in range(len(x)):
            pool = np.concatenate([self._leaves[t][leaves[i, t]]
                                   for t in range(leaves.shape[1])])
            low[i], high[i] = np.quantile(pool, [self.low, self.high])
        return centre, low, high

    def point_model(self):
        """A fresh point regressor, for the out-of-fold stacking pass."""
        return RandomForestRegressor(
            n_estimators=200, min_samples_leaf=20, max_features=0.6,
            n_jobs=-1, random_state=RANDOM_SEED)

    @property
    def estimator(self):
        return self.forest


class TripleRegressor:
    """Three fitted models: a central forecast and two quantile regressors."""

    def __init__(self, make, prepare, name, supports_export=False):
        self._make = make
        self.prepare = prepare
        self.name = name
        self.supports_export = supports_export
        self.center = self.lower = self.upper = None
        self.columns_ = None

    def fit(self, x, y):
        self.columns_ = list(x.columns)
        self.center = self._make(None).fit(x, y)
        self.lower = self._make(0.10).fit(x, y)
        self.upper = self._make(0.90).fit(x, y)
        return self

    def _frame(self, x):
        return align(x, self.columns_) if self.prepare is one_hot else x

    def predict(self, x):
        return self.center.predict(self._frame(x))

    def predict_band(self, x):
        f = self._frame(x)
        return self.center.predict(f), self.lower.predict(f), self.upper.predict(f)

    def point_model(self):
        return self._make(None)

    @property
    def estimator(self):
        return self.center


# ------------------------------------------------------------------ factories

def _hgb_regressor(quantile):
    return HistGradientBoostingRegressor(
        loss="quantile" if quantile else "squared_error", quantile=quantile,
        max_iter=300, learning_rate=0.06, max_depth=6, min_samples_leaf=24,
        l2_regularization=1.0, categorical_features="from_dtype",
        early_stopping=True, validation_fraction=0.12, n_iter_no_change=22,
        random_state=RANDOM_SEED)


def _xgb_regressor(quantile):
    kwargs = dict(n_estimators=400, learning_rate=0.06, max_depth=6,
                  min_child_weight=8, subsample=0.85, colsample_bytree=0.85,
                  reg_lambda=1.0, tree_method="hist", enable_categorical=True,
                  random_state=RANDOM_SEED, n_jobs=-1)
    if quantile is not None:
        kwargs.update(objective="reg:quantileerror", quantile_alpha=quantile)
    return XGBRegressor(**kwargs)


def _rf_classifier():
    return RandomForestClassifier(
        n_estimators=300, min_samples_leaf=8, max_features="sqrt",
        n_jobs=-1, random_state=RANDOM_SEED)


def _xgb_classifier():
    return XGBClassifier(
        n_estimators=350, learning_rate=0.06, max_depth=5, min_child_weight=8,
        subsample=0.85, colsample_bytree=0.85, reg_lambda=1.0,
        tree_method="hist", enable_categorical=True, eval_metric="logloss",
        random_state=RANDOM_SEED, n_jobs=-1)


def _hgb_classifier():
    return HistGradientBoostingClassifier(
        max_iter=280, learning_rate=0.06, max_depth=5, min_samples_leaf=28,
        l2_regularization=1.0, categorical_features="from_dtype",
        early_stopping=True, validation_fraction=0.15, n_iter_no_change=22,
        random_state=RANDOM_SEED)


# ------------------------------------------------------------------- registry

class Backend:
    def __init__(self, key, label, note, make_waste, make_classifier,
                 prepare, available=True, supports_export=False, library=""):
        self.key = key
        self.label = label
        self.note = note
        self.library = library
        self._make_waste = make_waste
        self._make_classifier = make_classifier
        self.prepare = prepare
        self.available = available
        self.supports_export = supports_export

    def waste_model(self):
        return self._make_waste()

    def classifier(self):
        return self._make_classifier()

    def as_dict(self):
        return {"key": self.key, "label": self.label, "note": self.note,
                "library": self.library, "available": self.available,
                "supports_export": self.supports_export}


BACKENDS = {
    "random_forest": Backend(
        "random_forest", "Random Forest",
        "Bagged trees with a quantile-regression-forest interval. Few knobs, "
        "hard to overfit, but cannot predict beyond the training range.",
        lambda: QuantileForest(),
        _rf_classifier, one_hot, library="scikit-learn"),

    "xgboost": Backend(
        "xgboost", "XGBoost",
        "Gradient boosting with a pinball objective for the interval and "
        "native categorical splits.",
        lambda: TripleRegressor(_xgb_regressor, as_codes, "xgboost"),
        _xgb_classifier, as_codes, available=HAS_XGBOOST, library="XGBoost"),

    "hist_gradient_boosting": Backend(
        "hist_gradient_boosting", "HistGradientBoosting",
        "sklearn's histogram booster. The only backend the browser build can "
        "evaluate, so the GitHub Pages site is pinned to it.",
        lambda: TripleRegressor(_hgb_regressor, as_codes, "hist_gradient_boosting",
                                supports_export=True),
        _hgb_classifier, as_codes, supports_export=True, library="scikit-learn"),
}

DEFAULT_BACKEND = "random_forest"


def get(key: str | None = None) -> Backend:
    key = key or DEFAULT_BACKEND
    if key not in BACKENDS:
        raise KeyError(f"unknown backend {key!r}; choose from {sorted(BACKENDS)}")
    backend = BACKENDS[key]
    if not backend.available:
        raise RuntimeError(f"backend {key!r} needs a package that is not installed")
    return backend


def available() -> list:
    return [b.as_dict() for b in BACKENDS.values()]
