/* MCWP analysis engine, ported from mcwp/engine.py + mcwp/costing.py.
 *
 * Same inputs, same cost stack, same outputs as the Flask app. The one
 * deliberate difference is the Monte Carlo: numpy's PCG64 stream cannot be
 * reproduced in the browser, so this uses its own seeded generator. The
 * distribution is the same, the individual draws are not, so simulation
 * figures (p10/p50/p90, buffer, simulated risk) land within Monte Carlo
 * noise of the Python app rather than exactly on it. Everything the trees
 * decide - waste rates, bands, overrun probability - matches exactly.
 */
(function (global) {
  "use strict";

  var M = global.MCWP_MODEL;
  var P = global.MCWPPredict;
  if (!M || !P) throw new Error("model.js and predict.js must load first");

  var CFG = M.config;
  var MATERIAL = {}, PTYPE = {}, REGION = {};
  M.materials.forEach(function (m) { MATERIAL[m.key] = m; });
  M.project_types.forEach(function (p) { PTYPE[p.key] = p; });
  M.regions.forEach(function (r) { REGION[r.key] = r; });

  var clamp = function (v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; };

  /* Python's round() is round-half-to-even. Matching it keeps every displayed
     figure identical to the Flask app rather than off by a cent. */
  function r2(v, d) {
    var f = Math.pow(10, d === undefined ? 2 : d);
    var x = v * f;
    var floor = Math.floor(x);
    if (x - floor === 0.5) return (floor % 2 === 0 ? floor : floor + 1) / f;
    return Math.round(x) / f;
  }

  /* ── seeded RNG: mulberry32 + Box-Muller ─────────────────────────── */

  function rng(seed) {
    var s = seed >>> 0, spare = null;
    function next() {
      s |= 0; s = (s + 0x6D2B79F5) | 0;
      var t = Math.imul(s ^ (s >>> 15), 1 | s);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    }
    function normal() {
      if (spare !== null) { var v = spare; spare = null; return v; }
      var u, v2, s2;
      do { u = next() * 2 - 1; v2 = next() * 2 - 1; s2 = u * u + v2 * v2; }
      while (s2 >= 1 || s2 === 0);
      var mul = Math.sqrt(-2 * Math.log(s2) / s2);
      spare = v2 * mul;
      return u * mul;
    }
    return { next: next, normal: normal,
             lognormal: function (mu, sigma) { return Math.exp(mu + sigma * normal()); } };
  }

  /* ── costing.py ──────────────────────────────────────────────────── */

  function lineCost(material, quantity, wastePct, unitPrice, laborIndex) {
    wastePct = clamp(wastePct, 0, 0.6);
    var orderQty = quantity / (1 - wastePct);
    var wasteQty = orderQty - quantity;
    var procurement = orderQty * unitPrice;
    var wastedValue = wasteQty * unitPrice;
    var landfillT = wasteQty * material.mass_kg_per_unit * (1 - material.recycle_rate) / 1000;
    var disposal = landfillT * CFG.disposal_cost_per_tonne;
    var rework = wastedValue * CFG.rework_labour_ratio * laborIndex;
    var salvage = wastedValue * material.recycle_rate * CFG.salvage_ratio;
    return {
      order_qty: orderQty, waste_qty: wasteQty, procurement: procurement,
      wasted_value: wastedValue, disposal: disposal, rework: rework, salvage: salvage,
      total: procurement + disposal + rework - salvage,
      waste_tonnes: wasteQty * material.mass_kg_per_unit / 1000,
      co2e_tonnes: wasteQty * material.co2e_kg_per_unit / 1000
    };
  }

  function benchmarkCost(priced, region) {
    return priced.reduce(function (sum, it) {
      return sum + lineCost(it.material, it.quantity, it.material.base_waste,
                            it.unit_price, region.labor_index).total;
    }, 0);
  }

  /* ── input prep ──────────────────────────────────────────────────── */

  function num(raw, fallback) {
    var v = parseFloat(String(raw === undefined || raw === null ? "" : raw).replace(/,/g, "").trim());
    return isFinite(v) ? v : Number(fallback || 0);
  }

  function suggestedLines(projectType, area) {
    var family = (PTYPE[projectType] || PTYPE[M.defaults.project_type]).family;
    return M.palettes[family].slice(0, 5).map(function (key) {
      return { material: key, quantity: r2(M.quantity_per_1000m2[key] * area / 1000, 1) };
    });
  }

  function normalise(raw) {
    raw = raw || {};
    var clean = {};
    Object.keys(M.defaults).forEach(function (k) { clean[k] = M.defaults[k]; });

    var pt = String(raw.project_type || "").trim();
    clean.project_type = PTYPE[pt] ? pt : M.defaults.project_type;
    var rg = String(raw.region || "").trim();
    clean.region = REGION[rg] ? rg : M.defaults.region;

    ["project_area", "duration_weeks", "budget",
     "storage_m2", "rain_days", "experience_years"].forEach(function (f) {
      var b = M.bounds[f];
      clean[f] = clamp(num(raw[f], M.defaults[f]), b[0], b[1]);
    });

    clean.project_name = String(raw.project_name || "").trim().slice(0, 120) || "Untitled Project";

    var lines = raw.lines;
    if (!Array.isArray(lines)) {
      var keys = raw["material[]"] || raw.material || [];
      var qty = raw["quantity[]"] || raw.quantity || [];
      if (typeof keys === "string") { keys = [keys]; qty = [qty]; }
      lines = keys.map(function (k, i) { return { material: k, quantity: qty[i] }; });
    }

    var cleaned = [], seen = {};
    lines.slice(0, M.max_lines * 2).forEach(function (line) {
      if (cleaned.length >= M.max_lines) return;
      var key = String((line || {}).material || "").trim();
      if (!MATERIAL[key] || seen[key]) return;
      var q = num((line || {}).quantity, 0);
      if (q <= 0) return;
      seen[key] = true;
      cleaned.push({ material: key, quantity: Math.min(q, 5000000) });
    });

    clean.lines = cleaned.length ? cleaned : suggestedLines(clean.project_type, clean.project_area);
    return clean;
  }

  function verdict(p) {
    if (p >= 0.65) return { label: "Overrun likely", tone: "rose", colour: "var(--tone-1)" };
    if (p >= 0.40) return { label: "Overrun plausible", tone: "amber", colour: "var(--tone-2)" };
    if (p >= 0.20) return { label: "Holds, with watch items", tone: "cyan", colour: "var(--tone-3)" };
    return { label: "Budget looks sound", tone: "mint", colour: "var(--tone-4)" };
  }

  function reference() {
    var d = new Date(), p = function (n, w) { return String(n).padStart(w || 2, "0"); };
    var stamp = String(d.getUTCFullYear()).slice(2) + p(d.getUTCMonth() + 1) + p(d.getUTCDate()) +
                p(d.getUTCHours()) + p(d.getUTCMinutes()) + p(d.getUTCSeconds());
    var h = 0;
    for (var i = 0; i < stamp.length; i++) h = (Math.imul(h, 31) + stamp.charCodeAt(i)) | 0;
    return "MC-" + stamp.slice(0, 10) + "-" +
           (h >>> 0).toString(16).slice(0, 4).toUpperCase().padStart(4, "0");
  }

  /* ── Monte Carlo ─────────────────────────────────────────────────── */

  function simulate(priced, centres, residualSigma, region, budget) {
    var N = CFG.simulations, g = rng(4242);
    var totals = new Float64Array(N), lineSigma = [];

    priced.forEach(function (item, idx) {
      var material = item.material, quantity = item.quantity;
      var centre = centres[idx];
      var priceSigma = Math.hypot(region.volatility, material.volatility);
      var mean = 0, m2 = 0, n = 0;

      for (var i = 0; i < N; i++) {
        var waste = clamp(centre * g.lognormal(-0.5 * residualSigma * residualSigma, residualSigma),
                          0.002, 0.58);
        var price = item.unit_price * g.lognormal(-0.5 * priceSigma * priceSigma, priceSigma);
        var order = quantity / (1 - waste);
        var wasted = order - quantity;
        var wv = wasted * price;
        var landfillT = wasted * material.mass_kg_per_unit * (1 - material.recycle_rate) / 1000;
        var cost = order * price + landfillT * CFG.disposal_cost_per_tonne +
                   wv * CFG.rework_labour_ratio * region.labor_index -
                   wv * material.recycle_rate * CFG.salvage_ratio;
        totals[i] += cost;
        n++; var d = cost - mean; mean += d / n; m2 += d * (cost - mean);
      }
      lineSigma.push(Math.sqrt(m2 / n));
    });

    var sorted = Float64Array.from(totals); sorted.sort();
    var q = function (p) {
      var pos = (sorted.length - 1) * p, lo = Math.floor(pos), hi = Math.ceil(pos);
      return lo === hi ? sorted[lo] : sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
    };
    var p10 = q(0.10), p50 = q(0.50), p90 = q(0.90);
    var simRisk = 0;
    for (var i = 0; i < N; i++) if (totals[i] > budget) simRisk++;
    simRisk /= N;

    var safe = q(1 - CFG.target_overrun_risk);
    var bufferAmount = Math.max(safe - budget, 0);

    var lo = sorted[0], hi = sorted[sorted.length - 1], bins = 26;
    var width = (hi - lo) / bins || 1, counts = new Array(bins).fill(0);
    for (var j = 0; j < N; j++) {
      var b = Math.min(bins - 1, Math.floor((totals[j] - lo) / width));
      counts[b]++;
    }
    var histogram = counts.map(function (c, k) {
      return { x: r2(lo + width * (k + 0.5), 2), n: c };
    });

    return {
      p10: p10, p50: p50, p90: p90, sim_risk: simRisk,
      line_sigma: lineSigma, histogram: histogram,
      buffer: {
        amount: r2(bufferAmount, 2),
        pct_of_budget: r2(bufferAmount / Math.max(budget, 1) * 100, 2),
        recommended_budget: r2(budget + bufferAmount, 2),
        target_risk: Math.round(CFG.target_overrun_risk * 100),
        adequate: bufferAmount <= 0.5
      }
    };
  }

  /* ── risk attribution ────────────────────────────────────────────── */

  function rankRisk(lines, lineSigma) {
    var totalVar = lineSigma.reduce(function (a, s) { return a + s * s; }, 0) || 1;
    var totalWasted = lines.reduce(function (a, r) { return a + r.wasted_value; }, 0) || 1;

    var scored = lines.map(function (row, i) {
      var s = lineSigma[i];
      var varianceShare = s * s / totalVar;
      var wastedShare = row.wasted_value / totalWasted;
      var wastePenalty = Math.max(row.waste_pct - row.benchmark_pct, 0);
      var score = 40 * Math.min(varianceShare / 0.40, 1)
                + 25 * Math.min(wastedShare / 0.40, 1)
                + 15 * Math.min(wastePenalty / 4.0, 1)
                + 12 * Math.min(row.volatility / 0.20, 1)
                + 8 * row.fragility;

      var reasons = [];
      if (varianceShare > 0.28) reasons.push("drives " + Math.round(varianceShare * 100) + "% of the cost variance");
      if (row.waste_pct > row.benchmark_pct + 0.8)
        reasons.push(row.waste_pct.toFixed(1) + "% forecast against a " + row.benchmark_pct.toFixed(1) + "% benchmark");
      if (row.volatility >= 0.14) reasons.push("volatile unit price");
      if (row.fragility >= 0.5) reasons.push("damage-prone in handling");
      if (row.value_share >= 30) reasons.push(Math.round(row.value_share) + "% of package value");
      if (row.lead_time_days >= 30) reasons.push(row.lead_time_days + "-day lead time");
      if (!reasons.length) reasons.push("stable and inside benchmark");

      return {
        key: row.key, name: row.name, accent: row.accent, unit: row.unit,
        score: Math.min(Math.round(score), 100),
        band: score >= 55 ? "high" : score >= 32 ? "medium" : "low",
        variance_share: r2(varianceShare * 100, 1),
        wasted_value: row.wasted_value, waste_pct: row.waste_pct,
        benchmark_pct: row.benchmark_pct, value_share: row.value_share,
        cost_low: row.total_low, cost_high: row.total_high, reasons: reasons
      };
    });
    scored.sort(function (a, b) { return b.score - a.score; });
    return scored;
  }

  /* ── recommendations ─────────────────────────────────────────────── */

  function money(v) { return "$" + Math.round(v).toLocaleString("en-US"); }

  function recommendations(lines, risks, scheduleIntensity, budgetRatio, sim, ptype) {
    var advice = [], buffer = sim.buffer;

    if (!buffer.adequate) {
      advice.push({
        title: "Carry a " + buffer.pct_of_budget.toFixed(1) + "% contingency",
        detail: "A buffer of " + money(buffer.amount) + " takes the working budget to " +
                money(buffer.recommended_budget) + " and holds overrun risk at " +
                buffer.target_risk + "%.",
        tone: "violet"
      });
    } else {
      advice.push({
        title: "The stated budget already carries enough cover",
        detail: "The 90th-percentile outturn is " + money(sim.p90) +
                ", inside the budget. No additional contingency is indicated.",
        tone: "mint"
      });
    }

    if (budgetRatio < 0.92) {
      advice.push({
        title: "The budget sits below benchmark for this scope",
        detail: "At " + Math.round(budgetRatio * 100) + "% of benchmark cost this package is " +
                "priced tight. In the archive that correlates with thinner supervision and " +
                "higher waste, which the forecast above already reflects.",
        tone: "rose"
      });
    }

    var top = risks[0];
    if (top && top.band !== "low") {
      advice.push({
        title: "Put " + top.name + " under tighter control",
        detail: "It carries " + Math.round(top.variance_share) + "% of the cost variance and " +
                money(top.wasted_value) + " of forecast waste. Tighten the takeoff, " +
                "sequence deliveries and fix the price early.",
        tone: "amber"
      });
    }

    var longLead = lines.filter(function (r) { return r.lead_time_days >= 30; });
    if (longLead.length) {
      var names = longLead.slice(0, 3).map(function (r) { return r.name; }).join(", ");
      var worstLead = Math.max.apply(null, longLead.map(function (r) { return r.lead_time_days; }));
      advice.push({
        title: "Lock the long-lead items now",
        detail: names + " run " + worstLead + " days or more. Ordering these late is the " +
                "usual route into an overrun.",
        tone: "cyan"
      });
    }

    var over = lines.filter(function (r) { return r.waste_pct > r.benchmark_pct + 1.5; });
    if (over.length) {
      var worst = over.reduce(function (a, b) {
        return (b.waste_pct - b.benchmark_pct) > (a.waste_pct - a.benchmark_pct) ? b : a;
      });
      advice.push({
        title: worst.name + " is forecast well above benchmark",
        detail: worst.waste_pct.toFixed(1) + "% against " + worst.benchmark_pct.toFixed(1) +
                "%. Cut-list optimisation, offcut reuse and covered storage are the levers " +
                "that close that gap.",
        tone: "amber"
      });
    }

    if (scheduleIntensity > Math.max(ptype.typical_area / 30, 40)) {
      advice.push({
        title: "The programme is compressed for a job this size",
        detail: Math.round(scheduleIntensity) + " m² per week is fast for a " +
                ptype.name.toLowerCase() + ". Compression pushes waste up through rework " +
                "and double-handling.",
        tone: "rose"
      });
    }

    return advice.slice(0, 5);
  }


  /* ── site factor leverage ────────────────────────────────────────── */

  var SITE_FACTORS = [
    { key: "storage_ratio", label: "Storage size", poor: 0.30, good: 2.60,
      note: "covered area against what the job needs" },
    { key: "rain_days", label: "Rain frequency", poor: 24.0, good: 1.0,
      note: "wet days across the build window" },
    { key: "experience_years", label: "Contractor experience", poor: 2.0, good: 35.0,
      note: "years running work of this type" }
  ];

  function sensitivity(records, projectRecord, stated) {
    var base = P.predictOverrun(projectRecord);
    var factors = SITE_FACTORS.map(function (spec) {
      var ends = ["poor", "good"].map(function (end) {
        var moved = records.map(function (row) {
          var copy = Object.assign({}, row); copy[spec.key] = spec[end]; return copy;
        });
        var waste = P.predictWaste(moved).reduce(function (sum, b, i) {
          return sum + moved[i].line_value_share * b.centre;
        }, 0);
        var rec = Object.assign({}, projectRecord);
        rec[spec.key] = spec[end];
        rec.expected_waste = waste;
        return P.predictOverrun(rec);
      });
      var poor = ends[0], good = ends[1];
      var span = spec.good - spec.poor;
      var position = span ? (stated[spec.key] - spec.poor) / span : 0.5;
      return {
        key: spec.key, label: spec.label, note: spec.note,
        stated: r2(stated[spec.key], 2),
        swing_pp: r2(Math.abs(poor - good) * 100, 1),
        recoverable_pp: r2(Math.max(base - good, 0) * 100, 1),
        at_best_pct: r2(good * 100, 1), at_worst_pct: r2(poor * 100, 1),
        position: r2(clamp(position, 0, 1) * 100, 1),
        helps: good < poor
      };
    });
    // every factor at its good end at once - the floor is not the best single
    // factor, and the three do not simply add up
    var bestLines = records.map(function (row) {
      var copy = Object.assign({}, row);
      SITE_FACTORS.forEach(function (spec) { copy[spec.key] = spec.good; });
      return copy;
    });
    var bestRecord = Object.assign({}, projectRecord);
    SITE_FACTORS.forEach(function (spec) { bestRecord[spec.key] = spec.good; });
    bestRecord.expected_waste = P.predictWaste(bestLines).reduce(function (sum, b, i) {
      return sum + bestLines[i].line_value_share * b.centre;
    }, 0);
    var floor = P.predictOverrun(bestRecord);

    factors.sort(function (a, b) { return b.swing_pp - a.swing_pp; });
    return {
      base_pct: r2(base * 100, 1), factors: factors,
      // a stated value can already beat the "good" end, which would put the
      // floor above where the project stands; it is a floor, so clamp it
      recoverable_pp: r2(Math.max(base - floor, 0) * 100, 1),
      floor_pct: r2(Math.min(floor, base) * 100, 1)
    };
  }


  /* ── the recommendation paragraph ────────────────────────────────── */

  function summarise(project, cost, waste, overrun, buffer, sens, risks) {
    var money = function (v) { return "$" + Math.round(v).toLocaleString("en-US"); };
    var text = project.project_name + " is forecast to waste " + waste.pct.toFixed(1) +
      "% of its materials against a " + waste.benchmark_pct.toFixed(1) +
      "% trade benchmark, putting the outturn at " + money(cost.expected) +
      " against a stated budget of " + money(cost.budget) + ".";

    text += buffer.adequate
      ? " The budget already covers the 90th-percentile outturn, so no further " +
        "contingency is indicated - the reading is " + overrun.verdict.label.toLowerCase() + "."
      : " That reads as " + overrun.verdict.label.toLowerCase() + ": a contingency of " +
        money(buffer.amount) + " (" + buffer.pct_of_budget.toFixed(1) +
        "% of budget) brings the chance of exceeding the budget back to " +
        buffer.target_risk + "%.";

    var top = sens.factors[0];
    text += (top && sens.recoverable_pp >= 3)
      ? " Of the " + overrun.probability.toFixed(0) + "% overrun risk, roughly " +
        sens.recoverable_pp.toFixed(0) + " points sit in conditions you control: " +
        top.label.toLowerCase() + " alone moves it " + top.swing_pp.toFixed(0) +
        " points between its worst and best case."
      : " Storage, weather and contractor experience are all close to their best case " +
        "here, so little of the remaining risk is recoverable from site conditions.";

    if (risks.length) {
      text += " " + risks[0].name + " carries the most cost variance of any line (" +
        risks[0].variance_share.toFixed(0) + "%), so it is the one to fix a price on first.";
    }
    return text;
  }


  function recommend(sens, storageM2, storageNeed, buffer) {
    var by = {}; sens.factors.forEach(function (f) { by[f.key] = f; });
    var lead = sens.factors[0];
    var worth = function (f) { return f && f.recoverable_pp >= 3; };
    var n0 = function (v) { return Math.round(v).toLocaleString("en-US"); };
    var parts = [];

    parts.push(worth(lead)
      ? lead.label + " is the biggest lever on this project, of the " +
        sens.base_pct.toFixed(0) + "% chance of going over budget."
      : "Storage, rainfall and the contractor's experience are all set close to their " +
        "best case, so little of the remaining risk can be recovered from site conditions.");

    var storage = by.storage_ratio, ratio = storageNeed ? storageM2 / storageNeed : 1;
    if (worth(storage) && ratio < 0.9) {
      parts.push("Only " + n0(storageM2) + " m² is under cover against the " +
        n0(storageNeed) + " m² a job this size needs, which is worth " +
        storage.recoverable_pp.toFixed(0) + " points - getting the balance into covered, " +
        "secure storage stops material weathering, being double-handled and going missing.");
    } else if (worth(storage)) {
      parts.push("Storage covers what the job needs and no more (" + n0(storageM2) +
        " m² against " + n0(storageNeed) + " m²); the spare capacity to stage " +
        "deliveries properly is worth another " + storage.recoverable_pp.toFixed(0) + " points.");
    } else if (storage && ratio < 0.9) {
      parts.push("Storage is short of what the job needs (" + n0(storageM2) +
        " m² against " + n0(storageNeed) + " m²), though little of this " +
        "package's risk lands there.");
    } else if (storage) {
      parts.push("Covered storage is already ample at " + n0(storageM2) +
        " m², so there is nothing to win there.");
    }

    var rain = by.rain_days;
    var wet = function (f) {
      return f.stated.toFixed(0) + " wet day" + (Math.round(f.stated) === 1 ? "" : "s");
    };
    if (worth(rain)) {
      parts.push("At " + wet(rain) + " a month the weather carries " +
        rain.recoverable_pp.toFixed(0) + " points; sequencing boards, insulation and " +
        "finishes behind a watertight envelope, or moving them out of the wettest months, " +
        "is where that comes back.");
    } else if (rain) {
      parts.push("At " + wet(rain) + " a month rainfall is not driving this forecast.");
    }

    var crew = by.experience_years, years = crew ? crew.stated : 0;
    if (worth(crew) && years < 8) {
      parts.push("The contractor's " + years.toFixed(0) + " years on work of this type is " +
        "light and accounts for " + crew.recoverable_pp.toFixed(0) + " points - closable " +
        "with a stronger site manager and tighter takeoff review rather than a different price.");
    } else if (worth(crew)) {
      parts.push("At " + years.toFixed(0) + " years the contractor is experienced without " +
        "being seasoned; " + crew.recoverable_pp.toFixed(0) + " points sit between them and " +
        "a team that has done this many times over.");
    } else if (crew) {
      parts.push("With " + years.toFixed(0) + " years on work of this type the contractor " +
        "is already an asset to the forecast.");
    }

    if (sens.recoverable_pp >= 3) {
      var tail = buffer.adequate ? "" :
        ", taking the contingency below the " + buffer.pct_of_budget.toFixed(1) + "% now indicated";
      parts.push("Put all three right and the risk falls from " + sens.base_pct.toFixed(0) +
        "% to about " + sens.floor_pct.toFixed(0) + "%" + tail + ".");
    }
    return parts.join(" ");
  }

  /* ── the analysis ────────────────────────────────────────────────── */

  function analyse(raw) {
    var project = normalise(raw);
    var ptype = PTYPE[project.project_type], region = REGION[project.region];
    var area = project.project_area, duration = project.duration_weeks;
    var lineCount = project.lines.length;

    var priced = project.lines.map(function (line) {
      var material = MATERIAL[line.material];
      var unitPrice = material.unit_cost * region.cost_index;
      return { material: material, quantity: line.quantity, unit_price: unitPrice,
               gross: line.quantity * unitPrice };
    });

    var totalGross = priced.reduce(function (a, i) { return a + i.gross; }, 0) || 1;
    var benchmark = benchmarkCost(priced, region);

    var budget = project.budget, autoBudget = budget <= 0;
    if (autoBudget) budget = benchmark;
    var budgetRatio = budget / Math.max(benchmark, 1);
    var scheduleIntensity = area / Math.max(duration, 1);

    // Storage only means something relative to what a job this size needs.
    var storageNeed = Math.max(0.02 * area, 12);
    var storageRatio = project.storage_m2 / storageNeed;
    var rainDays = project.rain_days;
    var experienceYears = project.experience_years;

    var records = priced.map(function (item) {
      return {
        material: item.material.key, project_type: ptype.key, region: region.key,
        quantity_log: Math.log1p(item.quantity),
        project_area_log: Math.log1p(area),
        duration_weeks: duration, line_count: lineCount,
        line_value_share: item.gross / totalGross,
        budget_ratio: budgetRatio, schedule_intensity: scheduleIntensity,
        storage_ratio: storageRatio, rain_days: rainDays,
        experience_years: experienceYears
      };
    });

    var band = P.predictWaste(records);
    var centres = band.map(function (b) { return b.centre; });

    var expectedWaste = 0;
    var results = priced.map(function (item, i) {
      var material = item.material, b = band[i];
      var price = item.unit_price, labour = region.labor_index;
      var stack = lineCost(material, item.quantity, b.centre, price, labour);
      var lowStack = lineCost(material, item.quantity, b.low, price, labour);
      var highStack = lineCost(material, item.quantity, b.high, price, labour);
      var share = records[i].line_value_share;
      expectedWaste += share * b.centre;

      return {
        key: material.key, name: material.name, category: material.category,
        unit: material.unit, accent: material.accent,
        quantity: r2(item.quantity, 2), unit_price: r2(item.unit_price, 2),
        waste_pct: r2(b.centre * 100, 2), waste_low: r2(b.low * 100, 2),
        waste_high: r2(b.high * 100, 2), benchmark_pct: r2(material.base_waste * 100, 2),
        order_qty: r2(stack.order_qty, 2), waste_qty: r2(stack.waste_qty, 2),
        wasted_value: r2(stack.wasted_value, 2), procurement: r2(stack.procurement, 2),
        total: r2(stack.total, 2), total_low: r2(lowStack.total, 2),
        total_high: r2(highStack.total, 2),
        co2e_tonnes: r2(stack.co2e_tonnes, 2), waste_tonnes: r2(stack.waste_tonnes, 2),
        value_share: r2(share * 100, 1),
        volatility: material.volatility, fragility: material.fragility,
        lead_time_days: material.lead_time_days
      };
    });

    var expectedCost = results.reduce(function (a, r) { return a + r.total; }, 0);
    var wastedValue = results.reduce(function (a, r) { return a + r.wasted_value; }, 0);
    var weights = results.map(function (r) { return r.value_share / 100; });
    var wavg = function (pick) {
      var num = 0, den = 0;
      results.forEach(function (r, i) { num += pick(r) * weights[i]; den += weights[i]; });
      return den ? num / den : 0;
    };

    var projectRecord = {
      project_type: ptype.key, region: region.key,
      project_area_log: Math.log1p(area), duration_weeks: duration,
      line_count: lineCount, budget_ratio: budgetRatio,
      budget_per_m2: budget / Math.max(area, 1),
      schedule_intensity: scheduleIntensity,
      storage_ratio: storageRatio, rain_days: rainDays,
      experience_years: experienceYears,
      expected_waste: expectedWaste,
      mix_concentration: weights.reduce(function (a, w) { return a + w * w; }, 0),
      fragile_share: results.reduce(function (a, r, i) {
        return a + (r.fragility > 0.35 ? weights[i] : 0); }, 0),
      volatility_weighted: results.reduce(function (a, r, i) {
        return a + weights[i] * r.volatility; }, 0)
    };
    var classifierRisk = P.predictOverrun(projectRecord);

    var sens = sensitivity(records, projectRecord, {
      storage_ratio: storageRatio, rain_days: rainDays, experience_years: experienceYears
    });
    var sim = simulate(priced, centres, M.residual_sigma, region, budget);
    var risks = rankRisk(results, sim.line_sigma);
    var advice = recommendations(results, risks, scheduleIntensity, budgetRatio, sim, ptype);

    var out = {
      reference: reference(),
      recommendation: recommend(sens, project.storage_m2, storageNeed, sim.buffer),
      summary: summarise(project,
        { expected: r2(expectedCost, 2), budget: r2(budget, 2) },
        { pct: r2(expectedWaste * 100, 2),
          benchmark_pct: r2(wavg(function (r) { return r.benchmark_pct; }), 2) },
        { verdict: verdict(classifierRisk), probability: r2(classifierRisk * 100, 1) },
        sim.buffer, sens, risks),
      created_at: new Date().toISOString().replace(/\.\d+Z$/, "+00:00"),
      project: Object.assign({}, project, {
        budget: r2(budget, 2), auto_budget: autoBudget,
        project_type_name: ptype.name, project_type_family: ptype.family,
        region_name: region.name, cost_index: region.cost_index,
        schedule_intensity: r2(scheduleIntensity, 1),
        storage_need: r2(storageNeed, 1), storage_ratio: r2(storageRatio, 3)
      }),
      waste: {
        pct: r2(expectedWaste * 100, 2),
        low_pct: r2(wavg(function (r) { return r.waste_low; }), 2),
        high_pct: r2(wavg(function (r) { return r.waste_high; }), 2),
        benchmark_pct: r2(wavg(function (r) { return r.benchmark_pct; }), 2),
        wasted_value: r2(wastedValue, 2),
        tonnes: r2(results.reduce(function (a, r) { return a + r.waste_tonnes; }, 0), 2),
        co2e_tonnes: r2(results.reduce(function (a, r) { return a + r.co2e_tonnes; }, 0), 2)
      },
      cost: {
        benchmark: r2(benchmark, 2), expected: r2(expectedCost, 2), budget: r2(budget, 2),
        budget_ratio: r2(budgetRatio, 3), variance: r2(budget - expectedCost, 2),
        procurement: r2(results.reduce(function (a, r) { return a + r.procurement; }, 0), 2)
      },
      overrun: {
        probability: r2(classifierRisk * 100, 1),
        simulated: r2(sim.sim_risk * 100, 1),
        verdict: verdict(classifierRisk),
        p10: r2(sim.p10, 2), p50: r2(sim.p50, 2), p90: r2(sim.p90, 2),
        histogram: sim.histogram
      },
      buffer: sim.buffer,
      sensitivity: sens,
      lines: results,
      risks: risks,
      advice: advice,
      model: M.metrics
    };
    return out;
  }

  global.MCWPEngine = {
    analyse: analyse,
    normalise: normalise,
    suggestedLines: suggestedLines,
    materials: M.materials
  };
})(typeof window !== "undefined" ? window : globalThis);
