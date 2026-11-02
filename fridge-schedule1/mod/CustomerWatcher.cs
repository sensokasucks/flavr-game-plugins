// Finds Schedule I's customers, puts chatter names on them and listens for their orders and deals.
// Main thread only: Core.OnUpdate calls ApplyNames (when Core sent names) and Refresh (every second);
// Core.OnSceneWasInitialized calls OnWorldLoaded / OnWorldUnloaded.
//
// Game types used (IL2CPP names; the same ones S1API uses, github.com/ifBars/S1API):
//   Il2CppScheduleOne.Economy.Customer   UnlockedCustomers / LockedCustomers (static lists),
//                                        onContractAssigned (UnityEvent<Contract>), onDealCompleted, onUnlocked
//   Il2CppScheduleOne.NPCs.NPC           ID, RelationData.Unlocked (same GameObject as its Customer)
//   Il2CppScheduleOne.Quests.Contract    Payment, ProductList.entries[i].ProductID / Quantity
//   Il2CppScheduleOne.Registry           GetItem(id).Name for a product's display name
// Names are changed through S1API's NPC.FirstName / LastName, which knows where the current game
// version keeps them. A game update that renames any of these shows up as warnings in
// MelonLoader's log, not a crash: every game call here sits in a try/catch.
//
// Renaming is local: only this PC sees the chatter names (other co-op players see the normal
// names), and nothing is written to the save. Each customer's own name is remembered the first
// time it is seen in this run of the game and put back when Core stops asking for a chatter name.

using System;
using System.Collections.Generic;
using Il2CppInterop.Runtime;
using MelonLoader;
using UnityEngine.Events;
using S1Customer = Il2CppScheduleOne.Economy.Customer;
using S1NPC = Il2CppScheduleOne.NPCs.NPC;
using S1Contract = Il2CppScheduleOne.Quests.Contract;

namespace FridgeSchedule1
{
    internal sealed class CustomerWatcher
    {
        private readonly MelonLogger.Instance _log;

        private bool _loaded;
        // NPC id -> the customer's own (first, last). Kept for the whole run of the game, because
        // S1API may write names into data that survives loading another save; an original read
        // after our own rename would be the chatter's name.
        private readonly Dictionary<string, (string first, string last)> _originals = new Dictionary<string, (string, string)>();
        // Customers whose game events we already listen to (by Unity instance id; new objects after a reload).
        private readonly HashSet<int> _hooked = new HashSet<int>();
        // The last full set of names Core sent; re-applied to customers that appear later (another save).
        private Dictionary<string, WantedName> _wanted = new Dictionary<string, WantedName>();
        // Names this mod has put on customers right now (so Refresh knows what to undo).
        private readonly Dictionary<string, WantedName> _applied = new Dictionary<string, WantedName>();
        // Latest order per customer, so the deal event can repeat what was bought and for how much.
        // Last counts logged by Refresh (it logs only when they change).
        private int _lastCount = -1;
        private int _lastUnwrapped = -1;
        private readonly Dictionary<string, Dictionary<string, object>> _lastOrder = new Dictionary<string, Dictionary<string, object>>();

        public CustomerWatcher(MelonLogger.Instance log)
        {
            _log = log;
        }

        public void OnWorldLoaded()
        {
            _loaded = true;
            _hooked.Clear();
            _applied.Clear();     // fresh NPC objects: nothing of ours is on them yet
        }

        public void OnWorldUnloaded()
        {
            _loaded = false;
            _hooked.Clear();
            _applied.Clear();
            Shared.SetCustomers(false, new List<CustomerInfo>());
        }

        /// <summary>The names in force (npc id -> name): from this player's Core on the host, from the
        /// host on a co-op client. LobbySync (host) shares them with the other players.</summary>
        public IReadOnlyDictionary<string, WantedName> Wanted => _wanted;

        /// <summary>Core's full set of wanted names (POST /names), or on a co-op client the host's
        /// (LobbySync). Anyone not listed gets their own name back.</summary>
        public void ApplyNames(Dictionary<string, WantedName> names)
        {
            _wanted = names ?? new Dictionary<string, WantedName>();
            if (_loaded)
                Refresh();
        }

