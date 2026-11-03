// The streamer's crew for Stream Core: workers named after chatters, dealers sponsored by chatters,
// and the suppliers list for !tab / !supply.
//
//   Workers  (EmployeeManager.AllEmployees)   GET /crew "staff"; POST /crewnames "staff" puts chatter
//            names on them (plugins/schedule1/staff.py picks who); each finished job ("harvested a
//            plant") becomes event "staff_job" {"id", "job"} so chat can hear what its worker did.
//   Dealers  (Dealer.AllPlayerDealers, recruited) GET /crew "dealers"; POST /crewnames "dealers" shows the
//            sponsor in brackets as the dealer's last name (dealers.py dealer_label). Events
//            "dealer_sale" {"id", "amount", "deals"} (cash went up after finished deals, counted by DealPatch: the sponsor's
//            kickback), "dealer_robbed" {"id", "cash", "items"} and "dealer_empty" {"id"} (no product left).
//   Suppliers (every Supplier NPC)              GET /crew "suppliers" with what the streamer owes;
//            Drops.cs pays debts and makes deliveries.
//
// Callers: Core.OnUpdate calls Tick() every frame (names Core sent) and Refresh() every second;
// Core.OnSceneWasInitialized calls OnWorldLoaded / OnWorldUnloaded. Main thread only.
//
// Names are local to this PC (other co-op players see the normal names) and never saved: while the
// game saves (SaveManager.onSaveStart .. onSaveComplete) everyone has their own name back. Event and
// field names must match plugins/schedule1/staff.py, dealers.py and mock/mock_server.py.

using System;
using System.Collections.Generic;
using HarmonyLib;
using Il2CppInterop.Runtime;
using MelonLoader;
using UnityEngine.Events;
using S1Behaviour = Il2CppScheduleOne.NPCs.Behaviour.Behaviour;
using S1Dealer = Il2CppScheduleOne.Economy.Dealer;
using S1Employee = Il2CppScheduleOne.Employees.Employee;
using S1EmployeeManager = Il2CppScheduleOne.Employees.EmployeeManager;
using S1NPC = Il2CppScheduleOne.NPCs.NPC;
using S1NPCManager = Il2CppScheduleOne.NPCs.NPCManager;
using S1SaveManager = Il2CppScheduleOne.Persistence.SaveManager;
using S1Supplier = Il2CppScheduleOne.Economy.Supplier;

namespace FridgeSchedule1
{
    internal sealed class Crew
    {
        // A finished deal whose cash hasn't shown up after this many seconds is reported with $0.
        private const float SaleWaitSec = 5f;

        // Game behaviour class -> words chat sees ("Dave (zackfan99) harvested a plant"). Behaviours not
        // listed (walking, idling, talking) aren't jobs. Keep the words short: staff.py joins them.
        private static readonly Dictionary<string, string> JobWords = new Dictionary<string, string>
        {
            ["HarvestPotBehaviour"] = "harvested a plant",
            ["WaterPotBehaviour"] = "watered a plant",
            ["SowSeedInPotBehaviour"] = "planted seeds",
            ["AddSoilToGrowContainerBehaviour"] = "added soil",
            ["ApplyAdditiveToGrowContainerBehaviour"] = "added fertiliser",
            ["HarvestMushroomBedBehaviour"] = "harvested mushrooms",
            ["MistMushroomBedBehaviour"] = "misted mushrooms",
            ["ApplySpawnToMushroomBedBehaviour"] = "spawned a mushroom bed",
            ["UseSpawnStationBehaviour"] = "made mushroom spawn",
            ["StartDryingRackBehaviour"] = "hung product to dry",
            ["StopDryingRackBehaviour"] = "took dried product down",
            ["StartMixingStationBehaviour"] = "started a mix",
            ["StartChemistryStationBehaviour"] = "started a cook",
            ["StartLabOvenBehaviour"] = "started the lab oven",
            ["FinishLabOvenBehaviour"] = "finished a lab oven batch",
            ["StartCauldronBehaviour"] = "started the cauldron",
            ["BrickPressBehaviour"] = "pressed a brick",
            ["PackagingStationBehaviour"] = "packaged product",
            ["MoveItemBehaviour"] = "moved stock",
            ["PickUpTrashBehaviour"] = "picked up trash",
            ["BagTrashCanBehaviour"] = "bagged a trash can",
            ["DisposeTrashBagBehaviour"] = "took out the trash",
            ["EmptyTrashGrabberBehaviour"] = "emptied a trash grabber",
        };

        private readonly MelonLogger.Instance _log;
        private bool _loaded;
        private bool _warnedNames;                  // one warning per run when this game hides worker names

