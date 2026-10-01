/**
 * Shared logic for individual Factorio stat widgets + the full overlay.
 * Works by only updating elements that exist on the current page.
 */
(function () {
  const WS_URL = `ws://${location.hostname || 'localhost'}:${location.port || 3847}`;
  let ws = null;
  let reconnectTimer = null;

  // Helpers
  function formatWatts(w) {
    if (w == null || isNaN(w)) return '—';
    const abs = Math.abs(w);
    if (abs >= 1e9) return (w / 1e9).toFixed(2) + ' GW';
    if (abs >= 1e6) return (w / 1e6).toFixed(2) + ' MW';
    if (abs >= 1e3) return (w / 1e3).toFixed(1) + ' kW';
    return Math.round(w) + ' W';
  }

  function formatJoules(j) {
    if (j == null || isNaN(j)) return '—';
    if (j >= 1e9) return (j / 1e9).toFixed(1) + ' GJ';
    if (j >= 1e6) return (j / 1e6).toFixed(1) + ' MJ';
    if (j >= 1e3) return (j / 1e3).toFixed(0) + ' kJ';
    return Math.round(j) + ' J';
  }

  function formatNumber(n) {
    if (n == null) return '0';
    return Number(n).toLocaleString();
  }

  function prettyTechName(name) {
    if (!name) return 'Idle';
    return String(name).replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function $(id) {
    return document.getElementById(id);
  }

  function setText(id, value) {
    const node = $(id);
    if (node) node.textContent = value;
  }

  function setHtml(id, html) {
    const node = $(id);
    if (node) node.innerHTML = html;
  }

  function setWidth(id, pct) {
    const node = $(id);
    if (node) node.style.width = pct + '%';
  }

  function setStatus(text, cls) {
    const node = $('status');
    if (!node) return;
    node.textContent = text;
    node.className = 'status ' + (cls || '');
  }

  // ---------- Renderers ----------
  function renderPower(data) {
    const prod = data.power?.production_watts ?? data.power?.production_watts_approx ?? 0;
    const cons = data.power?.consumption_watts ?? 0;
    setText('power-prod', formatWatts(prod));
    setText('power-cons', cons ? 'cons ' + formatWatts(cons) : (data.power?.note ? 'approx' : '—'));

    let pct = 0;
    if (prod > 0 && cons > 0) pct = Math.min(100, (cons / prod) * 100);
    else if (prod > 0) pct = 10;
    setWidth('power-bar', pct);

    const accC = data.power?.accumulator_charge_j ?? data.power?.accumulator_charge_joules;
    const accCap = data.power?.accumulator_capacity_j ?? data.power?.accumulator_capacity_joules;
    if (accCap > 0) {
      const accPct = ((accC / accCap) * 100).toFixed(0);
      setText('power-acc', `acc ${accPct}% (${formatJoules(accC)})`);
    } else {
      setText('power-acc', data.power?.note ? 'install Wiretap for live power' : '—');
    }
  }

  function renderResearch(data) {
    const r = data.research || {};
    setText('research-name', prettyTechName(r.current));
    const prog = Math.round((r.progress || 0) * 100);
    setText('research-pct', prog + '%');
    setWidth('research-bar', prog);
    if (r.queue && r.queue.length) {
      setText('research-queue', 'queue: ' + r.queue.slice(0, 3).map(prettyTechName).join(', '));
    } else {
      setText('research-queue', r.researched_count != null
        ? `${r.researched_count}/${r.total_technologies || '?'} researched`
        : '—');
    }
  }

  function renderKills(data) {
    setText('kills', formatNumber(data.kills?.total ?? 0));
  }

  function renderDeaths(data) {
    setText('deaths', formatNumber(data.deaths ?? 0));
  }

  function renderEvolution(data) {
    const evo = ((data.evolution || 0) * 100).toFixed(2);
    setText('evolution', evo + '%');
    setText('evolution-label', 'EVOLUTION');
  }

  function renderCombat(data) {
    renderKills(data);
    renderDeaths(data);
    renderEvolution(data);
  }

  function renderAlerts(data) {
    const alerts = data.alerts || [];
    if (alerts.length === 0) {
      setHtml('alerts', '<div class="alert-empty">No active alerts</div>');
      return;
    }
    const shown = alerts.slice(-8).reverse();
    setHtml('alerts', shown.map(a => {
      const isYellow = (a.type || '').toLowerCase().includes('warning') ||
                       (a.type || '').includes('2') ||
                       (a.type || '').includes('turret');
      const label = a.message || a.entity || a.type || 'Alert';
      const pos = a.position ? ` @ ${Math.round(a.position.x)},${Math.round(a.position.y)}` : '';
      return `<div class="alert-item">
        <div class="alert-icon ${isYellow ? 'yellow' : ''}"></div>
        <div class="alert-text">${escapeHtml(label)}${pos}</div>
      </div>`;
    }).join(''));
  }

  function renderFooter(data) {
    setText('tick', data.tick != null ? `tick ${data.tick}` : 'tick —');
    setText('source', data.source ? `src ${data.source}` : '');
  }

  // Master render – only touches elements that exist
  function render(data) {
    if ($('power-prod')) renderPower(data);
    if ($('research-name')) renderResearch(data);
    if ($('kills') && !$('deaths')) renderKills(data);          // pure kills widget
    if ($('deaths') && !$('kills')) renderDeaths(data);          // pure deaths widget
    if ($('kills') && $('deaths')) renderCombat(data);           // combat widget
    if ($('evolution') && !$('kills')) renderEvolution(data);    // pure evo widget
    if ($('alerts')) renderAlerts(data);
    renderFooter(data);
  }

  // ---------- Connection ----------
  function connect() {
    setStatus('CONNECTING…', 'connecting');
    try {
      ws = new WebSocket(WS_URL);
    } catch (e) {
      setStatus('ERROR', 'error');
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      setStatus('LIVE', 'live');
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        render(data);
        setStatus('LIVE', 'live');
      } catch (e) {
        console.warn('Bad message', e);
      }
    };

    ws.onclose = () => {
      setStatus('RECONNECTING…', 'connecting');
      scheduleReconnect();
    };

    ws.onerror = () => {
      setStatus('ERROR', 'error');
      try { ws.close(); } catch (_) {}
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, 2500);
  }

  // Start
  connect();

  // HTTP fallback
  setInterval(async () => {
    if (ws && ws.readyState === WebSocket.OPEN) return;
    try {
      const res = await fetch('/stats');
      if (res.ok) render(await res.json());
    } catch (_) {}
  }, 4000);
})();
