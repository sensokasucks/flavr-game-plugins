"""
HTTP client for the FridgeSchedule1 game mod (fridge-schedule1/ in this repo) or its mock server.

Both answer on ``schedule1.bridge_url`` (default http://127.0.0.1:3857):

  GET  /customers            {"loaded", "boot", "customers": [{"id", "first", "last", "unlocked"}]}
  POST /names                {"names": {npc id: {"first", "last"}}}  -> {"success", "applied", "missing"}
  GET  /events?after=<seq>   {"boot", "last", "events": [{"seq", "type", "id", ...}]}
                             (type "app_remove" / "app_swap" with "key": buttons in the phone app)
  POST /board                {"named", "waiting", "top"}: lists for the in-game phone app (plugin.board())
  POST /notify               {"title", "text", "kind", "message", "label", "accent", "bg", "text_color"...}:
                             a stream alert for the phone (pop-up + Alerts tab); no kind = Feed note
  POST /mug                  {"id", "by", "goons"}: !mug; answers arrive as mug_result / mug_outcome events
  POST /remote               {"type": "join" | "leave", chatter fields}: co-op client -> host's list
  POST /nudge                {"npc"}: newly named customer texts an order (nudge_result event)
  POST /find                 {"npc", "by"}: mark the customer on the streamer's phone map

Each GET /customers entry also has "status" (locked / deal / offer / dealer / waiting) and
"status_text" ("deal set for 16:30-18:00 at the Docks"), made by the mod's CustomerStatus.cs.

GET /customers also carries "role" ("host", or "client" in someone else's co-op game: the host's
mod decides names then, and plugin.py only forwards joins) and "board" (the shared lists).

"boot" is a random id the mod picks each time the game starts; when it changes, its event numbers
start again at 1 and plugin.py re-sends the names. Every request carries ``X-Fridge-Core: 1``
and, when ``schedule1.bridge_token`` is set, ``X-Fridge-Token`` (the mod's Token preference must
match). The mod refuses anything carrying a browser Origin header, so web pages can't rename people.
Keep the field names here in sync with fridge-schedule1/mod/BridgeServer.cs and mock/mock_server.py.
"""

from __future__ import annotations

from typing import Optional

import httpx


class BridgeError(Exception):
    """The mod could not be reached or answered with an error."""


class Bridge:
    def __init__(self, base_url: str, token: str = "", timeout: float = 3.0):
        self.base_url = (base_url or "http://127.0.0.1:3857").rstrip("/")
        headers = {"X-Fridge-Core": "1"}
        if token:
            headers["X-Fridge-Token"] = token
        self._client: Optional[httpx.AsyncClient] = httpx.AsyncClient(timeout=timeout, headers=headers)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _call(self, method: str, path: str, **kw) -> dict:
        if self._client is None:
            raise BridgeError("bridge closed")
        try:
            r = await self._client.request(method, self.base_url + path, **kw)
        except httpx.HTTPError as exc:
            raise BridgeError(f"can't reach the Schedule I mod at {self.base_url} ({exc.__class__.__name__})") from exc
        if r.status_code >= 400:
            raise BridgeError(f"Schedule I mod answered {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as exc:
            raise BridgeError("Schedule I mod sent something that isn't JSON") from exc

    async def customers(self) -> dict:
        return await self._call("GET", "/customers")

    async def set_names(self, names: dict) -> dict:
        return await self._call("POST", "/names", json={"names": names})

    async def events(self, after: int) -> dict:
        return await self._call("GET", "/events", params={"after": int(after)})

    async def set_board(self, board: dict) -> dict:
        """What the in-game phone app lists; plugin.py sends it after a sync when it changed."""
        return await self._call("POST", "/board", json=board)

    async def mug(self, mug_id: int, by: str, goons: int) -> dict:
        """!mug: send goons after this streamer's player. The answer comes later as events
        "mug_result" {"mug", "ok", "msg"} and "mug_outcome" {"mug", "outcome"} (plugin.py handle_event)."""
        return await self._call("POST", "/mug", json={"id": int(mug_id), "by": by, "goons": int(goons)})

    async def remote(self, kind: str, platform: str, user_id: str, username: str, display_name: str,
                     is_sub: bool = False) -> dict:
        """Co-op client: pass a chatter's join / leave ("join" / "leave") to the host's list."""
        return await self._call("POST", "/remote", json={
            "type": kind, "platform": platform, "user_id": user_id, "username": username,
            "display_name": display_name, "is_sub": bool(is_sub)})

    async def nudge(self, npc_id: str) -> dict:
        """A newly named, met customer texts an order soon (setting nudge_new; host only). Answered
        by event "nudge_result" {"npc", "ok", "msg"} (plugin.py handle_event)."""
        return await self._call("POST", "/nudge", json={"npc": npc_id})

    async def find(self, npc_id: str, label: str) -> dict:
        """Mark that customer on the streamer's in-game phone map (page Find button)."""
        return await self._call("POST", "/find", json={"npc": npc_id, "by": label})

    async def notify(self, title: str, text: str, **alert) -> dict:
        """Pop something up on the in-game phone. A stream alert (plugin.py _on_alert) also passes
        ``kind`` (core.alerts kind), ``message`` (the viewer's own words) and its look from
        alert_style.style_for: ``label``, ``accent``, ``bg``, ``text``, ``muted`` ("#RRGGBBAA"),
        ``bold``, ``image`` (URL); the mod keeps those in its Alerts tab. Without ``kind`` (or with
        "system") it's a plain note for the Feed. Field names match BridgeServer.cs /notify."""
        return await self._call("POST", "/notify", json={"title": title, "text": text, **alert})
