/* ==========================================================================
   MCWP - page behaviour: theme, scroll spy, materials list, live prediction
   ========================================================================== */

(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  /* ---------------------------------------------------------------- theme */

  const THEME_KEY = "mcwp-theme";
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_KEY, theme);
    $$("[data-theme-icon]").forEach((node) => {
      node.style.display = node.dataset.themeIcon === theme ? "block" : "none";
    });
  }
  applyTheme(localStorage.getItem(THEME_KEY) || "dark");

  document.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-theme-toggle]");
    if (!toggle) return;
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(next);
    document.dispatchEvent(new CustomEvent("mcwp:theme", { detail: next }));
  });

  /* ---------------------------------------------------------------- clock */

  const clock = $("[data-clock]");
  if (clock) {
    const tick = () => {
      const now = new Date();
      clock.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    };
    tick();
    setInterval(tick, 1000);
  }

  /* ------------------------------------------------------------- reveal -- */

  const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry, index) => {
      if (!entry.isIntersecting) return;
      const delay = Number(entry.target.dataset.delay || index * 55);
      entry.target.style.animationDelay = `${delay}ms`;
      entry.target.classList.add("in");
      revealObserver.unobserve(entry.target);
    });
  }, { threshold: 0.08, rootMargin: "0px 0px -40px 0px" });
  $$(".reveal").forEach((node) => revealObserver.observe(node));

  /* ------------------------------------------------------------ count up -- */

  function countUp(node) {
    const target = parseFloat(node.dataset.count);
    if (!isFinite(target)) return;
    const decimals = Number(node.dataset.decimals || 0);
    const prefix = node.dataset.prefix || "";
    const suffix = node.dataset.suffix || "";
    const compact = node.dataset.compact === "1";
    const duration = 1150;
    const start = performance.now();

    const format = (value) => {
      if (compact) return prefix + window.MC.fmt.compact(value) + suffix;
      return prefix + value.toLocaleString(undefined, {
        minimumFractionDigits: decimals, maximumFractionDigits: decimals,
      }) + suffix;
    };

    const frame = (now) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      node.textContent = format(target * eased);
      if (t < 1) requestAnimationFrame(frame);
      else node.textContent = format(target);
    };
    requestAnimationFrame(frame);
  }

  const countObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      countUp(entry.target);
      countObserver.unobserve(entry.target);
    });
  }, { threshold: 0.4 });
  $$("[data-count]").forEach((node) => countObserver.observe(node));

  /* ------------------------------------------------------ bar animations -- */

  const fillObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      const node = entry.target;
      requestAnimationFrame(() => { node.style.width = `${node.dataset.fill}%`; });
      fillObserver.unobserve(node);
    });
  }, { threshold: 0.2 });
  $$("[data-fill]").forEach((node) => fillObserver.observe(node));

  /* -------------------------------------------------------------- toasts -- */

  function dismiss(toast) {
    toast.classList.add("out");
    setTimeout(() => toast.remove(), 420);
  }
  $$(".toast").forEach((toast) => {
    setTimeout(() => dismiss(toast), 5200);
    const close = $(".x", toast);
    if (close) close.addEventListener("click", () => dismiss(toast));
  });

  window.mcToast = function (message, kind = "info") {
    let host = $(".toasts");
    if (!host) {
      host = document.createElement("div");
      host.className = "toasts";
      document.body.appendChild(host);
    }
    const toast = document.createElement("div");
    toast.className = `toast ${kind}`;
    toast.innerHTML = `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg>
      <div>${message}</div><button class="x" aria-label="Dismiss">&times;</button>`;
    host.appendChild(toast);
    $(".x", toast).addEventListener("click", () => dismiss(toast));
    setTimeout(() => dismiss(toast), 5200);
  };

  /* ------------------------------------------------- materials list rows -- */

  const linesHost = $("#lines");
  if (linesHost) {
    const form = $("#brief-form");
    const units = JSON.parse(document.getElementById("unit-map").textContent);

    const syncUnit = (row) => {
      const key = $("select", row).value;
      const suffix = $(".suffix", row);
      if (suffix) suffix.textContent = units[key] || "";
    };
    const syncState = () => {
      const rows = $$(".line-row", linesHost);
      rows.forEach((row) => {
        $(".line-drop", row).disabled = rows.length <= 1;
      });
    };

    $$(".line-row", linesHost).forEach(syncUnit);
    syncState();

    $("#add-line").addEventListener("click", () => {
      const rows = $$(".line-row", linesHost);
      if (rows.length >= 10) {
        window.mcToast("Ten materials is the maximum for one package.", "warn");
        return;
      }
      const clone = rows[rows.length - 1].cloneNode(true);
      // Step the new row on to a material that is not already in the list.
      const chosen = new Set(rows.map((row) => $("select", row).value));
      const select = $("select", clone);
      const options = Array.from(select.options).map((o) => o.value);
      select.value = options.find((value) => !chosen.has(value)) || options[0];
      $("input", clone).value = Math.round(Number($("input", rows[rows.length - 1]).value) || 100);
      linesHost.appendChild(clone);
      syncUnit(clone);
      syncState();
      clone.classList.add("just-added");
      form.dispatchEvent(new Event("change", { bubbles: true }));
    });

    linesHost.addEventListener("click", (event) => {
      const drop = event.target.closest(".line-drop");
      if (!drop) return;
      if ($$(".line-row", linesHost).length <= 1) return;
      drop.closest(".line-row").remove();
      syncState();
      form.dispatchEvent(new Event("change", { bubbles: true }));
    });

    linesHost.addEventListener("change", (event) => {
      const row = event.target.closest(".line-row");
      if (row) syncUnit(row);
    });

    const sample = $("#load-sample");
    if (sample) {
      const rebuild = (lines) => {
        const template = $(".line-row", linesHost);
        linesHost.innerHTML = "";
        lines.forEach((line) => {
          const row = template.cloneNode(true);
          $("select", row).value = line.material;
          $("input", row).value = line.quantity;
          linesHost.appendChild(row);
          syncUnit(row);
        });
        syncState();
      };

      sample.addEventListener("click", () => {
        const next = Number(sessionStorage.getItem("mcwp-sample") || 0);
        sample.disabled = true;
        fetch(`/api/sample?i=${next}`)
          .then((response) => response.json())
          .then((data) => {
            sessionStorage.setItem("mcwp-sample", String((next + 1) % data.count));
            form.elements.project_name.value = data.project_name;
            form.elements.project_type.value = data.project_type;
            form.elements.region.value = data.region;
            form.elements.project_area.value = data.project_area;
            form.elements.duration_weeks.value = data.duration_weeks;
            form.elements.budget.value = data.budget;
            rebuild(data.lines);
            // Submit so the whole page reflects the sample, not just the headline.
            form.submit();
          })
          .catch(() => {
            sample.disabled = false;
            window.mcToast("Could not load the sample.", "warn");
          });
      });
    }

    const suggest = $("#suggest-lines");
    if (suggest) {
      suggest.addEventListener("click", () => {
        const type = $("#f-type").value;
        const area = $("#f-area").value;
        fetch(`/api/suggest?project_type=${encodeURIComponent(type)}&area=${encodeURIComponent(area)}`)
          .then((response) => response.json())
          .then((lines) => {
            const template = $(".line-row", linesHost);
            linesHost.innerHTML = "";
            lines.forEach((line) => {
              const row = template.cloneNode(true);
              $("select", row).value = line.material;
              $("input", row).value = line.quantity;
              linesHost.appendChild(row);
              syncUnit(row);
            });
            syncState();
            window.mcToast(`Loaded a typical ${lines.length}-material list for this project.`, "success");
            form.dispatchEvent(new Event("change", { bubbles: true }));
          })
          .catch(() => window.mcToast("Could not load a suggestion.", "warn"));
      });
    }

    /* ------------------------------------------- live headline prediction */

    const stale = $("#stale");
    let timer = null;
    let inflight = null;
    let firstRun = true;

    const payload = () => ({
      project_name: form.elements.project_name.value,
      project_type: form.elements.project_type.value,
      region: form.elements.region.value,
      project_area: form.elements.project_area.value,
      duration_weeks: form.elements.duration_weeks.value,
      budget: form.elements.budget.value,
      lines: $$(".line-row", linesHost).map((row) => ({
        material: $("select", row).value,
        quantity: $("input", row).value,
      })),
    });

    const set = (name, value) => {
      const node = document.querySelector(`[data-out="${name}"]`);
      if (node) node.textContent = value;
    };

    const refresh = () => {
      if (inflight) inflight.abort();
      inflight = new AbortController();
      fetch("/api/analyse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload()),
        signal: inflight.signal,
      })
        .then((response) => response.json())
        .then((data) => {
          set("waste", data.waste.pct.toFixed(2));
          set("waste-band", `${data.waste.low_pct.toFixed(1)}–${data.waste.high_pct.toFixed(1)}%`);
          set("wasted-value", window.MC.fmt.money(data.waste.wasted_value));
          set("overrun", data.overrun.probability.toFixed(1));
          set("verdict", data.overrun.verdict.label);
          set("buffer", window.MC.fmt.moneyCompact(data.buffer.amount));
          set("buffer-pct", data.buffer.pct_of_budget.toFixed(1));
          set("risk-count", data.risks.filter((row) => row.band === "high").length);
          set("expected", window.MC.fmt.money(data.cost.expected));
          set("stated", window.MC.fmt.money(data.cost.budget));
          set("headroom", window.MC.fmt.money(data.cost.variance));
          set("simulated", `${data.overrun.simulated.toFixed(1)}%`);
          set("leg-budget", window.MC.fmt.money(data.cost.budget));
          set("leg-p50", window.MC.fmt.money(data.overrun.p50));
          set("leg-p90", window.MC.fmt.money(data.overrun.p90));

          // Verdict badges carry their tone as a class, so recolour them too.
          document.querySelectorAll('[data-out="verdict"], [data-out="verdict2"]')
            .forEach((node) => {
              node.textContent = data.overrun.verdict.label;
              node.className = `badge ${data.overrun.verdict.tone}`;
            });
          const headroom = document.querySelector('[data-out="headroom"]');
          if (headroom) {
            headroom.className = `ml-auto mono ${data.cost.variance >= 0 ? "c-mint" : "c-rose"}`;
          }

          if (stale && !firstRun) stale.hidden = false;
          firstRun = false;

          if (window.repaintOutturn) window.repaintOutturn(data);
        })
        .catch((error) => {
          if (error.name === "AbortError") return;
          firstRun = false;
          console.error("live prediction failed", error);
        });
    };

    form.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(refresh, 320);
    });
    form.addEventListener("change", () => {
      clearTimeout(timer);
      timer = setTimeout(refresh, 90);
    });
  }

  /* ------------------------------------------------------- table search -- */

  const filter = $("[data-table-filter]");
  if (filter) {
    const table = $(filter.dataset.tableFilter);
    filter.addEventListener("input", () => {
      const needle = filter.value.toLowerCase().trim();
      let shown = 0;
      $$("tbody tr", table).forEach((row) => {
        const match = row.textContent.toLowerCase().includes(needle);
        row.style.display = match ? "" : "none";
        if (match) shown += 1;
      });
      const counter = $("[data-filter-count]");
      if (counter) counter.textContent = shown;
    });
  }

  /* --------------------------------------------------------- print/copy -- */

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-print]")) window.print();

    const copy = event.target.closest("[data-copy]");
    if (copy) {
      navigator.clipboard.writeText(copy.dataset.copy)
        .then(() => window.mcToast("Copied to clipboard.", "success"))
        .catch(() => window.mcToast("Clipboard unavailable.", "warn"));
    }
  });
})();