        /// <summary>Every second: hook new customers, keep names as Core wants them, publish the list.</summary>
        public void Refresh()
        {
            if (!_loaded)
                return;
            var list = new List<CustomerInfo>();
            int unwrapped = 0;
            foreach (var customer in AllCustomers())
            {
                try
                {
                    var npc = customer.GetComponent<S1NPC>();
                    if (npc == null || string.IsNullOrEmpty(npc.ID))
                        continue;
                    var id = npc.ID;
                    var wrapper = FindWrapper(id);
                    if (wrapper == null)
                    {
                        unwrapped++;
                        continue;   // S1API can't wrap this NPC yet; try again next second
                    }
                    if (!_originals.ContainsKey(id))
                        _originals[id] = (wrapper.FirstName ?? "", wrapper.LastName ?? "");
                    Hook(customer, id);
                    KeepName(wrapper, id);
                    var own = _originals[id];
                    list.Add(new CustomerInfo
                    {
                        id = id,
                        first = own.first,
                        last = own.last,
                        shown = wrapper.FullName ?? "",
                        unlocked = npc.RelationData != null && npc.RelationData.Unlocked,
                    });
                }
                catch (Exception ex)
                {
                    _log.Warning("customer skipped: " + ex.Message);
                }
            }
            Shared.SetCustomers(true, list);
            // One console line whenever the count changes, so the streamer can see the mod found everyone.
            int met = list.FindAll(c => c.unlocked).Count;
            if (list.Count != _lastCount || unwrapped != _lastUnwrapped)
            {
                _lastCount = list.Count;
                _lastUnwrapped = unwrapped;
                _log.Msg($"{list.Count} customers found ({met} met)" + (unwrapped > 0 ? $", {unwrapped} not ready yet" : ""));
            }
        }

        // Every customer in the world: met ones first, then the ones still to meet.
        private static IEnumerable<S1Customer> AllCustomers()
        {
            foreach (var group in new[] { S1Customer.UnlockedCustomers, S1Customer.LockedCustomers })
            {
                if (group == null)
                    continue;
                for (int i = 0; i < group.Count; i++)
                    if (group[i] != null)
                        yield return group[i];
            }
        }

        // S1API's wrapper for a game NPC. NPC.Get makes the wrapper for a base-game NPC on first ask;
        // NPC.All only lists wrappers something already made, which left most customers out.
        private static S1API.Entities.NPC FindWrapper(string id)
        {
            try
            {
                return S1API.Entities.NPC.Get(id);
            }
            catch
            {
                return null;
            }
        }

        // Put the chatter name on, or the customer's own name back, when it isn't what it should be.
        private void KeepName(S1API.Entities.NPC wrapper, string id)
        {
            _wanted.TryGetValue(id, out var want);
            _applied.TryGetValue(id, out var have);
            if (want != null)
            {
                if (have != null && have.first == want.first && have.last == want.last && wrapper.FirstName == want.first)
                    return;
                wrapper.FirstName = want.first ?? "";
                wrapper.LastName = want.last ?? "";
                _applied[id] = want;
                var own0 = _originals[id];
                _log.Msg($"renamed {own0.first} {own0.last} -> {$"{want.first} {want.last}".Trim()}");
            }
            else if (have != null)
            {
                var own = _originals[id];
                wrapper.FirstName = own.first;
                wrapper.LastName = own.last;
                _applied.Remove(id);
                _log.Msg($"{own.first} {own.last} has their own name back");
            }
        }

