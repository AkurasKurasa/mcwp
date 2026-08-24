/* MCWP model evaluation in the browser.
 *
 * Mirrors sklearn's _predict_one_from_raw_data: numerical splits compare
 * against num_threshold, categorical splits test a bit in the node's left
 * bitset, and NaN follows missing_go_to_left. Categories arrive as their
 * index into CATEGORY_LEVELS, which is what pandas hands sklearn.
 */
(function (global) {
  "use strict";

  var M = global.MCWP_MODEL;
  if (!M) throw new Error("model.js must load before predict.js");

  /* sklearn's OrdinalEncoder sorts categories, so a code is the index into
     the encoder's own sorted list - not into catalog.CATEGORY_LEVELS. The
     export carries the fitted encoder's order for each feature space. */
  function indexOf(levels) {
    var out = {};
    Object.keys(levels).forEach(function (col) {
      var map = {};
      levels[col].forEach(function (key, i) { map[key] = i; });
      out[col] = map;
    });
    return out;
  }
  var LINE_INDEX = indexOf(M.encoders.line);
  var PROJECT_INDEX = indexOf(M.encoders.project);

  /* ── tree evaluation ─────────────────────────────────────────────── */

  function inBitset(bitset, val) {
    if (!(val >= 0) || val >= 256 || val !== Math.floor(val)) return false;
    return ((bitset[val >> 5] >>> (val & 31)) & 1) === 1;
  }

  function evalTree(t, x) {
    var i = 0;
    while (!t.lf[i]) {
      var v = x[t.f[i]], left;
      if (v === null || v === undefined || v !== v) {
        left = !!t.m[i];
      } else if (t.c[i]) {
        left = inBitset(t.bs[t.b[i]], v);
      } else {
        left = v <= t.t[i];
      }
      i = left ? t.l[i] : t.r[i];
    }
    return t.v[i];
  }

  function rawPredict(name, x) {
    var m = M.models[name], sum = m.baseline, trees = m.trees;
    for (var k = 0; k < trees.length; k++) sum += evalTree(trees[k], x);
    return sum;
  }

  function sigmoid(z) { return 1 / (1 + Math.exp(-z)); }

  /* ── feature vectors ─────────────────────────────────────────────── */

  function code(index, col, key) {
    var i = index[col] && index[col][key];
    return i === undefined ? NaN : i;
  }

  function lineVector(rec) {
    return M.features.line.map(function (f) {
      return M.features.line_cat.indexOf(f) >= 0
        ? code(LINE_INDEX, f, rec[f]) : Number(rec[f]);
    });
  }

  function projectVector(rec) {
    return M.features.project.map(function (f) {
      return M.features.project_cat.indexOf(f) >= 0
        ? code(PROJECT_INDEX, f, rec[f]) : Number(rec[f]);
    });
  }

  /* ── public predictions ──────────────────────────────────────────── */

  var clip = function (v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; };

  function predictWaste(records) {
    var k = M.calibration || 1.0;
    return records.map(function (rec) {
      var x = lineVector(rec);
      var centre = clip(rawPredict("center", x), 0.002, 0.60);
      var lo = centre - k * (centre - rawPredict("lower", x));
      var hi = centre + k * (rawPredict("upper", x) - centre);
      return {
        centre: centre,
        low: clip(Math.min(lo, centre * 0.99), 0.001, 0.60),
        high: clip(Math.max(hi, centre * 1.01), 0.002, 0.72)
      };
    });
  }

  function predictOverrun(record) {
    return sigmoid(rawPredict("overrun", projectVector(record)));
  }

  global.MCWPPredict = {
    predictWaste: predictWaste,
    predictOverrun: predictOverrun,
    rawPredict: rawPredict,
    lineVector: lineVector,
    projectVector: projectVector,
    lineIndex: LINE_INDEX,
    projectIndex: PROJECT_INDEX
  };
})(typeof window !== "undefined" ? window : globalThis);
