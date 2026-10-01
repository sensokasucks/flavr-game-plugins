-- Fridge Factorio Stats mod
-- Provides /fridge-stats RCON command (alias /xsplit-stats) returning JSON for streaming overlays.
-- Tracks player deaths via events.
-- Compatible with Factorio 2.0 / 2.1 (Space Age).

local json = helpers and helpers.table_to_json or function(t) return game.table_to_json(t) end

-- Persistent storage
local DYNAMO_NAME = "fridge-chat-dynamo"
local POWER_VAULT_NAME = "fridge-power-vault"
local ITEM_VAULT_NAME = "fridge-item-vault"

local function max_watts()
  local setting = settings.startup["fridge-dynamo-max-mw"]
  local mw = (setting and setting.value) or 6
  return mw * 1000000
end

local function watts_for_level(level)
  level = tonumber(level) or 0
  if level <= 0 then return 0 end
  if level > 15 then level = 15 end
  return (max_watts() * level) / 15
end

local function market_factor()
  local f = tonumber(storage.market_factor) or 1
  if f < 0.25 then f = 0.25 end
  if f > 3 then f = 3 end
  return f
end

local function apply_dynamo(entity)
  if not (entity and entity.valid and entity.name == DYNAMO_NAME) then return end
  local watts = watts_for_level(storage.power_level or 0) * market_factor()
  pcall(function()
    entity.power_production = watts
  end)
end

local function apply_power_vault(entity)
  if not (entity and entity.valid and entity.name == POWER_VAULT_NAME) then return end
  pcall(function()
    entity.power_usage = max_watts()
  end)
end

local function apply_all_dynamos()
  if not storage.dynamos then return end
  for unit, entity in pairs(storage.dynamos) do
    if entity and entity.valid then
      apply_dynamo(entity)
    else
      storage.dynamos[unit] = nil
    end
  end
end

local function register_dynamo(entity)
  if not (entity and entity.valid and entity.name == DYNAMO_NAME) then return end
  storage.dynamos = storage.dynamos or {}
  storage.dynamos[entity.unit_number] = entity
  apply_dynamo(entity)
end

local function unregister_dynamo(entity)
  if not entity then return end
  if storage.dynamos and entity.unit_number then
    storage.dynamos[entity.unit_number] = nil
  end
end

local function register_named(map_key, expected_name, entity, apply_fn)
  if not (entity and entity.valid and entity.name == expected_name) then return end
  storage[map_key] = storage[map_key] or {}
  storage[map_key][entity.unit_number] = entity
  if apply_fn then apply_fn(entity) end
end

local function unregister_named(map_key, entity)
  if not entity or not entity.unit_number then return end
  if storage[map_key] then
    storage[map_key][entity.unit_number] = nil
  end
end

local function scan_existing_dynamos()
  storage.dynamos = {}
  storage.power_vaults = {}
  storage.item_vaults = {}
  for _, surface in pairs(game.surfaces) do
    for _, entity in pairs(surface.find_entities_filtered{ name = DYNAMO_NAME }) do
      register_dynamo(entity)
    end
    for _, entity in pairs(surface.find_entities_filtered{ name = POWER_VAULT_NAME }) do
      register_named("power_vaults", POWER_VAULT_NAME, entity, apply_power_vault)
    end
    for _, entity in pairs(surface.find_entities_filtered{ name = ITEM_VAULT_NAME }) do
      register_named("item_vaults", ITEM_VAULT_NAME, entity, nil)
    end
  end
  apply_all_dynamos()
end

local function set_power_level(level)
  level = math.floor(tonumber(level) or 0)
  if level < 0 then level = 0 end
  if level > 15 then level = 15 end
  storage.power_level = level
  apply_all_dynamos()
  return level
end

local function set_market_factor(factor)
  factor = tonumber(factor) or 1
  storage.market_factor = factor
  apply_all_dynamos()
  return market_factor()
end

local function count_map(map)
  local n = 0
  if not map then return 0 end
  for _, entity in pairs(map) do
    if entity and entity.valid then n = n + 1 end
  end
  return n
end

local function tick_vaults(dt_seconds)
  storage.vault_work = storage.vault_work or { mj = 0, items = 0 }
  -- Power vault: if the buffer has energy, the network is feeding it.
  for id, entity in pairs(storage.power_vaults or {}) do
    if not (entity and entity.valid) then
      storage.power_vaults[id] = nil
    elseif (entity.energy or 0) > 1000 then
      local watts = entity.power_usage or max_watts()
      storage.vault_work.mj = (storage.vault_work.mj or 0) + (watts * dt_seconds) / 1e6
    end
  end
  -- Item vault: void whatever is in the chest.
  for id, entity in pairs(storage.item_vaults or {}) do
    if not (entity and entity.valid) then
      storage.item_vaults[id] = nil
    else
      local inv = entity.get_inventory and entity.get_inventory(defines.inventory.chest)
      if inv then
        for i = 1, #inv do
          local stack = inv[i]
          if stack and stack.valid_for_read then
            storage.vault_work.items = (storage.vault_work.items or 0) + stack.count
            stack.clear()
          end
        end
      end
    end
  end
