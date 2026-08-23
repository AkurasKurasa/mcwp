# MCWP — Material Cost & Waste Prediction

A single-page Flask tool for construction estimating. An engineer states the
project, its materials list, its budget, size, location and duration. The page
returns the likely material waste, the probability the budget is exceeded, which
materials carry that risk, and the contingency needed to bring the risk back to
target.

```
python -m pip install -r requirements.txt
python app.py
# http://127.0.0.1:5000
```

First launch generates a 2,600-project archive and fits both models — about
50 seconds. Everything after that starts instantly from `instance/`.

---

## Input → output

| Engineer enters | System predicts |
|---|---|
| Project type (residential / commercial / other) | Likely material waste %, with an 80% band |
| Materials list (up to 10 lines, with quantities) | Probability of cost overrun |
| Material budget | Which materials are high risk, and why |
| Project size and duration | Recommended buffer budget |
| Location | |

Everything is on one route. Edit any field and the four headline figures, the
outturn distribution and the risk gauge re-compute live; **Run prediction**
re-renders the full breakdown, ranking and actions. **Load sample** cycles
through four worked projects — each states its budget as a ratio of its own
benchmark, so the scenario stays meaningful if the price book changes.

## How it works

**Two learners over one archive of completed projects.**

1. **Waste model** — `HistGradientBoostingRegressor` predicting the waste rate
   of each material line, plus quantile heads at 0.10 and 0.90. The interval
   they produce is rescaled on held-out data until its empirical coverage
   matches the 80% it claims.

2. **Overrun classifier** — `HistGradientBoostingClassifier` predicting whether
   the stated budget is exceeded. It receives the waste model's forecast as a
   feature, **generated out-of-fold** with `GroupKFold`, so it never sees a
   waste figure that was fitted on the same project.

**Cost simulation.** 4,000 Monte Carlo draws over the waste model's measured
residual spread and regional/commodity price dispersion produce the outturn
distribution. The recommended buffer is the distance from the budget to its 90th
percentile. The distribution is left at its own level rather than bent toward
the classifier — the two are independent reads on the same question, and on the
shipped archive they track each other closely:

| Budget vs benchmark | Classifier | Simulation |
|---|---|---|
| 0.85× | 98.6% | 98.5% |
| 0.95× | 67.9% | 73.8% |
| 1.00× | 59.5% | 49.8% |
| 1.05× | 20.2% | 27.7% |
| 1.15× | 5.6% | 2.8% |

**Risk ranking.** Each material is scored relative to the rest of the package on
its share of cost variance, its share of wasted value, its excess over
benchmark, its price volatility and its fragility — so the ranking means the
same thing on a three-line fit-out as on a ten-line tower.

## Held-out performance

| Waste model | | Overrun classifier | |
|---|---|---|---|
| R² | 0.699 | ROC-AUC | 0.900 |
| MAE | 1.89 pp | Brier | 0.127 |
| RMSE | 2.76 pp | Accuracy | 81.3% |
| 80% band coverage | 80.6% | Base rate | 46.7% |

Trained on 2,600 projects / 14,349 material lines, split by project so no
project straddles the train/test boundary.

**Why R² is 0.70 and not 0.95.** The model only sees what an engineer can state
at bid time. Crew quality, storage discipline, design churn, BIM maturity and
prefabrication all move waste hard, and none are knowable when the bid goes in.
The generator applies them; the learner never sees them. They surface as
spread rather than false precision — and that spread is exactly what the
contingency is sized against.

## Data provenance

**The archive is synthetic.** `mcwp/datagen.py` encodes a documented causal
process — material baselines scaled by project archetype, order size, schedule
intensity, budget pressure and regional labour, then perturbed by the latent
site factors above and heteroscedastic noise. The learners see only noisy
outcomes.

To run on real data, replace `build_corpus()` with a loader returning the same
two frames: one row per project (with `budget`, `actual_cost`, `overrun`) and
one row per material line (with `waste_pct`). Nothing downstream changes.

Prices in `mcwp/catalog.py` are illustrative 2026 North-American benchmarks;
regional indices apply on top.

## HTTP API

```
POST /api/analyse    -> the full analysis (this is what the live page calls)
GET  /api/suggest    -> ?project_type=&area= — a typical materials list
GET  /api/sample     -> ?i= — a worked example project, budget included
GET  /api/materials  -> the catalogue
GET  /api/health     -> model metrics
```

```bash
curl -X POST http://127.0.0.1:5000/api/analyse \
  -H "Content-Type: application/json" \
  -d '{"project_type":"res_multi","region":"ne_metro","project_area":14000,
       "duration_weeks":72,"budget":3000000,
       "lines":[{"material":"gypsum_drywall","quantity":17500},
                {"material":"glazing_unit","quantity":2600}]}'
```

## Layout

```
app.py                one route, a JSON API, Jinja filters
mcwp/
  catalog.py          materials, regions, project archetypes, feature schema
  costing.py          the cost model — shared by the generator and the engine
  datagen.py          the synthetic project archive and its causal process
  model.py            both learners: fit, calibrate, predict, importance
  engine.py           analysis: forecast, simulation, buffer, risk, advice
  bootstrap.py        first-run setup and refit
  samples.py          the worked example projects
templates/index.html  the page
static/css/           core.css (tokens, shell) + ui.css (components)
static/js/            charts.js (dependency-free SVG charts) + app.js
instance/             generated: models.joblib, model_metrics.json
```

No build step, no CDN scripts, no database. Charts are hand-built SVG that read
their colours from CSS custom properties, so they follow the theme toggle.

The interface is monochrome and deliberately cheap to paint: one tone ramp and
no hue anywhere, a single static lattice layer at ~2% contrast, flat surfaces,
hairline borders, and no `backdrop-filter`, blurred glow layers, cursor-tracking
gradients or looping animations. It holds 60 fps under continuous scrolling.

Severity is carried by contrast rather than colour — a filled chip means act on
it, a bright outline means watch it, a quiet outline means it is fine — and
every tone is a CSS token, so the dark and light themes invert correctly instead
of leaving pale bars on a white page.

## Caveats

The band is a forecast interval, not a guarantee, and the overrun probability is
a probability — a 20% risk still loses one time in five. Useful for sizing
allowances, comparing options and prioritising attention; not a substitute for
supplier quotations before money is committed.
