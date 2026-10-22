"""
Minecraft plugin.

Talks to the Fabric client-mod (stats) and server-mod
(command execution + Chat Dynamo + dividend vaults) over HTTP.
Mods: fridge-minecraft/ (Fabric + NeoForge).

Ports: client mod 3852 (player stats, inventory flash), server mod 3853
(commands, metrics, Fridge blocks, vaults). Settings live under ``minecraft:`` in
Core's config.yaml; defaults and the Gamer Stonks fields are in plugin.json, chat
commands in commands.json. Every call sends ``X-Fridge-Core: 1`` (the mods refuse
calls without it).

Each metrics tick (every 2 s, on_metrics) does, in order: push metrics + market
settings to the server mod, dip the tickers if the player died, drive the placed
Fridge blocks (Chat Dynamo / Kinetic / Dividend Chest), then pay out full vaults
as Gamer Stonks dividends.

Everything market-related needs the Gamer Stonks plugin (plugins/stonks) running:
the tickers come from ctx.service("market") and payouts go through Gamer Stonks'
dividend(). plugin.json says "after": ["market"] so Gamer Stonks starts first. Without
it the dynamo runs at 1x, nothing dips, and vault work stays pending in the server mod.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from core.models import ExecuteRequest, MetricsSnapshot
from core.plugin_api import BasePlugin

log = logging.getLogger("plugins.minecraft")


def _mc_market_cfg(config: dict) -> dict:
    """Market settings for Minecraft, later blocks winning: the old top-level ``market:``
    (Stream Core's built-in market, kept for old config files), then ``stonks:`` (Gamer
    Stonks' settings: hourly_cap_points, dividend_price_bump, death_return ...), then
    ``minecraft.market:`` (this plugin's own fields from plugin.json)."""
    mc = (config.get("minecraft") or {}).get("market") or {}
    stonks = config.get("stonks") or {}
    mkt = config.get("market") or {}
    return {**mkt, **stonks, **mc}


def plan_machine_rf(
    drain_rate: int,
    factor: float,
    *,
    off_below: float = 0.5,
    lo: float = 0.25,
    hi: float = 3.0,
    max_rf: float = 2400,
) -> int:
    """FE/t Core authorizes. Zero if the tape is under the off threshold."""
    # drain_rate is the block's 0..15 setting (sneak-click in game). Output scales
    # linearly with it and with the ticker factor (clamped lo..hi), up to max_rf FE/tick.
    rate = max(0, min(15, int(drain_rate or 0)))
    if rate <= 0 or float(factor) < float(off_below):
        return 0
    clamped = max(float(lo), min(float(hi), float(factor)))
    return int(max(0.0, float(max_rf) * (rate / 15.0) * clamped))


def plan_chest_burns(
    items: list,
    drain_rate: int,
    values: dict,
    default: float,
    *,
    max_count: int = 64,
) -> tuple[list[dict], float]:
    """Pick items Core should delete this pulse. drain_rate 0 = storage only."""
    # At most max_count * drain_rate / 15 items per pulse, taken in slot order. Items
    # worth 0 (no value in ``values`` and default 0) are left alone.
    # Returns ([{slot, count}, ...] to delete, total value of those items).
    rate = max(0, min(15, int(drain_rate or 0)))
    if rate <= 0:
        return [], 0.0
    budget = max(1, int(max_count * rate / 15.0))
    consume: list[dict] = []
    work = 0.0
    valmap = {str(k).lower(): float(v) for k, v in (values or {}).items()}
    for row in items or []:
        if budget <= 0:
            break
        item_id = str(row.get("id") or "").lower()
        count = int(row.get("count") or 0)
        slot = int(row.get("slot") or 0)
        if count <= 0:
            continue
        unit = valmap.get(item_id, float(default or 0))
        if unit <= 0:
            continue
        take = min(count, budget)
        consume.append({"slot": slot, "count": take})
        work += unit * take
        budget -= take
    return consume, work


class MinecraftIntegration(BasePlugin):
    """Core side of Minecraft: forwards chat commands to the server mod, drives
    the Fridge blocks from stream metrics + ticker prices, and pays vault dividends."""

    name = "minecraft"

    def __init__(self, config: dict, ctx=None):
        super().__init__(config, ctx)
        mc = config.get("minecraft", {})
        self.enabled = bool(mc.get("enabled", False))
        self.player = mc.get("player_name", "Player")
        self.client_url = mc.get("client_mod_url", "http://127.0.0.1:3852").rstrip("/")
        self.server_url = mc.get("server_mod_url", "http://127.0.0.1:3853").rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._attached_market = None   # set by attach_market (tests); live Core leaves it None
        self._store = None
        self._core_state = None
        self.last_vault: dict = {}
        self.last_devices: dict = {}
        self._last_deaths: int | None = None

    def attach_market(self, tape) -> None:
        """Pin a Gamer Stonks tape (MarketTape) by hand. Only the unit tests call this;
        a live Core never does, ``_market`` finds the tape through ctx.service instead."""
        self._attached_market = tape

    @property
    def _market(self):
        """The Gamer Stonks tape (plugins/stonks/tape.py MarketTape), or None.

        Looked up on every use rather than once in start(), so it keeps working when
        Gamer Stonks is switched on or restarted after Minecraft. ctx.service("market")
        asks Core's plugin manager for whichever running plugin "provides" market.
        """
        if self._attached_market is not None:
            return self._attached_market
        return self.ctx.service("market") if self.ctx is not None else None

    def _stonks(self):
        """The running Gamer Stonks plugin (for its dividend()), or None when it is off
        or not installed. Vault payouts go through it so holders, the payout cap and the
        price bump all follow Gamer Stonks' own settings."""
        plugins = getattr(self.ctx, "plugins", None) if self.ctx is not None else None
        inst = plugins.running("stonks") if plugins is not None else None
        return inst if inst is not None and callable(getattr(inst, "dividend", None)) else None

    def attach_store(self, store) -> None:
        """Core's points store (core.store.Store); Core's plugin manager calls this."""
        self._store = store

    def _cfg(self) -> dict:
        return _mc_market_cfg(self.config)

    def _symbol_list(self, extra: list | None = None) -> list[str]:
        """Tickers the dynamo follows: the configured ones that are listed, else
        MINECRAF / STEVE and the rest of the minecraft book."""
        cfg = self._cfg()
        raw = extra if extra is not None else cfg.get("dynamo_symbols")
        if isinstance(raw, str):
            names = [s.strip().upper() for s in raw.split(",") if s.strip()]
        else:
            names = [str(s).strip().upper() for s in (raw or []) if s]
        if not names:
            names = ["MINECRAF", "STEVE"]
        tape = self._market
        if tape is None:
            return names
        found = [s for s in names if tape.quote(s)]
        if found:
            return found
        for fallback in ("MINECRAF", "STEVE"):
            if tape.quote(fallback) and fallback not in names:
                names.append(fallback)
        for inst in (tape.snapshot(book="minecraft").get("instruments") or []):
            sym = str(inst.get("symbol") or "")
            if sym and sym not in names:
                names.append(sym)
        return names or ["MINECRAF"]

    def stock_boost(self) -> dict:
        """{factor, raw, symbols} from the tape's stock_factor; factor 1.0 without a market."""
        cfg = self._cfg()
        tape = self._market
        if tape is None:
            return {"factor": 1.0, "raw": 1.0, "symbols": []}
        return tape.stock_factor(
            self._symbol_list(),
            lo=float(cfg.get("dynamo_min_factor", 0.25) or 0.25),
            hi=float(cfg.get("dynamo_max_factor", 3.0) or 3.0),
        )

    async def start(self) -> None:
        if not self.enabled:
            log.info("Minecraft integration disabled in config")
            return
        # X-Fridge-Core: the mods / bridge only accept calls that carry it
        # (a browser page cannot add custom headers cross-origin without a preflight).
        self._client = httpx.AsyncClient(timeout=5.0, headers={"X-Fridge-Core": "1"})
        log.info(
            "Minecraft integration ready (client=%s server=%s player=%s)",
            self.client_url, self.server_url, self.player,
        )

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def execute(self, req: ExecuteRequest) -> dict:
        """Run one chat command: show_inventory goes to the client mod, everything else
        is a game command (``req.template``) for the server mod's /api/execute."""
        if not self.enabled or not self._client:
            return {"success": False, "error": "minecraft integration disabled"}

        if req.special == "show_inventory":
            try:
                seconds = req.metadata.get("seconds", 12)
                await self._client.post(
                    f"{self.client_url}/api/show_inventory",
                    params={"seconds": seconds},
                )
                return {"success": True, "special": "show_inventory"}
            except Exception as e:
                log.warning("show_inventory failed: %s", e)
                return {"success": False, "error": str(e)}

        try:
            r = await self._client.post(
                f"{self.server_url}/api/execute",
                json={
                    "command": req.template,
                    "player": self.player,
                    "source_user": req.user.username if req.user else "",
                    "platform": req.platform.value,
                    "original": req.original_message,
                },
            )
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            ok = r.status_code < 400 and data.get("success", True)
            if not ok:
                log.warning("MC execute failed: %s %s", r.status_code, data)
            return {"success": ok, **data}
        except Exception as e:
            log.error("MC execute error: %s", e)
            return {"success": False, "error": str(e)}

    async def on_metrics(self, snap: MetricsSnapshot) -> None:
        """Every 2 s from Core: see the module docstring for the steps."""
        if not self.enabled or not self._client:
            return
        boost = self.stock_boost()
        cfg = self._cfg()
        try:
            await self._client.post(
                f"{self.server_url}/api/metrics",
                json={
                    "viewers": snap.viewers,
                    "cpm": snap.cpm,
                    "commands": snap.command_rate,
                    "powerLevel": snap.power_level,
                    "stockFactor": boost.get("factor", 1.0),
                    "chestDefaultValue": float(cfg.get("chest_default_value", 0.05) or 0.05),
                    "chestUseSmeltXp": bool(cfg.get("chest_use_smelt_xp", True)),
                    # The mod expects "item:value,item:value" strings, not JSON lists.
                    "chestValues": ",".join(
                        f"{k}:{v}" for k, v in dict(cfg.get("chest_item_values") or {}).items()
                    ),
                    "dividendSymbols": ",".join(self._symbol_list([
                        cfg.get("vault_symbol"),
                        cfg.get("chest_symbol"),
                    ] + self._symbol_list())),
                },
            )
        except Exception:
            log.warning("minecraft metrics push failed", exc_info=True)
        await self._apply_deaths()
        try:
            await self._drive_devices(boost)
        except Exception:
            log.exception("minecraft device drive failed")
        try:
            await self._flush_vaults()
        except Exception:
            log.exception("minecraft vault flush failed")

    async def _drive_devices(self, boost: dict) -> None:
        """Read placed Fridge blocks and push Core-computed orders back."""
        if not self._client:
            return
        try:
            r = await self._client.get(f"{self.server_url}/api/devices")
            if r.status_code != 200:
                log.warning("minecraft /api/devices HTTP %s — rebuild NeoForge/Fabric server jar", r.status_code)
                return
            data = r.json()
        except Exception:
            log.warning("minecraft /api/devices unreachable — rebuild NeoForge/Fabric server jar")
            return
        if not isinstance(data, dict):
            return
        self.last_devices = data
        if not data.get("devices"):
            log.info("minecraft device list empty — place a Dynamo and sneak drain > 0")
        cfg = self._cfg()
        factor = float(boost.get("factor") or 1.0)
        off_below = float(cfg.get("dynamo_off_below", 0.5) or 0.0)
        orders: list[dict] = []
        drain_units = 0.0
        chest_work = 0.0
        values = dict(cfg.get("chest_item_values") or {})
        default = float(cfg.get("chest_default_value", 0.05) or 0.05)
        for dev in data.get("devices") or []:
            if not isinstance(dev, dict) or not dev.get("id"):
                continue
            kind = str(dev.get("kind") or "")
            rate = int(dev.get("drainRate") or 0)
            if kind in ("dynamo", "kinetic"):
                rf = plan_machine_rf(
                    rate,
                    factor,
                    off_below=off_below,
                    lo=float(cfg.get("dynamo_min_factor", 0.25) or 0.25),
                    hi=float(cfg.get("dynamo_max_factor", 3.0) or 3.0),
                    max_rf=float(cfg.get("max_rf_per_tick", 2400) or 2400),
                )
                rpm = 0
                if kind == "kinetic" and rf > 0:
                    rpm = max(1, int(128 * (rate / 15.0) * min(3.0, max(0.25, factor))))
                orders.append({"id": dev["id"], "generateRf": rf, "generateRpm": rpm})
                if rf > 0 or rpm > 0:
                    drain_units += rate / 15.0
                    log.info("MC %s order rf=%s rpm=%s drain=%s/15", kind, rf, rpm, rate)
            elif kind == "chest":
                if self._stonks() is None:
                    # Without Gamer Stonks nobody can be paid, so leave the items in the chest.
                    continue
                consume, work = plan_chest_burns(
                    list(dev.get("items") or []),
                    rate,
                    values,
                    default,
                )
                if consume:
                    orders.append({"id": dev["id"], "generateRf": 0, "consume": consume})
                    chest_work += work
        if orders:
            try:
                await self._client.post(
                    f"{self.server_url}/api/devices/control",
                    json={"orders": orders},
                )
            except Exception:
                log.warning("minecraft device control failed", exc_info=True)
        # Running machines cost the tickers: power_drain_bps basis points (default 80;
        # 1 bp = 0.01 %) per full-drain machine, at most 3 machines' worth per tick.
        # On unless market.power_drain is set to false.
        if drain_units and cfg.get("power_drain") is not False and self._market:
            if factor >= off_below:
                bps = float(cfg.get("power_drain_bps") or 80)
                frac = -(bps / 10_000.0) * min(drain_units, 3.0)
                if frac:
                    for sym in self._symbol_list():
                        inst = self._market.apply_return(sym, frac, reason="power_drain")
                        if inst:
                            log.info("MC market drain %s %.2f%% → %.2f",
                                     sym, frac * 100.0, inst.get("price"))
        if chest_work > 0:
            min_xp = float(cfg.get("chest_min_xp", 1) or 1)
            rate_pts = float(cfg.get("chest_points_per_xp", 1) or 1)
            if chest_work >= min_xp and rate_pts > 0:
                points = max(0, min(int(chest_work * rate_pts), int(cfg.get("hourly_cap_points") or 500)))
                if points:
                    await self._pay(
                        symbol=str(cfg.get("chest_symbol") or "MINECRAF"),
                        work=chest_work,
                        unit="items",
                        points=points,
                        reason="mc-chest",
                    )

    async def _apply_deaths(self) -> None:
        """When the client mod's death counter goes up, dip the Minecraft tickers
        by death_return (default -8 %), with a per-symbol cooldown."""
        stats = await self.fetch_client_stats()
        if not stats:
            return
        try:
            deaths = int(stats.get("deaths") or 0)
        except (TypeError, ValueError):
            return
        prev = self._last_deaths
        self._last_deaths = deaths
        if prev is None or deaths <= prev:
            return
        # death_cooldown_sec / death_return are Gamer Stonks settings (stonks:), see _mc_market_cfg.
        cfg = self._cfg()
        cooldown = float(cfg.get("death_cooldown_sec", 20) or 0)
        frac = float(cfg.get("death_return", -0.08) or -0.08)
        tape = self._market
        if tape is None:
            return
        for sym in self._symbol_list():
            gate = tape.try_signal(
                name="player_death",
                symbol=sym,
                cooldown_sec=cooldown,
                book="game:minecraft",
                scope="symbol",
            )
            if not gate.get("ok"):
                continue
            tape.apply_return(sym, frac, reason="player_death")
            log.info("MC death dip %s %s%% (deaths %s→%s)", sym, round(frac * 100, 2), prev, deaths)

    async def _flush_vaults(self) -> None:
        """Pay out the server mod's pending vault work.

        Dividend Vault: pendingRf / vault_rf_per_point points once vault_min_rf is reached.
        Dividend Chest: pendingXp * chest_points_per_xp points once chest_min_xp is reached.
        Both capped at hourly_cap_points per flush. Only the work actually paid is
        acknowledged back (POST /api/market/ack), so the remainder stays pending.
        While Gamer Stonks isn't running nothing is paid or acknowledged, so the vaults
        keep their work until it is.
        """
        if not self._client or self._stonks() is None:
            return
        try:
            r = await self._client.get(f"{self.server_url}/api/market")
            if r.status_code != 200:
                return
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        except Exception:
            return
        if not isinstance(data, dict):
            return
        self.last_vault = data
        cfg = self._cfg()
        pending_rf = float(data.get("pendingRf") or 0)
        pending_xp = float(data.get("pendingXp") or 0)
        vault_sym = str(data.get("vaultSymbol") or cfg.get("vault_symbol") or "MINECRAF").upper()
        chest_sym = str(data.get("chestSymbol") or cfg.get("chest_symbol") or "MINECRAF").upper()
        if self._market:
            if not self._market.quote(vault_sym):
                vault_sym = self._symbol_list()[0]
            if not self._market.quote(chest_sym):
                chest_sym = self._symbol_list()[0]
        ack_rf = 0.0
        ack_xp = 0.0

        min_rf = float(cfg.get("vault_min_rf", 1000) or 1000)
        rf_per = float(cfg.get("vault_rf_per_point", 200) or 200)
        if pending_rf >= min_rf and rf_per > 0:
            points = int(pending_rf / rf_per)
            cap = int(cfg.get("hourly_cap_points") or 500)
            points = max(0, min(points, cap))
            if points > 0:
                paid = await self._pay(
                    symbol=vault_sym,
                    work=pending_rf,
                    unit="rf",
                    points=points,
                    reason="mc-vault",
                )
                # Gamer Stonks may cap lower (its own hourly_cap_points): ack only what it paid.
                ack_rf = int(paid.get("points") or 0) * rf_per

        min_xp = float(cfg.get("chest_min_xp", 1) or 1)
        xp_rate = float(cfg.get("chest_points_per_xp", 1) or 1)
        if pending_xp >= min_xp and xp_rate > 0:
            points = int(pending_xp * xp_rate)
            cap = int(cfg.get("hourly_cap_points") or 500)
            points = max(0, min(points, cap))
            if points > 0:
                paid = await self._pay(
                    symbol=chest_sym,
                    work=pending_xp,
                    unit="xp",
                    points=points,
                    reason="mc-chest",
                )
                ack_xp = int(paid.get("points") or 0) / xp_rate

        if ack_rf > 0 or ack_xp > 0:
            try:
                await self._client.post(
                    f"{self.server_url}/api/market/ack",
                    json={"rf": ack_rf, "xp": ack_xp},
                )
            except Exception:
                pass

    async def _pay(self, *, symbol: str, work: float, unit: str, points: int, reason: str) -> dict:
        """Pay ``points`` to the holders of ``symbol`` through Gamer Stonks' dividend().

        Called by _flush_vaults (Dividend Vault "mc-vault", Dividend Chest "mc-chest") and
        _drive_devices (chest burns). Lists the symbol in the minecraft book first if the
        tape does not have it. Gamer Stonks then caps the payout at its hourly_cap_points,
        splits it by shares (holdings.py), bumps the price by dividend_price_bump and
        records the event for the market overlays.

        Returns {"points": points actually paid, "holders": n, "burned": unpaid points, ...};
        points 0 when Gamer Stonks isn't running.
        """
        symbol = str(symbol or "MINECRAF").upper()
        stonks = self._stonks()
        if stonks is None or points <= 0:
            return {"points": 0, "holders": 0, "burned": 0}
        tape = self._market
        if tape is not None and not tape.quote(symbol):
            tape.upsert(
                symbol=symbol,
                name=symbol,
                book="game:minecraft",
                role="plain",
                price=8.5,
                base_price=8.5,
                persist=True,
            )
        out = await stonks.dividend({
            "symbol": symbol,
            "game": "minecraft",
            "unit": unit,
            "work": work,
            "points": points,      # already worked out here, so Gamer Stonks skips points_per_unit
            "reason": reason,
        })
        event = out.get("dividend") or {}
        paid = {**(out.get("payout") or {}), "points": int(event.get("points") or 0)}
        log.info("MC dividend %s %s pts work=%s %s paid=%s burned=%s",
                 symbol, paid["points"], work, unit, paid.get("holders"), paid.get("burned"))
        return paid

    def overlay_catalog(self) -> list[dict]:
        """Overlay pages on Core (:3850) for Admin -> Integrations; the market pages live in overlay/ here."""
        base = (self.ctx.core_url() if self.ctx else "http://127.0.0.1:3850") + "/overlay"
        return [
            {"name": "Minecraft / metrics overlay", "url": f"{base}/overlay.html", "notes": "HP, CPM, power level, inventory flash"},
            {"name": "Minecraft market tape", "url": f"{base}/market-minecraft.html", "notes": "MINECRAF + vault/chest feed"},
            {"name": "Minecraft dynamo", "url": f"{base}/market-minecraft-dynamo.html", "notes": "Power level + stock factor"},
        ]

    def status(self) -> dict:
        return {"detail": f"player {self.player}", "player_name": self.player}

    def market_status(self) -> list[str]:
        """Lines on the plugin's Gamer Stonks tab: boost, vault / chest totals, each placed block."""
        boost = self.stock_boost()
        bits = " · ".join(
            f"{row.get('symbol')} {float(row.get('factor') or 0):.2f}×" for row in boost.get("symbols") or []
            if isinstance(row, dict)
        ) or "no quotes"
        vault = self.last_vault or {}
        lines = [
            f"Boost now: {float(boost.get('factor') or 1):.2f}×  ({bits})",
            f"Dividend Dynamo: pending RF {vault.get('pendingRf', '—')}  lifetime {vault.get('lifetimeRf', '—')}",
            f"Dividend Chest: pending XP {vault.get('pendingXp', '—')}  lifetime {vault.get('lifetimeXp', '—')}",
        ]
        devices = (self.last_devices or {}).get("devices") or []
        if devices:
            lines += [
                f"{d.get('kind')}  drain {d.get('drainRate') or 0}/15  FE {d.get('orderedRf') or 0}/t  {d.get('id')}"
                for d in devices if isinstance(d, dict)
            ]
        else:
            lines.append("(no Fridge blocks reported: place a Dynamo / Chest)")
        return lines

    async def state_fragment(self) -> dict:
        """Client-mod stats for the metrics overlay (overlay.html)."""
        stats = await self.fetch_client_stats() or {}
        inventory = stats.get("inventory") if isinstance(stats, dict) else None
        return {"stats": stats, "inventory": inventory, "showInventory": bool(inventory)}

    @classmethod
    def routes(cls, router, get_running) -> None:
        @router.get("/api/stats")
        async def minecraft_stats():
            """Live player stats from the Minecraft client mod (empty while it's off)."""
            mc = get_running()
            if mc is not None:
                return await mc.fetch_client_stats()
            return {}

    async def fetch_client_stats(self) -> dict:
        """Player stats from the client mod's /api/stats; {} when it is not running."""
        if not self._client:
            return {}
        try:
            r = await self._client.get(f"{self.client_url}/api/stats")
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return {}

    async def health(self) -> bool:
        """True when the server mod answers /api/health (any status below 500)."""
        if not self.enabled or not self._client:
            return False
        try:
            r = await self._client.get(f"{self.server_url}/api/health", timeout=2.0)
            return r.status_code < 500
        except Exception:
            return False
