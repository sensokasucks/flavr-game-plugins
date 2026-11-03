"""
Stream Core's alert look, boiled down for the in-game phone (the FridgeSchedule1 mod's Alerts tab).

Called by plugin.py ``_on_alert`` for every alert it forwards; the result rides along on the mod's
POST /notify (bridge.py ``notify``; the mod reads it in BridgeServer.cs -> Shared.Notice). The mod
can't run CSS, so this reads Core's own alert stylesheets and hands over plain colours:

  overlay/alerts.css         the built-in look: --alert-text, --alert-muted, --alert-card-bg and an
                             accent per kind (--alert-accent-follow / -sub / -raid / ...)
  overlay/alerts-custom.css  the streamer's CSS from Admin -> Alert test, read after the built-in one
                             so its values win (core.alerts.read_custom_css)

Mapped, per kind (the kind's Streamlabs class names from core.alerts.KIND_CLASSES):
  --alert-accent / border-color  -> accent (label, unread dot, side bar)
  color                          -> text (the headline)
  .name { color }                -> text as well (the chatter's name is the headline's start)
  background-color / background  -> bg (only a plain colour; gradients and images are skipped)
  font-weight (bold / 600+)      -> bold headline
  --alert-muted                  -> muted (the viewer's own message)
Everything else in the CSS (fonts, sizes, shadows, animations, color-mix) has no Unity equivalent and
is ignored. With the "card" skin the card background is --alert-card-bg; other skins use the phone
app's own row colour.

Picture: the kind's picture picked on Core's alert page (core.alerts.read_alert_settings "media"), or
the alert's own image (stickers / gifts), or the fallback kind's; made absolute against Core's address.
Colours come out as "#RRGGBBAA" (the mod's ColorUtility.TryParseHtmlString reads that).
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Optional

from core import alerts as core_alerts

CSS_CACHE_SEC = 10            # re-read the stylesheets at most this often (they change rarely)
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_VAR = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)")

_cache: dict[str, Any] = {"at": 0.0, "rules": []}


def _rules() -> list[tuple[list[str], dict[str, str]]]:
    """(selectors, declarations) of alerts.css then alerts-custom.css, cached CSS_CACHE_SEC."""
    if time.monotonic() - _cache["at"] < CSS_CACHE_SEC:
        return _cache["rules"]
    texts = []
    try:
        texts.append(core_alerts.ALERT_STYLE.css_path().parent.joinpath("alerts.css").read_text(encoding="utf-8"))
    except (OSError, AttributeError):
        pass
    try:
        texts.append(core_alerts.read_custom_css() or "")
    except OSError:
        pass
    rules = []
    for text in texts:
        for sel, body in _RULE.findall(_COMMENT.sub("", text)):
            decls = {}
            for part in body.split(";"):
                if ":" in part:
                    k, v = part.split(":", 1)
                    decls[k.strip().lower()] = v.replace("!important", "").strip()
            rules.append(([s.strip() for s in sel.split(",") if s.strip()], decls))
    _cache.update(at=time.monotonic(), rules=rules)
    return rules


def colour(value: str, variables: dict[str, str], depth: int = 0) -> Optional[str]:
    """A CSS colour as "#RRGGBBAA", resolving var(); None for anything that isn't a plain colour."""
    v = (value or "").strip()
    m = _VAR.fullmatch(v)
    if m and depth < 6:
        return colour(variables.get(m.group(1)) or m.group(2) or "", variables, depth + 1)
    if re.fullmatch(r"#[0-9a-fA-F]{3}", v):
        return "#" + "".join(c * 2 for c in v[1:]).upper() + "FF"
    if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        return v.upper() + "FF"
    if re.fullmatch(r"#[0-9a-fA-F]{8}", v):
        return v.upper()
    m = re.fullmatch(r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+%?))?\s*\)", v)
    if m:
        r, g, b = (max(0, min(255, int(float(x)))) for x in m.groups()[:3])
        a = m.group(4)
        alpha = 1.0 if a is None else float(a[:-1]) / 100 if a.endswith("%") else float(a)
        return f"#{r:02X}{g:02X}{b:02X}{max(0, min(255, round(alpha * 255))):02X}"
    return None


def style_for(kind: str, payload: dict, core_url: str) -> dict[str, Any]:
    """The phone card's look for one alert: {"label", "accent", "bg", "text", "muted", "bold", "image"}."""
    classes = set(core_alerts.KIND_CLASSES.get(kind) or [])
    variables: dict[str, str] = {}
    picked: dict[str, str] = {}
    for selectors, decls in _rules():
        for sel in selectors:
            general = sel in (":root", "#alert-box", "body", "html", "#wrap")
            m = re.fullmatch(r"#alert-box\.([\w-]+)(\s+\.name)?", sel)
            mine = bool(m and m.group(1) in classes)
            if not (general or mine):
                continue
            variables.update({k: v for k, v in decls.items() if k.startswith("--")})
            if not mine:
                continue
            if m.group(2):                                    # "#alert-box.<kind> .name { color }"
                if "color" in decls:
                    picked["text"] = decls["color"]
                continue
            for prop, key in (("--alert-accent", "accent"), ("border-color", "accent"), ("color", "text"),
                              ("background-color", "bg"), ("background", "bg"), ("font-weight", "bold")):
                if prop in decls:
                    picked[key] = decls[prop]

    settings = {}
    try:
        settings = core_alerts.read_alert_settings() or {}
    except Exception:
        pass
    accent = colour(picked.get("accent") or "var(--alert-accent)", variables)
    text = colour(picked.get("text") or "var(--alert-text)", variables)
    bg = colour(picked["bg"], variables) if picked.get("bg") else None
    if bg is None and settings.get("skin") == "card":
        bg = colour("var(--alert-card-bg)", variables)
    weight = str(picked.get("bold") or "").lower()
    media = settings.get("media") or {}
    image = media.get(kind) or payload.get("image") or media.get(payload.get("falls_back") or "") or ""
    if image.startswith("/"):
        image = core_url.rstrip("/") + image
    meta = core_alerts.KINDS.get(kind) or {}
    return {
        "label": str(meta.get("label") or kind or "Alert"),
        "accent": accent or "#53FC18FF",
        "bg": bg or "",
        "text": text or "#F4F6FBFF",
        "muted": colour("var(--alert-muted)", variables) or "#C5CDDCFF",
        "bold": weight in ("bold", "bolder") or (weight.isdigit() and int(weight) >= 600) or not weight,
        "image": image if image.startswith(("http://", "https://")) else "",
    }
