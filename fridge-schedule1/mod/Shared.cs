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
        public string status;    // "locked" / "deal" / "offer" / "dealer" / "waiting" (CustomerStatus.Describe)
        public string statusText;// the same in words: "deal set for 16:30-18:00 at the Docks" ("status_text" in JSON)
        public bool regular;     // one of FridgeRegulars' ten (id "fridge_regular_NN"); plugin.py's
                                 // regulars_only setting names only these
    }

    /// <summary>A name Core wants on a customer (POST /names).</summary>
    internal sealed class WantedName
    {
        public string first;
        public string last;
    }

    /// <summary>One chatter on the phone app's lists (POST /board). Built by Core's plugin.py board().</summary>
    internal sealed class BoardRow
    {
        public string key;       // Core's person key ("twitch:123"); sent back with the app's Remove / Swap
        public string name;      // chatter name as shown in chat
        public string platform;  // twitch / youtube / kick
        public string customer;  // the customer's own name ("Kyle Cooley"); empty while waiting
        public string npc;       // the customer's game id ("kyle_cooley"); empty while waiting.
                                 // A client streamer's Core uses it to find its own chatters' customers.
        public string status;    // when they'll turn up, in words (CustomerStatus.Describe via plugin.py board())
        public int deals;
        public double spent;     // in-game dollars
    }

    /// <summary>What the phone app shows from Core: named chatters, the waiting list, top spenders.</summary>
    internal sealed class Board
    {
        public List<BoardRow> named = new List<BoardRow>();
        public List<BoardRow> waiting = new List<BoardRow>();
        public List<BoardRow> top = new List<BoardRow>();
    }

    /// <summary>Something this player's Core asks the game for, handled on the main thread:
    /// a mugging (POST /mug), or on a co-op client a chatter joining / leaving the host's list
    /// (POST /remote). LobbySync.cs sends client requests to the host.</summary>
    internal sealed class CoreRequest
    {
        public string type;       // "mug", "join", "leave", "nudge" (POST /nudge) or "find" (POST /find)
        public string npc;        // nudge / find: the customer's NPC id; find: label in "by"
        public long id;           // Core's own number for a mug; results come back with it
        public string by;         // mug: the redeemer's name (put on the goons)
        public int goons;         // mug: how many goons (Core's mug_goons setting)
        public string platform;   // join / leave: the chatter (hide lists are checked on both sides)
        public string userId;
        public string username;
        public string displayName;
        public bool isSub;
    }

    /// <summary>A stream alert Core wants shown in the game (POST /notify): a phone pop-up plus a feed line.</summary>
    internal sealed class Notice
    {
        public string title;     // "New subscriber"
        public string text;      // "zackfan99 subscribed!"
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

        // Phone app data (ChatApp.cs). _boardVersion / _feedVersion go up on every change so the
        // app only rebuilds its lists when something is new.
        private const int MaxFeed = 40;        // feed lines the app keeps (newest first)
        private const int MaxNotices = 20;     // alerts waiting for the main thread; more are dropped
        private static Board _board = new Board();
        private static int _boardVersion;
        private static readonly List<string> _feed = new List<string>();
        private static int _feedVersion;
        private static readonly Queue<Notice> _notices = new Queue<Notice>();

        // Co-op (LobbySync.cs). Role is "host" (also when playing alone) or "client"; on a client the
        // host's mod decides the names and the list, and this player's Core only forwards requests.
        private const int MaxRequests = 20;    // Core requests waiting for the main thread
        private static string _role = "host";
        private static readonly Queue<CoreRequest> _requests = new Queue<CoreRequest>();

        /// <summary>"host" or "client"; set by LobbySync every second, read by BridgeServer.</summary>
        public static string Role
        {
            get { lock (Lock) return _role; }
            set { lock (Lock) _role = value; }
        }

        /// <summary>HTTP thread (POST /mug, POST /remote): queue a request; false when the queue is full.</summary>
        public static bool AddRequest(CoreRequest r)
        {
            lock (Lock)
            {
                if (_requests.Count >= MaxRequests)
                    return false;
                _requests.Enqueue(r);
                return true;
            }
        }

        /// <summary>Main thread (Core.OnUpdate): the next request, or null.</summary>
        public static CoreRequest TakeRequest()
        {
            lock (Lock)
                return _requests.Count > 0 ? _requests.Dequeue() : null;
        }

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

        /// <summary>Main thread: add an event (CustomerWatcher's orders / deals / unlocks, ChatApp's
        /// "app_remove" / "app_swap" button presses). Core reads them with GET /events.</summary>
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

        /// <summary>HTTP thread (POST /board): the lists the phone app shows.</summary>
        public static void SetBoard(Board board)
        {
            lock (Lock)
            {
                _board = board ?? new Board();
                _boardVersion++;
            }
        }

        /// <summary>Main thread (ChatApp): the board and its version number.</summary>
        public static (Board board, int version) GetBoard()
        {
            lock (Lock)
                return (_board, _boardVersion);
        }

        /// <summary>Either thread: add a line to the app's feed (orders, deals, alerts).</summary>
        public static void AddFeed(string line)
        {
            if (string.IsNullOrEmpty(line))
                return;
            lock (Lock)
            {
                _feed.Insert(0, $"{DateTime.Now:HH:mm}  {line}");
                if (_feed.Count > MaxFeed)
                    _feed.RemoveRange(MaxFeed, _feed.Count - MaxFeed);
                _feedVersion++;
            }
        }

        /// <summary>Main thread (ChatApp): copy of the feed, newest first, and its version number.</summary>
        public static (List<string> lines, int version) GetFeed()
        {
            lock (Lock)
                return (new List<string>(_feed), _feedVersion);
        }

        /// <summary>HTTP thread (POST /notify): queue an alert for Core.OnUpdate to show.</summary>
        public static void AddNotice(Notice n)
        {
            lock (Lock)
            {
                if (_notices.Count < MaxNotices)
                    _notices.Enqueue(n);
            }
        }

        /// <summary>Main thread (Core.OnUpdate): the next alert to show, or null.</summary>
        public static Notice TakeNotice()
        {
            lock (Lock)
                return _notices.Count > 0 ? _notices.Dequeue() : null;
        }
    }
}
