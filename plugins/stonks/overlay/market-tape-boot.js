/* Scrolling ticker tape for the games' market overlays (market-factorio / -minecraft / -openttd.html; load market.js first).
   The page needs .tape-track > #inner, and optionally #event for the latest move.
   Query string: ?speed=<px per second> (default 80), ?book=, ?symbols=A,B.
   Polls /api/market/state every 4 s. */
(function () {
  const M = FridgeMarket;
  const inner = document.getElementById("inner");
  const ev = document.getElementById("event");
  if (!inner || !M) return;
  const speed = Number(M.param("speed", "80")) || 80;
  let measure = M.startTicker(document.querySelector(".tape-track"), inner, speed);
  function item(it) {
    const d = M.dir(it.pct);
    const arrow = d === "up" ? "▲" : d === "down" ? "▼" : "■";
    return (
      '<span class="tick ' + d + '">' +
        '<span class="sym">' + it.symbol + '</span>' +
        '<span class="px">' + M.fmtPx(it.price) + '</span>' +
        '<span class="chg">' + arrow + " " + M.fmtChg(it.delta, it.pct) + "</span>" +
      "</span>"
    );
  }
  async function poll() {
    try {
      const data = await M.fetchState();
      const list = M.filterInstruments(data.instruments || []);
      // The list is written twice so the tape can wrap seamlessly (see startTicker).
      inner.innerHTML = (list.map(item).join("") || '<span class="tick flat">No listings</span>') +
        (list.length ? list.map(item).join("") : "");
      if (ev && data.last_event) {
        ev.textContent = (data.last_event.symbol || "") + " " + (data.last_event.reason || "");
      }
      if (measure) measure();
    } catch (e) {
      inner.textContent = "market offline";
    }
  }
  poll();
  setInterval(poll, 4000);
})();
