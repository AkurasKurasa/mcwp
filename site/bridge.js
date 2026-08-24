/* Serves the Flask app's own API from the browser.
 *
 * static/js/app.js is unmodified: it still fetches /api/analyse, /api/sample
 * and /api/suggest on every input change. This intercepts those calls and
 * answers them from engine.js instead of a Python process, so the page behaves
 * exactly as it does under Flask.
 *
 * It also re-renders the three sections Jinja used to render server-side -
 * the materials table, the risk ranking and the advice cards - which under
 * Flask only refreshed on a full page POST.
 */
(function () {
  "use strict";

  var E = window.MCWPEngine, M = window.MCWP_MODEL;
  if (!E || !M) throw new Error("engine.js must load before bridge.js");

  /* ── fetch shim ──────────────────────────────────────────────────── */

  function json(body) {
    if (typeof Response === "function") {
      return Promise.resolve(new Response(JSON.stringify(body), {
        status: 200, headers: { "Content-Type": "application/json" }
      }));
    }
    // Response is not universally available; app.js only needs .json()
    return Promise.resolve({
      ok: true, status: 200,
      json: function () { return Promise.resolve(body); },
      text: function () { return Promise.resolve(JSON.stringify(body)); }
    });
  }

  var nativeFetch = window.fetch ? window.fetch.bind(window) : null;

  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || "";
    var path = url.split("?")[0];
    var query = new URLSearchParams(url.indexOf("?") >= 0 ? url.split("?")[1] : "");

    if (path === "/api/analyse") {
      var payload = {};
      try { payload = JSON.parse((init && init.body) || "{}"); } catch (e) { payload = {}; }
      return json(E.analyse(payload));
    }
    if (path === "/api/sample") {
      var i = parseInt(query.get("i"), 10);
      if (!isFinite(i)) i = 0;
      var list = M.samples || [];
      return json(list.length ? list[((i % list.length) + list.length) % list.length] : {});
    }
    if (path === "/api/suggest") {
      var pt = query.get("project_type") || M.defaults.project_type;
      var area = parseFloat(query.get("area"));
      if (!isFinite(area)) area = 9200;
      return json(E.suggestedLines(pt, Math.max(area, 50)));
    }
    if (path === "/api/materials") return json(M.materials);
    if (path === "/api/health") return json({ status: "ok", model: M.metrics });

    if (nativeFetch) return nativeFetch(input, init);
    return Promise.reject(new Error("offline: " + url));
  };

  /* ── re-render what Jinja used to render ─────────────────────────── */

  var SYM = "$";
  var esc = function (s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  };
  var money = function (v) {
    var n = Number(v) || 0;
    return (n < 0 ? "-" : "") + SYM + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });
  };
  var num = function (v, d) {
    return (Number(v) || 0).toLocaleString("en-US",
      { minimumFractionDigits: d, maximumFractionDigits: d });
  };

  function renderLines(lines) {
    var body = document.querySelector("table.data tbody");
    if (!body) return;
    body.innerHTML = lines.map(function (l) {
      return '<tr>' +
        '<td><div class="row gap-8">' +
          '<span class="swatch" style="background:' + esc(l.accent) + '"></span>' +
          '<div class="cell-title"><b>' + esc(l.name) + '</b>' +
          '<span>' + num(l.value_share, 1) + '% of value &middot; ' + SYM +
            num(l.unit_price, 2) + '/' + esc(l.unit) + '</span></div>' +
        '</div></td>' +
        '<td class="right muted">' + num(l.quantity, 0) + '</td>' +
        '<td class="right">' + num(l.order_qty, 0) + '</td>' +
        '<td class="right strong">' + num(l.waste_pct, 2) + '%' +
          '<div class="tiny dim">' + num(l.waste_low, 2) + '–' + num(l.waste_high, 2) + '</div></td>' +
        '<td class="right c-rose">' + money(l.wasted_value) + '</td>' +
        '<td class="right">' + money(l.total) + '</td>' +
      '</tr>';
    }).join("");
  }

  function renderRisks(risks) {
    var host = document.querySelector(".stack.gap-16");
    if (!host) return;
    host.innerHTML = risks.map(function (r) {
      var tone = r.band === "high" ? "rose" : r.band === "medium" ? "amber" : "mint";
      return '<div class="risk-row">' +
        '<div class="row gap-8 mb-8">' +
          '<span class="swatch" style="background:' + esc(r.accent) + '"></span>' +
          '<b class="small">' + esc(r.name) + '</b>' +
          '<span class="badge ' + tone + ' ml-auto">' + esc(r.band) + ' · ' + r.score + '</span>' +
        '</div>' +
        '<div class="rail"><div class="fill" data-fill="' + r.score +
          '" style="background:' + esc(r.accent) + ';width:' + r.score + '%"></div></div>' +
        '<div class="tiny dim mt-8">' + esc(r.reasons.join(" · ")) + '</div>' +
      '</div>';
    }).join("");
  }

  function renderAdvice(advice) {
    var host = document.querySelector("#actions .grid.g2");
    if (!host) return;
    host.innerHTML = advice.map(function (a, i) {
      return '<div class="panel lift reveal advice ' + esc(a.tone) + '" style="opacity:1;transform:none">' +
        '<div class="row gap-12 mb-8"><span class="rank">' + (i + 1) + '</span>' +
        '<b>' + esc(a.title) + '</b></div>' +
        '<p class="small muted" style="margin:0">' + esc(a.detail) + '</p>' +
      '</div>';
    }).join("");
  }

  function renderAll(data) {
    if (!data) return;
    renderLines(data.lines || []);
    renderRisks(data.risks || []);
    renderAdvice(data.advice || []);
  }

  /* app.js calls window.repaintOutturn(data) after every live refresh, so
     wrapping it keeps the tables in step with the headline figures. */
  window.addEventListener("load", function () {
    var chart = window.repaintOutturn;
    window.repaintOutturn = function (data) {
      if (typeof chart === "function") { try { chart(data); } catch (e) { /* chart only */ } }
      renderAll(data);
    };

    var form = document.getElementById("brief-form");
    if (!form) return;

    // No server to post to: let the live path do the work.
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      form.dispatchEvent(new Event("input", { bubbles: true }));
      var target = document.getElementById("forecast");
      if (target && target.scrollIntoView) {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });

    // app.js calls form.submit() directly after loading a sample, which would
    // bypass the submit listener and navigate. Route it back to the live path.
    form.submit = function () {
      form.dispatchEvent(new Event("input", { bubbles: true }));
    };
  });
})();
