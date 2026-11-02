// What the game thread (CustomerWatcher, via Core.OnUpdate) and the HTTP thread (BridgeServer)
// share. Every member takes the same lock; nothing in here touches Unity or game objects.
//
// JSON field names produced here are read by plugins/schedule1/bridge.py and plugin.py in Stream
// Core and imitated by mock/mock_server.py; keep all three in sync.

using System;
using System.Collections.Generic;

namespace FridgeSchedule1
{
    /// <summary>One customer as Core sees it (GET /customers).</summary>
    internal sealed class CustomerInfo
    {
        public string id;        // game NPC id, e.g. "kyle_cooley"; stable across saves
        public string first;     // the customer's own first name (not a chatter name)
        public string last;      // the customer's own last name
        public string shown;     // the name the game shows right now
        public bool unlocked;    // the streamer has met them (they're in the phone's contacts)
    }

    /// <summary>A name Core wants on a customer (POST /names).</summary>
    internal sealed class WantedName
    {
        public string first;
        public string last;
    }

    internal static class Shared
    {
        // Events kept for GET /events; Core polls every couple of seconds, so this is plenty.
        private const int MaxEvents = 500;

        private static readonly object Lock = new object();

        // Random id for this run of the game. Core sees it change after a restart and knows
        // event numbers started again at 1.
        public static readonly string Boot = Guid.NewGuid().ToString("N").Substring(0, 12);

        private static bool _loaded;
        private static List<CustomerInfo> _customers = new List<CustomerInfo>();
        private static readonly List<Dictionary<string, object>> _events = new List<Dictionary<string, object>>();
        private static long _seq;
        private static Dictionary<string, WantedName> _pending;

        /// <summary>Main thread: the latest customer list (CustomerWatcher.Refresh).</summary>
        public static void SetCustomers(bool loaded, List<CustomerInfo> customers)
        {
            lock (Lock)
            {
                _loaded = loaded;
                _customers = customers ?? new List<CustomerInfo>();
            }
        }

        /// <summary>HTTP thread: copy of the list for GET /customers.</summary>
        public static (bool loaded, List<CustomerInfo> customers) GetCustomers()
        {
            lock (Lock)
                return (_loaded, new List<CustomerInfo>(_customers));
        }

        /// <summary>Main thread: add an order / deal / unlock event (CustomerWatcher's game listeners).</summary>
        public static void AddEvent(string type, Dictionary<string, object> fields)
        {
            lock (Lock)
            {
                _seq++;
                var ev = new Dictionary<string, object>(fields ?? new Dictionary<string, object>())
                {
                    ["seq"] = _seq,
                    ["type"] = type,
                    ["time"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
                };
                _events.Add(ev);
                if (_events.Count > MaxEvents)
                    _events.RemoveRange(0, _events.Count - MaxEvents);
            }
        }

        /// <summary>HTTP thread: events newer than <paramref name="after"/> for GET /events.</summary>
        public static (long last, List<Dictionary<string, object>> events) EventsAfter(long after)
        {
            lock (Lock)
            {
                var list = new List<Dictionary<string, object>>();
                foreach (var ev in _events)
                    if ((long)ev["seq"] > after)
                        list.Add(ev);
                return (_seq, list);
            }
        }

        /// <summary>HTTP thread: Core's full set of wanted names (replaces any not yet applied).</summary>
        public static void SetPendingNames(Dictionary<string, WantedName> names)
        {
            lock (Lock)
                _pending = names ?? new Dictionary<string, WantedName>();
        }

        /// <summary>Main thread: the names to apply this frame, or null when Core sent nothing new.</summary>
        public static Dictionary<string, WantedName> TakePendingNames()
        {
            lock (Lock)
            {
                var p = _pending;
                _pending = null;
                return p;
            }
        }
    }
}
