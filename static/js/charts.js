/* ==========================================================================
   MCWP - a small dependency-free SVG charting kit.
   Every chart is plain SVG built through the DOM, themed from CSS variables,
   and animated on first paint.
   ========================================================================== */

(function (global) {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  let uid = 0;
  const nextId = (p) => `${p}-${(++uid).toString(36)}`;

  function el(name, attrs, parent) {
    const node = document.createElementNS(NS, name);
    for (const key in attrs || {}) {
      if (attrs[key] === null || attrs[key] === undefined) continue;
      node.setAttribute(key, attrs[key]);
    }
    if (parent) parent.appendChild(node);
    return node;
  }

  /* Charts render at their host's true pixel width so that a requested
     height is the height you actually get, in any column. */
  function hostWidth(host, fallback) {
    const w = host.clientWidth || host.getBoundingClientRect().width;
    return Math.max(Math.round(w) || fallback, 300);
  }

  function remember(host, fn, opts) {
    host.__mcRender = () => fn(host, opts);
    resizeWatcher.observe(host);
  }

  let resizeTimer = null;
  const pending = new Set();
  const resizeWatcher = new ResizeObserver((entries) => {
    entries.forEach((entry) => {
      const host = entry.target;
      if (host.__mcWidth === host.clientWidth) return;
      host.__mcWidth = host.clientWidth;
      pending.add(host);
    });
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      pending.forEach((host) => { if (host.__mcRender) host.__mcRender(); });
      pending.clear();
    }, 180);
  });

  function svgRoot(host, w, h) {
    host.innerHTML = "";
    const svg = el("svg", {
      viewBox: `0 0 ${w} ${h}`,
      role: "img",
      preserveAspectRatio: "xMidYMid meet",
    }, host);
    return svg;
  }

  /* ----------------------------------------------------------- tooltip -- */

  let tip;
  function tooltip() {
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "chart-tip";
      document.body.appendChild(tip);
    }
    return tip;
  }
  function showTip(html, event) {
    const node = tooltip();
    node.innerHTML = html;
    node.classList.add("show");
    const box = node.getBoundingClientRect();
    let x = event.clientX + 16;
    let y = event.clientY - box.height - 12;
    if (x + box.width > window.innerWidth - 12) x = event.clientX - box.width - 16;
    if (y < 12) y = event.clientY + 18;
    node.style.left = `${x}px`;
    node.style.top = `${y}px`;
  }
  function hideTip() { if (tip) tip.classList.remove("show"); }

  /* ------------------------------------------------------------- utils -- */

  const fmt = {
    num: (v, d = 1) => Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }),
    pct: (v, d = 1) => `${Number(v).toFixed(d)}%`,
    money: (v) => `$${Math.round(Number(v)).toLocaleString()}`,
    compact: (v) => {
      const n = Math.abs(Number(v));
      const s = Number(v) < 0 ? "-" : "";
      if (n >= 1e9) return `${s}${(n / 1e9).toFixed(2)}B`;
      if (n >= 1e6) return `${s}${(n / 1e6).toFixed(2)}M`;
      if (n >= 1e3) return `${s}${(n / 1e3).toFixed(1)}K`;
      return `${s}${n.toFixed(0)}`;
    },
    moneyCompact: (v) => `$${fmt.compact(v)}`,
  };

  function niceTicks(min, max, count = 4) {
    if (min === max) { min -= 1; max += 1; }
    const span = max - min;
    const raw = span / count;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
    const start = Math.floor(min / step) * step;
    const end = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = start; v <= end + step * 0.001; v += step) ticks.push(Number(v.toFixed(10)));
    return ticks;
  }

  function smoothPath(points, tension = 0.32) {
    if (points.length < 2) return "";
    let d = `M${points[0][0]},${points[0][1]}`;
    for (let i = 0; i < points.length - 1; i++) {
      const p0 = points[i - 1] || points[i];
      const p1 = points[i];
      const p2 = points[i + 1];
      const p3 = points[i + 2] || p2;
      const c1x = p1[0] + (p2[0] - p0[0]) * tension / 3;
      const c1y = p1[1] + (p2[1] - p0[1]) * tension / 3;
      const c2x = p2[0] - (p3[0] - p1[0]) * tension / 3;
      const c2y = p2[1] - (p3[1] - p1[1]) * tension / 3;
      d += ` C${c1x},${c1y} ${c2x},${c2y} ${p2[0]},${p2[1]}`;
    }
    return d;
  }

  function animateDraw(path) {
    try {
      const len = path.getTotalLength();
      path.style.setProperty("--len", len);
      path.classList.add("draw-in");
    } catch (_) { /* non-rendered host */ }
  }

  /* ------------------------------------------------------- area / line -- */

  function areaChart(host, opts) {
    if (!host) return;
    const o = Object.assign({
      height: 260, labels: [], series: [], format: fmt.num,
      yFormat: null, showArea: true, band: null, minZero: true,
    }, opts);
    const W = hostWidth(host, 860), H = o.height;
    const pad = { t: 18, r: 16, b: 30, l: 52 };
    const svg = svgRoot(host, W, H);
    remember(host, areaChart, o);
    const iw = W - pad.l - pad.r;
    const ih = H - pad.t - pad.b;

    let values = o.series.flatMap((s) => s.values);
    if (o.band) values = values.concat(o.band.low, o.band.high);
    let lo = Math.min(...values), hi = Math.max(...values);
    if (o.minZero) lo = 0;
    const pad_v = (hi - lo) * 0.12 || 1;
    let ticks = niceTicks(o.minZero ? 0 : lo - pad_v * 0.6, hi + pad_v, 4);
    if (o.minZero) ticks = ticks.filter((t) => t >= 0);
    const yMin = ticks[0], yMax = ticks[ticks.length - 1];

    const X = (i) => pad.l + (o.labels.length > 1 ? (i / (o.labels.length - 1)) * iw : iw / 2);
    const Y = (v) => pad.t + ih - ((v - yMin) / (yMax - yMin)) * ih;
    const yFmt = o.yFormat || o.format;

    ticks.forEach((t) => {
      el("line", { class: "grid-line", x1: pad.l, x2: W - pad.r, y1: Y(t), y2: Y(t) }, svg);
      el("text", { class: "tick", x: pad.l - 10, y: Y(t) + 3.5, "text-anchor": "end" }, svg)
        .textContent = yFmt(t);
    });

    const every = Math.max(1, Math.ceil(o.labels.length / 9));
    o.labels.forEach((label, i) => {
      if (i % every && i !== o.labels.length - 1) return;
      el("text", { class: "tick", x: X(i), y: H - 8, "text-anchor": "middle" }, svg)
        .textContent = label;
    });

    if (o.band) {
      const up = o.band.high.map((v, i) => [X(i), Y(v)]);
      const down = o.band.low.map((v, i) => [X(i), Y(v)]).reverse();
      const gid = nextId("band");
      const defs = el("defs", {}, svg);
      const grad = el("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
      el("stop", { offset: "0%", "stop-color": o.band.color || "var(--tone-3)", "stop-opacity": 0.22 }, grad);
      el("stop", { offset: "100%", "stop-color": o.band.color || "var(--tone-3)", "stop-opacity": 0.05 }, grad);
      el("path", {
        d: `${smoothPath(up)} L${down[0][0]},${down[0][1]} ${smoothPath(down).slice(1)} Z`,
        fill: `url(#${gid})`, stroke: "none", class: "fade-in-area",
      }, svg);
    }

    o.series.forEach((s) => {
      const pts = s.values.map((v, i) => [X(i), Y(v)]);
      const line = smoothPath(pts);
      if (o.showArea && s.area !== false) {
        const gid = nextId("area");
        const defs = el("defs", {}, svg);
        const grad = el("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
        el("stop", { offset: "0%", "stop-color": s.color, "stop-opacity": 0.36 }, grad);
        el("stop", { offset: "100%", "stop-color": s.color, "stop-opacity": 0 }, grad);
        el("path", {
          d: `${line} L${X(pts.length - 1)},${pad.t + ih} L${pad.l},${pad.t + ih} Z`,
          fill: `url(#${gid})`, stroke: "none", class: "fade-in-area",
        }, svg);
      }
      const path = el("path", {
        d: line, class: "series-path", stroke: s.color,
        "stroke-dasharray": s.dashed ? "6 5" : null,
      }, svg);
      if (!s.dashed) animateDraw(path);
      s._pts = pts;
    });

    // hover layer
    const cross = el("line", { class: "crosshair", y1: pad.t, y2: pad.t + ih }, svg);
    const markers = o.series.map((s) =>
      el("circle", { r: 5, fill: s.color, stroke: "var(--bg)", "stroke-width": 2, opacity: 0 }, svg));

    const hit = el("rect", { class: "hit", x: pad.l, y: pad.t, width: iw, height: ih }, svg);
    hit.addEventListener("mousemove", (event) => {
      const box = svg.getBoundingClientRect();
      const rel = ((event.clientX - box.left) / box.width) * W;
      const i = Math.max(0, Math.min(o.labels.length - 1,
        Math.round(((rel - pad.l) / iw) * (o.labels.length - 1))));
      cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i));
      cross.style.opacity = 1;
      let html = `<div class="t-title">${o.labels[i]}</div>`;
      o.series.forEach((s, k) => {
        markers[k].setAttribute("cx", X(i));
        markers[k].setAttribute("cy", Y(s.values[i]));
        markers[k].setAttribute("opacity", 1);
        html += `<div class="t-row"><span class="swatch" style="background:${s.color}"></span>` +
                `${s.name} <b style="margin-left:auto">${(s.format || o.format)(s.values[i])}</b></div>`;
      });
      if (o.band) {
        html += `<div class="t-row dim" style="opacity:.7">band ${o.format(o.band.low[i])} - ${o.format(o.band.high[i])}</div>`;
      }
      showTip(html, event);
    });
    hit.addEventListener("mouseleave", () => {
      cross.style.opacity = 0;
      markers.forEach((m) => m.setAttribute("opacity", 0));
      hideTip();
    });
  }

  /* --------------------------------------------------------------- donut */

  function donut(host, opts) {
    if (!host) return;
    const o = Object.assign({ slices: [], size: 240, thickness: 26, format: fmt.moneyCompact,
      centerCap: "Total" }, opts);
    const S = o.size, R = (S - o.thickness) / 2 - 6, C = S / 2;
    const svg = svgRoot(host, S, S);
    const total = o.slices.reduce((a, s) => a + s.value, 0) || 1;
    const circ = 2 * Math.PI * R;

    el("circle", { cx: C, cy: C, r: R, fill: "none", stroke: "var(--track)",
      "stroke-width": o.thickness }, svg);

    const ring = el("g", { transform: `rotate(-90 ${C} ${C})` }, svg);
    let offset = 0;
    o.slices.forEach((slice, index) => {
      const share = slice.value / total;
      const dash = Math.max(share * circ - 3, 0.5);
      const arc = el("circle", {
        class: "arc", cx: C, cy: C, r: R, fill: "none",
        stroke: slice.accent, "stroke-width": o.thickness, "stroke-linecap": "round",
        "stroke-dasharray": `${dash} ${circ - dash}`,
        "stroke-dashoffset": -offset,
      }, ring);
      arc.style.opacity = 0;
      arc.style.animation = `fade-area .5s var(--ease) ${index * 0.07 + 0.15}s forwards`;
      arc.addEventListener("mousemove", (event) => showTip(
        `<div class="t-title">${slice.label}</div><div class="t-row"><b>${o.format(slice.value)}</b>` +
        `<span class="dim">${(share * 100).toFixed(1)}%</span></div>`, event));
      arc.addEventListener("mouseleave", hideTip);
      offset += share * circ;
    });

    const g = el("g", {}, svg);
    el("text", { x: C, y: C - 4, "text-anchor": "middle", fill: "var(--text)",
      "font-size": 25, "font-weight": 600, "font-family": "var(--font-display)" }, g)
      .textContent = o.centerValue || o.format(total);
    el("text", { x: C, y: C + 18, "text-anchor": "middle", fill: "var(--dim)",
      "font-size": 11, "letter-spacing": 1.6 }, g).textContent = o.centerCap.toUpperCase();
  }

  /* ----------------------------------------------------------- bars (v) */

  function bars(host, opts) {
    if (!host) return;
    const o = Object.assign({ height: 250, labels: [], groups: [], format: fmt.num,
      yFormat: null, rotate: false }, opts);
    const W = hostWidth(host, 860), H = o.height;
    const pad = { t: 16, r: 12, b: o.rotate ? 62 : 30, l: 52 };
    const svg = svgRoot(host, W, H);
    remember(host, bars, o);
    const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;

    const all = o.groups.flatMap((g) => g.values);
    const ticks = niceTicks(0, Math.max(...all) * 1.08, 4);
    const yMax = ticks[ticks.length - 1];
    const Y = (v) => pad.t + ih - (v / yMax) * ih;
    const yFmt = o.yFormat || o.format;

    ticks.forEach((t) => {
      el("line", { class: "grid-line", x1: pad.l, x2: W - pad.r, y1: Y(t), y2: Y(t) }, svg);
      el("text", { class: "tick", x: pad.l - 10, y: Y(t) + 3.5, "text-anchor": "end" }, svg)
        .textContent = yFmt(t);
    });

    const slot = iw / o.labels.length;
    const n = o.groups.length;
    const bw = Math.min(38, (slot * 0.66) / n);

    o.labels.forEach((label, i) => {
      const cx = pad.l + slot * (i + 0.5);
      o.groups.forEach((group, k) => {
        const value = group.values[i];
        const x = cx - (n * bw) / 2 + k * bw + (n > 1 ? 1.5 : 0);
        const h = Math.max(ih - (Y(value) - pad.t), 2);
        const rect = el("rect", {
          class: "bar", x, y: pad.t + ih, width: Math.max(bw - 3, 3), height: 0,
          rx: 5, fill: group.color,
        }, svg);
        rect.style.transition = `y .9s var(--ease) ${i * 0.03 + k * 0.06}s, height .9s var(--ease) ${i * 0.03 + k * 0.06}s`;
        requestAnimationFrame(() => {
          rect.setAttribute("y", Y(value));
          rect.setAttribute("height", h);
        });
        rect.addEventListener("mousemove", (event) => showTip(
          `<div class="t-title">${label}</div><div class="t-row">` +
          `<span class="swatch" style="background:${group.color}"></span>${group.name} ` +
          `<b style="margin-left:auto">${o.format(value)}</b></div>`, event));
        rect.addEventListener("mouseleave", hideTip);
      });
      const text = el("text", {
        class: "tick", x: cx, y: o.rotate ? pad.t + ih + 14 : H - 8,
        "text-anchor": o.rotate ? "end" : "middle",
      }, svg);
      if (o.rotate) text.setAttribute("transform", `rotate(-38 ${cx} ${pad.t + ih + 14})`);
      text.textContent = label.length > 20 ? `${label.slice(0, 19)}...` : label;
    });
  }

  /* ------------------------------------------------------------- scatter */

  function scatter(host, opts) {
    if (!host) return;
    const o = Object.assign({ height: 300, points: [], xLabel: "", yLabel: "",
      xFormat: fmt.num, yFormat: fmt.pct, diagonal: false }, opts);
    const W = hostWidth(host, 860), H = o.height;
    const pad = { t: 18, r: 18, b: 40, l: 54 };
    const svg = svgRoot(host, W, H);
    remember(host, scatter, o);
    const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;

    const xs = o.points.map((p) => p.x), ys = o.points.map((p) => p.y);
    const xt = niceTicks(Math.min(...xs), Math.max(...xs), 5)
      .filter((t) => o.max === undefined || t <= o.max);
    const yt = niceTicks(0, Math.max(...ys) * 1.05, 4)
      .filter((t) => o.max === undefined || t <= o.max);
    const X = (v) => pad.l + ((v - xt[0]) / (xt[xt.length - 1] - xt[0])) * iw;
    const Y = (v) => pad.t + ih - ((v - yt[0]) / (yt[yt.length - 1] - yt[0])) * ih;

    yt.forEach((t) => {
      el("line", { class: "grid-line", x1: pad.l, x2: W - pad.r, y1: Y(t), y2: Y(t) }, svg);
      el("text", { class: "tick", x: pad.l - 10, y: Y(t) + 3.5, "text-anchor": "end" }, svg)
        .textContent = o.yFormat(t);
    });
    xt.forEach((t) => {
      el("text", { class: "tick", x: X(t), y: H - 20, "text-anchor": "middle" }, svg)
        .textContent = o.xFormat(t);
    });

    if (o.diagonal) {
      const lo = Math.max(xt[0], yt[0]);
      const hi = Math.min(xt[xt.length - 1], yt[yt.length - 1]);
      el("line", {
        x1: X(lo), y1: Y(lo), x2: X(hi), y2: Y(hi),
        stroke: "var(--border-hi)", "stroke-width": 1.4, "stroke-dasharray": "6 6",
      }, svg);
    }

    const rs = o.points.map((p) => p.r || 1);
    const rMax = Math.max(...rs) || 1;

    o.points.forEach((p, i) => {
      const r = p.r ? 3 + Math.sqrt(p.r / rMax) * 8 : 4.5;
      const dot = el("circle", {
        class: "dot", cx: X(p.x), cy: Y(p.y), r: 0,
        fill: p.accent || "var(--tone-3)", opacity: 0.62,
        stroke: p.accent || "var(--tone-3)", "stroke-width": 1, "stroke-opacity": 0.9,
      }, svg);
      dot.style.transition = `r .7s var(--ease) ${(i % 40) * 0.012}s`;
      requestAnimationFrame(() => dot.setAttribute("r", r));
      dot.addEventListener("mousemove", (event) => showTip(
        `<div class="t-title">${p.label || "Project"}</div>` +
        `<div class="t-row">${o.xLabel} <b style="margin-left:auto">${o.xFormat(p.x)}</b></div>` +
        `<div class="t-row">${o.yLabel} <b style="margin-left:auto">${o.yFormat(p.y)}</b></div>` +
        (p.r ? `<div class="t-row dim">value ${fmt.moneyCompact(p.r)}</div>` : ""), event));
      dot.addEventListener("mouseleave", hideTip);
    });

    if (o.xLabel) {
      el("text", { class: "tick", x: pad.l + iw / 2, y: H - 4, "text-anchor": "middle" }, svg)
        .textContent = o.xLabel;
    }
  }

  /* --------------------------------------------------------------- gauge */

  function gauge(host, opts) {
    if (!host) return;
    const o = Object.assign({ value: 0, max: 100, size: 200, thickness: 15,
      color: "var(--tone-2)", label: "", format: (v) => Math.round(v) }, opts);
    const S = o.size, H = S * 0.62;
    const R = S / 2 - o.thickness / 2 - 4;
    const C = { x: S / 2, y: S / 2 - 4 };
    const svg = svgRoot(host, S, H);

    const arc = (from, to) => {
      const a0 = Math.PI + from * Math.PI, a1 = Math.PI + to * Math.PI;
      const x0 = C.x + R * Math.cos(a0), y0 = C.y + R * Math.sin(a0);
      const x1 = C.x + R * Math.cos(a1), y1 = C.y + R * Math.sin(a1);
      // A gauge sweep never exceeds 180 degrees, so large-arc is always 0.
      // Setting it otherwise makes the renderer pick the opposite circle centre.
      return `M${x0},${y0} A${R},${R} 0 0 1 ${x1},${y1}`;
    };

    el("path", { d: arc(0, 1), fill: "none", stroke: "var(--track)",
      "stroke-width": o.thickness, "stroke-linecap": "round" }, svg);

    const gid = nextId("gg");
    const defs = el("defs", {}, svg);
    const grad = el("linearGradient", { id: gid, x1: 0, y1: 0, x2: 1, y2: 0 }, defs);
    el("stop", { offset: "0%", "stop-color": o.color, "stop-opacity": 0.45 }, grad);
    el("stop", { offset: "100%", "stop-color": o.color }, grad);

    const share = Math.max(0.001, Math.min(1, o.value / o.max));
    const path = el("path", {
      d: arc(0, share), fill: "none", stroke: `url(#${gid})`,
      "stroke-width": o.thickness, "stroke-linecap": "round",
    }, svg);
    animateDraw(path);

    const angle = Math.PI + share * Math.PI;
    el("circle", {
      cx: C.x + R * Math.cos(angle), cy: C.y + R * Math.sin(angle), r: o.thickness / 2 + 2,
      fill: "var(--bg)", stroke: o.color, "stroke-width": 3,
    }, svg);

    el("text", { x: C.x, y: C.y - 6, "text-anchor": "middle", fill: "var(--text)",
      "font-size": 30, "font-weight": 700, "font-family": "var(--font-display)" }, svg)
      .textContent = o.format(o.value);
    if (o.label) {
      el("text", { x: C.x, y: C.y + 14, "text-anchor": "middle", fill: "var(--dim)",
        "font-size": 10.5, "letter-spacing": 1.6 }, svg).textContent = o.label.toUpperCase();
    }
  }

  /* ----------------------------------------------------------- sparkline */

  function sparkline(host, values, color) {
    if (!host || !values || values.length < 2) return;
    const W = 120, H = 34;
    const svg = svgRoot(host, W, H);
    const lo = Math.min(...values), hi = Math.max(...values);
    const span = hi - lo || 1;
    const pts = values.map((v, i) => [
      (i / (values.length - 1)) * W,
      H - 3 - ((v - lo) / span) * (H - 8),
    ]);
    const gid = nextId("sp");
    const defs = el("defs", {}, svg);
    const grad = el("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    el("stop", { offset: "0%", "stop-color": color, "stop-opacity": 0.45 }, grad);
    el("stop", { offset: "100%", "stop-color": color, "stop-opacity": 0 }, grad);
    const d = smoothPath(pts);
    el("path", { d: `${d} L${W},${H} L0,${H} Z`, fill: `url(#${gid})`, stroke: "none" }, svg);
    const line = el("path", { d, fill: "none", stroke: color, "stroke-width": 2,
      "stroke-linecap": "round" }, svg);
    animateDraw(line);
    el("circle", { cx: pts[pts.length - 1][0] - 1, cy: pts[pts.length - 1][1], r: 2.6, fill: color }, svg);
  }

  /* -------------------------------------------------- outturn distribution */

  function distribution(host, opts) {
    if (!host) return;
    const o = Object.assign({
      height: 280, bins: [], markers: [], format: fmt.moneyCompact,
      tipFormat: fmt.money, accent: "var(--tone-3)",
    }, opts);
    if (!o.bins.length) return;

    const W = hostWidth(host, 860), H = o.height;
    const pad = { t: 44, r: 18, b: 18, l: 18 };
    const svg = svgRoot(host, W, H);
    remember(host, distribution, o);
    const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;

    const xs = o.bins.map((b) => b.x);
    let lo = Math.min(...xs, ...o.markers.map((m) => m.x));
    let hi = Math.max(...xs, ...o.markers.map((m) => m.x));
    const margin = (hi - lo) * 0.06 || 1;
    lo -= margin; hi += margin;
    const peak = Math.max(...o.bins.map((b) => b.n)) || 1;

    const X = (v) => pad.l + ((v - lo) / (hi - lo)) * iw;
    const Y = (n) => pad.t + ih - (n / peak) * ih;

    const gid = nextId("dist");
    const defs = el("defs", {}, svg);
    const grad = el("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    el("stop", { offset: "0%", "stop-color": o.accent, "stop-opacity": 0.85 }, grad);
    el("stop", { offset: "100%", "stop-color": o.accent, "stop-opacity": 0.25 }, grad);

    const step = o.bins.length > 1 ? X(o.bins[1].x) - X(o.bins[0].x) : iw / 12;
    const bw = Math.max(step - 2, 1.5);

    o.bins.forEach((bin, i) => {
      const h = Math.max(ih - (Y(bin.n) - pad.t), 0.8);
      const rect = el("rect", {
        class: "bar", x: X(bin.x) - bw / 2, y: pad.t + ih, width: bw, height: 0,
        rx: Math.min(3, bw / 2), fill: `url(#${gid})`,
      }, svg);
      rect.style.transition = `y .8s var(--ease) ${i * 0.012}s, height .8s var(--ease) ${i * 0.012}s`;
      requestAnimationFrame(() => {
        rect.setAttribute("y", Y(bin.n));
        rect.setAttribute("height", h);
      });
      rect.addEventListener("mousemove", (event) => showTip(
        `<div class="t-title">${o.tipFormat(bin.x)}</div>` +
        `<div class="t-row">${bin.n} of the simulated outturns</div>`, event));
      rect.addEventListener("mouseleave", hideTip);
    });

    el("line", { class: "axis-line", x1: pad.l, x2: W - pad.r,
      y1: pad.t + ih, y2: pad.t + ih }, svg);

    // Markers can sit on top of each other, so labels alternate between two
    // rows and only step down when the previous one is actually in the way.
    let lastX = -Infinity;
    let row = 0;
    o.markers.slice().sort((a, b) => a.x - b.x).forEach((marker) => {
      const x = X(marker.x);
      row = (x - lastX) < 78 ? 1 - row : 0;
      lastX = x;
      const labelY = pad.t - 20 + row * 13;

      el("line", {
        x1: x, x2: x, y1: labelY + 4, y2: pad.t + ih,
        stroke: marker.color, "stroke-width": marker.bold ? 2.2 : 1.4,
        "stroke-dasharray": marker.bold ? null : "5 4", opacity: 0.95,
      }, svg);
      el("text", {
        x, y: labelY, "text-anchor": x > W - 80 ? "end" : x < 80 ? "start" : "middle",
        fill: marker.color, "font-size": 10.5, "font-weight": 700, "letter-spacing": 0.6,
      }, svg).textContent = marker.label.toUpperCase();
    });
  }

  global.MC = { areaChart, donut, bars, scatter, gauge, sparkline, distribution,
                fmt, showTip, hideTip };
})(window);
