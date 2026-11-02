"""
Schedule I plugin web addresses, used by its dashboard page (pages/index.html). All need Core's
admin token (the dashboard sends X-Admin-Token); while the plugin is off they answer 503.

  GET  /api/schedule1/customers          mod status + everyone on the list (Schedule1Customers.snapshot)
  POST /api/schedule1/customers/add      {"platform", "username"}: streamer adds a chatter by hand
  POST /api/schedule1/customers/remove   {"key"}: take a chatter off (their customer gets its own name back)
  POST /api/schedule1/customers/find     {"key"}: mark their customer on the in-game phone map
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Body, Header, HTTPException

OFF = "Schedule I is off (Settings → Plugins)"


def add_routes(router, get_running) -> None:
    """Register the routes on Core's router; get_running() is the live Schedule1Customers or None."""
    def admin(token: Optional[str]):
        inst = get_running()
        if inst is None or inst.roster is None:
            raise HTTPException(503, OFF)
        inst.ctx.require_admin(token)
        return inst

    @router.get("/api/schedule1/customers")
    async def s1_customers(x_admin_token: Optional[str] = Header(default=None)):
        return await admin(x_admin_token).snapshot()

    @router.post("/api/schedule1/customers/add")
    async def s1_add(payload: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(default=None)):
        inst = admin(x_admin_token)
        try:
            row = await inst.add_person(payload.get("platform"), payload.get("username"))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "key": row["key"]}

    @router.post("/api/schedule1/customers/find")
    async def s1_find(payload: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(default=None)):
        """Mark a chatter's customer on the streamer's in-game phone map (Schedule1Customers.find_person)."""
        inst = admin(x_admin_token)
        return {"ok": await inst.find_person(str(payload.get("key") or ""))}

    @router.post("/api/schedule1/customers/remove")
    async def s1_remove(payload: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(default=None)):
        inst = admin(x_admin_token)
        return {"ok": await inst.remove_person(str(payload.get("key") or ""))}
