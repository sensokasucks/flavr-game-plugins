"""
Build the games pack: StreamCore-games-pack-<version>.zip with every game plugin folder.

Unzip it into fridge-stream-core/ (it holds plugins/<id>/...), restart Core, and the games show
under Settings -> Game plugins. Only files git tracks go in (no __pycache__, data or local
edits that were never committed); tests stay out.

    python tools/pack_games.py                 version = today (YYYY.MM.DD)
    python tools/pack_games.py 2026.10.08 --out dist
"""

from __future__ import annotations

import argparse
import datetime as _dt
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"
SKIP_PARTS = {"__pycache__", "tests", "data"}


def tracked_files(folder: Path) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", str(folder)],
            cwd=ROOT, capture_output=True, check=True,
        ).stdout.decode("utf-8")
        files = [ROOT / p for p in out.split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        files = [p for p in folder.rglob("*") if p.is_file()]
    return [p for p in files if p.is_file() and not (SKIP_PARTS & set(p.relative_to(folder).parts))]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("version", nargs="?", default=_dt.date.today().strftime("%Y.%m.%d"))
    ap.add_argument("--out", default=str(ROOT / "dist"), help="folder for the zip (default dist/)")
    args = ap.parse_args(argv)

    games = sorted(p for p in PLUGINS.iterdir() if (p / "plugin.json").is_file())
    if not games:
        print("No plugin folders in", PLUGINS)
        return 1
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"StreamCore-games-pack-{args.version}.zip"
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for extra in ("README.md", "__init__.py"):
            if (PLUGINS / extra).is_file():
                zf.write(PLUGINS / extra, f"plugins/{extra}")
        for game in games:
            for f in tracked_files(game):
                zf.write(f, f.relative_to(ROOT).as_posix())
                count += 1
    print(f"{target}  ({', '.join(g.name for g in games)}; {count} files, {target.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
