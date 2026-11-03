// Things chat leaves for the streamer in the game's dead drops, and supplier favours:
//
//   POST /drop     {"id", "by", "note", "cash", "label"}  a donation as in-game cash (plugins/schedule1/
//                  drops.py): the cash goes into an empty dead drop near the streamer, the drop gets a map
//                  marker ("Cash drop from zackfan99") and a pop-up shows the donor's note.
//                  Answer: event "drop_result" {"drop", "ok", "msg", "where"}.
//   POST /supplier {"id", "action": "pay", "supplier", "by", "amount"}  !tab (suppliers.py): the
//                  supplier's debt goes down by "amount" in-game $ (never below 0).
//                  {"action": "deliver", "qty"}  !supply: "qty" of one of the supplier's goods (what they
//                  sell on the phone, Supplier.Shop.Listings) goes into a dead drop with a marker.
//                  Answer: event "supplier_result" {"req", "ok", "msg", "paid", "debt", "where", "what"}.
//   Either kind of drop, once emptied, sends "drop_taken" {"drop": the same id} and loses its marker.
//
// Callers: Core.OnUpdate calls Tick() every frame (one queued job) and Watch() every second;
// Core.OnSceneWasInitialized calls Clear(). BridgeServer.Crew.cs queues the jobs (CrewShared.AddDrop)
// and refuses them on a co-op client: drops and debts belong to the host's world.
//
// The cash and goods are real game items, so they stay in the drop (and in the save) like anything
// the player puts there. The note, the marker and the chatter's name are never saved: notes are a
// pop-up (Shared.AddNotice), markers are S1API map markers that go with the scene.

using System;
using System.Collections.Generic;
using System.Reflection;
using MelonLoader;
using S1API.Map;
using UnityEngine;
using S1DeadDrop = Il2CppScheduleOne.Economy.DeadDrop;
using S1Player = Il2CppScheduleOne.PlayerScripts.Player;
using S1Supplier = Il2CppScheduleOne.Economy.Supplier;
using S1CashInstance = Il2CppScheduleOne.ItemFramework.CashInstance;

namespace FridgeSchedule1
{
    internal sealed class Drops
    {
        private const int NearestDrops = 5;          // a drop is picked at random from the 5 empty ones nearest the streamer
        private const string MarkerPrefix = "fridge-schedule1:drop:";
        private const float MarkerMinutes = 60f;     // real minutes a marker stays when nobody empties the drop

        private readonly MelonLogger.Instance _log;
        // Drops waiting to be emptied: Core's id -> (the drop, marker id, real time it gives up)
        private readonly Dictionary<long, (S1DeadDrop drop, string marker, float until)> _open =
            new Dictionary<long, (S1DeadDrop, string, float)>();

        public Drops(MelonLogger.Instance log)
        {
            _log = log;
        }

        /// <summary>New scene: the drops' objects and markers are gone.</summary>
        public void Clear()
        {
            foreach (var o in _open.Values)
                RemoveMarker(o.marker);
            _open.Clear();
        }

        /// <summary>Every frame: run one job Core queued (POST /drop, POST /supplier).</summary>
        public void Tick(bool inWorld)
        {
            var r = CrewShared.TakeDrop();
            if (r == null)
                return;
            try
            {
                if (r.kind == "cash")
                    CashDrop(r, inWorld);
                else
                    SupplierJob(r, inWorld);
            }
            catch (Exception ex)
            {
                _log.Warning($"{r.kind} job failed: {ex.Message}");
                Answer(r, false, "the game refused (" + ex.GetType().Name + ")");
            }
        }

        /// <summary>Every second: drops that were emptied ("drop_taken") or forgotten (marker removed).</summary>
        public void Watch()
        {
            if (_open.Count == 0)
                return;
            var now = Time.realtimeSinceStartup;
            foreach (var id in new List<long>(_open.Keys))
            {
                var (drop, marker, until) = _open[id];
                bool taken;
                try
                {
                    taken = drop == null || drop.Storage == null || drop.Storage.ItemCount == 0;
                }
                catch
                {
                    taken = true;
                }
                if (!taken && now < until)
                    continue;
                RemoveMarker(marker);
                _open.Remove(id);
                if (taken)
                {
                    Shared.AddEvent("drop_taken", new Dictionary<string, object> { ["drop"] = id });
                    Shared.AddFeed("You emptied a chat drop");
                }
            }
        }

