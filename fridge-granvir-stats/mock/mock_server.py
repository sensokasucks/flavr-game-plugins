#!/usr/bin/env python3
"""Dev stand-in for the BepInEx plugin. Serves /stats + overlay HTML on :3855."""

from __future__ import annotations

import json
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "overlay"
HOST = "127.0.0.1"
PORT = 3855

START = time.time()


def snapshot() -> dict:
    elapsed = int(time.time() - START)
    heat = min(100, 8 + (elapsed % 40) * 2)
    hp = max(20, 100 - (elapsed // 15) % 80)
    return {
        "ok": True,
        "source": "mock",
        "plugin_version": "0.1.0-mock",
        "game_version": "",
        "ts": int(time.time()),
        "online": True,
        "is_host": True,
        "phase": "mission" if elapsed % 90 < 60 else "rest",
        "campaign": {
            "name": "Zero Front",
            "region": "Inheritance",
            "hours_left": max(1, 18 - (elapsed // 30) % 16),
            "credits": 24000 + elapsed * 10,
            "threat": 120 + (elapsed // 20) % 80,
        },
        "squad": {
            "count": 3,
            "max": 10,
            "players": [
                {"name": "Host", "alive": True},
                {"name": "Wing", "alive": True},
                {"name": "Anchor", "alive": hp > 30},
            ],
        },
        "pilot": {
            "name": "Host",
            "alive": True,
            "health": hp,
            "health_max": 100,
            "heat": heat,
            "heat_max": 100,
            "ammo": 240,
            "kills": elapsed // 8,
            "deaths": 0,
        },
        "parts": {
            "equipped": 7,
            "depot": 12,
            "codex_found": 41,
            "codex_total": 300,
        },
        "notes": ["mock data — start Granvir + BepInEx for live numbers"],
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(OVERLAY), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        print("[granvir-mock]", fmt % args)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] in ("/stats", "/health", "/ping"):
            body = json.dumps(snapshot()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path in ("/", "/index.html"):
            self.path = "/overlay.html"
        super().do_GET()

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/command":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        print("[granvir-mock] command", payload)
        body = json.dumps(
            {
                "success": False,
                "error": "mock refuses writes — host-only commands land in the BepInEx plugin",
                "command": payload.get("command"),
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Fridge Granvir Stats mock  http://{HOST}:{PORT}/stats")
    print(f"Overlay                    http://{HOST}:{PORT}/overlay.html")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
