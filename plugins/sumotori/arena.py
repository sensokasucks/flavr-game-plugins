"""
Sumotori Dreams arena files: the built-in piece list and the .smo text Stream Core writes.

Sumotori Dreams loads plain-text arena scripts (.smo) from Select Arena > Load Mod and reloads the
file by itself whenever it changes (the developer's modding page, gravitysensation.com/sumotori/
modding.htm). plugin.py calls build_smo() and write_smo() whenever the arena changes: at "Next
arena", or straight away when the ``apply`` setting is "now".

What we know of the format (from that page, NOT yet checked against the Steam "Classic" build):
  addbox(vec(size x,y,z), vec(position x,y,z), texture, physics flag)   a box; negative y is down
  breakability(n)                                                     how easily the LAST box breaks
  man(vec(position), vec(facing), control)                            a wrestler; 2 = player 1,
                                                                      3 = player 2, other = AI
An arena needs 4 men. We never write comments into the file because we don't know the comment
syntax; every line we add is one of the calls above.

Because the physics flag values aren't documented, the snippets below use placeholders that come
from settings (plugin.json ``fixed_flag`` / ``loose_flag`` / ``texture`` / ``break_strength`` /
``floor_y``). If a piece falls through the floor or floats, those settings are what to change.
"""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Iterable

# The arena used when the ``base_file`` setting is empty: one square floor and four men facing the
# middle, player 1 on the west side and three AI wrestlers. The streamer can point ``base_file`` at
# any .smo they made instead (a copy of one that works in their game is the safest start).
# {tex} / {fixed} are filled from settings by build_smo().
BUILTIN_BASE = [
    "addbox(vec(24,2,24),vec(0,-8,0),{tex},{fixed});",
    "man(vec(-5,-5,0),vec(1,0,0),2);",
    "man(vec(5,-5,0),vec(-1,0,0),0);",
    "man(vec(0,-5,-5),vec(0,0,1),0);",
    "man(vec(0,-5,5),vec(0,0,-1),0);",
]

# Pieces chat can buy (!arena <piece>). Each: shown name, then the .smo lines with placeholders:
#   {x} {z}   random spot on the floor (plugin.py picks it, inside the ``arena_half`` setting)
#   {y}       floor top (``floor_y``), so {y}+h puts a box h units above the floor
#   {tex} {fixed} {loose} {brk}   from settings (see the module docstring)
# Prices are the ``prices`` setting (piece: points, 0 = off); keep these keys in step with
# plugin.json config_defaults "prices" and the README's piece table.
PIECES: dict[str, tuple[str, list[str]]] = {
    "crate": ("a crate", [
        "addbox(vec(2,2,2),vec({x},{y}+8,{z}),{tex},{loose});",
    ]),
    "bigcrate": ("a big crate", [
        "addbox(vec(4,4,4),vec({x},{y}+10,{z}),{tex},{loose});",
    ]),
    "crates": ("a crate shower", [
        "addbox(vec(1.5,1.5,1.5),vec({x},{y}+8,{z}),{tex},{loose});",
        "addbox(vec(1.5,1.5,1.5),vec({x}+2,{y}+11,{z}),{tex},{loose});",
        "addbox(vec(1.5,1.5,1.5),vec({x},{y}+14,{z}+2),{tex},{loose});",
        "addbox(vec(1.5,1.5,1.5),vec({x}-2,{y}+17,{z}),{tex},{loose});",
        "addbox(vec(1.5,1.5,1.5),vec({x},{y}+20,{z}-2),{tex},{loose});",
    ]),
    "wall": ("a wall", [
        "addbox(vec(1,3,8),vec({x},{y}+1.5,{z}),{tex},{fixed});",
    ]),
    "breakwall": ("a breakable wall", [
        "addbox(vec(1,3,8),vec({x},{y}+1.5,{z}),{tex},{fixed});",
        "breakability({brk});",
    ]),
    "pillars": ("three pillars", [
        "addbox(vec(1,5,1),vec({x},{y}+2.5,{z}),{tex},{fixed});",
        "addbox(vec(1,5,1),vec({x}+3,{y}+2.5,{z}),{tex},{fixed});",
        "addbox(vec(1,5,1),vec({x},{y}+2.5,{z}+3),{tex},{fixed});",
    ]),
    "step": ("a step", [
        "addbox(vec(6,0.6,6),vec({x},{y}+0.3,{z}),{tex},{fixed});",
    ]),
}


def num(value: float) -> str:
    """A number as .smo text: 4.0 -> "4", 1.25 -> "1.25" (no exponent, at most 2 decimals)."""
    v = round(float(value), 2)
    return str(int(v)) if v.is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")


def pick_spot(rng: random.Random, half: float) -> tuple[float, float]:
    """A random (x, z) on the floor within ``half`` units of the middle, rounded to 0.5.
    Keeps 1.5 units clear of the exact middle so a piece rarely lands on top of a clinch."""
    half = max(1.5, float(half))
    for _ in range(20):
        x = round(rng.uniform(-half, half) * 2) / 2
        z = round(rng.uniform(-half, half) * 2) / 2
        if abs(x) >= 1.5 or abs(z) >= 1.5:
            return x, z
    return half, half


def piece_lines(piece: str, x: float, z: float, opts: dict) -> list[str]:
    """The .smo lines for one bought piece at (x, z). ``opts``: tex, fixed, loose, brk, floor_y.

    Sums like "{x}+2" are worked out here, so the game only ever sees plain numbers."""
    _name, template = PIECES[piece]
    out = []
    for line in template:
        text = line.format(x=num(x), z=num(z), y=num(opts["floor_y"]), tex=num(opts["tex"]),
                           fixed=num(opts["fixed"]), loose=num(opts["loose"]), brk=num(opts["brk"]))
        out.append(_fold_sums(text))
    return out


def _fold_sums(text: str) -> str:
    """Turn "vec(3,-7+8,-2.5)" into "vec(3,1,-2.5)": each comma/paren-separated part that is a
    plain sum of numbers is replaced by its value. Anything else is left as it was."""
    import re

    def fold(m: re.Match) -> str:
        part = m.group(0)
        if not re.fullmatch(r"-?\d+(\.\d+)?([+-]\d+(\.\d+)?)+", part):
            return part
        total = sum(float(t) for t in re.findall(r"[+-]?\d+(?:\.\d+)?", part))
        return num(total)

    return re.sub(r"[-\d.+]+", fold, text)


def base_lines(base_text: str | None, opts: dict) -> list[str]:
    """The arena's own lines: the streamer's base file (as it is) or BUILTIN_BASE filled in."""
    if base_text is not None and base_text.strip():
        return [ln.rstrip("\r") for ln in base_text.split("\n")]
    return [ln.format(tex=num(opts["tex"]), fixed=num(opts["fixed"])) for ln in BUILTIN_BASE]


def build_smo(base_text: str | None, pieces: Iterable[dict], opts: dict) -> str:
    """The whole .smo file: base lines, then each piece ({"piece", "x", "z"}) in the order bought.
    Lines end in CRLF (the game is a Windows program); unknown piece names are skipped."""
    lines = base_lines(base_text, opts)
    while lines and not lines[-1].strip():
        lines.pop()
    for p in pieces:
        if p.get("piece") in PIECES:
            lines.extend(piece_lines(p["piece"], float(p.get("x") or 0), float(p.get("z") or 0), opts))
    return "\r\n".join(lines) + "\r\n"


def write_smo(path: Path, text: str) -> None:
    """Write the arena file in one go (temp file + rename), so the game never reloads half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(text.encode("ascii", "replace"))
    os.replace(tmp, path)