        // NPC id -> own (first, last), read the first time we see them, before any rename.
        private readonly Dictionary<string, (string first, string last)> _originals = new Dictionary<string, (string, string)>();
        // What Core wants (kept for the whole run: re-applied after loading another save) and what is on now.
        private Dictionary<string, WantedName> _wantStaff = new Dictionary<string, WantedName>();
        private Dictionary<string, WantedName> _wantDealers = new Dictionary<string, WantedName>();
        private readonly Dictionary<string, WantedName> _applied = new Dictionary<string, WantedName>();
        // Every renamable NPC seen by the last Refresh, for the save-time name swap.
        private readonly Dictionary<string, S1NPC> _byId = new Dictionary<string, S1NPC>();

        private readonly HashSet<int> _hooked = new HashSet<int>();      // workers listened to (Unity instance id)
        private bool _saveHooked;
        private bool _saving;                         // between onSaveStart and onSaveComplete: own names on

        // Dealer watch: last cash and stock seen, finished deals waiting for their cash.
        private readonly Dictionary<string, float> _dealerCash = new Dictionary<string, float>();
        private readonly Dictionary<string, int> _dealerStock = new Dictionary<string, int>();
        private readonly Dictionary<string, (int deals, float since)> _dealsWaiting = new Dictionary<string, (int, float)>();

        public Crew(MelonLogger.Instance log)
        {
            _log = log;
            Instance = this;
        }

        /// <summary>The one crew watcher (Core makes it); RobPatch reports robberies through it.</summary>
        internal static Crew Instance { get; private set; }

        public void OnWorldLoaded()
        {
            _loaded = true;
            ClearWorld();
        }

        public void OnWorldUnloaded()
        {
            _loaded = false;
            ClearWorld();
            CrewShared.SetCrew(false, null, null, null);
        }

        private void ClearWorld()
        {
            _applied.Clear();      // fresh NPC objects: nothing of ours is on them
            _byId.Clear();
            _hooked.Clear();
            _saveHooked = false;
            _saving = false;
            _dealerCash.Clear();
            _dealerStock.Clear();
            _dealsWaiting.Clear();
        }

        /// <summary>Every frame: names Core sent (POST /crewnames), applied at once.</summary>
        public void Tick()
        {
            var (staff, dealers) = CrewShared.TakeNames();
            if (staff == null && dealers == null)
                return;
            if (staff != null)
                _wantStaff = staff;
            if (dealers != null)
                _wantDealers = dealers;
            if (_loaded)
                Refresh();
        }

        /// <summary>Every second: list the crew for GET /crew, keep names as Core wants them, hook new
        /// workers / dealers, and report dealer sales and empty stock.</summary>
        public void Refresh()
        {
            if (!_loaded)
                return;
            HookSaves();
            var staff = new List<CrewMember>();
            var dealers = new List<CrewMember>();
            var suppliers = new List<CrewMember>();
            try
            {
                var all = S1EmployeeManager.Instance?.AllEmployees;
                for (int i = 0; all != null && i < all.Count; i++)
                {
                    var e = all[i];
                    if (e == null || e.Fired || string.IsNullOrEmpty(e.ID))
                        continue;
                    var own = Own(e);
                    KeepName(e, _wantStaff);
                    HookJobs(e);
                    staff.Add(new CrewMember
                    {
                        id = e.ID, first = own.first, last = own.last, shown = Shown(e),
                        type = e.EmployeeType.ToString().ToLowerInvariant(),
                        property = e.AssignedProperty != null ? e.AssignedProperty.PropertyName ?? "" : "",
                    });
                }
            }
            catch (Exception ex)
            {
                _log.Warning("workers skipped: " + ex.Message);
            }
            try
            {
                var all = S1Dealer.AllPlayerDealers;
                for (int i = 0; all != null && i < all.Count; i++)
                {
                    var d = all[i];
                    if (d == null || !d.IsRecruited || string.IsNullOrEmpty(d.ID))
                        continue;
                    var own = Own(d);
                    KeepName(d, _wantDealers);
                    WatchDealer(d);
                    dealers.Add(new CrewMember
                    {
                        id = d.ID, first = own.first, last = own.last, shown = Shown(d),
                        cash = d.Cash, stock = d.GetPackagedProductAmount(),
                        customers = d.AssignedCustomers != null ? d.AssignedCustomers.Count : 0,
                    });
                }
            }
            catch (Exception ex)
            {
                _log.Warning("dealers skipped: " + ex.Message);
            }
            try
            {
                var all = S1NPCManager.NPCRegistry;
                for (int i = 0; all != null && i < all.Count; i++)
                {
                    var s = all[i]?.TryCast<S1Supplier>();
                    if (s == null || string.IsNullOrEmpty(s.ID))
                        continue;
                    var own = Own(s);
                    suppliers.Add(new CrewMember
                    {
                        id = s.ID, first = own.first, last = own.last, shown = Shown(s),
                        unlocked = s.RelationData != null && s.RelationData.Unlocked,
                        debt = s.Debt,
                    });
                }
            }
            catch (Exception ex)
            {
                _log.Warning("suppliers skipped: " + ex.Message);
            }
            CrewShared.SetCrew(true, staff, dealers, suppliers);
        }

