// Where the ingredient vote looks for ingredients, and where auto-place takes the winner from
// (MixPicker.cs). Core's setting mixpick_take_from (plugins/schedule1/mixpick.py, sent as "take_from"):
//
//   "carried"  the player's own inventory (hotbar + pockets)                         (the default)
//   "nearby"   the player's inventory, then the shelves / racks / safes in the same property as the
//              mixing station, then the player's vehicles parked within NearbyMetres of it
//   "owned"    the player's inventory, then storage at every property the player owns, then every
//              player-owned vehicle's trunk
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

        /// <summary>Item slots to look in, the player's own first. <paramref name="takeFrom"/> is
        /// "carried", "nearby" or "owned"; anything else (or a co-op guest) means "carried".</summary>
        public static List<S1ItemSlot> Slots(string takeFrom, S1Station station)
        {
            var list = new List<S1ItemSlot>();
            try
            {
                var mine = Il2CppScheduleOne.DevUtilities.PlayerSingleton<S1Inventory>.Instance?.GetAllInventorySlots();
                for (int i = 0; mine != null && i < mine.Count; i++)
                    if (mine[i] != null)
                        list.Add(mine[i]);
            }
            catch { /* no inventory yet */ }
            if (Shared.Role == "client" || (takeFrom != "nearby" && takeFrom != "owned"))
                return list;
            try
            {
                if (takeFrom == "nearby")
                {
                    var here = station != null ? station.ParentProperty : null;
                    if (here != null)
                        AddProperty(list, here);
                }
                else
                {
                    var props = S1Property.OwnedProperties;
                    for (int i = 0; props != null && i < props.Count; i++)
                        if (props[i] != null)
                            AddProperty(list, props[i]);
                }
                AddVehicles(list, takeFrom == "nearby" ? station : null);
            }
            catch { /* a game update moved storage: the player's inventory still works */ }
            return list;
        }

        // Every shelf / rack / safe placed in the property (not employee beds).
        private static void AddProperty(List<S1ItemSlot> list, S1Property prop)
        {
            var items = prop.BuildableItems;
            for (int i = 0; items != null && i < items.Count; i++)
            {
                var shelf = items[i]?.TryCast<S1Shelf>();
                if (shelf == null || items[i].TryCast<S1Bed>() != null)
                    continue;
                AddStorage(list, shelf.StorageEntity);
            }
        }

        // Player-owned vehicles' trunks; only those near <paramref name="near"/> when it's given.
        private static void AddVehicles(List<S1ItemSlot> list, S1Station near)
        {
            var cars = Il2CppScheduleOne.DevUtilities.NetworkSingleton<S1Vehicles>.Instance?.PlayerOwnedVehicles;
            for (int i = 0; cars != null && i < cars.Count; i++)
            {
                var car = cars[i];
                if (car == null)
                    continue;
                if (near != null && Vector3.Distance(near.transform.position, car.transform.position) > NearbyMetres)
                    continue;
                AddStorage(list, car.Storage);
            }
        }

        private static void AddStorage(List<S1ItemSlot> list, S1Storage storage)
        {
            var slots = storage != null ? storage.ItemSlots : null;
            for (int i = 0; slots != null && i < slots.Count; i++)
                if (slots[i] != null)
                    list.Add(slots[i]);
        }
    }
}
