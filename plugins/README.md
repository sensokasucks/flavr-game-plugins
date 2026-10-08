# Game plugins

One folder per game: `minecraft/`, `factorio/`, `granvir/`, `openttd/`. Stream Core works with
this folder empty; each plugin folder here adds its card under **Settings → Game plugins**.

- Add a game: copy its folder in here (from the games pack zip, or someone's plugin), restart Core,
  tick **Enabled** on its card, **Save & apply**, restart Core.
- Remove a game: untick it, delete its folder, restart Core.

Writing your own (often just a `plugin.json`): [../docs/PLUGINS.md](../docs/PLUGINS.md).
Plugins run inside Core with no sandbox; install only ones you trust.
