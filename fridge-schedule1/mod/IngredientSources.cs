// Where the ingredient vote looks for ingredients, and where auto-place takes the winner from
// (MixPicker.cs). Core's three "Take ingredients from" tick boxes (plugins/schedule1/mixpick.py
// take_flags, sent as "take": {"inventory", "nearby", "owned"}), any mix of them:
//
//   inventory  the player's own inventory (hotbar + pockets)                         (the default)
//   nearby     the shelves / racks / safes in the same property as the mixing station, and the
//              player's vehicles parked within NearbyMetres of it
//   owned      storage at every property the player owns, and every player-owned vehicle's trunk
//
// The player's inventory always comes first in the list, so auto-place empties pockets before shelves.
// A slot is listed once even when "nearby" and "owned" both reach it.
//
// Storage means PlaceableStorageEntity.StorageEntity (shelves, racks, safes) and LandVehicle.Storage
// (trunks). Left alone on purpose: employee beds' lockers (BedItem, a PlaceableStorageEntity subclass:
// that's their pay), dead drops (WorldStorageEntity), dealers' stock and other stations' hoppers (not
// StorageEntity at all). On a co-op guest only "carried" is used: storage belongs to the host's world
// and moving its items from a guest is untested.
//
// Callers: MixPicker.Ingredients (vote lists) and MixPicker.Place (moving the winner). Main thread
// only. Game names (Property.OwnedProperties, BuildableItem.ParentProperty, Property.BuildableItems,
// VehicleManager.PlayerOwnedVehicles) come from the installed game build (checked 2026-11-03).

using System;
using System.Collections.Generic;
using UnityEngine;
using S1Bed = Il2CppScheduleOne.ObjectScripts.BedItem;
using S1Inventory = Il2CppScheduleOne.PlayerScripts.PlayerInventory;
using S1ItemSlot = Il2CppScheduleOne.ItemFramework.ItemSlot;
using S1Property = Il2CppScheduleOne.Property.Property;
using S1Shelf = Il2CppScheduleOne.ObjectScripts.PlaceableStorageEntity;
using S1Station = Il2CppScheduleOne.ObjectScripts.MixingStation;
using S1Storage = Il2CppScheduleOne.Storage.StorageEntity;
using S1Vehicles = Il2CppScheduleOne.Vehicles.VehicleManager;

namespace FridgeSchedule1
{
    internal static class IngredientSources
    {
        // A vehicle counts as "near the station" within this many metres of it (a car in the driveway).
        private const float NearbyMetres = 30f;
        private static bool _warned;      // storage warning already logged this run
        private static int _lastCount = -1;
        private static string _lastWhat = "";

        /// <summary>Item slots to look in, the player's own first, in the places that are true. Nothing
        /// true means the inventory; a co-op guest only ever gets the inventory.</summary>
        public static List<S1ItemSlot> Slots(bool inventory, bool nearby, bool owned, S1Station station)
        {
            var list = new List<S1ItemSlot>();
            if (Shared.Role == "client" || (!nearby && !owned))
                inventory = true;
            if (inventory)
                AddInventory(list);
            if (Shared.Role != "client" && (nearby || owned))
            {
                try
                {
                    var seen = new HashSet<IntPtr>();       // shelves reached both ways, listed once
                    if (owned)
                    {
                        var props = S1Property.OwnedProperties;
                        for (int i = 0; props != null && i < props.Count; i++)
                            if (props[i] != null)
                                AddProperty(list, seen, props[i]);
                        AddVehicles(list, seen, null);
                    }
                    if (nearby)
                    {
                        var here = station != null ? station.ParentProperty : null;
                        if (here != null)
                            AddProperty(list, seen, here);
                        AddVehicles(list, seen, station);
                    }
                }
                catch (Exception ex)
                {
                    // a game update moved storage: the player's inventory still works. Logged once per run.
                    if (!_warned)
                        MelonLoader.MelonLogger.Warning("[FridgeSchedule1] can't read storage for the ingredient vote: " + ex.Message);
                    _warned = true;
                }
            }
            var what = $"{(inventory ? "inventory " : "")}{(nearby ? "nearby " : "")}{(owned ? "owned" : "")}".Trim();
            if (list.Count != _lastCount || what != _lastWhat)
            {
                // one line when the result changes, so a test shows whether storage was found
                _lastCount = list.Count;
                _lastWhat = what;
                MelonLoader.MelonLogger.Msg($"[FridgeSchedule1] ingredient search ({what}): {list.Count} slots");
            }
            return list;
        }

        private static void AddInventory(List<S1ItemSlot> list)
        {
            try
            {
                var mine = Il2CppScheduleOne.DevUtilities.PlayerSingleton<S1Inventory>.Instance?.GetAllInventorySlots();
                for (int i = 0; mine != null && i < mine.Count; i++)
                    if (mine[i] != null)
                        list.Add(mine[i]);
            }
            catch { /* no inventory yet */ }
        }

        // Every shelf / rack / safe placed in the property (not employee beds).
        private static void AddProperty(List<S1ItemSlot> list, HashSet<IntPtr> seen, S1Property prop)
        {
            var items = prop.BuildableItems;
            for (int i = 0; items != null && i < items.Count; i++)
            {
                var shelf = items[i]?.TryCast<S1Shelf>();
                if (shelf == null || items[i].TryCast<S1Bed>() != null)
                    continue;
                AddStorage(list, seen, shelf.StorageEntity);
            }
        }

        // Player-owned vehicles' trunks; only those near <paramref name="near"/> when it's given.
        private static void AddVehicles(List<S1ItemSlot> list, HashSet<IntPtr> seen, S1Station near)
        {
            var cars = Il2CppScheduleOne.DevUtilities.NetworkSingleton<S1Vehicles>.Instance?.PlayerOwnedVehicles;
            for (int i = 0; cars != null && i < cars.Count; i++)
            {
                var car = cars[i];
                if (car == null)
                    continue;
                if (near != null && Vector3.Distance(near.transform.position, car.transform.position) > NearbyMetres)
                    continue;
                AddStorage(list, seen, car.Storage);
            }
        }

        private static void AddStorage(List<S1ItemSlot> list, HashSet<IntPtr> seen, S1Storage storage)
        {
            if (storage == null || !seen.Add(storage.Pointer))
                return;
            var slots = storage.ItemSlots;
            for (int i = 0; slots != null && i < slots.Count; i++)
                if (slots[i] != null)
                    list.Add(slots[i]);
        }
    }
}