        // Listen to one customer's game events (once per customer object).
        private void Hook(S1Customer customer, string id)
        {
            if (!_hooked.Add(customer.GetInstanceID()))
                return;
            try
            {
                // DelegateSupport wraps a C# lambda as the game's own UnityAction type.
                if (customer.onContractAssigned != null)
                    customer.onContractAssigned.AddListener(
                        DelegateSupport.ConvertDelegate<UnityAction<S1Contract>>(new Action<S1Contract>(c => OnOrder(id, c))));
                if (customer.onDealCompleted != null)
                    customer.onDealCompleted.AddListener(
                        DelegateSupport.ConvertDelegate<UnityAction>(new Action(() => OnDeal(id))));
                if (customer.onUnlocked != null)
                    customer.onUnlocked.AddListener(
                        DelegateSupport.ConvertDelegate<UnityAction>(new Action(() => OnUnlocked(id))));
            }
            catch (Exception ex)
            {
                _log.Warning($"can't listen to customer {id}: {ex.Message}");
            }
        }

        // A customer texted an order (the game gave them a contract). Event "contract".
        private void OnOrder(string id, S1Contract contract)
        {
            try
            {
                var fields = new Dictionary<string, object> { ["id"] = id, ["name"] = ShownName(id) };
                int qty = 0;
                var products = new List<string>();
                float payment = 0f;
                if (contract != null)
                {
                    payment = contract.Payment;
                    var list = contract.ProductList;
                    if (list != null && list.entries != null)
                    {
                        for (int i = 0; i < list.entries.Count; i++)
                        {
                            var e = list.entries[i];
                            qty += Math.Max(0, e.Quantity);
                            products.Add(ProductName(e.ProductID));
                        }
                    }
                }
                fields["qty"] = qty;
                fields["products"] = products;
                fields["payment"] = payment;
                _lastOrder[id] = fields;
                Shared.AddEvent("contract", fields);
                if (_applied.ContainsKey(id))   // the phone app's feed only follows chatter customers
                    Shared.AddFeed($"{fields["name"]} wants {OrderText(fields)}");
            }
            catch (Exception ex)
            {
                _log.Warning("order event failed: " + ex.Message);
            }
        }

        // The deal went through. Event "deal", with the customer's latest order details.
        private void OnDeal(string id)
        {
            var fields = _lastOrder.TryGetValue(id, out var order)
                ? new Dictionary<string, object>(order)
                : new Dictionary<string, object> { ["id"] = id, ["qty"] = 0, ["products"] = new List<string>(), ["payment"] = 0f };
            fields["name"] = ShownName(id);
            _lastOrder.Remove(id);
            Shared.AddEvent("deal", fields);
            if (_applied.ContainsKey(id))
                Shared.AddFeed($"{fields["name"]} bought {OrderText(fields)}");
        }

        // "3x OG Kush for $120" for the phone app's feed; same wording as order_text() + money() in plugin.py.
        private static string OrderText(Dictionary<string, object> fields)
        {
            var products = fields.TryGetValue("products", out var p) && p is List<string> l && l.Count > 0
                ? string.Join(", ", l.GetRange(0, Math.Min(3, l.Count)))
                : "product";
            var qty = fields.TryGetValue("qty", out var q) && q is int n ? n : 0;
            var pay = fields.TryGetValue("payment", out var m) && m is float f ? f : 0f;
            return (qty > 0 ? $"{qty}x {products}" : products) + $" for ${pay:0}";
        }

        // The streamer met a new customer. Event "unlocked"; Core may move a waiting chatter onto them.
        private void OnUnlocked(string id)
        {
            Shared.AddEvent("unlocked", new Dictionary<string, object> { ["id"] = id, ["name"] = ShownName(id) });
        }

        private string ShownName(string id)
        {
            if (_applied.TryGetValue(id, out var n))
                return $"{n.first} {n.last}".Trim();
            return _originals.TryGetValue(id, out var o) ? $"{o.first} {o.last}".Trim() : id;
        }

        // "ogkush" -> "OG Kush" via the game's item registry; the id itself when the lookup fails.
        private static string ProductName(string productId)
        {
            try
            {
                var item = Il2CppScheduleOne.Registry.GetItem(productId);
                if (item != null && !string.IsNullOrEmpty(item.Name))
                    return item.Name;
            }
            catch { /* unknown id or the registry moved; fall back to the id */ }
            return productId ?? "";
        }
    }
}
