// "When will this chatter's customer turn up?": a customer's state in words, the order nudge,
// and the Find marker. Main thread only (game objects).
//
// Callers:
//   CustomerWatcher.Refresh -> Describe() every second for every customer (GET /customers "status"
//     and "status_text"; plugin.py shows status_text on the Schedule I page, in the phone app's
//     list via the board, and in !customer replies).
//   Core.HandleRequest -> Nudge() for POST /nudge (plugin.py: setting nudge_new, host only), and
//     Mark() for POST /find (page / phone app Find button).
//   ChatApp -> Mark() and Distance() for its Find button and distance line.
// Status codes ("locked", "deal", "offer", "dealer", "waiting") are matched in plugin.py and the
// mock (mock_server.py); keep them in sync.

using System;
using MelonLoader;
using S1API.Map;
using UnityEngine;
using S1Customer = Il2CppScheduleOne.Economy.Customer;
using S1NPC = Il2CppScheduleOne.NPCs.NPC;
using S1Player = Il2CppScheduleOne.PlayerScripts.Player;
using S1Time = Il2CppScheduleOne.GameTime.TimeManager;

namespace FridgeSchedule1
{
    internal static class CustomerStatus
    {
        private const string FindMarkerId = "fridge-schedule1:find";   // one marker at a time
        private static readonly string[] DayNames =
            { "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday" };

        /// <summary>(code, words) for one customer, e.g. ("deal", "deal set for 16:30-18:00 at the Docks").</summary>
        public static (string code, string text) Describe(S1Customer c, S1NPC npc, bool unlocked)
        {
            var area = Area(npc);
            if (!unlocked)
                return ("locked", "not met yet: walk up and offer a sample" + (area.Length > 0 ? $" (lives in {area})" : ""));
            var contract = c.CurrentContract;
            if (contract != null)
            {
                var where = contract.DeliveryLocation != null ? contract.DeliveryLocation.LocationName : "the meeting spot";
                var w = contract.DeliveryWindow;
                return ("deal", w != null
                    ? $"deal set for {Clock(w.WindowStartTime)}-{Clock(w.WindowEndTime)} at {where}"
                    : $"deal set at {where}");
            }
            if (c.OfferedContractInfo != null)
                return ("offer", "texted you an order, waiting for your reply");
            if (c.AssignedDealer != null)
                return ("dealer", "buys from your dealer " + c.AssignedDealer.FirstName);
            return ("waiting", NextOrder(c) + (area.Length > 0 ? $" (lives in {area})" : ""));
        }

        /// <summary>Make a met customer text an order now (the game's own Customer.ForceDealOffer) unless
        /// the game's rules say no. "" when done, else why not (logged; Core doesn't tell chat).</summary>
        public static string Nudge(S1Customer c, S1NPC npc)
        {
            try
            {
                if (c == null || npc == null)
                    return "customer not in this save";
                if (npc.RelationData == null || !npc.RelationData.Unlocked)
                    return "not met yet";
                if (c.CurrentContract != null)
                    return "already has a deal set";
                if (c.OfferedContractInfo != null)
                    return "already texted an order";
                if (c.AssignedDealer != null)
                    return "buys from a dealer";
                if (c.IsAwaitingDelivery)
                    return "waiting for a delivery";
                if (!npc.IsConscious)
                    return "is knocked out";
                var me = S1Player.Local;
                if (me == null || me.IsArrested || me.IsUnconscious)
                    return "you can't take a deal right now";
                if (c.TimeSinceLastDealCompleted < S1Customer.DEAL_COOLDOWN)   // game minutes
                    return "just had a deal";
                c.ForceDealOffer();
                return "";
            }
            catch (Exception ex)
            {
                MelonLogger.Warning("[FridgeSchedule1] order nudge failed: " + ex.Message);
                return "the game refused";
            }
        }

        // ---------------------------------------------------------------- Find marker
        // One marker at a time on this player's phone map (S1API MapPOI; this PC only, never saved).
        // It stays until Stop (ChatApp), until the player is within ArriveMetres of the customer, or
        // after FindMinutes real minutes (MelonPreferences "FindMinutes", set by Core.OnInitializeMelon).
        // TickFind (Core.OnUpdate, every second) moves it to where the customer is now; a marker bound to
        // the NPC's transform dropped off the map too soon (Sen, 2026-11-02).

        private const float ArriveMetres = 5f;
        /// <summary>How long a Find marker stays, in real minutes (MelonPreferences "FindMinutes", default 10).</summary>
        public static float FindMinutes = 10f;
        private static MapPOI _marker;
        private static S1NPC _findNpc;
        private static float _findUntil;
        /// <summary>"zackfan99 (Kyle Cooley)" while a marker is out, else null (ChatApp's Finding bar).</summary>
        public static string FindingLabel { get; private set; }
        /// <summary>Goes up whenever a marker starts or stops, so ChatApp redraws its Finding bar.</summary>
        public static int FindVersion { get; private set; }

