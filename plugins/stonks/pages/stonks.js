/* Gamer Stonks page (shown inside the Stream Core dashboard). API: ../routes.py

   Loaded by pages/index.html. window.StreamCore (api, escapeHtml) comes from the
   dashboard and sends the admin token. Tabs: listings, settings, one tab per game
   plugin that has a "market" block in its plugin.json, investors, preview. The last
   open tab is remembered in localStorage ("gamer_stonks_tab"). */
(() => {
  const $ = (id) => document.getElementById(id);
  const { api, escapeHtml } = window.StreamCore;
  const tabKey = "gamer_stonks_tab";

  function say(msg) {
    $("status").textContent = msg || "";
  }

  async function act(fn) {
    try {
      await fn();
    } catch (e) {
      say(String(e.message || e));
    }
  }

  // ---------------------------------------------------------------- tabs

  function showTab(sub) {
    const tabs = Array.from(document.querySelectorAll("#tabs .subtab"));
    if (!tabs.some((b) => b.dataset.sub === sub)) sub = "listings";
    tabs.forEach((b) => {
      const on = b.dataset.sub === sub;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll("section.sub").forEach((s) => { s.hidden = s.dataset.sub !== sub; });
    if (sub === "preview" && !$("preview").src) $("preview").src = "/overlay/market.html";
    try { localStorage.setItem(tabKey, sub); } catch (_) { /* fine */ }
  }

  $("tabs").addEventListener("click", (ev) => {
    const b = ev.target.closest(".subtab");
    if (b) showTab(b.dataset.sub);
  });

  // ---------------------------------------------------------------- settings fields
  // A plugin.json "market" block: {title, hint, fields: [{key, label, type, group ...}]}.
  // Saved with PUT /api/admin/plugins/<id>/settings (Stream Core checks and converts the values).

  function pathGet(obj, key) {
    return String(key).split(".").reduce((cur, part) => (cur && typeof cur === "object" ? cur[part] : undefined), obj);
  }

  function slug(text) {
    return String(text).replace(/[^a-z0-9_]+/gi, "-");
  }

  // One settings input for a plugin.json field. Types: checkbox, map ("key: value"
  // lines), lines (one per line), select, list (comma separated), number, password, text.
  function fieldHtml(pid, f, value) {
    const type = f.type || "text";
    const id = `f-${slug(pid)}-${slug(f.key)}`;
    const attrs = `id="${id}" class="plg-field" data-key="${escapeHtml(f.key)}" data-type="${escapeHtml(type)}"`;
    const label = escapeHtml(f.label || f.key);
    const help = f.help ? ` <span class="field-help">${escapeHtml(f.help)}</span>` : "";
    const ph = f.placeholder != null ? ` placeholder="${escapeHtml(String(f.placeholder))}"` : "";
    if (type === "checkbox") {
      return `<label class="check"><input type="checkbox" ${attrs} ${value ? "checked" : ""} /> ${label}${help}</label>`;
    }
    if (type === "map") {
      const text = Object.entries(value || {}).map(([k, v]) => k + ": " + v).join("\n");
      return `<label>${label}${help}<textarea ${attrs} rows="5"${ph}>${escapeHtml(text)}</textarea></label>`;
    }
    if (type === "lines") {
      return `<label>${label}${help}<textarea ${attrs} rows="4"${ph}>${escapeHtml((value || []).join("\n"))}</textarea></label>`;
    }
    if (type === "select") {
      const opts = (f.options || []).map((o) =>
        `<option value="${escapeHtml(String(o))}" ${String(o) === String(value ?? "") ? "selected" : ""}>${escapeHtml(String(o))}</option>`).join("");
      return `<label>${label}${help}<select ${attrs}>${opts}</select></label>`;
    }
    let shown = value ?? "";
    if (type === "list") shown = Array.isArray(value) ? value.join(", ") : String(value ?? "");
    const inputType = type === "number" ? "number" : type === "password" ? "password" : "text";
    const extra = type === "number" ? ["min", "max", "step"].filter((k) => f[k] != null).map((k) => ` ${k}="${escapeHtml(String(f[k]))}"`).join("") : "";
    return `<label>${label}${help}<input type="${inputType}" ${attrs} value="${escapeHtml(String(shown))}"${ph}${extra} /></label>`;
  }

  /** Fill a section with one plugin's market block; the first box gets live numbers + Save. */
  function renderBlock(host, p, ownTitle) {
    const m = p.market || {};
    const groups = [];
    (m.fields || []).forEach((f) => {
      const g = f.group || m.title || p.name;
      let row = groups.find((x) => x.name === g);
      if (!row) groups.push((row = { name: g, fields: [] }));
      row.fields.push(f);
    });
    const live = (p.market_status || []).join("\n") ||
      (p.running ? "" : p.name + " is not running: live numbers show while it runs");
    host.innerHTML =
      (m.hint ? `<p class="hint">${escapeHtml(m.hint)}</p>` : "") +
      `<div class="mc-grid">` +
      groups.map((g, i) =>
        `<fieldset class="cfg-card"><legend>${escapeHtml(g.name)}</legend>` +
        g.fields.map((f) => fieldHtml(p.id, f, pathGet(p.values || {}, f.key))).join("") +
        (i === 0
          ? (live ? `<pre class="integ-result">${escapeHtml(live)}</pre>` : "") +
            `<div class="form-row" style="gap:8px;flex-wrap:wrap">` +
            `<button type="button" class="primary save-block">Save ${escapeHtml(ownTitle || p.name)}</button>` +
            `<span class="muted block-status"></span></div>`
          : "") +
        `</fieldset>`).join("") +
      `</div>`;
    host.querySelector(".save-block").onclick = async () => {
      const values = {};
      host.querySelectorAll(".plg-field").forEach((el) => {
        values[el.dataset.key] = el.dataset.type === "checkbox" ? el.checked : el.value;
      });
      const out = host.querySelector(".block-status");
      try {
        await api("/api/admin/plugins/" + encodeURIComponent(p.id) + "/settings", {
          method: "PUT",
          body: JSON.stringify({ values }),
        });
        out.textContent = "Saved";
        say((ownTitle || p.name) + " saved");
        load();
      } catch (e) {
        out.textContent = String(e.message || e);
      }
    };
  }

  /** Our own settings, plus one tab per game plugin with a "market" block. */
  function renderPlugins(plugins) {
    const bar = $("tabs");
    const main = document.querySelector("main");
    plugins.filter((p) => p.market).forEach((p) => {
      if (p.id === "stonks") {
        renderBlock(document.querySelector('section.sub[data-sub="settings"]'), p, "settings");
        return;
      }
      const sub = "plg-" + slug(p.id);
      let sec = document.querySelector(`section.sub[data-sub="${sub}"]`);
      if (!sec) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "subtab";
        btn.dataset.sub = sub;
        btn.textContent = p.name;
        bar.insertBefore(btn, bar.querySelector('.subtab[data-sub="investors"]'));
        sec = document.createElement("section");
        sec.className = "sub";
        sec.dataset.sub = sub;
        sec.hidden = true;
        main.insertBefore(sec, document.querySelector('section.sub[data-sub="investors"]'));
      } else if (sec.querySelector(".plg-field:focus")) {
        return;   // being edited: keep what was typed
      }
      renderBlock(sec, p, p.name + " market");
    });
  }

  // ---------------------------------------------------------------- listings, investors

  // Listings table, book picker and holdings list from GET /api/admin/market.
  function renderMarket(data) {
    const sel = $("new-book");
    const keep = sel.value;
    sel.innerHTML = (data.books || ["core"]).map((b) => `<option value="${escapeHtml(b)}">${escapeHtml(b)}</option>`).join("");
    if ((data.books || []).includes(keep)) sel.value = keep;

    const holds = data.holdings || [];
    $("holdings").textContent = holds.length
      ? holds.map((h) => `user ${h.user_id}  ${h.symbol}  ${(h.milli_shares / 1000).toFixed(3)} sh`).join("\n")
      : "(nobody holds shares yet: give some, or dividends go nowhere)";
    const last = data.last_dividend;
    if (last) say(`Last dividend ${last.symbol} ${last.points} pts (${last.reason || ""})`);

    const rows = (data.tape || {}).instruments || [];
    document.querySelector("#book tbody").innerHTML = rows.map((it) => {
      const sym = escapeHtml(it.symbol);
      const hidden = it.status === "hidden" || it.status === "delisted";
      return `<tr data-sym="${sym}">
        <td><code>${sym}</code></td>
        <td><input class="t-name" type="text" value="${escapeHtml(it.name || "")}" /></td>
        <td>${escapeHtml(it.book || "")}</td>
        <td><input class="t-appid" type="number" min="0" value="${escapeHtml(it.steam_appid || "")}" style="width:7.5em" /></td>
        <td class="${it.steam_stale ? "stale" : ""}">${it.steam_ccu != null ? escapeHtml(it.steam_ccu) : "—"}</td>
        <td><input class="t-px" type="number" step="0.1" value="${Number(it.price || 0).toFixed(2)}" style="width:5.5em" /></td>
        <td><input class="t-show" type="checkbox" ${hidden ? "" : "checked"} aria-label="Show ${sym}" /></td>
        <td><button type="button" class="t-save">Save</button> <button type="button" class="t-del">Delist</button></td>
      </tr>`;
    }).join("") || `<tr><td colspan="8" class="muted">No listings</td></tr>`;
  }

  async function load() {
    await act(async () => {
      const [market, plugins] = await Promise.all([api("/api/admin/market"), api("/api/admin/plugins")]);
      renderMarket(market);
      renderPlugins(plugins.plugins || []);
    });
  }

  $("refresh").onclick = load;

  // Row buttons: Save sends PATCH (name, Steam App ID, live price, shown/hidden);
  // Delist sends DELETE.
  $("book").addEventListener("click", (ev) => {
    const row = ev.target.closest("tr[data-sym]");
    if (!row) return;
    const sym = row.dataset.sym;
    const url = "/api/admin/market/tickers/" + encodeURIComponent(sym);
    if (ev.target.closest(".t-save")) {
      act(async () => {
        const appid = row.querySelector(".t-appid").value;
        await api(url, {
          method: "PATCH",
          body: JSON.stringify({
            name: row.querySelector(".t-name").value,
            steam_appid: appid ? Number(appid) : 0,
            price: Number(row.querySelector(".t-px").value),
            status: row.querySelector(".t-show").checked ? "listed" : "hidden",
          }),
        });
        say(sym + " saved");
        load();
      });
    } else if (ev.target.closest(".t-del")) {
      act(async () => {
        await api(url, { method: "DELETE" });
        say(sym + " delisted");
        load();
      });
    }
  });

  $("add").onclick = () => act(async () => {
    const appid = $("new-appid").value;
    const px = Number($("new-px").value || 10);
    await api("/api/admin/market/tickers", {
      method: "POST",
      body: JSON.stringify({
        symbol: $("new-sym").value,
        name: $("new-name").value,
        book: $("new-book").value,
        price: px,
        base_price: px,
        feed: $("new-feed").value || (appid ? "steam" : "walk"),
        steam_appid: appid ? Number(appid) : null,
      }),
    });
    say("Ticker added");
    ["new-sym", "new-name", "new-appid"].forEach((id) => { $(id).value = ""; });
    load();
  });

  // List a chatter as a stock: its price follows that user's points (see tape.tick_chatter).
  $("chat-add").onclick = () => act(async () => {
    const uid = Number($("chat-uid").value);
    const sym = ($("chat-sym").value || "CHAT").toUpperCase();
    await api("/api/admin/market/tickers", {
      method: "POST",
      body: JSON.stringify({
        symbol: sym,
        name: sym,
        book: "core",
        role: "chatter",
        feed: "chatter",
        chatter_user_id: uid,
        chatter_link_points: $("chat-link").checked,
        chatter_streak_bonus: Number($("chat-bonus").value || 0.05),
        chatter_points_scale: Number($("chat-scale").value || 10),
      }),
    });
    say("Listed chatter " + uid + " as " + sym);
    load();
  });

  $("steam-poll").onclick = () => act(async () => {
    const r = await api("/api/admin/market/steam/poll", { method: "POST", body: "{}" });
    say(`Checked Steam for ${r.polled || 0} game(s)`);
    load();
  });

  $("hold-grant").onclick = () => act(async () => {
    const r = await api("/api/admin/market/holding", {
      method: "POST",
      body: JSON.stringify({
        user_id: Number($("hold-uid").value),
        symbol: $("hold-sym").value,
        shares: Number($("hold-shares").value),
      }),
    });
    say(`User ${r.user_id} now holds ${r.milli_shares / 1000} ${r.symbol}`);
    load();
  });

  // Test dividend of 10 points to the holders of the symbol in the holdings box.
  $("div-test").onclick = () => act(async () => {
    const r = await api("/api/admin/market/dividend", {
      method: "POST",
      body: JSON.stringify({ symbol: ($("hold-sym").value || "FRG").trim().toUpperCase(), points: 10 }),
    });
    const p = r.payout || {};
    say(`Paid ${p.total - (p.burned || 0)} of ${p.total} points to ${p.holders || 0} holder(s)`);
    load();
  });

  load().then(() => {
    let tab = "listings";
    try { tab = localStorage.getItem(tabKey) || tab; } catch (_) { /* fine */ }
    showTab(tab);
  });
})();
