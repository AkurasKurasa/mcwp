# Requirements — MCWP (Material Cost & Waste Prediction)

> **Draft.** These were written from the built system, not from the client's own words.
> Reverse-derived requirements are met by definition, so check them against the client
> before citing them as evidence of delivery.

## Context

An estimator pricing a materials package knows the takeoff but not what will actually be
wasted. Customary allowances (5% concrete, 10% drywall) are flat rates that ignore project
size, programme pressure and how tight the budget is. MCWP predicts waste per material line,
turns that into a cost distribution, and sizes the contingency needed to hold overrun risk
at a target.

**Client:** _to be recorded_ · **Users:** construction estimators / quantity surveyors

## Functional requirements

**Input**

- **FR-1** — State project name, type, location, floor area, duration and material budget.
- **FR-2** — Choose from 9 project types, 8 regions (each with a cost and labour index), and up to 10 material lines drawn from a 16-material catalogue.
- **FR-3** — With no budget stated, judge the package against its own benchmark cost.
- **FR-3a** — State the site conditions that drive waste: on-site covered storage (m²), rain frequency (wet days/month) and contractor experience (years).
- **FR-4** — Suggest a starting materials list for the project type and size, and offer worked examples.

**Output**

- **FR-5** — Predict a waste rate per material line, with an 80% interval, and a package rate weighted by value.
- **FR-6** — Show each line against the customary trade allowance, so the user sees where the model disagrees with standard practice.
- **FR-7** — Predict the probability the budget is exceeded.
- **FR-8** — Simulate cost at completion; report p10 / p50 / p90.
- **FR-9** — Recommend a contingency: budget to p90.
- **FR-10** — Rank materials by contribution to cost *variance*, not cost, with plain-language reasons.
- **FR-11** — Give ordered, concrete actions tied to the numbers.
- **FR-12** — Report waste tonnage and embodied CO₂e.
- **FR-13** — Update predictions live as the brief is edited, with no page reload.
- **FR-17** — Show how much of the overrun risk sits in the three site conditions: each factor's swing between its worst and best case, and the points recoverable from where it stands now.
- **FR-18** — Give a written recommendation of what to do, as a paragraph plus an ordered breakdown tied to the figures.

**Behaviour**

- **FR-14** — Clamp out-of-range input rather than rejecting it: area 50–500,000 m², duration 2–260 weeks.
- **FR-15** — Discard duplicate and zero-quantity lines silently.
- **FR-16** — Let the user choose which learner backs the prediction (Random Forest, XGBoost, HistGradientBoosting) and re-run against it.

## Non-functional requirements

Measured on held-out projects. **No target has been agreed with the client** — the figures
are what the current model achieves, and a requirement without a threshold cannot be passed
or failed.

| ID | Requirement | Measured |
|---|---|---|
| NFR-1 | Waste model accuracy | R² 0.807 · MAE 1.51pp |
| NFR-2 | The 80% interval covers 80% of outcomes | 79.6% |
| NFR-3 | Overrun classifier ranks risk reliably | AUC 0.899 · Brier 0.130 |

Per backend, on the same held-out split:

| Backend | R² | MAE pp | Cover% | Calib | AUC | Brier | Fit s | Browser |
|---|---|---|---|---|---|---|---|---|
| Random Forest *(default)* | 0.797 | 1.55 | 79.1 | 0.95 | 0.898 | 0.134 | 50 | no |
| XGBoost | 0.803 | 1.53 | 80.7 | 1.25 | 0.889 | 0.141 | 35 | no |
| HistGradientBoosting | 0.807 | 1.51 | 79.6 | 1.20 | 0.899 | 0.130 | 48 | yes |

Adding the three site conditions moved waste R² from 0.699 to 0.797–0.807 and MAE
from ~1.90pp to ~1.51pp: they were previously latent in the generator, so the model
was carrying them as noise.

- **NFR-4** — Split by project, so none appears in both training and test data; the classifier consumes out-of-fold waste forecasts.
- **NFR-5** — Cost distribution from 4,000 Monte Carlo draws; contingency sized to 10% overrun risk.
- **NFR-6** — Runs locally with no account, no network, no external service. USD.
- **NFR-7** — Works on desktop and mobile, light and dark.

> The model trains on a **synthetic** 2,600-project corpus, so these figures measure how well
> it recovers a known generative process — not how well it predicts real construction waste.

## Deployment

- **DR-1** — Runs locally as a Flask app (`python app.py`).
- **DR-2** — Deployable to a Python host (`render.yaml`, `Procfile`).
- **DR-3** — Published on GitHub Pages with the HistGradientBoosting model ported to JavaScript, so predictions run in the browser with no server. Verified against scikit-learn: waste models match exactly, overrun to 1.1e-16. Only the Monte Carlo differs (0.01–0.8%), as numpy's random stream cannot be reproduced in a browser.

## Out of scope

Labour, plant and preliminaries · real project data and real-world validation · accounts,
saved projects, history · live commodity pricing · scope change and design churn ·
placing or tracking orders.

## Open questions

1. What accuracy is acceptable? NFR-1–3 have no agreed threshold.
2. Is 10% target overrun risk the client's number or a placeholder?
3. Is the synthetic corpus accepted, or is validation against real projects expected?
4. Are 16 materials and 10 lines enough for the packages they price?
5. Is export needed — PDF, Excel, print?
6. Which deployment is the deliverable: local, hosted, or GitHub Pages?