        // ---- cash drops (drops.py)

        private void CashDrop(DropRequest r, bool inWorld)
        {
            if (!inWorld)
            {
                Answer(r, false, "no save is loaded");
                return;
            }
            var drop = PickDrop();
            if (drop == null)
            {
                Answer(r, false, "every dead drop near the streamer is full");
                return;
            }
            var cash = Il2CppScheduleOne.Registry.GetItem("cash").GetDefaultInstance(1).TryCast<S1CashInstance>();
            if (cash == null)
            {
                Answer(r, false, "the game has no cash item");
                return;
            }
            cash.SetBalance((float)r.cash);
            if (!drop.Storage.CanItemFit(cash, 1))
            {
                Answer(r, false, "the dead drop is full");
                return;
            }
            drop.Storage.InsertItem(cash, true);
            var where = DropName(drop);
            var label = $"{(string.IsNullOrEmpty(r.label) ? "Cash drop" : r.label)} from {r.by}";
            Open(r.id, drop, label);
            Shared.AddNotice(new Notice
            {
                title = $"${r.cash:0} from {r.by}",
                text = (string.IsNullOrEmpty(r.note) ? "Left you some cash" : $"\"{r.note}\"") + $" ({where})",
                kind = "system",
            });
            Answer(r, true, "", where: where);
        }

        // ---- supplier favours (suppliers.py)

        private void SupplierJob(DropRequest r, bool inWorld)
        {
            var s = inWorld ? Crew.FindSupplier(r.supplier) : null;
            if (s == null)
            {
                Answer(r, false, inWorld ? "that supplier isn't in this save" : "no save is loaded");
                return;
            }
            if (s.RelationData == null || !s.RelationData.Unlocked)
            {
                Answer(r, false, "the streamer hasn't met them yet");
                return;
            }
            var (first, _) = NpcNames.Get(s);
            if (r.kind == "pay")
            {
                float debt = s.Debt;
                float pay = Mathf.Min((float)r.amount, debt);
                if (pay <= 0.005f)
                {
                    Answer(r, false, "nothing is owed");
                    return;
                }
                if (!ChangeDebt(s, -pay))
                {
                    Answer(r, false, "this game version won't let the mod change debts");
                    return;
                }
                Shared.AddNotice(new Notice
                    { title = first, text = $"{r.by} paid ${pay:0} of your tab. You owe ${Math.Max(0f, debt - pay):0}.", kind = "system" });
                Answer(r, true, "", paid: pay, debt: Math.Max(0f, debt - pay));
                return;
            }
            if (r.kind != "deliver")
            {
                Answer(r, false, "action must be pay or deliver");
                return;
            }
            var listing = PickListing(s);
            if (listing == null)
            {
                Answer(r, false, $"{first} has nothing to deliver right now");
                return;
            }
            int qty = Math.Max(1, r.qty);
            var item = listing.Item.GetDefaultInstance(qty);
            var drop = PickDrop();
            if (drop == null || !drop.Storage.CanItemFit(item, qty))
            {
                Answer(r, false, "every dead drop near the streamer is full");
                return;
            }
            drop.Storage.InsertItem(item, true);
            var where = DropName(drop);
            var what = $"{qty}x {listing.Item.Name}";
            Open(r.id, drop, $"{first}: delivery from {r.by}");
            Shared.AddNotice(new Notice { title = first, text = $"{r.by} sent you {what}. It's at {where}.", kind = "system" });
            Answer(r, true, "", where: where, what: what);
        }

