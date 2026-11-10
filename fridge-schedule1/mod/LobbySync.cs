// Co-op: shares chatter names and chat's doings between everyone in a Schedule I lobby. Every player
// has this mod; the host's mod is the authority. A guest needs only the mod, not Stream Core, to see it all.
//
// How it travels: Steam lobby data, which every lobby member can read. No custom network code:
//   host  -> lobby data  "fs1.names"  {npc id: [first, last]}   the chatter names on customers
//                        "fs1.board"  {"n": named, "w": waiting, "t": top}  the Chat app's lists
//                        "fs1.res"    {steam id: [[Core's mug id, stage, text], ...]}  mug answers;
//                                     stage "ok" / "no" (goons sent or not), then "won" / "lost" / "left"
//                        "fs1.crew"   {"s": {npc id: [first, last]}, "d": {...}, "m": [[drop id, label, x, y, z], ...]}
//                                     worker ("s") and dealer ("d") names (Crew.cs) and the open cash /
//                                     supplier drops' map markers (Drops.OpenMarkers)
//                        "fs1.pop"    {"b": host's Shared.Boot, "p": [[no, title, text, kind, message, amount,
//                                     label, accent, bg, text colour, muted, bold, image], ...]}  the host's
//                                     last phone pop-ups (drop notes, supplier notes, stream alerts)
//   client -> its own lobby member data "fs1.req"  {"r": [{"n", "t", ...}, ...]}  last requests
// Everyone reads every second (Tick, from Core.OnUpdate). Steam keeps each value under 8 KB, so
// the board drops waiting-list rows if it gets too long (Shrink).
//
// Roles (Shared.Role): "host" when this game hosts the lobby or plays alone, "client" otherwise.
// On a client this mod takes names and lists from the host instead of from its own Stream Core,
// and its Core forwards !customer joins / leaves and !mug here (BridgeServer POST /remote, /mug).
// Pop-ups on a client: the host's drop / supplier notes always show (they happen in the shared world);
// the host's stream alerts only show while the guest has no Stream Core of its own running
// (Shared.OwnCoreActive), so a guest who streams keeps just their own alerts.
// Request types: "join" / "leave" (a client streamer's chatter; host's Core gets a "remote_join" /
// "remote_leave" event) and "mug" (the host runs Mugger on that client's player). Field names here
// must match plugin.py (remote events, mug results) and stay small: they count against the 8 KB.

using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Il2CppSteamworks;
using MelonLoader;
using S1Lobby = Il2CppScheduleOne.Networking.Lobby;
using S1Player = Il2CppScheduleOne.PlayerScripts.Player;

namespace FridgeSchedule1
{
    internal sealed class LobbySync
    {
        private const string KeyNames = "fs1.names";
        private const string KeyBoard = "fs1.board";
        private const string KeyResults = "fs1.res";
        private const string KeyRequests = "fs1.req";
        private const int MaxValueBytes = 7800;       // Steam's limit is 8192 per value; leave room
        private const int KeepRequests = 10;          // a client's last requests kept in its member data
        private const int KeepResults = 8;            // per client, in fs1.res
        private const string KeyCrew = "fs1.crew";
        private const string KeyPops = "fs1.pop";
        private const int KeepPops = 6;               // host's last pop-ups kept in fs1.pop (fewer if over 8 KB)
        private const string HostMarkerPrefix = "fridge-schedule1:hostdrop:";   // guest's copies of the host's drop markers

        private readonly MelonLogger.Instance _log;
        private readonly CustomerWatcher _watcher;
        private readonly Mugger _mugger;
        private readonly Crew _crew;
        private readonly Drops _drops;