end

local function flush_vault_work()
  storage.vault_work = storage.vault_work or { mj = 0, items = 0 }
  local out = {
    mj = storage.vault_work.mj or 0,
    items = storage.vault_work.items or 0,
  }
  storage.vault_work = { mj = 0, items = 0 }
  return out
end

script.on_init(function()
  storage.deaths = 0
  storage.kill_cache = {}
  storage.power_level = 0
  storage.market_factor = 1
  storage.dynamos = {}
  storage.power_vaults = {}
  storage.item_vaults = {}
  storage.vault_work = { mj = 0, items = 0 }
end)

script.on_configuration_changed(function()
  storage.deaths = storage.deaths or 0
  storage.kill_cache = storage.kill_cache or {}
  storage.power_level = storage.power_level or 0
  storage.dynamos = storage.dynamos or {}
  storage.power_vaults = storage.power_vaults or {}
  storage.item_vaults = storage.item_vaults or {}
  storage.market_factor = storage.market_factor or 1
  storage.vault_work = storage.vault_work or { mj = 0, items = 0 }
  scan_existing_dynamos()
end)

script.on_event(defines.events.on_player_died, function(event)
  storage.deaths = (storage.deaths or 0) + 1
end)

local dynamo_built_events = {
  defines.events.on_built_entity,
  defines.events.on_robot_built_entity,
  defines.events.script_raised_built,
  defines.events.script_raised_revive,
}
if defines.events.on_space_platform_built_entity then
  table.insert(dynamo_built_events, defines.events.on_space_platform_built_entity)
end
script.on_event(dynamo_built_events, function(event)
  local entity = event.entity or event.created_entity
  register_dynamo(entity)
  register_named("power_vaults", POWER_VAULT_NAME, entity, apply_power_vault)
  register_named("item_vaults", ITEM_VAULT_NAME, entity, nil)
end)

local dynamo_removed_events = {
  defines.events.on_player_mined_entity,
  defines.events.on_robot_mined_entity,
  defines.events.on_entity_died,
  defines.events.script_raised_destroy,
}
if defines.events.on_space_platform_mined_entity then
  table.insert(dynamo_removed_events, defines.events.on_space_platform_mined_entity)
end
script.on_event(dynamo_removed_events, function(event)
  unregister_dynamo(event.entity)
  unregister_named("power_vaults", event.entity)
  unregister_named("item_vaults", event.entity)
end)

-- Helper: safe surface name
local function surface_name(surface)
  return surface and surface.name or "nauvis"
end

-- Collect kill counts (biters / enemies killed by player force)
local function get_kills(force, surface)
  local stats = force.get_kill_count_statistics(surface)
  if not stats then return 0, {} end

  -- input_counts = entities killed *by* this force
  local total = 0
  local by_type = {}
  for name, count in pairs(stats.input_counts or {}) do
    total = total + count
    by_type[name] = count
  end
  return total, by_type
end

-- Collect current alerts from connected players
local function get_alerts()
  local alerts = {}
  for _, player in pairs(game.connected_players) do
    local ok, player_alerts = pcall(function()
      return player.get_alerts({})
    end)
    if ok and player_alerts then
      for surface_index, type_map in pairs(player_alerts) do
        for alert_type, alert_list in pairs(type_map) do
          for _, alert in pairs(alert_list) do
            local entry = {
              type = tostring(alert_type),
              surface = surface_index,
              tick = game.tick
            }
            if alert.target and alert.target.valid then
              entry.entity = alert.target.name
              entry.position = {x = alert.target.position.x, y = alert.target.position.y}
            end
            if alert.message then
              entry.message = alert.message
            end
            table.insert(alerts, entry)
          end
        end
      end
    end
  end
  return alerts
end

-- Power is intentionally left as a stub here.
-- Accurate production / consumption / accumulator data comes from the companion
-- "Wiretap – Stats Exporter" mod (hmph-wiretap) which the Node bridge automatically merges.
-- Scanning every electric entity every few seconds would hurt UPS on large bases.
local function get_power_approx(force)
  return {
    production_watts_approx = 0,
    note = "Install 'Wiretap – Stats Exporter' (hmph-wiretap) for live power production & consumption."
  }
end

