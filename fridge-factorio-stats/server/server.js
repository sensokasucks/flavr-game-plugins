/**
 * Fridge Factorio Stats Bridge
 * - Connects to Factorio via RCON and polls /fridge-stats
 * - Optionally watches Wiretap stats.json for accurate power data
 * - Broadcasts merged JSON over WebSocket for the overlay
 * - Serves the overlay HTML statically
 *
 * Usage:
 *   1. Enable RCON in Factorio config.ini
 *   2. Install the fridge-factorio-stats mod (and optionally Wiretap)
 *   3. npm install && npm start
 *   4. In XSplit add Webpage source → http://localhost:3847/overlay.html
 */

const express = require('express');
const http = require('http');
const WebSocket = require('ws');
const path = require('path');
const fs = require('fs');
const { Rcon } = require('rcon-client');
const chokidar = require('chokidar');

// ============== CONFIG ==============
const CONFIG = {
  // Factorio RCON (must match config.ini)
  rconHost: process.env.RCON_HOST || '127.0.0.1',
  rconPort: parseInt(process.env.RCON_PORT || '25575', 10),
  rconPassword: process.env.RCON_PASSWORD || 'factorio',

  // HTTP + WebSocket port. Loopback only unless BIND_HOST says otherwise.
  port: parseInt(process.env.PORT || '3847', 10),
  bindHost: process.env.BIND_HOST || '127.0.0.1',

  coreUrl: (process.env.CORE_URL || 'http://127.0.0.1:3850').replace(/\/$/, ''),
  vaultFlushMj: parseFloat(process.env.VAULT_FLUSH_MJ || '25'),
  vaultFlushItems: parseInt(process.env.VAULT_FLUSH_ITEMS || '20', 10),

  // Poll interval for RCON (ms)
  pollIntervalMs: 2000,

  // Path to Wiretap JSON (optional – gives accurate power)
  // Windows default: %APPDATA%\Factorio\script-output\wiretap\stats.json
  wiretapPath: process.env.WIRETAP_PATH || path.join(
    process.env.APPDATA || process.env.HOME || '',
    'Factorio', 'script-output', 'wiretap', 'stats.json'
  ),

  // Path to our mod's JSON (fallback / extra)
  modStatsPath: process.env.MOD_STATS_PATH || path.join(
    process.env.APPDATA || process.env.HOME || '',
    'Factorio', 'script-output', 'fridge-stats', 'stats.json'
  )
};

// ============== STATE ==============
let latestStats = {
  tick: 0,
  deaths: 0,
  kills: { total: 0 },
  research: { current: null, progress: 0 },
  evolution: 0,
  alerts: [],
  power: { production_watts: 0, consumption_watts: 0, note: 'Waiting for data…' },
  dynamo: { power_level: 0, watts: 0, count: 0 },
  stream: {
    powerLevel: 0, viewers: 0, cpm: 0, commands: 0,
    pwrFactor: 1, vaultSymbols: ['PWR'], chestSymbols: ['FACT'],
    vaultFlushMj: 25, chestFlushItems: 20,
  },
  vaults: { pending_mj: 0, pending_items: 0 },
  players_online: 0,
  source: 'none',
  lastUpdate: null
};

let rcon = null;
let rconConnected = false;
let lastPushedPowerLevel = null;
let lastPowerPushAt = 0;
let lastPushedFactor = null;
let lastVaultFlushAt = 0;

// ============== RCON ==============
async function connectRcon() {
  try {
    rcon = await Rcon.connect({
      host: CONFIG.rconHost,
      port: CONFIG.rconPort,
      password: CONFIG.rconPassword,
      timeout: 3000
    });
    rconConnected = true;
    console.log(`[RCON] Connected to ${CONFIG.rconHost}:${CONFIG.rconPort}`);
    rcon.on('end', () => {
      rconConnected = false;
      console.log('[RCON] Disconnected – will retry…');
      setTimeout(connectRcon, 5000);
    });
  } catch (err) {
    rconConnected = false;
    console.warn(`[RCON] Connect failed: ${err.message}. Retrying in 5s…`);
    setTimeout(connectRcon, 5000);
  }
}