        // host
        private string _sentNames, _sentBoard, _sentResults, _sentCrew, _sentPops;
        private readonly List<object[]> _pops = new List<object[]>();   // fs1.pop rows, oldest first
        private long _popNo;
        private readonly Dictionary<ulong, long> _handled = new Dictionary<ulong, long>();   // member -> last request no.
        private readonly Dictionary<ulong, List<object[]>> _results = new Dictionary<ulong, List<object[]>>();
        // client
        private string _gotNames, _gotBoard, _gotCrew, _gotPops;
        private readonly HashSet<long> _hostMarkers = new HashSet<long>();   // host drop ids drawn on this map
        private string _popBoot;      // host's Boot the pop numbers below belong to (a host restart starts again)
        private long _popSeen = -1;   // newest host pop-up number already handled; -1 = not looked yet
        private readonly HashSet<string> _seenResults = new HashSet<string>();
        private readonly List<Dictionary<string, object>> _myRequests = new List<Dictionary<string, object>>();
        // Request numbers only go up, also across game restarts (they start at the clock in ms),
        // so the host never mistakes a new request for one it already handled.
        private long _requestNo = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

        public LobbySync(MelonLogger.Instance log, CustomerWatcher watcher, Mugger mugger, Crew crew, Drops drops)
        {
            _log = log;
            _watcher = watcher;
            _mugger = mugger;
            _crew = crew;
            _drops = drops;
        }

        /// <summary>Core.OnSceneWasInitialized: a new scene has no markers of ours, and a client should
        /// apply the host's names again on the fresh NPC objects.</summary>
        public void OnSceneChanged()
        {
            _hostMarkers.Clear();
            _gotNames = _gotBoard = _gotCrew = null;
        }

        /// <summary>Core.ShowNotice (main thread), for every pop-up this game shows. The host (in a lobby)
        /// keeps the last few for its guests (fs1.pop); a client's or solo player's own are not shared.</summary>
        public void OnNotice(Notice n)
        {
            if (n == null || Shared.Role != "host" || Lobby() == null)
                return;
            // Core's alert pictures are usually on the host's own PC (127.0.0.1 / localhost), which a
            // guest can't reach; those cards go without the picture there.
            var image = n.image ?? "";
            if (image.Contains("://127.") || image.Contains("://localhost") || image.Contains("://[::1]"))
                image = "";
            _pops.Add(new object[] { ++_popNo, n.title ?? "", Cut(n.text, 300), n.kind ?? "", Cut(n.message, 300),
                n.amount ?? "", n.label ?? "", n.accent ?? "", n.bg ?? "", n.textColor ?? "", n.muted ?? "", n.bold, image });
            if (_pops.Count > KeepPops)
                _pops.RemoveRange(0, _pops.Count - KeepPops);
        }

        private static string Cut(string s, int max) =>
            string.IsNullOrEmpty(s) ? "" : (s.Length <= max ? s : s.Substring(0, max));

        /// <summary>This player's lobby, or null when playing alone (then this game is the host).</summary>
        private static S1Lobby Lobby()
        {
            var lobby = Il2CppScheduleOne.DevUtilities.PersistentSingleton<S1Lobby>.Instance;
            return lobby != null && lobby.IsInLobby && lobby.PlayerCount > 1 ? lobby : null;
        }

        /// <summary>Once a second from Core.OnUpdate (main thread): set the role and swap data.</summary>
        public void Tick()
        {
            try
            {
                var lobby = Lobby();
                bool client = lobby != null && !lobby.IsHost;
                var role = client ? "client" : "host";
                if (Shared.Role != role)
                {
                    Shared.Role = role;
                    _log.Msg(client ? "co-op: following the host's chatter customers" : "co-op: this game decides chatter customers");
                    _gotNames = _gotBoard = _sentNames = _sentBoard = _sentResults = null;
                    _gotCrew = _gotPops = _sentCrew = _sentPops = null;
                    _popSeen = -1;
                    _pops.Clear();
                    if (!client)
                    {
                        // back to hosting / solo: our own Core's crew names again, and no host markers
                        _crew.SetHostNames(null, null);
                        ClearHostMarkers();
                    }
                }
                if (lobby == null)
                    return;
                var id = new CSteamID(lobby.LobbyID);
                if (client)
                    ClientTick(id);
                else
                    HostTick(id);
            }
            catch (Exception ex)
            {
                _log.Warning("co-op sync: " + ex.Message);
            }
        }

