-- Chat Dynamo: scripted electric-energy-interface driven by stream power level 0–15.
-- Graphics reuse the vanilla accumulator so we don't ship custom sprites.

local max_mw = 6
if settings and settings.startup and settings.startup["fridge-dynamo-max-mw"] then
  max_mw = settings.startup["fridge-dynamo-max-mw"].value or 6
end
local max_str = tostring(max_mw) .. "MW"

local acc = data.raw["accumulator"] and data.raw["accumulator"]["accumulator"]
local picture = nil
local icon = "__base__/graphics/icons/accumulator.png"
local icon_size = 64

if acc then
  if acc.icon then
    icon = acc.icon
    icon_size = acc.icon_size or 64
  end
  if acc.chargable_graphics and acc.chargable_graphics.picture then
    picture = table.deepcopy(acc.chargable_graphics.picture)
  elseif acc.picture then
    picture = table.deepcopy(acc.picture)
  end
end

if not picture then
  local solar = data.raw["solar-panel"] and data.raw["solar-panel"]["solar-panel"]
  if solar and solar.picture then
    picture = table.deepcopy(solar.picture)
  else
    picture = {
      filename = "__base__/graphics/entity/accumulator/accumulator.png",
      priority = "extra-high",
      width = 130,
      height = 189,
      shift = { 0, -0.3 },
      scale = 0.5,
    }
  end
end

-- Orange tint so it is visually distinct from a normal accumulator
local function tint_sprite(obj)
  if type(obj) ~= "table" then return end
  if obj.filename or obj.filenames then
    obj.tint = { r = 1.0, g = 0.55, b = 0.15, a = 1 }
  end
  for _, v in pairs(obj) do
    if type(v) == "table" then
      tint_sprite(v)
    end
  end
end
if picture then
  tint_sprite(picture)
end

data:extend({
  {
    type = "item",
    name = "fridge-chat-dynamo",
    icon = icon,
    icon_size = icon_size,
    subgroup = "energy",
    order = "e[accumulator]-b[fridge-chat-dynamo]",
    place_result = "fridge-chat-dynamo",
    stack_size = 20,
  },
  {
    type = "recipe",
    name = "fridge-chat-dynamo",
    enabled = true,
    energy_required = 5,
    ingredients = {
      { type = "item", name = "iron-plate", amount = 20 },
      { type = "item", name = "copper-plate", amount = 10 },
      { type = "item", name = "iron-gear-wheel", amount = 5 },
    },
    results = {
      { type = "item", name = "fridge-chat-dynamo", amount = 1 },
    },
  },
  {
    type = "electric-energy-interface",
    name = "fridge-chat-dynamo",
    icon = icon,
    icon_size = icon_size,
    flags = { "placeable-neutral", "player-creation" },
    minable = { mining_time = 0.4, result = "fridge-chat-dynamo" },
    max_health = 250,
    corpse = acc and acc.corpse or "accumulator-remnants",
    dying_explosion = acc and acc.dying_explosion or "accumulator-explosion",
    collision_box = { { -0.9, -0.9 }, { 0.9, 0.9 } },
    selection_box = { { -1, -1 }, { 1, 1 } },
    energy_source = {
      type = "electric",
      buffer_capacity = "10MJ",
      usage_priority = "primary-output",
      input_flow_limit = "0W",
      output_flow_limit = max_str,
      render_no_power_icon = false,
    },
    energy_production = max_str,
    energy_usage = "0W",
    gui_mode = "none",
    continuous_animation = true,
    picture = picture,
    working_sound = acc and acc.working_sound or nil,
  },
})

-- Power vault: opposite of Chat Dynamo — eats electricity for market dividends.
local vault_picture = picture and table.deepcopy(picture) or nil
local function tint_blue(obj)
  if type(obj) ~= "table" then return end
  if obj.filename or obj.filenames then
    obj.tint = { r = 0.25, g = 0.55, b = 1.0, a = 1 }
  end
  for _, v in pairs(obj) do
    if type(v) == "table" then tint_blue(v) end
  end
end
if vault_picture then tint_blue(vault_picture) end

data:extend({
  {
    type = "item",
    name = "fridge-power-vault",
    icon = icon,
    icon_size = icon_size,
    subgroup = "energy",
    order = "e[accumulator]-c[fridge-power-vault]",
    place_result = "fridge-power-vault",
    stack_size = 20,
  },
  {
    type = "recipe",
    name = "fridge-power-vault",
    enabled = true,
    energy_required = 5,
    ingredients = {
      { type = "item", name = "iron-plate", amount = 20 },
      { type = "item", name = "copper-plate", amount = 15 },
      { type = "item", name = "iron-gear-wheel", amount = 5 },
    },
    results = { { type = "item", name = "fridge-power-vault", amount = 1 } },
  },
  {
    type = "electric-energy-interface",
    name = "fridge-power-vault",
    icon = icon,
    icon_size = icon_size,
    flags = { "placeable-neutral", "player-creation" },
    minable = { mining_time = 0.4, result = "fridge-power-vault" },
    max_health = 250,
    corpse = acc and acc.corpse or "accumulator-remnants",
    dying_explosion = acc and acc.dying_explosion or "accumulator-explosion",
    collision_box = { { -0.9, -0.9 }, { 0.9, 0.9 } },
    selection_box = { { -1, -1 }, { 1, 1 } },
    energy_source = {
      type = "electric",
      buffer_capacity = "10MJ",
      usage_priority = "primary-input",
      input_flow_limit = max_str,
      output_flow_limit = "0W",
      render_no_power_icon = false,
    },
    energy_production = "0W",
    energy_usage = max_str,
    gui_mode = "none",
    picture = vault_picture,
  },
})

-- Item vault: steel-chest that the script voids. Dividends from sacrificed items.
local chest = data.raw.container and data.raw.container["steel-chest"]
if chest then
  local item_vault = table.deepcopy(chest)
  item_vault.name = "fridge-item-vault"
  item_vault.minable = { mining_time = 0.3, result = "fridge-item-vault" }
  item_vault.icon = chest.icon or "__base__/graphics/icons/steel-chest.png"
  item_vault.icon_size = chest.icon_size or 64
  if item_vault.picture then
    local function tint_gold(obj)
      if type(obj) ~= "table" then return end
      if obj.filename or obj.filenames then
        obj.tint = { r = 1.0, g = 0.82, b = 0.2, a = 1 }
      end
      for _, v in pairs(obj) do
        if type(v) == "table" then tint_gold(v) end
      end
    end
    tint_gold(item_vault.picture)
  end
  data:extend({
    item_vault,
    {
      type = "item",
      name = "fridge-item-vault",
      icon = item_vault.icon,
      icon_size = item_vault.icon_size or 64,
      subgroup = "storage",
      order = "a[items]-c[fridge-item-vault]",
      place_result = "fridge-item-vault",
      stack_size = 20,
    },
    {
      type = "recipe",
      name = "fridge-item-vault",
      enabled = true,
      energy_required = 3,
      ingredients = {
        { type = "item", name = "iron-plate", amount = 20 },
        { type = "item", name = "copper-plate", amount = 5 },
      },
      results = { { type = "item", name = "fridge-item-vault", amount = 1 } },
    },
  })
end
