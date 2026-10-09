# Game plugins

One folder per game: `minecraft/`, `factorio/`, `granvir/`, `openttd/`. Each one is a Stream Core
plugin. Copy the folders you want into Stream Core's `fridge-stream-core/plugins/` folder (so you get
`fridge-stream-core/plugins/minecraft/plugin.json`), restart Core, then switch the game on under
**Settings → Game plugins**.

`__init__.py` here only lets this repo's tests import the plugins; Core doesn't need it copied.

Writing your own (often just a `plugin.json`):
[docs/PLUGINS.md](https://github.com/sensokasucks/flavr-leftovers/blob/main/fridge-stream-core/docs/PLUGINS.md) in flavr-leftovers.
Plugins run inside Core with no sandbox; install only ones you trust.