async function pollRcon() {
  if (!rconConnected || !rcon) return;
  try {
    let raw = await rcon.send('/fridge-stats');
    if (!raw || !raw.includes('{')) {
      raw = await rcon.send('/xsplit-stats');
    }
    // Factorio RCON often prefixes or has multiple lines; find the JSON object
    const match = raw.match(/\{[\s\S]*\}/);
    if (!match) {
      console.warn('[RCON] No JSON in response:', raw.slice(0, 120));
      return;
    }
    const data = JSON.parse(match[0]);
    mergeStats(data, 'rcon');
  } catch (err) {
    console.warn('[RCON] Poll error:', err.message);
    // reconnect on hard failure
    if (err.message.includes('closed') || err.message.includes('timeout')) {
      rconConnected = false;
      try { rcon.end(); } catch (_) {}
      setTimeout(connectRcon, 2000);
    }
  }
}

// ============== FILE WATCHERS ==============
function mergeWiretap(filePath) {
  try {
    if (!fs.existsSync(filePath)) return;
    const raw = fs.readFileSync(filePath, 'utf8');
    const wt = JSON.parse(raw);

    // Extract power from first surface that has data (usually nauvis)
    let power = { production_watts: 0, consumption_watts: 0, accumulator_charge_j: 0, accumulator_capacity_j: 0 };
    if (wt.surfaces) {
      for (const [name, surf] of Object.entries(wt.surfaces)) {
        if (surf.power && surf.power.totals) {
          const t = surf.power.totals;
          power = {
            production_watts: t.production_watts || 0,
            consumption_watts: t.consumption_watts || 0,
            accumulator_charge_j: t.accumulator_charge_joules || 0,
            accumulator_capacity_j: t.accumulator_capacity_joules || 0,
            network_count: t.network_count || 0,
            surface: name
          };
          break; // take first meaningful surface
        }
      }
    }

    // Research from forces.player
    let research = null;
    if (wt.forces && wt.forces.player && wt.forces.player.research) {
      const r = wt.forces.player.research;
      research = {
        current: r.current || null,
        progress: r.progress || 0,
        queue: r.queue || [],
        researched_count: r.technologies_researched || 0,
        total_technologies: r.technologies_total || 0
      };
    }

    // Evolution
    let evolution = 0;
    if (wt.forces && wt.forces.enemy && wt.forces.enemy.evolution) {
      const evo = wt.forces.enemy.evolution;
      evolution = evo.nauvis || Object.values(evo)[0] || 0;
    }

    mergeStats({
      power,
      research: research || undefined,
      evolution,
      meta: wt.meta
    }, 'wiretap');
  } catch (err) {
    console.warn('[Wiretap] Parse error:', err.message);
  }
}

function mergeModFile(filePath) {
  try {
    if (!fs.existsSync(filePath)) return;
    const raw = fs.readFileSync(filePath, 'utf8');
    const data = JSON.parse(raw);
    mergeStats(data, 'mod-file');
  } catch (err) {
    console.warn('[ModFile] Parse error:', err.message);
  }
}

function mergeStats(incoming, source) {
  // Prefer Wiretap for power & research when available
  if (incoming.power && (source === 'wiretap' || !latestStats.power.production_watts)) {
    latestStats.power = { ...latestStats.power, ...incoming.power };
  }
  if (incoming.research) {
    latestStats.research = { ...latestStats.research, ...incoming.research };
  }
  if (incoming.deaths !== undefined) latestStats.deaths = incoming.deaths;
  if (incoming.kills) latestStats.kills = incoming.kills;
  if (incoming.alerts) latestStats.alerts = incoming.alerts;
  if (incoming.evolution !== undefined) latestStats.evolution = incoming.evolution;
  if (incoming.players_online !== undefined) latestStats.players_online = incoming.players_online;
  if (incoming.tick) latestStats.tick = incoming.tick;
  if (incoming.game_time_seconds) latestStats.game_time_seconds = incoming.game_time_seconds;
  if (incoming.dynamo) latestStats.dynamo = { ...latestStats.dynamo, ...incoming.dynamo };
  if (incoming.vaults) latestStats.vaults = incoming.vaults;

  latestStats.source = source;
  latestStats.lastUpdate = new Date().toISOString();

  // Broadcast to all WS clients
  const payload = JSON.stringify(latestStats);
  wss.clients.forEach(client => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(payload);
    }
  });
}

// ============== HTTP + WS ==============
const app = express();
const server = http.createServer(app);
const LOOPBACK_ORIGIN = /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/i;
const wss = new WebSocket.Server({
  server,
  // Overlays are same-origin; refuse WebSockets opened by foreign web pages.
  verifyClient: (info) => !info.origin || LOOPBACK_ORIGIN.test(info.origin),
});