        /// <summary>Put the Find marker on this customer (replaces the previous one) and open it on the map
        /// when the phone's map is ready. False when the customer isn't in this save.</summary>
        public static bool Mark(S1NPC npc, string label)
        {
            try
            {
                StopFinding(null);
                if (npc == null)
                    return false;
                _marker = new MapPOIBuilder(FindMarkerId)
                    .WithLabel(label)
                    .WithPosition(npc.transform.position)
                    .WithTextVisibility(MapPOITextVisibility.Always)
                    .Build();
                _findNpc = npc;
                _findUntil = Time.realtimeSinceStartup + Mathf.Max(1f, FindMinutes) * 60f;
                FindingLabel = label;
                FindVersion++;
                if (_marker.IsUIReady)
                    _marker.Focus();
                return true;
            }
            catch (Exception ex)
            {
                MelonLogger.Warning("[FridgeSchedule1] map marker failed: " + ex.Message);
                return false;
            }
        }

        /// <summary>Take the Find marker away; with a reason ("stopped", "found", "time's up") the feed says so.</summary>
        public static void StopFinding(string reason)
        {
            if (FindingLabel != null && reason != null)
                Shared.AddFeed(reason == "found" ? $"You found {FindingLabel}" : $"Stopped finding {FindingLabel} ({reason})");
            try { MapPOIManager.Remove(FindMarkerId); } catch { /* already gone */ }
            _marker = null;
            _findNpc = null;
            if (FindingLabel != null)
            {
                FindingLabel = null;
                FindVersion++;
            }
        }

        /// <summary>Every second (Core.OnUpdate): follow the customer, end on arrival or after FindMinutes.</summary>
        public static void TickFind()
        {
            if (FindingLabel == null)
                return;
            try
            {
                var me = S1Player.Local;
                if (_findNpc == null || _marker == null)
                    StopFinding("they left the game");
                else if (Time.realtimeSinceStartup > _findUntil)
                    StopFinding("time's up");
                else if (me != null && Vector3.Distance(me.transform.position, _findNpc.transform.position) <= ArriveMetres)
                    StopFinding("found");
                else
                    _marker.SetPosition(_findNpc.transform.position);
            }
            catch
            {
                StopFinding(null);
            }
        }

        /// <summary>"230 m north-east" from this player to the NPC, or "" (phone app list).</summary>
        public static string Distance(S1NPC npc)
        {
            var me = S1Player.Local;
            if (npc == null || me == null)
                return "";
            var d = npc.transform.position - me.transform.position;
            d.y = 0;
            string[] dirs = { "north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west" };
            var angle = (Mathf.Atan2(d.x, d.z) * Mathf.Rad2Deg + 360f + 22.5f) % 360f;
            return $"{Mathf.RoundToInt(d.magnitude)} m {dirs[(int)(angle / 45f)]}";
        }

        // "Westville" from the NPC's home region, or "".
        private static string Area(S1NPC npc)
        {
            try { return npc != null ? npc.Region.ToString() : ""; }
            catch { return ""; }
        }

        // "next order expected tomorrow around 18:00" from the customer's order days and order time
        // (CustomerData.OrderTime, the game's cached order days). Only "expected": the game still
        // decides on the day whether they really order (relationship, addiction, cooldowns).
        private static string NextOrder(S1Customer c)
        {
            try
            {
                var data = c.CustomerData;
                var time = S1Time.Instance;
                if (data == null || time == null)
                    return "orders now and then";
                int orderAt = data.OrderTime;                         // HHMM
                int today = (int)time.CurrentDay;                     // 0 = Monday
                int now = Minutes(time.CurrentTime);
                var days = c._cachedOrderDays;
                for (int k = 0; k < 8; k++)
                {
                    int d = (today + k) % 7;
                    bool orders = days != null && days.Count > 0
                        ? days.Contains((Il2CppScheduleOne.GameTime.EDay)d)
                        : d == (int)data.PreferredOrderDay;
                    if (!orders || (k == 0 && Minutes(orderAt) <= now))
                        continue;
                    int ahead = k * 1440 + Minutes(orderAt) - now;
                    var when = k == 0 ? "today" : k == 1 ? "tomorrow" : "on " + DayNames[d];
                    var hours = ahead < 90 ? "in under 2 in-game hours" : $"in about {Mathf.RoundToInt(ahead / 60f)} in-game hours";
                    return $"next order expected {when} around {Clock(orderAt)} ({hours})";
                }
                return "orders now and then";
            }
            catch
            {
                return "orders now and then";
            }
        }

        private static int Minutes(int hhmm) => hhmm / 100 * 60 + hhmm % 100;
        private static string Clock(int hhmm) => $"{hhmm / 100:00}:{hhmm % 100:00}";
    }
}
