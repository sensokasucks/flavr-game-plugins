"""
Sumotori Dreams plugin web addresses. While the plugin is off they answer 503.

  GET  /api/sumotori/state     public, read-only: score, open bets, arena pieces (overlay/sumotori.html).
                               Only things chat already sees; no tokens, no points balances.
  GET  /api/sumotori/admin     admin: the same plus the arena file's path and text (pages/index.html)
  POST /api/sumotori/round     admin: {"action": "open" | "lock" | "win_a" | "win_b" | "cancel"}
  POST /api/sumotori/arena     admin: {"action": "next" | "clear" | "rewrite"}
  POST /api/sumotori/score/reset   admin: count wins from zero again

Admin routes need Core's admin token (the dashboard and phone remote send X-Admin-Token).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Body, Header, HTTPException

OFF = "Sumotori Dreams is off (Settings → Plugins)"


def add_routes(router, get_running) -> None:
    """Register the routes on Core's router; get_running() is the live SumotoriDreams or None."""
    def running():
        inst = get_running()
        if inst is None or inst.db is None:
            raise HTTPException(503, OFF)
        return inst

    def admin(token: Optional[str]):
        inst = running()
        inst.ctx.require_admin(token)
        return inst

    @router.get("/api/sumotori/state")
    async def sumo_state():
        return await running().state(admin=False)

    @router.get("/api/sumotori/admin")
    async def sumo_admin(x_admin_token: Optional[str] = Header(default=None)):
        return await admin(x_admin_token).state(admin=True)

    @router.post("/api/sumotori/round")
    async def sumo_round(payload: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(default=None)):
        inst = admin(x_admin_token)
        action = str(payload.get("action") or "")
        if action == "open":
            return await inst.open_round()
        if action == "lock":
            return await inst.lock_round()
        if action in ("win_a", "win_b"):
            return await inst.settle_round(action[-1])
        if action == "cancel":
            return await inst.cancel_round()
        raise HTTPException(400, "action must be open, lock, win_a, win_b or cancel")

    @router.post("/api/sumotori/arena")
    async def sumo_arena(payload: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(default=None)):
        inst = admin(x_admin_token)
        action = str(payload.get("action") or "")
        if action == "next":
            return await inst.next_arena()
        if action == "clear":
            return await inst.clear_queue()
        if action == "rewrite":
            return {"ok": await inst.rewrite(), "error": inst.last_error}
        raise HTTPException(400, "action must be next, clear or rewrite")

    @router.post("/api/sumotori/score/reset")
    async def sumo_reset(x_admin_token: Optional[str] = Header(default=None)):
        return await admin(x_admin_token).reset_score()
