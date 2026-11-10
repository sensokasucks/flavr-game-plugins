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
        // A stream alert (kind set, not "system") also goes into the Chat app's Alerts tab, drawn with
        // Stream Core's look as plugins/schedule1/alert_style.py resolved it. Colours "#RRGGBBAA".
        public string kind;      // core.alerts kind ("subscribe", "raid", ...); "" / "system" = a plain Feed note
        public string message;   // the viewer's own words (Super Chat, tip message), may be ""
        public string amount;    // "$5.00", "500 bits", may be ""
        public string label;     // the kind's name ("Gifted sub")
        public string accent;    // label, side bar, unread dot
        public string bg;        // card background; "" = the app's row colour
        public string textColor; // headline ("text_color" in JSON)
        public string muted;     // the viewer's message
        public bool bold;        // headline in bold
        public string image;     // picture URL (png / jpg), "" = none; fetched by ImageCache.cs
    }

    /// <summary>One name on chat's list for a new mix (POST /mixvote "options"): an idea and how many
    /// chatters suggested it, or a vote option and its votes.</summary>
    internal sealed class MixOption
    {
        public string name;
        public int votes;
    }

    /// <summary>Where chat's vote on a new mix's name is (POST /mixvote, from plugins/schedule1/mixvote.py
    /// mod_state). Read by MixNamer.cs on the main thread.</summary>
    internal sealed class MixState
    {
        public string state;     // "off" / "suggest" / "vote" / "done" / "stopped"
        public int endsIn;       // seconds left in this phase ("ends_in")
        public List<MixOption> options = new List<MixOption>();
        public List<string> ranked = new List<string>();   // done: best name first, then the rest to try
        public bool confirm;     // done: press the game's Confirm (Core's mix_auto_confirm setting)
        public string msg;       // off: why
    }

    /// <summary>One alert kept in the Alerts tab (newest first, MaxAlerts of them).</summary>
    internal sealed class AlertEntry
    {
        public int id;
        public Notice n;
        public DateTime at;
        public bool read;
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
        // Alerts tab (ChatApp). Only touched from the main thread (Core.ShowNotice, ChatApp), but kept
        // here with the rest under the same lock. The host's pop-ups also go to co-op guests (LobbySync
        // "fs1.pop"), whose Core.ShowNotice adds them here like their own.
        private const int MaxAlerts = 50;
        private static readonly List<AlertEntry> _alerts = new List<AlertEntry>();
        private static int _alertSeq;
        private static int _alertsVersion;

        // Co-op (LobbySync.cs). Role is "host" (also when playing alone) or "client"; on a client the
        // host's mod decides the names and the list, and this player's Core only forwards requests.
        private const int MaxRequests = 20;    // Core requests waiting for the main thread
        private static string _role = "host";
        private static readonly Queue<CoreRequest> _requests = new Queue<CoreRequest>();
        // Last time (UTC) this player's own Stream Core talked to the mod (BridgeServer.Handle, any
        // allowed request; Core polls every couple of seconds). A co-op guest without Core of its own
        // shows the host's stream alerts instead (LobbySync.ClientTick, OwnCoreActive).
        private const double OwnCoreQuietSec = 30;
        private static DateTime _coreSeen = DateTime.MinValue;
        // Latest POST /mixvote not yet seen by MixNamer (only the newest matters).
        private static MixState _mixState;

        /// <summary>HTTP thread (POST /mixvote): replace the vote state MixNamer will read.</summary>
        public static void SetMixState(MixState s)
        {
            lock (Lock)
                _mixState = s;
        }

        /// <summary>Main thread (MixNamer.Tick): the newest vote state, or null when none came since.</summary>
        public static MixState TakeMixState()
        {
            lock (Lock)
            {
                var s = _mixState;
                _mixState = null;
                return s;
            }
        }

        /// <summary>HTTP thread (BridgeServer.Handle): this player's Stream Core just made a request.</summary>
        public static void CoreSeen()
        {
            lock (Lock)
                _coreSeen = DateTime.UtcNow;
        }

        /// <summary>True while this player's own Stream Core has talked to the mod in the last
        /// OwnCoreQuietSec seconds. Read by LobbySync on a co-op guest: with no Core of its own the
        /// guest shows the host's stream alerts; with one it keeps only its own.</summary>
        public static bool OwnCoreActive
        {
            get { lock (Lock) return (DateTime.UtcNow - _coreSeen).TotalSeconds < OwnCoreQuietSec; }
        }

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

        /// <summary>Main thread (Core.ShowNotice): keep a stream alert for the Alerts tab, unread.</summary>
        public static void AddAlert(Notice n)
        {
            lock (Lock)
            {
                _alerts.Insert(0, new AlertEntry { id = ++_alertSeq, n = n, at = DateTime.Now });
                if (_alerts.Count > MaxAlerts)
                    _alerts.RemoveRange(MaxAlerts, _alerts.Count - MaxAlerts);
                _alertsVersion++;
            }
        }

        /// <summary>Main thread (ChatApp): the kept alerts (newest first), how many are unread, and a version.</summary>
        public static (List<AlertEntry> alerts, int unread, int version) GetAlerts()
        {
            lock (Lock)
                return (new List<AlertEntry>(_alerts), _alerts.FindAll(a => !a.read).Count, _alertsVersion);
        }

        /// <summary>Main thread (ChatApp): tapping a card marks it read; id 0 marks them all.</summary>
        public static void MarkAlertsRead(int id)
        {
            lock (Lock)
            {
                foreach (var a in _alerts)
                    if (id == 0 || a.id == id)
                        a.read = true;
                _alertsVersion++;
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