-- Main data collector
local function collect_stats()
  local force = game.forces["player"] or game.forces[1]
  if not force then
    return { error = "No player force found" }
  end

  local surface = game.surfaces["nauvis"] or game.surfaces[1]
  local kills_total, kills_by_type = get_kills(force, surface)

  -- Research
  local research = {
    current = nil,
    progress = 0,
    queue = {},
    researched_count = 0
  }
  if force.current_research then
    research.current = force.current_research.name
    research.progress = force.research_progress or 0
  end
  if force.research_queue then
    for _, tech in pairs(force.research_queue) do
      table.insert(research.queue, type(tech) == "string" and tech or (tech.name or tostring(tech)))
    end
  end
  -- Count researched
  local researched = 0
  local total_tech = 0
  for name, tech in pairs(force.technologies) do
    total_tech = total_tech + 1
    if tech.researched then
      researched = researched + 1
    end
  end
  research.researched_count = researched
  research.total_technologies = total_tech

  -- Evolution (enemy force)
  local evolution = 0
  if game.forces["enemy"] then
    evolution = game.forces["enemy"].get_evolution_factor(surface) or 0
  end

  local data = {
    tick = game.tick,
    game_time_seconds = math.floor(game.tick / 60),
    deaths = storage.deaths or 0,
    kills = {
      total = kills_total,
      by_type = kills_by_type  -- can be large; overlay can ignore details
    },
    research = research,
    evolution = evolution,
    alerts = get_alerts(),
    power = get_power_approx(force),
    dynamo = {
      power_level = storage.power_level or 0,
      watts = watts_for_level(storage.power_level or 0) * market_factor(),
      max_watts = max_watts(),
      market_factor = market_factor(),
      count = storage.dynamos and table_size(storage.dynamos) or 0,
    },
    vaults = {
      power_count = count_map(storage.power_vaults),
      item_count = count_map(storage.item_vaults),
      pending_mj = (storage.vault_work and storage.vault_work.mj) or 0,
      pending_items = (storage.vault_work and storage.vault_work.items) or 0,
    },
    players_online = #game.connected_players,
    surface = surface_name(surface)
  }

  return data
end

-- RCON / console command
local function print_stats(command)
  local data = collect_stats()
  local success, encoded = pcall(json, data)
  if success then
    rcon.print(encoded)
  else
    rcon.print('{"error":"json encode failed"}')
  end
end

commands.add_command("fridge-stats", "Return JSON stats for Fridge overlays", print_stats)
-- kept so an old bridge still works until you update the Node process
commands.add_command("xsplit-stats", "Legacy alias for /fridge-stats", print_stats)

commands.add_command("fridge-power", "Set Chat Dynamo stream power level 0-15", function(command)
  local level = set_power_level(command.parameter)
  rcon.print(tostring(level))
end)

commands.add_command("fridge-give-dynamo", "Give the player a Chat Dynamo", function(command)
  local player = command.player_index and game.get_player(command.player_index)
  if not player then
    rcon.print("no player")
    return
  end
  player.insert({ name = DYNAMO_NAME, count = 1 })
  rcon.print("ok")
end)

commands.add_command("fridge-pwr-factor", "Set Chat Dynamo market multiplier (PWR price / base)", function(command)
  local f = set_market_factor(command.parameter)
  rcon.print(tostring(f))
end)

commands.add_command("fridge-vault-flush", "Return and reset pending vault work as JSON", function()
  local flushed = flush_vault_work()
  rcon.print(json(flushed))
end)

-- Optional: also write file every ~5 seconds for file-based consumers
local write_interval = 300  -- ticks (~5s at 60ups)
script.on_nth_tick(write_interval, function()
  tick_vaults(write_interval / 60)
  local data = collect_stats()
  -- Trim kills_by_type to keep file small (top killers only)
  if data.kills and data.kills.by_type then
    local sorted = {}
    for k, v in pairs(data.kills.by_type) do
      table.insert(sorted, {name = k, count = v})
    end
    table.sort(sorted, function(a, b) return a.count > b.count end)
    local top = {}
    for i = 1, math.min(15, #sorted) do
      top[sorted[i].name] = sorted[i].count
    end
    data.kills.by_type = top
  end
  pcall(function()
    helpers.write_file("fridge-stats/stats.json", json(data), false)
  end)
end)

-- Remote interface for other mods
local stats_interface = {
  get_stats = function()
    return collect_stats()
  end,
  get_deaths = function()
    return storage.deaths or 0
  end,
  set_power_level = function(level)
    return set_power_level(level)
  end,
  get_power_level = function()
    return storage.power_level or 0
  end,
  set_market_factor = function(factor)
    return set_market_factor(factor)
  end,
  flush_vaults = function()
    return flush_vault_work()
  end,
}
remote.add_interface("fridge-stats", stats_interface)
remote.add_interface("xsplit-stats", stats_interface)
