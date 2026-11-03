// Co-op: shares chatter customers between everyone in a Schedule I lobby. Every player has this
// mod; the host's mod is the authority.
//
// How it travels: Steam lobby data, which every lobby member can read. No custom network code:
//   host  -> lobby data  "fs1.names"  {npc id: [first, last]}   the chatter names on customers
//                        "fs1.board"  {"n": named, "w": waiting, "t": top}  the Chat app's lists
//                        "fs1.res"    {steam id: [[Core's mug id, stage, text], ...]}  mug answers;
//                                     stage "ok" / "no" (goons sent or not), then "won" / "lost" / "left"
//   client -> its own lobby member data "fs1.req"  {"r": [{"n", "t", ...}, ...]}  last requests
// Everyone reads every second (Tick, from Core.OnUpdate). Steam keeps each value under 8 KB, so
// the board drops waiting-list rows if it gets too long (Shrink).
//
// Roles (Shared.Role): "host" when this game hosts the lobby or plays alone, "client" otherwise.
// On a client this mod takes names and lists from the host instead of from its own Stream Core,
// and its Core forwards !customer joins / leaves and !mug here (BridgeServer POST /remote, /mug).
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

        private readonly MelonLogger.Instance _log;
        private readonly CustomerWatcher _watcher;
        private readonly Mugger _mugger;

        // host
        private string _sentNames, _sentBoard, _sentResults;
        private readonly Dictionary<ulong, long> _handled = new Dictionary<ulong, long>();   // member -> last request no.
        private readonly Dictionary<ulong, List<object[]>> _results = new Dictionary<ulong, List<object[]>>();
        // client
        private string _gotNames, _gotBoard;
        private readonly HashSet<string> _seenResults = new HashSet<string>();
        private readonly List<Dictionary<string, object>> _myRequests = new List<Dictionary<string, object>>();
        // Request numbers only go up, also across game restarts (they start at the clock in ms),
        // so the host never mistakes a new request for one it already handled.
        private long _requestNo = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

        public LobbySync(MelonLogger.Instance log, CustomerWatcher watcher, Mugger mugger)
        {
            _log = log;
            _watcher = watcher;
            _mugger = mugger;
        }

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
