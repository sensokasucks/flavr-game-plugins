/* Schedule I customers page (pages/index.html). API: ../routes.py (Customers tab) and Core's
   /api/admin/plugins routes (Settings tab).

   window.StreamCore (api, escapeHtml, resize) comes from the dashboard's plugin-page.js and
   sends the admin token. Refreshes every 5 s while the page is open. */
(() => {
  const $ = (id) => document.getElementById(id);
  const { api, escapeHtml, resize } = window.StreamCore;

  function say(msg) { $("status").textContent = msg || ""; }

  // $240 / $12.50, like the chat announcements (plugin.py money()).
  function money(v) {
    const n = Number(v || 0);
    return "$" + (Number.isInteger(n) ? n.toLocaleString() : n.toFixed(2));
  }

  async function load() {
    let data;
    try {
      data = await api("/api/schedule1/customers");
    } catch (e) {
      say(String(e.message || e));
      return;
    }
    const named = data.people.filter((p) => p.npc_id).length;
    const waiting = data.people.length - named;
    let line;
    if (!data.connected) line = "Not connected to the Schedule I mod. " + (data.error || "");
    else if (!data.loaded) line = "Connected; the game is on the main menu.";
    else line = `Connected: ${data.customers_in_game} customers in the game, ${data.named} carry a chatter name.`;
    $("summary").textContent = `${line} ${named} named, ${waiting} waiting.`;
    say("");

    const rows = data.people.map((p) => {
      const cust = p.npc_id
        ? (p.in_game ? escapeHtml(p.customer) : escapeHtml(p.npc_id) + " (not in this save)")
        : "waiting";
      return `<tr>
        <td>${escapeHtml(p.name)}</td>
        <td>${escapeHtml(p.platform)}</td>
        <td class="${p.npc_id ? "" : "waiting"}">${cust}</td>
        <td>${p.deals}</td>
        <td>${money(p.spent)}</td>
        <td><button type="button" data-key="${escapeHtml(p.key)}">Remove</button></td>
      </tr>`;
    });
    $("people").querySelector("tbody").innerHTML = rows.join("") ||
      '<tr><td colspan="6" class="waiting">Nobody yet. Chat types !customer to join.</td></tr>';
    resize();
  }

  $("people").addEventListener("click", async (ev) => {
    const b = ev.target.closest("button[data-key]");
    if (!b) return;
    try {
      await api("/api/schedule1/customers/remove", { method: "POST", body: JSON.stringify({ key: b.dataset.key }) });
      await load();
    } catch (e) { say(String(e.message || e)); }
  });

  $("add").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await api("/api/schedule1/customers/add", {
        method: "POST",
        body: JSON.stringify({ platform: $("add-platform").value, username: $("add-name").value }),
      });
      $("add-name").value = "";
      await load();
    } catch (e) { say(String(e.message || e)); }
  });

  // ---------------------------------------------------------------- tabs

  const TAB_KEY = "schedule1.tab";     // remembered tab (this browser only)

  function showTab(sub) {
    const tabs = Array.from(document.querySelectorAll("#tabs .subtab"));
    if (!tabs.some((b) => b.dataset.sub === sub)) sub = "customers";
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
  // Fields come from GET /api/admin/plugins (this plugin's row: settings + current values); the ones
  // marked "page": true in plugin.json are shown here. Saved with PUT /api/admin/plugins/schedule1/settings,
  // which checks and converts the values; plugin.py reads its config live, so no restart.
  // Field HTML follows the Gamer Stonks page (plugins/stonks/pages/stonks.js fieldHtml) so both look alike.

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
      p = ((await api("/api/admin/plugins")).plugins || []).find((x) => x.id === "schedule1");
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
      await api("/api/admin/plugins/schedule1/settings", { method: "PUT", body: JSON.stringify({ values }) });
      $("settings-status").textContent = "Saved";
      loadSettings();
    } catch (e) {
      $("settings-status").textContent = String(e.message || e);
    }
  });

  $("refresh").addEventListener("click", load);
  let start = "customers";
  try { start = localStorage.getItem(TAB_KEY) || start; } catch (_) { /* fine */ }
  showTab(start);
  load();
  setInterval(load, 5000);
})();
