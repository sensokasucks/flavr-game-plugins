"""Lets the game plugins' tests run against a Stream Core checkout.

Core is found at STREAM_CORE_DIR, or next to this repo at ../flavr-leftovers/fridge-stream-core.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _core_dir() -> Path:
    env = os.environ.get("STREAM_CORE_DIR", "").strip()
    core = Path(env) if env else HERE.parent / "flavr-leftovers" / "fridge-stream-core"
    if not (core / "core" / "plugin_api.py").is_file():
        raise SystemExit(
            f"Stream Core not found at {core}. Clone flavr-leftovers next to this repo "
            "or set STREAM_CORE_DIR to its fridge-stream-core folder."
        )
    return core


CORE = _core_dir()
# Core first, then this repo in front of it so `plugins` is this repo's folder, not Core's empty one.
for path in (str(CORE), str(HERE)):
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)
os.environ["STREAM_CORE_PLUGINS_DIR"] = str(HERE / "plugins")
