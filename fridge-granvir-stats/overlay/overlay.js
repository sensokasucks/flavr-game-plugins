/* Granvir stats overlay script, loaded by every page in this folder.
   Polls GET /stats (BepInEx plugin or mock/mock_server.py, port 3855) every 1.5 s
   and fills whichever of these element ids the page has: hp, hp-max, hp-bar, heat,
   heat-max, heat-bar, phase, region, credits, hours, threat, squad, kills, note,
   status. The badge shows HOST or CLIENT, or OFFLINE when /stats does not answer. */
(function () {
  const STATS = "/stats";
  const statusEl = document.getElementById("status");

  // cur as a percentage of max, clamped 0..100 (0 when max is missing).
  function pct(cur, max) {
    const c = Number(cur);
    const m = Number(max);
    if (!isFinite(c) || !isFinite(m) || m <= 0) return 0;
    return Math.max(0, Math.min(100, (c / m) * 100));
  }

  // Set an element's text if the page has it; empty values show a dash.
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