        /// <summary>Client: a request from this player's Core (Core.OnUpdate hands it over).</summary>
        public void Send(CoreRequest r)
        {
            var lobby = Lobby();
            if (lobby == null)
                return;
            var req = new Dictionary<string, object> { ["n"] = ++_requestNo, ["t"] = r.type };
            if (r.type == "mug")
            {
                req["id"] = r.id;              // Core's number; the host's answer carries it back
                req["by"] = r.by ?? "";
                req["g"] = r.goons;
            }
            else
            {
                req["p"] = r.platform ?? "";
                req["u"] = r.userId ?? "";
                req["un"] = r.username ?? "";
                req["d"] = r.displayName ?? "";
                req["s"] = r.isSub;
            }
            _myRequests.Add(req);
            if (_myRequests.Count > KeepRequests)
                _myRequests.RemoveRange(0, _myRequests.Count - KeepRequests);
            var json = JsonSerializer.Serialize(new Dictionary<string, object> { ["r"] = _myRequests });
            SteamMatchmaking.SetLobbyMemberData(new CSteamID(lobby.LobbyID), KeyRequests, json);
        }

        // ---------------------------------------------------------------- host

        private void HostTick(CSteamID lobby)
        {
            // names Core asked for -> everyone
            var names = JsonSerializer.Serialize(_watcher.Wanted.ToDictionary(kv => kv.Key, kv => new[] { kv.Value.first, kv.Value.last }));
            if (names != _sentNames && SteamMatchmaking.SetLobbyData(lobby, KeyNames, names))
                _sentNames = names;
            var board = Shrink(Shared.GetBoard().board);
            if (board != _sentBoard && SteamMatchmaking.SetLobbyData(lobby, KeyBoard, board))
                _sentBoard = board;

            // requests from the other players
            var me = SteamUser.GetSteamID().m_SteamID;
            int count = SteamMatchmaking.GetNumLobbyMembers(lobby);
            for (int i = 0; i < count; i++)
            {
                var member = SteamMatchmaking.GetLobbyMemberByIndex(lobby, i);
                if (member.m_SteamID == me)
                    continue;
                var raw = SteamMatchmaking.GetLobbyMemberData(lobby, member, KeyRequests);
                if (!string.IsNullOrEmpty(raw))
                    HandleRequests(member.m_SteamID, raw);
            }

            var results = JsonSerializer.Serialize(_results.ToDictionary(kv => kv.Key.ToString(), kv => kv.Value));
            if (results != _sentResults && SteamMatchmaking.SetLobbyData(lobby, KeyResults, results))
                _sentResults = results;

            // worker / dealer names and open drop markers -> everyone
            object Pairs(Dictionary<string, WantedName> d) => d.ToDictionary(kv => kv.Key, kv => new[] { kv.Value.first, kv.Value.last });
            var markers = _drops.OpenMarkers()
                .Select(m => new object[] { m.id, m.label, Math.Round(m.where.x, 2), Math.Round(m.where.y, 2), Math.Round(m.where.z, 2) })
                .ToList();
            var crew = JsonSerializer.Serialize(new Dictionary<string, object>
                { ["s"] = Pairs(_crew.WantedStaff), ["d"] = Pairs(_crew.WantedDealers), ["m"] = markers });
            if (crew != _sentCrew && crew.Length <= MaxValueBytes && SteamMatchmaking.SetLobbyData(lobby, KeyCrew, crew))
                _sentCrew = crew;

            // last pop-ups -> everyone; the oldest go first when over Steam's limit
            var keep = new List<object[]>(_pops);
            string pops;
            while (true)
            {
                pops = JsonSerializer.Serialize(new Dictionary<string, object> { ["b"] = Shared.Boot, ["p"] = keep });
                if (pops.Length <= MaxValueBytes || keep.Count == 0)
                    break;
                keep.RemoveAt(0);
            }
            if (pops != _sentPops && SteamMatchmaking.SetLobbyData(lobby, KeyPops, pops))
                _sentPops = pops;
        }