        /// <summary>A supplier by NPC id (Drops.cs); null when not in this save.</summary>
        public static S1Supplier FindSupplier(string id)
        {
            var all = S1NPCManager.NPCRegistry;
            for (int i = 0; all != null && i < all.Count; i++)
            {
                var s = all[i]?.TryCast<S1Supplier>();
                if (s != null && s.ID == id)
                    return s;
            }
            return null;
        }

        // ---- names

        private (string first, string last) Own(S1NPC npc)
        {
            if (!_originals.TryGetValue(npc.ID, out var own))
                _originals[npc.ID] = own = NpcNames.Get(npc);
            _byId[npc.ID] = npc;
            return own;
        }

        private string Shown(S1NPC npc)
        {
            var (f, l) = NpcNames.Get(npc);
            return $"{f} {l}".Trim();
        }

        // Put Core's name on, or the own name back, when it isn't what it should be. Not while saving.
        private void KeepName(S1NPC npc, Dictionary<string, WantedName> wanted)
        {
            if (_saving)
                return;
            var id = npc.ID;
            wanted.TryGetValue(id, out var want);
            _applied.TryGetValue(id, out var have);
            var own = _originals[id];
            if (want != null)
            {
                if (have != null && have.first == want.first && have.last == want.last)
                    return;
                if (!NpcNames.Set(npc, want.first, want.last))
                {
                    if (!_warnedNames)
                        _log.Warning("this game version keeps worker names where the mod can't change them; staff names are off");
                    _warnedNames = true;
                    return;
                }
                _applied[id] = want;
                RefreshLabels(npc);
                _log.Msg($"crew: {own.first} {own.last} -> {$"{want.first} {want.last}".Trim()}");
            }
            else if (have != null)
            {
                NpcNames.Set(npc, own.first, own.last);
                _applied.Remove(id);
                RefreshLabels(npc);
                _log.Msg($"crew: {own.first} {own.last} has their own name back");
            }
        }

        // A worker's name also shows on their bed / locker (EmployeeHome.NameLabel), drawn when the bed is
        // assigned; assigning the same worker again redraws it with the new name. Dealers have no bed.
        private void RefreshLabels(S1NPC npc)
        {
            var emp = npc?.TryCast<S1Employee>();
            if (emp == null)
                return;
            try
            {
                var homes = UnityEngine.Object.FindObjectsOfType<Il2CppScheduleOne.Employees.EmployeeHome>();
                for (int i = 0; homes != null && i < homes.Length; i++)
                    if (homes[i] != null && homes[i].AssignedEmployee != null && homes[i].AssignedEmployee.ID == emp.ID)
                        homes[i].SetAssignedEmployee(emp);
            }
            catch (Exception ex)
            {
                _log.Warning("worker's bed label not redrawn: " + ex.Message);
            }
        }

        // Own names on for the whole save, chatter names back afterwards (the save file never sees them).
        private void HookSaves()
        {
            if (_saveHooked)
                return;
            try
            {
                var sm = S1SaveManager.Instance;
                if (sm == null)
                    return;
                sm.onSaveStart?.AddListener(DelegateSupport.ConvertDelegate<UnityAction>(new Action(OnSaveStart)));
                sm.onSaveComplete?.AddListener(DelegateSupport.ConvertDelegate<UnityAction>(new Action(OnSaveComplete)));
                _saveHooked = true;
            }
            catch (Exception ex)
            {
                _saveHooked = true;     // don't retry every second
                _log.Warning("can't follow game saves, crew names stay off the save only by luck: " + ex.Message);
            }
        }

        private void OnSaveStart()
        {
            _saving = true;
            foreach (var id in new List<string>(_applied.Keys))
                if (_byId.TryGetValue(id, out var npc) && npc != null && _originals.TryGetValue(id, out var own))
                    NpcNames.Set(npc, own.first, own.last);
            _applied.Clear();           // the next Refresh after the save puts chatter names back
        }

        private void OnSaveComplete()
        {
            _saving = false;
        }

        // ---- worker jobs

