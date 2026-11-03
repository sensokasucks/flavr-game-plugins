// What the HTTP thread (BridgeServer.Crew.cs) and the game thread (Crew.cs, Drops.cs, MixPicker.cs)
// share for the "crew" features: workers named after chatters, dealer sponsors, cash drops, supplier
// favours (!tab / !supply) and chat's ingredient vote. Kept apart from Shared.cs so those features can
// change without touching the customer code. Every member takes the same lock; nothing in here
// touches Unity or game objects.
//
// JSON field names made from these classes are read by plugins/schedule1/feature.py (CrewSync),
// staff.py, dealers.py, drops.py, suppliers.py and mixpick.py in Stream Core, and imitated by
// mock/mock_server.py; keep all of them in sync.

using System.Collections.Generic;

namespace FridgeSchedule1
{
    /// <summary>One worker, recruited dealer or met supplier as Core sees it (GET /crew).</summary>
    internal sealed class CrewMember
    {
        public string id;         // game NPC id; stable across saves
        public string first;      // their own first name (never a chatter name)
        public string last;       // their own last name
        public string shown;      // the name the game shows right now (a chatter's while renamed)
        // staff only
        public string type;       // "botanist" / "handler" / "chemist" / "cleaner" (EEmployeeType, lower case)
        public string property;   // the property they work at ("Barn"), "" when none
        // dealers only
        public double cash;       // in-game $ the dealer holds for the streamer
        public int stock;         // packaged product the dealer still has (Dealer.GetPackagedProductAmount)
        public int customers;     // customers assigned to the dealer
        // suppliers only
        public bool unlocked;     // the streamer has met them (they're in the phone's contacts)
        public double debt;       // in-game $ the streamer owes them
    }

    /// <summary>A job for the main thread from POST /drop or POST /supplier (Drops.cs runs it).</summary>
    internal sealed class DropRequest
    {
        public string kind;       // "cash" (POST /drop), "pay" or "deliver" (POST /supplier "action")
        public long id;           // Core's own number; answers carry it back ("drop" / "req")
        public string by;         // the chatter's name (marker label, pop-up text)
        public string note;       // cash: the donor's note ("" = none)
        public string label;      // cash: what the marker says before the name ("Cash drop")
        public double cash;       // cash: in-game $ to put in the drop
        public string supplier;   // pay / deliver: the supplier's NPC id
        public double amount;     // pay: in-game $ off the debt
        public int qty;           // deliver: how many of the supplier's goods
    }

    /// <summary>Where chat's ingredient vote is (POST /mixpick from plugins/schedule1/mixpick.py).
    /// Read by MixPicker.cs on the main thread.</summary>
    internal sealed class PickState
    {
        public string state;      // "off" / "vote" / "done" / "stopped" (mixpick.py names)
        public int endsIn;        // vote: seconds left ("ends_in")
        public List<MixOption> options = new List<MixOption>();   // vote: ingredients and their votes
        public string winner;     // done: the ingredient chat picked
        public bool place;        // done: move the winner into the station (Core's mixpick_auto_place)
        public string takeFrom;   // where from: "carried" / "nearby" / "owned" (Core's mixpick_take_from, "take_from")
        public string msg;        // off: why
    }

    internal static class CrewShared
    {
        private const int MaxDrops = 20;          // drop / supplier jobs waiting for the main thread

        private static readonly object Lock = new object();
        private static bool _loaded;
        private static List<CrewMember> _staff = new List<CrewMember>();
        private static List<CrewMember> _dealers = new List<CrewMember>();
        private static List<CrewMember> _suppliers = new List<CrewMember>();
        // Names Core sent and Crew.cs hasn't applied yet; null = that list didn't change.
        private static Dictionary<string, WantedName> _staffNames, _dealerNames;
        private static readonly Queue<DropRequest> _drops = new Queue<DropRequest>();
        private static PickState _pick;

        /// <summary>Main thread (Crew.Refresh, every second): the lists GET /crew answers with.</summary>
        public static void SetCrew(bool loaded, List<CrewMember> staff, List<CrewMember> dealers, List<CrewMember> suppliers)
        {
            lock (Lock)
            {
                _loaded = loaded;
                _staff = staff ?? new List<CrewMember>();
                _dealers = dealers ?? new List<CrewMember>();
                _suppliers = suppliers ?? new List<CrewMember>();
            }
        }

        /// <summary>HTTP thread (GET /crew): copies of the three lists.</summary>
        public static (bool loaded, List<CrewMember> staff, List<CrewMember> dealers, List<CrewMember> suppliers) GetCrew()
        {
            lock (Lock)
                return (_loaded, new List<CrewMember>(_staff), new List<CrewMember>(_dealers), new List<CrewMember>(_suppliers));
        }

        /// <summary>HTTP thread (POST /crewnames): a list that is passed replaces the wanted names for
        /// that group; null leaves it as it was.</summary>
        public static void SetNames(Dictionary<string, WantedName> staff, Dictionary<string, WantedName> dealers)
        {
            lock (Lock)
            {
                if (staff != null)
                    _staffNames = staff;
                if (dealers != null)
                    _dealerNames = dealers;
            }
        }

        /// <summary>Main thread (Crew.Tick): names sent since the last call; null for a group that didn't change.</summary>
        public static (Dictionary<string, WantedName> staff, Dictionary<string, WantedName> dealers) TakeNames()
        {
            lock (Lock)
            {
                var r = (_staffNames, _dealerNames);
                _staffNames = _dealerNames = null;
                return r;
            }
        }

        /// <summary>HTTP thread: queue a cash drop or supplier job; false when the queue is full.</summary>
        public static bool AddDrop(DropRequest r)
        {
            lock (Lock)
            {
                if (_drops.Count >= MaxDrops)
                    return false;
                _drops.Enqueue(r);
                return true;
            }
        }

        /// <summary>Main thread (Drops.Tick): the next job, or null.</summary>
        public static DropRequest TakeDrop()
        {
            lock (Lock)
                return _drops.Count > 0 ? _drops.Dequeue() : null;
        }

        /// <summary>HTTP thread (POST /mixpick): replace the vote state MixPicker will read.</summary>
        public static void SetPick(PickState s)
        {
            lock (Lock)
                _pick = s;
        }

        /// <summary>Main thread (MixPicker.Tick): the newest vote state, or null when none came since.</summary>
        public static PickState TakePick()
        {
            lock (Lock)
            {
                var s = _pick;
                _pick = null;
                return s;
            }
        }
    }
}