        private void HandleRequests(ulong member, string raw)
        {
            using var doc = JsonDocument.Parse(raw);
            if (!doc.RootElement.TryGetProperty("r", out var list) || list.ValueKind != JsonValueKind.Array)
                return;
            _handled.TryGetValue(member, out var last);
            if (!_handled.ContainsKey(member))
            {
                // first look at this player: skip what they asked before we were listening
                long max = 0;
                foreach (var r in list.EnumerateArray())
                    max = Math.Max(max, Num(r, "n"));
                _handled[member] = max;
                return;
            }
            foreach (var r in list.EnumerateArray())
            {
                long n = Num(r, "n");
                if (n <= last)
                    continue;
                _handled[member] = Math.Max(_handled[member], n);
                var type = Str(r, "t");
                var player = FindPlayer(member);
                if (type == "mug")
                {
                    long mugId = Num(r, "id");
                    var why = _mugger.Start(player, Str(r, "by"), (int)Num(r, "g"), outcome => AddResult(member, mugId, outcome, ""));
                    AddResult(member, mugId, why.Length == 0 ? "ok" : "no", why);
                    Shared.AddFeed(why.Length == 0
                        ? $"{Str(r, "by")} sent goons after {player?.PlayerName}"
                        : $"{Str(r, "by")} tried to mug {player?.PlayerName}: {why}");
                }
                else if (type == "join" || type == "leave")
                {
                    Shared.AddEvent("remote_" + type, new Dictionary<string, object>
                    {
                        ["from"] = member.ToString(),
                        ["player"] = player?.PlayerName ?? "",
                        ["platform"] = Str(r, "p"),
                        ["user_id"] = Str(r, "u"),
                        ["username"] = Str(r, "un"),
                        ["display_name"] = Str(r, "d"),
                        ["is_sub"] = r.TryGetProperty("s", out var s) && s.ValueKind == JsonValueKind.True,
                    });
                }
            }
        }

        private void AddResult(ulong member, long n, string stage, string text)
        {
            if (!_results.TryGetValue(member, out var list))
                _results[member] = list = new List<object[]>();
            list.Add(new object[] { n, stage, text });
            if (list.Count > KeepResults)
                list.RemoveRange(0, list.Count - KeepResults);
        }

        private static S1Player FindPlayer(ulong steamId)
        {
            var code = steamId.ToString();
            var players = S1Player.PlayerList;
            if (players == null)
                return null;
            for (int i = 0; i < players.Count; i++)
                if (players[i] != null && players[i].PlayerCode == code)
                    return players[i];
            return null;
        }

        // The board as compact JSON under MaxValueBytes; rows [name, platform, customer, deals, spent, npc, key, status].
        private static string Shrink(Board b)
        {
            object Row(BoardRow r) => new object[] { r.name, r.platform, r.customer, r.deals, Math.Round(r.spent), r.npc ?? "", r.key ?? "", r.status ?? "" };
            var waiting = b.waiting.Select(Row).ToList();
            while (true)
            {
                var json = JsonSerializer.Serialize(new Dictionary<string, object>
                {
                    ["n"] = b.named.Select(Row).ToList(),
                    ["w"] = waiting,
                    ["t"] = b.top.Select(Row).ToList(),
                });
                if (json.Length <= MaxValueBytes || waiting.Count == 0)
                    return json;
                waiting.RemoveRange(Math.Max(0, waiting.Count - 5), Math.Min(5, waiting.Count));
            }
        }

        // ---------------------------------------------------------------- client