        // Listen to the end of every job behaviour on one worker (once per worker object).
        private void HookJobs(S1Employee e)
        {
            if (!_hooked.Add(e.GetInstanceID()))
                return;
            var id = e.ID;
            try
            {
                var behaviours = e.GetComponentsInChildren<S1Behaviour>(true);
                for (int i = 0; i < behaviours.Length; i++)
                {
                    var b = behaviours[i];
                    if (b == null || b.onEnd == null || !JobWords.TryGetValue(b.GetIl2CppType().Name, out var job))
                        continue;
                    b.onEnd.AddListener(DelegateSupport.ConvertDelegate<UnityAction>(new Action(() =>
                        Shared.AddEvent("staff_job", new Dictionary<string, object> { ["id"] = id, ["job"] = job }))));
                }
            }
            catch (Exception ex)
            {
                _log.Warning($"can't follow worker {id}'s jobs: {ex.Message}");
            }
        }

        // ---- dealers

        // DealPatch (Harmony, on Dealer.CompletedDeal): one more finished deal waiting for its cash.
        // A patch instead of a listener because the game's deal event changed from a UnityEvent
        // (onCompleteDeal) to a plain Action (OnCompleteDeal) between versions; the method stayed.
        internal void DealDone(S1Dealer d)
        {
            if (d == null || !d.IsRecruited || string.IsNullOrEmpty(d.ID))
                return;
            _dealsWaiting.TryGetValue(d.ID, out var w);
            _dealsWaiting[d.ID] = (w.deals + 1, w.deals == 0 ? UnityEngine.Time.realtimeSinceStartup : w.since);
        }

        // Cash up after finished deals = a sale (the sponsor's kickback in dealers.py). Cash down = the
        // streamer collected (or a robbery, reported by RobPatch). Stock reaching 0 = "dealer_empty".
        private void WatchDealer(S1Dealer d)
        {
            var id = d.ID;
            float cash = d.Cash;
            int stock = d.GetPackagedProductAmount();
            bool seen = _dealerCash.TryGetValue(id, out var lastCash);
            _dealerStock.TryGetValue(id, out var lastStock);
            if (seen && _dealsWaiting.TryGetValue(id, out var w) && w.deals > 0)
            {
                float gained = cash - lastCash;
                if (gained > 0.01f || UnityEngine.Time.realtimeSinceStartup - w.since > SaleWaitSec)
                {
                    Shared.AddEvent("dealer_sale", new Dictionary<string, object>
                        { ["id"] = id, ["amount"] = Math.Max(0f, gained), ["deals"] = w.deals });
                    _dealsWaiting.Remove(id);
                }
                else
                {
                    cash = lastCash;     // keep the old figure until the deal's cash arrives
                }
            }
            if (seen && lastStock > 0 && stock == 0)
                Shared.AddEvent("dealer_empty", new Dictionary<string, object> { ["id"] = id });
            _dealerCash[id] = cash;
            _dealerStock[id] = stock;
        }

        // RobPatch: a robbery took cash and / or product. The baselines move so it isn't a "sale".
        internal void Robbed(S1Dealer d, float cashBefore, int itemsBefore)
        {
            try
            {
                float lost = Math.Max(0f, cashBefore - d.Cash);
                int items = Math.Max(0, itemsBefore - d.GetTotalInventoryItemCount());
                _dealerCash[d.ID] = d.Cash;
                if (lost <= 0.01f && items == 0)
                    return;      // the robbers lost the fight
                Shared.AddEvent("dealer_robbed", new Dictionary<string, object>
                    { ["id"] = d.ID, ["cash"] = lost, ["items"] = items });
                Shared.AddFeed($"{Shown(d)} was robbed");
            }
            catch (Exception ex)
            {
                _log.Warning("robbery report failed: " + ex.Message);
            }
        }
    }

    /// <summary>Harmony patch: the game calls Dealer.CompletedDeal when a dealer finishes a deal; Crew
    /// counts it and reports the sale once the deal's cash shows up (Crew.WatchDealer).</summary>
    [HarmonyPatch(typeof(S1Dealer), nameof(S1Dealer.CompletedDeal))]
    internal static class DealPatch
    {
        private static void Postfix(S1Dealer __instance)
        {
            try { Crew.Instance?.DealDone(__instance); } catch { /* never break the game's deal */ }
        }
    }

    /// <summary>Harmony patch (MelonLoader applies every [HarmonyPatch] in this DLL at start): notes a
    /// player dealer's cash and items before the game's robbery roll and tells Crew what was taken.</summary>
    [HarmonyPatch(typeof(S1Dealer), nameof(S1Dealer.TryRobDealer))]
    internal static class RobPatch
    {
        private static void Prefix(S1Dealer __instance, out (float cash, int items) __state)
        {
            __state = (0f, 0);
            try
            {
                __state = (__instance.Cash, __instance.GetTotalInventoryItemCount());
            }
            catch { /* reported as nothing taken */ }
        }

        private static void Postfix(S1Dealer __instance, (float cash, int items) __state)
        {
            if (__instance != null && __instance.IsRecruited)
                Crew.Instance?.Robbed(__instance, __state.cash, __state.items);
        }
    }
}
