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

  /* The materials table, risk ranking and advice cards that used to be
     re-rendered here were removed from the page. The remaining dynamic
     content - the site-factor bars, the summary and the recommendation
     list - is rendered by the page's own renderFactors(), which runs from
     repaintOutturn for both the Flask app and this build.

     Nothing may target ".stack.gap-16" from here: that class now belongs to
     the factor-bar container, and writing risk rows into it silently
     replaced the factor bars. */

  /* app.js calls window.repaintOutturn(data) after every live refresh, so
     wrapping it keeps the tables in step with the headline figures. */
  window.addEventListener("load", function () {
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