        private void ClientTick(CSteamID lobby)
        {
            var names = SteamMatchmaking.GetLobbyData(lobby, KeyNames);
            if (!string.IsNullOrEmpty(names) && names != _gotNames)
            {
                _gotNames = names;
                var wanted = new Dictionary<string, WantedName>();
                using (var doc = JsonDocument.Parse(names))
                    foreach (var p in doc.RootElement.EnumerateObject())
                        if (p.Value.ValueKind == JsonValueKind.Array && p.Value.GetArrayLength() == 2)
                            wanted[p.Name] = new WantedName { first = p.Value[0].GetString(), last = p.Value[1].GetString() };
                _watcher.ApplyNames(wanted);
            }

            var board = SteamMatchmaking.GetLobbyData(lobby, KeyBoard);
            if (!string.IsNullOrEmpty(board) && board != _gotBoard)
            {
                _gotBoard = board;
                using var doc = JsonDocument.Parse(board);
                Shared.SetBoard(new Board
                {
                    named = Rows(doc.RootElement, "n"),
                    waiting = Rows(doc.RootElement, "w"),
                    top = Rows(doc.RootElement, "t"),
                });
            }

            ClientCrew(SteamMatchmaking.GetLobbyData(lobby, KeyCrew));
            ClientPops(SteamMatchmaking.GetLobbyData(lobby, KeyPops));

            // answers to this player's !mug requests -> events for this player's Core
            var res = SteamMatchmaking.GetLobbyData(lobby, KeyResults);
            if (string.IsNullOrEmpty(res))
                return;
            using (var doc = JsonDocument.Parse(res))
            {
                if (!doc.RootElement.TryGetProperty(SteamUser.GetSteamID().m_SteamID.ToString(), out var mine))
                    return;
                foreach (var e in mine.EnumerateArray())
                {
                    long n = e[0].GetInt64();
                    var stage = e[1].GetString();
                    if (!_seenResults.Add(n + ":" + stage))
                        continue;
                    if (stage == "ok" || stage == "no")
                        Shared.AddEvent("mug_result", new Dictionary<string, object> { ["mug"] = n, ["ok"] = stage == "ok", ["msg"] = e[2].GetString() });
                    else
                        Shared.AddEvent("mug_outcome", new Dictionary<string, object> { ["mug"] = n, ["outcome"] = stage });
                }
            }
        }

        // fs1.crew on a client: the host's worker / dealer names onto our copies of those NPCs (Crew.cs),
        // and the host's open drops as markers on our own map (gone again when the host's drop is emptied).
        private void ClientCrew(string raw)
        {
            if (string.IsNullOrEmpty(raw) || raw == _gotCrew)
                return;
            _gotCrew = raw;
            using var doc = JsonDocument.Parse(raw);
            var root = doc.RootElement;
            _crew.SetHostNames(Names(root, "s"), Names(root, "d"));

            var now = new HashSet<long>();
            if (root.TryGetProperty("m", out var list) && list.ValueKind == JsonValueKind.Array)
            {
                foreach (var m in list.EnumerateArray())
                {
                    if (m.ValueKind != JsonValueKind.Array || m.GetArrayLength() < 5)
                        continue;
                    long id = m[0].GetInt64();
                    now.Add(id);
                    if (!_hostMarkers.Add(id))
                        continue;      // already on our map
                    try
                    {
                        new S1API.Map.MapPOIBuilder(HostMarkerPrefix + id)
                            .WithLabel(m[1].GetString() ?? "Chat drop")
                            .WithPosition(new UnityEngine.Vector3((float)m[2].GetDouble(), (float)m[3].GetDouble(), (float)m[4].GetDouble()))
                            .WithTextVisibility(S1API.Map.MapPOITextVisibility.Always)
                            .Build();
                    }
                    catch (Exception ex)
                    {
                        _log.Warning("host's drop marker failed: " + ex.Message);
                    }
                }
            }
            foreach (var id in _hostMarkers.Where(i => !now.Contains(i)).ToList())
            {
                try { S1API.Map.MapPOIManager.Remove(HostMarkerPrefix + id); } catch { /* gone with the scene */ }
                _hostMarkers.Remove(id);
            }
        }