        // One of the goods the supplier sells on the phone (Supplier.Shop.Listings), at random, preferring
        // ones the game would deliver and has in stock; null when the shop lists nothing.
        private static Il2CppScheduleOne.UI.Shop.ShopListing PickListing(S1Supplier s)
        {
            var all = s.Shop != null ? s.Shop.Listings : null;
            if (all == null || all.Count == 0)
                return null;
            var good = new List<Il2CppScheduleOne.UI.Shop.ShopListing>();
            for (int i = 0; i < all.Count; i++)
                if (all[i] != null && all[i].Item != null && all[i].CanBeDelivered && all[i].IsInStock)
                    good.Add(all[i]);
            if (good.Count == 0)
                for (int i = 0; i < all.Count; i++)
                    if (all[i] != null && all[i].Item != null)
                        good.Add(all[i]);
            return good.Count == 0 ? null : good[UnityEngine.Random.Range(0, good.Count)];
        }

        // The game's ChangeDebt is private and networked; Il2CppInterop may or may not show it as public,
        // so it is found by reflection. Fallback: set the synced debt value directly (host only anyway).
        private static bool ChangeDebt(S1Supplier s, float change)
        {
            const BindingFlags any = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
            try
            {
                var m = s.GetType().GetMethod("ChangeDebt", any, null, new[] { typeof(float) }, null);
                if (m != null)
                {
                    m.Invoke(s, new object[] { change });
                    return true;
                }
                var p = s.GetType().GetProperty("SyncAccessor_debt", any);
                if (p != null && p.CanWrite)
                {
                    p.SetValue(s, Math.Max(0f, s.Debt + change));
                    return true;
                }
            }
            catch { /* reported as not possible */ }
            return false;
        }

        // ---- helpers

        // An empty dead drop, at random from the few nearest the streamer (so nobody is sent across the
        // map); null when they're all in use.
        private static S1DeadDrop PickDrop()
        {
            var all = S1DeadDrop.DeadDrops;
            if (all == null)
                return null;
            var me = S1Player.Local;
            var from = me != null ? me.transform.position : Vector3.zero;
            var empty = new List<(float dist, S1DeadDrop drop)>();
            for (int i = 0; i < all.Count; i++)
            {
                var d = all[i];
                if (d != null && d.Storage != null && d.Storage.ItemCount == 0)
                    empty.Add((Vector3.Distance(from, d.transform.position), d));
            }
            if (empty.Count == 0)
                return null;
            empty.Sort((a, b) => a.dist.CompareTo(b.dist));
            return empty[UnityEngine.Random.Range(0, Math.Min(NearestDrops, empty.Count))].drop;
        }

        private static string DropName(S1DeadDrop d) =>
            string.IsNullOrEmpty(d.DeadDropName) ? "a dead drop" : d.DeadDropName;

        // Map marker on the drop and watch it until it's emptied.
        private void Open(long id, S1DeadDrop drop, string label)
        {
            var marker = MarkerPrefix + id;
            try
            {
                new MapPOIBuilder(marker)
                    .WithLabel(label)
                    .WithPosition(drop.transform.position)
                    .WithTextVisibility(MapPOITextVisibility.Always)
                    .Build();
            }
            catch (Exception ex)
            {
                _log.Warning("drop marker failed: " + ex.Message);
            }
            _open[id] = (drop, marker, Time.realtimeSinceStartup + MarkerMinutes * 60f);
            Shared.AddFeed($"{label} at {DropName(drop)}");
        }

        private static void RemoveMarker(string marker)
        {
            try { MapPOIManager.Remove(marker); } catch { /* already gone with the scene */ }
        }

        // "drop_result" for a cash drop, "supplier_result" for a supplier job; field names as drops.py /
        // suppliers.py read them.
        private static void Answer(DropRequest r, bool ok, string msg, string where = "", string what = "",
                                   float paid = 0f, float debt = 0f)
        {
            if (r.kind == "cash")
                Shared.AddEvent("drop_result", new Dictionary<string, object>
                    { ["drop"] = r.id, ["ok"] = ok, ["msg"] = msg, ["where"] = where });
            else
                Shared.AddEvent("supplier_result", new Dictionary<string, object>
                {
                    ["req"] = r.id, ["ok"] = ok, ["msg"] = msg, ["paid"] = paid, ["debt"] = debt,
                    ["where"] = where, ["what"] = what,
                });
        }
    }
}
