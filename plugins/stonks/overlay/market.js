/* Gamer Stonks overlay helpers. No CDN — OBS / XSplit CEF friendly. */
(function (root) {
  const qs = new URLSearchParams(location.search);

  function param(name, fallback) {
    const v = qs.get(name);
    return v === null || v === "" ? fallback : v;
  }

  function fmtPx(n) {
    n = Number(n || 0);
    if (!isFinite(n)) return "—";
    if (Math.abs(n) >= 100) return n.toFixed(1);
    return n.toFixed(2);
  }

  function fmtChg(delta, pct) {
    const d = Number(delta || 0);
    const p = Number(pct || 0);
    const sign = d > 0 ? "+" : "";
    return `${sign}${fmtPx(d)}  ${sign}${p.toFixed(2)}%`;
  }

  function dir(pct) {
    if (pct > 0.02) return "up";
    if (pct < -0.02) return "down";
    return "flat";
  }

  async function fetchState() {
    const book = param("book", "");
    const symbols = param("symbols", param("symbol", ""));
    const q = new URLSearchParams();
    if (book) q.set("book", book);
    if (symbols) q.set("symbols", symbols);
    const url = "/api/market/state" + (q.toString() ? "?" + q.toString() : "");
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error("market state " + r.status);
    return r.json();
  }

  async function fetchHistory(symbol, points) {
    const q = new URLSearchParams({
      symbol: symbol,
      points: String(points || 120),
    });
    const r = await fetch("/api/market/history?" + q.toString(), { cache: "no-store" });
    if (!r.ok) throw new Error("market history " + r.status);
    return r.json();
  }

  function filterInstruments(list) {
    const book = param("book", "");
    const raw = param("symbols", param("symbol", ""));
    const want = raw
      ? raw.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean)
      : [];
    return (list || []).filter((it) => {
      if (book && it.book !== book && !(it.book || "").endsWith(":" + book)) return false;
      if (want.length && !want.includes(it.symbol)) return false;
      return true;
    });
  }

  function drawSeries(canvas, points, color, opts) {
    if (!canvas) return;
    opts = opts || {};
    const mode = opts.mode || "spark";
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 320;
    const h = canvas.clientHeight || 120;
    canvas.width = Math.max(1, Math.floor(w * dpr));
    canvas.height = Math.max(1, Math.floor(h * dpr));
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const vals = (points || []).map((p) => Number(p.p)).filter((n) => isFinite(n));
    if (vals.length < 2) {
      ctx.fillStyle = "rgba(243,239,228,0.35)";
      ctx.font = "12px Segoe UI, sans-serif";
      ctx.fillText("Waiting for ticks…", 14, h / 2);
      return;
    }

    const tv = mode === "tv";
    const padL = tv ? 8 : 0;
    const padR = tv ? 52 : 0;
    const padT = tv ? 8 : 0;
    const padB = tv ? 22 : 0;
    const plotW = Math.max(8, w - padL - padR);
    const plotH = Math.max(8, h - padT - padB);

    let min = Math.min.apply(null, vals);
    let max = Math.max.apply(null, vals);
    if (max === min) {
      min -= 0.2;
      max += 0.2;
    }
    const pad = (max - min) * 0.14;
    min -= pad;
    max += pad;

    const xAt = (i) => padL + (i / (vals.length - 1)) * plotW;
    const yAt = (v) => padT + plotH - ((v - min) / (max - min)) * plotH;
    const last = vals[vals.length - 1];
    const first = vals[0];
    const stroke = color || (last >= first ? "#3dd68c" : "#ff5d73");
    const fillTop = last >= first ? "rgba(61,214,140,0.28)" : "rgba(255,93,115,0.24)";
    const fillBot = last >= first ? "rgba(61,214,140,0.02)" : "rgba(255,93,115,0.02)";

    const gridN = tv ? 4 : 3;
    ctx.strokeStyle = "rgba(243,239,228,0.10)";
    ctx.lineWidth = 1;
    ctx.font = "11px Cascadia Mono, Consolas, monospace";
    ctx.fillStyle = "rgba(243,239,228,0.42)";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let i = 0; i <= gridN; i++) {
      const y = padT + (plotH * i) / gridN;
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(padL + plotW, y);
      ctx.stroke();
      if (tv) {
        const v = max - ((max - min) * i) / gridN;
        ctx.fillText(fmtPx(v), w - 6, y);
      }
    }

    if (tv && opts.open != null && isFinite(opts.open)) {
      const oy = yAt(Number(opts.open));
      ctx.save();
      ctx.strokeStyle = "rgba(214,176,80,0.45)";
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(padL, oy);
      ctx.lineTo(padL + plotW, oy);
      ctx.stroke();
      ctx.restore();
    }

    const grad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
    grad.addColorStop(0, fillTop);
    grad.addColorStop(1, fillBot);
    ctx.beginPath();
    vals.forEach((v, i) => {
      const x = xAt(i);
      const y = yAt(v);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.lineTo(xAt(vals.length - 1), padT + plotH);
    ctx.lineTo(xAt(0), padT + plotH);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    ctx.beginPath();
    vals.forEach((v, i) => {
      const x = xAt(i);
      const y = yAt(v);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = stroke;
    ctx.lineWidth = tv ? 2.4 : 2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();

    const lastY = yAt(last);
    ctx.fillStyle = stroke;
    ctx.beginPath();
    ctx.arc(xAt(vals.length - 1), lastY, tv ? 4 : 3, 0, Math.PI * 2);
    ctx.fill();

    if (tv) {
      ctx.fillStyle = "rgba(243,239,228,0.38)";
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillText("session", padL, h - 16);
      ctx.textAlign = "right";
      ctx.fillText("now", padL + plotW, h - 16);
    }
  }

  function startTicker(trackEl, innerEl, speedPx) {
    let offset = 0;
    let last = performance.now();
    let width = 0;

    function measure() {
      width = innerEl.scrollWidth / 2;
    }
    measure();
    window.addEventListener("resize", measure);

    function frame(now) {
      const dt = Math.min(48, now - last);
      last = now;
      offset += (speedPx * dt) / 1000;
      if (width > 0 && offset >= width) offset -= width;
      innerEl.style.transform = "translateX(" + (-offset) + "px)";
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
    return measure;
  }

  // Ticker names / books can come from game bridges — escape before innerHTML.
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  root.FridgeMarket = {
    esc,
    qs,
    param,
    fmtPx,
    fmtChg,
    dir,
    fetchState,
    fetchHistory,
    filterInstruments,
    drawSeries,
    startTicker,
  };
})(window);
