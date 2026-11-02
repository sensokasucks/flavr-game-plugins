/* Schedule I customers page (pages/index.html). API: ../routes.py

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

  $("refresh").addEventListener("click", load);
  load();
  setInterval(load, 5000);
})();
