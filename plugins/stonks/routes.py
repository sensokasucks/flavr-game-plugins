"""
Gamer Stonks' web addresses. They are the ones Stream Core's built-in market had, so OBS
sources, game bridges and bookmarks keep working:

  GET  /api/market/state, /api/market/history     overlays (anyone on this PC)
  POST /api/market/signal, /api/market/dividend   games / bridges only (ctx.require_game)
  /api/admin/market/...                           the Gamer Stonks page (admin token)

They exist while the plugin is installed; while it is off they answer 503.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Body, Header, HTTPException, Request

OFF = "Gamer Stonks is off (Settings → Plugins)"


def add_routes(router, get_running) -> None:
    # The running plugin instance, or HTTP 503 while Gamer Stonks is off.
    """Register the routes on Core's router; get_running() is the live GamerStonks or None."""
    def running():
        inst = get_running()
        if inst is None or inst.tape is None:
            raise HTTPException(503, OFF)
        return inst

    # Same, plus Core's admin token check (X-Admin-Token header from the dashboard).
    def admin(token: Optional[str]):
        inst = running()
        inst.ctx.require_admin(token)
        return inst

    # -------------------------------------------------------------- overlays

    @router.get("/api/market/state")
    async def market_state(book: str = "", symbols: str = ""):
        want = [s.strip() for s in (symbols or "").split(",") if s.strip()]
        return running().tape.snapshot(book=book or None, symbols=want or None)

    @router.get("/api/market/history")
    async def market_history(symbol: str = "FRG", points: int = 120):
        # points is clamped to 8..2000 samples.
        return running().tape.history(symbol, points=max(8, min(int(points or 120), 2000)))

    # -------------------------------------------------------------- games

    @router.post("/api/market/signal")
    async def market_signal(request: Request, payload: Dict[str, Any] = Body(default={})):
        """Death / named game signals move a ticker, with optional cooldowns."""
        inst = running()
        inst.ctx.require_game(request)
        try:
            return inst.signal(payload or {})
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/market/dividend")
    async def market_dividend(request: Request, payload: Dict[str, Any] = Body(default={})):
        """
        Vault flush from a game bridge. Body: { game, symbol, work, unit, reason?, points? }
        Games only (no web pages); the page's test button uses /api/admin/market/dividend.
        """
        inst = running()
        inst.ctx.require_game(request)
        try:
            return await inst.dividend(payload or {})
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    # -------------------------------------------------------------- the Gamer Stonks page

    @router.get("/api/admin/market")
    async def market_admin(x_admin_token: Optional[str] = Header(None)):
        inst = admin(x_admin_token)
        tape = inst.tape
        return {
            "tape": tape.snapshot(include_hidden=True),
            "books": ["core"] + [f"game:{pid}" for pid in inst.ctx.plugins.ids() if pid != "stonks"],
            "holdings": await inst.holdings.list(),
            "last_dividend": tape.last_dividend,
            "last_event": tape.last_event,
        }

    # Grant (or with negative shares, take) shares by hand: {user_id, symbol, shares}.
    @router.post("/api/admin/market/holding")
    async def market_grant_holding(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        inst = admin(x_admin_token)
        uid = int(body.get("user_id") or 0)
        if uid <= 0:
            raise HTTPException(400, "user_id required (from Users & points)")
        symbol = str(body.get("symbol") or "FRG").upper()
        milli = int(round(float(body.get("shares") or 0) * 1000))
        nxt = await inst.holdings.adjust(uid, symbol, milli)
        return {"ok": True, "user_id": uid, "symbol": symbol, "milli_shares": nxt}

    # Test button: pay {points} to {symbol}'s holders without a game.
    @router.post("/api/admin/market/dividend")
    async def market_test_dividend(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        inst = admin(x_admin_token)
        tape = inst.tape
        symbol = str(body.get("symbol") or "FRG").upper()
        points = int(body.get("points") or 10)
        paid = await inst.holdings.pay_dividend(symbol, points, "admin-test")
        bump = float(inst.ctx.section.get("dividend_price_bump", 0.01) or 0)
        tape.apply_return(symbol, bump, reason="admin-test")
        tape.last_dividend = {"symbol": symbol, "points": points, "reason": "admin-test",
                              "holders": paid.get("holders"), "burned": paid.get("burned")}
        return {"ok": True, "payout": paid}

    # List a new ticker. A chatter ticker starts at the chatter's points / chatter_points_scale.
    @router.post("/api/admin/market/tickers")
    async def market_create_ticker(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        inst = admin(x_admin_token)
        tape, store = inst.tape, inst.ctx.store
        try:
            row = tape.upsert(
                symbol=str(body.get("symbol") or ""),
                name=str(body.get("name") or body.get("symbol") or ""),
                book=str(body.get("book") or "core"),
                role=str(body.get("role") or "plain"),
                price=float(body.get("price") or body.get("base_price") or 10),
                base_price=float(body.get("base_price") or body.get("price") or 10),
                status="listed",
                feed=body.get("feed"),
                steam_appid=body.get("steam_appid"),
                steam_mode=body.get("steam_mode"),
                chatter_user_id=body.get("chatter_user_id"),
                chatter_link_points=body.get("chatter_link_points"),
                chatter_streak_bonus=body.get("chatter_streak_bonus"),
                chatter_points_scale=body.get("chatter_points_scale"),
                persist=True,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if row.get("chatter_user_id") and row.get("chatter_listed_points") is None and store is not None:
            user = await store.get_user(int(row["chatter_user_id"]))
            if user:
                row["chatter_listed_points"] = int(user.get("points") or 0)
                scale = float(row.get("chatter_points_scale") or 10) or 10
                row["price"] = max(0.5, row["chatter_listed_points"] / scale)
                row["base_price"] = row["price"]
                tape.save_listings()
        return {"ok": True, "ticker": row}

    # Edit a ticker; fields left out (or null) keep their value. "price" sets the live price.
    @router.patch("/api/admin/market/tickers/{symbol}")
    async def market_edit_ticker(symbol: str, body: Dict[str, Any] = Body(default={}),
                                 x_admin_token: Optional[str] = Header(None)):
        tape = admin(x_admin_token).tape
        current = tape.quote(symbol)
        if not current:
            raise HTTPException(404, "unknown symbol")
        merged = dict(current)
        merged.update({k: v for k, v in body.items() if v is not None})
        try:
            row = tape.upsert(
                symbol=current["symbol"],
                name=str(merged.get("name") or current["symbol"]),
                book=str(merged.get("book") or "core"),
                role=str(merged.get("role") or "plain"),
                price=float(current.get("price") or 10),
                base_price=float(merged.get("base_price") or current.get("base_price") or 10),
                min_price=float(merged.get("min_price") or current.get("min_price") or 0.5),
                max_price=float(merged.get("max_price") or current.get("max_price") or 500),
                status=str(merged.get("status") or current.get("status") or "listed"),
                feed=merged.get("feed"),
                steam_appid=merged.get("steam_appid"),
                steam_mode=merged.get("steam_mode"),
                persist=True,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if body.get("price") is not None:
            try:
                row["price"] = float(body["price"])
            except (TypeError, ValueError):
                pass
        return {"ok": True, "ticker": row}

    # Delisting keeps the row with status "delisted" (hidden from overlays and trading).
    @router.delete("/api/admin/market/tickers/{symbol}")
    async def market_delist_ticker(symbol: str, x_admin_token: Optional[str] = Header(None)):
        if not admin(x_admin_token).tape.delist(symbol):
            raise HTTPException(404, "unknown symbol")
        return {"ok": True, "symbol": symbol.upper(), "status": "delisted"}

    @router.post("/api/admin/market/steam/poll")
    async def market_steam_poll(x_admin_token: Optional[str] = Header(None)):
        return await admin(x_admin_token).tape.poll_steam()

    # Make the latest Steam player count the new 1.0x baseline for that ticker.
    @router.post("/api/admin/market/steam/baseline")
    async def market_steam_baseline(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        tape = admin(x_admin_token).tape
        row = tape.quote(str(body.get("symbol") or ""))
        if not row:
            raise HTTPException(404, "unknown symbol")
        ccu = row.get("steam_ccu")
        if not ccu:
            raise HTTPException(400, "no CCU sample yet — poll Steam first")
        row["steam_baseline"] = int(ccu)
        row["steam_factor"] = 1.0
        tape.save_listings()
        return {"ok": True, "symbol": row["symbol"], "baseline": int(ccu)}