function hostName(req) {
  const h = String(req.headers.host || '').toLowerCase();
  if (h.startsWith('[')) return h.slice(0, h.indexOf(']') + 1);
  return h.split(':')[0];
}

// Write endpoints are for Stream Core only. A web page open in the browser can
// reach 127.0.0.1 too, so require Core's X-Fridge-Core header (cannot be sent
// cross-origin without a preflight we never approve), no browser Origin, and a
// loopback Host (DNS rebinding).
function requireCore(req, res, next) {
  const loopback = ['127.0.0.1', 'localhost', '[::1]'].includes(hostName(req));
  if (loopback && !req.headers.origin && req.headers['x-fridge-core'] === '1') return next();
  console.warn(`[HTTP] Refused ${req.method} ${req.path} (host=${req.headers.host}, origin=${req.headers.origin || '-'})`);
  res.status(403).json({ ok: false, error: 'forbidden' });
}

app.use(express.json());

// Serve overlay static files
const overlayDir = path.join(__dirname, '..', 'overlay');
app.use(express.static(overlayDir));

function clampLevel(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return 0;
  return Math.max(0, Math.min(15, Math.round(v)));
}

async function pushPowerToGame(level, pwrFactor) {
  const now = Date.now();
  if (!rconConnected || !rcon) return;
  if (level !== lastPushedPowerLevel || now - lastPowerPushAt >= 4000) {
    try {
      await rcon.send('/fridge-power ' + level);
      lastPushedPowerLevel = level;
      lastPowerPushAt = now;
    } catch (err) {
      console.warn('[RCON] fridge-power failed:', err.message);
    }
  }
  if (pwrFactor != null && Number.isFinite(Number(pwrFactor))) {
    const f = Math.max(0.25, Math.min(3, Number(pwrFactor)));
    if (lastPushedFactor == null || Math.abs(f - lastPushedFactor) > 0.02) {
      try {
        await rcon.send('/fridge-pwr-factor ' + f.toFixed(3));
        lastPushedFactor = f;
      } catch (err) {
        console.warn('[RCON] fridge-pwr-factor failed:', err.message);
      }
    }
  }
}

async function postDividend(symbol, work, unit) {
  if (!(work > 0)) return;
  const url = CONFIG.coreUrl + '/api/market/dividend';
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Fridge-Core': '1' },
      body: JSON.stringify({
        game: 'factorio',
        symbol,
        work,
        unit,
        reason: 'vault',
      }),
    });
    if (!res.ok) {
      console.warn('[Market] dividend HTTP', res.status);
    }
  } catch (err) {
    console.warn('[Market] dividend failed:', err.message);
  }
}

async function flushVaultsIfReady() {
  const now = Date.now();
  if (now - lastVaultFlushAt < 15000) return;
  const vaults = latestStats.vaults || {};
  const mj = Number(vaults.pending_mj || 0);
  const items = Number(vaults.pending_items || 0);
  const flushMj = Number(latestStats.stream.vaultFlushMj || CONFIG.vaultFlushMj);
  const flushItems = Number(latestStats.stream.chestFlushItems || CONFIG.vaultFlushItems);
  if (mj < flushMj && items < flushItems) return;
  if (!rconConnected || !rcon) return;
  lastVaultFlushAt = now;
  try {
    const raw = await rcon.send('/fridge-vault-flush');
    const match = String(raw).match(/\{[\s\S]*\}/);
    const flushed = match ? JSON.parse(match[0]) : { mj, items };
    const powerSyms = latestStats.stream.vaultSymbols || ['PWR'];
    const itemSyms = latestStats.stream.chestSymbols || ['FACT'];
    const mjEach = (flushed.mj || 0) / Math.max(1, powerSyms.length);
    const itemEach = (flushed.items || 0) / Math.max(1, itemSyms.length);
    for (const sym of powerSyms) await postDividend(sym, mjEach, 'mj');
    for (const sym of itemSyms) await postDividend(sym, itemEach, 'items');
    latestStats.vaults = { ...vaults, pending_mj: 0, pending_items: 0, last_flush: flushed };
  } catch (err) {
    console.warn('[RCON] vault flush failed:', err.message);
  }
}

// Health / latest stats endpoint (for debugging)
app.get('/stats', (req, res) => {
  res.json(latestStats);
});