        private void ClearHostMarkers()
        {
            foreach (var id in _hostMarkers)
                try { S1API.Map.MapPOIManager.Remove(HostMarkerPrefix + id); } catch { /* gone with the scene */ }
            _hostMarkers.Clear();
        }

        private static Dictionary<string, WantedName> Names(JsonElement root, string key)
        {
            var d = new Dictionary<string, WantedName>();
            if (root.TryGetProperty(key, out var o) && o.ValueKind == JsonValueKind.Object)
                foreach (var p in o.EnumerateObject())
                    if (p.Value.ValueKind == JsonValueKind.Array && p.Value.GetArrayLength() == 2)
                        d[p.Name] = new WantedName { first = p.Value[0].GetString(), last = p.Value[1].GetString() };
            return d;
        }

        // fs1.pop on a client: the host's new pop-ups, shown here by Core.ShowNotice like our own. The first
        // look (joining, or the host restarted) only notes where the host is, so old pop-ups don't replay.
        private void ClientPops(string raw)
        {
            if (string.IsNullOrEmpty(raw) || raw == _gotPops)
                return;
            _gotPops = raw;
            using var doc = JsonDocument.Parse(raw);
            var root = doc.RootElement;
            var boot = Str(root, "b");
            if (!root.TryGetProperty("p", out var list) || list.ValueKind != JsonValueKind.Array)
                return;
            bool first = _popSeen < 0 || boot != _popBoot;
            _popBoot = boot;
            long newest = first ? 0 : _popSeen;
            foreach (var p in list.EnumerateArray())
            {
                if (p.ValueKind != JsonValueKind.Array || p.GetArrayLength() < 13)
                    continue;
                long no = p[0].GetInt64();
                if (no <= (first ? long.MaxValue : _popSeen))
                {
                    newest = Math.Max(newest, no);
                    continue;
                }
                newest = Math.Max(newest, no);
                var kind = p[3].GetString() ?? "";
                bool streamAlert = kind.Length > 0 && kind != "system";
                if (streamAlert && Shared.OwnCoreActive)
                    continue;      // this guest streams with their own Core: only their own alerts
                Shared.AddNotice(new Notice
                {
                    title = p[1].GetString(), text = p[2].GetString(), kind = kind, message = p[4].GetString(),
                    amount = p[5].GetString(), label = p[6].GetString(), accent = p[7].GetString(), bg = p[8].GetString(),
                    textColor = p[9].GetString(), muted = p[10].GetString(),
                    bold = p[11].ValueKind == JsonValueKind.True, image = p[12].GetString(),
                });
            }
            _popSeen = newest;
        }

        private static List<BoardRow> Rows(JsonElement root, string key)
        {
            var list = new List<BoardRow>();
            if (!root.TryGetProperty(key, out var arr) || arr.ValueKind != JsonValueKind.Array)
                return list;
            foreach (var r in arr.EnumerateArray())
            {
                if (r.ValueKind != JsonValueKind.Array || r.GetArrayLength() < 7)
                    continue;
                list.Add(new BoardRow
                {
                    name = r[0].GetString(), platform = r[1].GetString(), customer = r[2].GetString(),
                    deals = r[3].GetInt32(), spent = r[4].GetDouble(), npc = r[5].GetString(), key = r[6].GetString(),
                    status = r.GetArrayLength() > 7 ? r[7].GetString() : "",   // older hosts send 7 fields
                });
            }
            return list;
        }

        private static string Str(JsonElement o, string k) =>
            o.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";

        private static long Num(JsonElement o, string k) =>
            o.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetInt64() : 0;
    }
}
