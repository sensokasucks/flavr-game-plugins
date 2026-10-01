(function () {
  const STATS = "/stats";
  const statusEl = document.getElementById("status");

  function pct(cur, max) {
    const c = Number(cur);
    const m = Number(max);
    if (!isFinite(c) || !isFinite(m) || m <= 0) return 0;
    return Math.max(0, Math.min(100, (c / m) * 100));
  }

  function text(id, value, fallback) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = value == null || value === "" ? (fallback || "—") : String(value);
  }

  function bar(id, cur, max) {
    const el = document.getElementById(id);
    if (el) el.style.width = pct(cur, max) + "%";
  }

  async function tick() {
    try {
      const r = await fetch(STATS, { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      const s = await r.json();
      if (statusEl) {
        statusEl.textContent = s.is_host ? "HOST" : "CLIENT";
        statusEl.className = "status ok";
      }
      const p = s.pilot || {};
      const c = s.campaign || {};
      const q = s.squad || {};
      text("hp", p.health);
      text("hp-max", p.health_max);
      bar("hp-bar", p.health, p.health_max);
      text("heat", p.heat);
      text("heat-max", p.heat_max);
      bar("heat-bar", p.heat, p.heat_max);
      text("phase", s.phase);
      text("region", c.region || c.name);
      text("credits", c.credits);
      text("hours", c.hours_left);
      text("threat", c.threat);
      text("squad", (q.count || 0) + " / " + (q.max || 10));
      text("kills", p.kills);
      text("note", (s.notes && s.notes[0]) || "");
    } catch (err) {
      if (statusEl) {
        statusEl.textContent = "OFFLINE";
        statusEl.className = "status bad";
      }
    }
  }

  tick();
  setInterval(tick, 1500);
})();