app.get('/api/health', (req, res) => {
  res.json({
    ok: true,
    rcon: rconConnected,
    powerLevel: latestStats.stream.powerLevel,
    dynamo: latestStats.dynamo,
  });
});

app.get('/api/metrics', (req, res) => {
  res.json({
    ok: true,
    ...latestStats.stream,
    dynamo: latestStats.dynamo,
  });
});

app.post('/api/metrics', requireCore, async (req, res) => {
  const body = req.body || {};
  const level = clampLevel(body.powerLevel ?? body.power_level);
  function asSymbols(raw, fallback) {
    if (Array.isArray(raw)) return raw.map((s) => String(s).toUpperCase()).filter(Boolean);
    if (typeof raw === 'string') return raw.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
    return fallback;
  }
  const pwrFactor = Number(body.pwrFactor);
  latestStats.stream = {
    powerLevel: level,
    viewers: Number(body.viewers) || 0,
    cpm: Number(body.cpm) || 0,
    commands: Number(body.commands ?? body.command_rate) || 0,
    pwrFactor: Number.isFinite(pwrFactor) ? pwrFactor : (latestStats.stream.pwrFactor || 1),
    vaultSymbols: asSymbols(body.vaultSymbols || body.vault_symbol, latestStats.stream.vaultSymbols || ['PWR']),
    chestSymbols: asSymbols(body.chestSymbols || body.chest_symbol, latestStats.stream.chestSymbols || ['FACT']),
    vaultFlushMj: Number(body.vaultFlushMj) || latestStats.stream.vaultFlushMj || CONFIG.vaultFlushMj,
    chestFlushItems: Number(body.chestFlushItems) || latestStats.stream.chestFlushItems || CONFIG.vaultFlushItems,
  };
  latestStats.dynamo = {
    ...latestStats.dynamo,
    power_level: level,
  };
  latestStats.lastUpdate = new Date().toISOString();
  await pushPowerToGame(level, latestStats.stream.pwrFactor);
  flushVaultsIfReady().catch(() => {});
  res.json({ ok: true, ...latestStats.stream });
});

app.get('/', (req, res) => {
  res.redirect('/overlay.html');
});

wss.on('connection', (ws) => {
  console.log('[WS] Client connected');
  // Send current state immediately
  ws.send(JSON.stringify(latestStats));
  ws.on('close', () => console.log('[WS] Client disconnected'));
});

// ============== START ==============
async function start() {
  console.log('=== Fridge Factorio Stats Bridge ===');
  console.log(`HTTP/WS listening on http://${CONFIG.bindHost}:${CONFIG.port}`);
  console.log(`Overlay URL for XSplit: http://localhost:${CONFIG.port}/overlay.html`);
  console.log(`RCON target: ${CONFIG.rconHost}:${CONFIG.rconPort}`);
  console.log(`Wiretap path: ${CONFIG.wiretapPath}`);
  console.log('');

  // Start RCON
  await connectRcon();
  setInterval(pollRcon, CONFIG.pollIntervalMs);
  setInterval(() => { flushVaultsIfReady().catch(() => {}); }, 10000);

  // Watch Wiretap file (accurate power)
  if (fs.existsSync(path.dirname(CONFIG.wiretapPath))) {
    chokidar.watch(CONFIG.wiretapPath, { ignoreInitial: false, awaitWriteFinish: { stabilityThreshold: 200 } })
      .on('add', mergeWiretap)
      .on('change', mergeWiretap);
    console.log('[Watch] Monitoring Wiretap stats.json');
  } else {
    console.log('[Watch] Wiretap folder not found – power will be approximate or missing until you install hmph-wiretap');
  }

  // Watch our mod file as fallback
  const modDir = path.dirname(CONFIG.modStatsPath);
  if (!fs.existsSync(modDir)) {
    try { fs.mkdirSync(modDir, { recursive: true }); } catch (_) {}
  }
  chokidar.watch(CONFIG.modStatsPath, { ignoreInitial: false, awaitWriteFinish: { stabilityThreshold: 200 } })
    .on('add', mergeModFile)
    .on('change', mergeModFile);

  server.listen(CONFIG.port, CONFIG.bindHost, () => {
    console.log(`[HTTP] Ready. Add the Webpage source in XSplit pointing to the overlay URL above.`);
  });
}

start().catch(err => {
  console.error('Fatal:', err);
  process.exit(1);
});
