/* Sumotori Dreams page (pages/index.html). API: ../routes.py (Round and Arena file tabs) and Core's
   /api/admin/plugins routes (Settings tab).

   window.StreamCore (api, escapeHtml, resize) comes from the dashboard's plugin-page.js and sends
   the admin token. Refreshes every 2 s while the page is open so the bet countdown moves. */
(() => {
  const $ = (id) => document.getElementById(id);
  const { api, escapeHtml, resize } = window.StreamCore;
  const PLUGIN = "sumotori";

  function say(msg) { $("status").textContent = msg || ""; }

  let last = null;    // last GET /api/sumotori/admin answer
  let keepUntil = 0;  // Date.now() until which a button's message stays instead of the refresh's

  async function load() {
    let d;
    try {
      d = await api("/api/sumotori/admin");
    } catch (e) {
      say(String(e.message || e));
      return;
    }
    last = d;
    const a = d.sides.a, b = d.sides.b;
    $("name-a").textContent = a;
    $("name-b").textContent = b;
    $("win-a").textContent = a + " won";
    $("win-b").textContent = b + " won";
    $("score-a").textContent = d.score.a;
    $("score-b").textContent = d.score.b;
    $("streak").textContent = d.score.streak >= 2
      ? `${d.sides[d.score.streak_side]} has won ${d.score.streak} in a row.` : `${d.score.rounds} rounds counted.`;

    // Bets: state line, buttons that make sense now, top bettors.
    const r = d.round;
    let line;
    if (!d.bets_enabled) line = "Bets are switched off (Settings tab).";
    else if (!r) line = "No bets running. Open bets before the fight starts.";
    else if (r.state === "open") {
      const left = r.locks_at ? Math.max(0, Math.round(r.locks_at - Date.now() / 1000)) : null;
      line = `Bets open${left !== null ? `, closing in ${left}s` : " until you close them"}: ` +
        `${a} ${r.pools.a.toLocaleString()} (${r.pools.a_n}) vs ${b} ${r.pools.b.toLocaleString()} (${r.pools.b_n}).`;
    } else line = `Bets closed: ${a} ${r.pools.a.toLocaleString()} vs ${b} ${r.pools.b.toLocaleString()}. Press who won.`;
    $("round-line").textContent = line;
    $("b-open").disabled = !d.bets_enabled || !!r;
    $("b-lock").disabled = !r || r.state !== "open";
    $("b-cancel").disabled = !r;
    $("bets").querySelector("tbody").innerHTML = (r ? r.top : []).map((t) =>
      `<tr><td>${escapeHtml(t.who)}</td><td class="${t.side === "a" ? "side-a" : "side-b"}">${escapeHtml(d.sides[t.side])}</td><td>${t.amount.toLocaleString()}</td></tr>`).join("");

    // Arena: queued pieces (next_round) or the pieces in the arena now ("now" mode).
    const list = d.apply === "now" ? d.arena : d.queue;
    $("queue-title").textContent = d.apply === "now" ? `Arena #${d.arena_no} (pieces show up straight away)` : `Next arena (#${d.arena_no + 1})`;
    $("queue").innerHTML = list.map((p) => `<li>${escapeHtml(p.name)} <span class="muted">from ${escapeHtml(p.who)}</span></li>`).join("")
      || `<li class="muted">Nothing yet. ${d.pieces_enabled ? "Chat types !arena to see what's for sale." : "Arena pieces are switched off."}</li>`;
    $("b-next").hidden = d.apply === "now";

    // Arena file tab
    $("file-path").textContent = d.arena_file;
    $("last-write").textContent = d.error ? d.error
      : d.last_write ? `Last written ${new Date(d.last_write * 1000).toLocaleTimeString()} (arena #${d.arena_no}).` : "";
    $("file-text").textContent = d.file_text || "(no file yet)";
    if (Date.now() > keepUntil) say(d.error || "");
    resize();
  }

  async function post(path, body) {
    try {
      const res = await api(path, { method: "POST", body: JSON.stringify(body || {}) });
      say(res && res.ok === false ? (res.error || "Not done") : "");
    } catch (e) {
      say(String(e.message || e));
    }
    keepUntil = Date.now() + 5000;
    await load();
  }

  document.addEventListener("click", (ev) => {
    const r = ev.target.closest("button[data-round]");
    if (r) return post("/api/sumotori/round", { action: r.dataset.round });
    const a = ev.target.closest("button[data-arena]");
    if (a) {
      if (a.dataset.arena === "clear" && !confirm("Take every queued piece out?")) return;
      return post("/api/sumotori/arena", { action: a.dataset.arena });
    }
  });
  $("b-reset").addEventListener("click", () => {
    if (confirm("Start the score from 0 - 0?")) post("/api/sumotori/score/reset");
  });
  $("copy-path").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(last ? last.arena_file : ""); say("Path copied."); keepUntil = Date.now() + 3000; }
    catch (_) { say("Couldn't copy; select the path and press Ctrl+C."); }
  });

  // ---------------------------------------------------------------- tabs

  const TAB_KEY = "sumotori.tab";     // remembered tab (this browser only)

  function showTab(sub) {
    const tabs = Array.from(document.querySelectorAll("#tabs .subtab"));
    if (!tabs.some((b) => b.dataset.sub === sub)) sub = "round";
    tabs.forEach((b) => {
      const on = b.dataset.sub === sub;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll("section.sub").forEach((s) => { s.hidden = s.dataset.sub !== sub; });
    if (sub === "settings") loadSettings();
    try { localStorage.setItem(TAB_KEY, sub); } catch (_) { /* private window: fine */ }
    resize();
  }

  $("tabs").addEventListener("click", (ev) => {
    const b = ev.target.closest(".subtab");
    if (b) showTab(b.dataset.sub);
  });

  // ---------------------------------------------------------------- settings tab
  // Same as the Schedule I page (plugins/schedule1/pages/customers.js), plus "map" fields (the piece
  // prices) as a "piece: points" textarea. Saved with PUT /api/admin/plugins/sumotori/settings, which
  // turns that text back into numbers (Core api/admin_routes.py); plugin.py reads its config live.

  function pathGet(obj, key) {
    return String(key).split(".").reduce((cur, part) => (cur && typeof cur === "object" ? cur[part] : undefined), obj);
  }

  function fieldHtml(f, value) {
    const type = f.type || "text";
    const attrs = `id="f-${escapeHtml(f.key)}" class="plg-field" data-key="${escapeHtml(f.key)}" data-type="${escapeHtml(type)}"`;
    const label = escapeHtml(f.label || f.key);
    const help = f.help ? ` <span class="field-help">${escapeHtml(f.help)}</span>` : "";
    if (type === "checkbox") {
      return `<label class="check"><input type="checkbox" ${attrs} ${value ? "checked" : ""} /> ${label}${help}</label>`;
    }
    if (type === "map") {
      const text = Object.entries(value || {}).map(([k, v]) => k + ": " + v).join("\n");
      return `<label>${label}${help}<textarea ${attrs} rows="7">${escapeHtml(text)}</textarea></label>`;
    }
    if (type === "select") {
      const opts = (f.options || []).map((o) =>
        `<option value="${escapeHtml(String(o))}" ${String(o) === String(value ?? "") ? "selected" : ""}>${escapeHtml(String(o))}</option>`).join("");
      return `<label>${label}${help}<select ${attrs}>${opts}</select></label>`;
    }
    const shown = type === "list" ? (Array.isArray(value) ? value.join(", ") : String(value ?? "")) : (value ?? "");
    const inputType = type === "number" ? "number" : "text";
    const extra = type === "number"
      ? ["min", "max", "step"].filter((k) => f[k] != null).map((k) => ` ${k}="${escapeHtml(String(f[k]))}"`).join("") : "";
    return `<label>${label}${help}<input type="${inputType}" ${attrs} value="${escapeHtml(String(shown))}"${extra} /></label>`;
  }

  async function loadSettings() {
    let p;
    try {
      p = ((await api("/api/admin/plugins")).plugins || []).find((x) => x.id === PLUGIN);
    } catch (e) {
      $("settings-status").textContent = String(e.message || e);
      return;
    }
    if (!p) return;
    const groups = [];
    (p.settings || []).filter((f) => f.page).forEach((f) => {
      const name = f.group || "Settings";
      let g = groups.find((x) => x.name === name);
      if (!g) groups.push((g = { name, fields: [] }));
      g.fields.push(f);
    });
    $("settings").innerHTML = groups.map((g) =>
      `<fieldset class="cfg-card"><legend>${escapeHtml(g.name)}</legend>` +
      g.fields.map((f) => fieldHtml(f, pathGet(p.values || {}, f.key))).join("") +
      `</fieldset>`).join("");
    resize();
  }

  $("save-settings").addEventListener("click", async () => {
    const values = {};
    $("settings").querySelectorAll(".plg-field").forEach((el) => {
      values[el.dataset.key] = el.dataset.type === "checkbox" ? el.checked : el.value;
    });
    try {
      await api(`/api/admin/plugins/${PLUGIN}/settings`, { method: "PUT", body: JSON.stringify({ values }) });
      $("settings-status").textContent = "Saved";
      loadSettings();
      load();
    } catch (e) {
      $("settings-status").textContent = String(e.message || e);
    }
  });

  let start = "round";
  try { start = localStorage.getItem(TAB_KEY) || start; } catch (_) { /* fine */ }
  showTab(start);
  load();
  setInterval(load, 2000);
})();
