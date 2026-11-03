// The crew routes of the HTTP server (the rest is in BridgeServer.cs). Same thread and safety rules:
// this runs on the server's background thread after BridgeServer.Allowed passed, and only reads /
// writes CrewShared and Shared (never game objects).
//
//   GET  /crew        {"loaded", "boot", "staff": [{"id", "first", "last", "type", "property", "shown"}],
//                     "dealers": [{"id", "first", "last", "cash", "stock", "customers", "shown"}],
//                     "suppliers": [{"id", "first", "last", "unlocked", "debt"}]}            (Crew.cs)
//   POST /crewnames   {"staff": {id: {"first", "last"}}, "dealers": {...}}: a list left out stays as it
//                     was -> {"success"}                                                     (Crew.cs)
//   POST /drop        {"id", "by", "note", "cash", "label"} -> {"success"}; answer events from Drops.cs
//   POST /supplier    {"id", "action": "pay" | "deliver", "supplier", "by", "amount", "qty"} -> {"success"}
//   POST /mixpick     {"state", "ends_in", "options": [{"name", "votes"}], "winner", "place", "take_from", "msg"} (MixPicker.cs)
// On a co-op client /crewnames, /drop and /supplier answer 409: workers, dealers, drops and debts are
// the host's. /mixpick works for everyone (each player mixes at their own station).
// Callers: plugins/schedule1/bridge.py (crew, crew_names, drop, supplier, mixpick); the mock
// (mock/mock_server.py) answers the same paths with the same fields.

using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Text.Json;

namespace FridgeSchedule1
{
    internal sealed partial class BridgeServer
    {
        /// <summary>Handle one of the crew paths; false when <paramref name="path"/> isn't one of them.</summary>
        private bool HandleCrew(HttpListenerContext ctx, string method, string path)
        {
            if (method == "GET" && path == "/crew")
            {
                var (loaded, staff, dealers, suppliers) = CrewShared.GetCrew();
                Json(ctx, 200, new Dictionary<string, object>
                {
                    ["loaded"] = loaded,
                    ["boot"] = Shared.Boot,
                    ["staff"] = staff.Select(m => new Dictionary<string, object>
                    {
                        ["id"] = m.id, ["first"] = m.first, ["last"] = m.last, ["shown"] = m.shown,
                        ["type"] = m.type ?? "", ["property"] = m.property ?? "",
                    }).ToList(),
                    ["dealers"] = dealers.Select(m => new Dictionary<string, object>
                    {
                        ["id"] = m.id, ["first"] = m.first, ["last"] = m.last, ["shown"] = m.shown,
                        ["cash"] = m.cash, ["stock"] = m.stock, ["customers"] = m.customers,
                    }).ToList(),
                    ["suppliers"] = suppliers.Select(m => new Dictionary<string, object>
                    {
                        ["id"] = m.id, ["first"] = m.first, ["last"] = m.last,
                        ["unlocked"] = m.unlocked, ["debt"] = m.debt,
                    }).ToList(),
                });
                return true;
            }
            if (method != "POST" || (path != "/crewnames" && path != "/drop" && path != "/supplier" && path != "/mixpick"))
                return false;
            if (path != "/mixpick" && Shared.Role == "client")
            {
                Json(ctx, 409, Error("this game is a co-op client: the host's game has the crew"));
                return true;
            }
            JsonDocument doc;
            try
            {
                doc = JsonDocument.Parse(ReadBody(ctx.Request));
            }
            catch (System.Exception ex)
            {
                Json(ctx, 400, Error("bad body: " + ex.Message));
                return true;
            }
            using (doc)
            {
                var o = doc.RootElement;
                if (o.ValueKind != JsonValueKind.Object)
                {
                    Json(ctx, 400, Error("body must be an object"));
                    return true;
                }
                switch (path)
                {
                    case "/crewnames":
                        CrewShared.SetNames(NameMap(o, "staff"), NameMap(o, "dealers"));
                        break;
                    case "/drop":
                    case "/supplier":
                        var r = new DropRequest
                        {
                            kind = path == "/drop" ? "cash" : Str(o, "action"),
                            id = Num(o, "id") is double id ? (long)id : 0,
                            by = Str(o, "by"),
                            note = Str(o, "note"),
                            label = Str(o, "label"),
                            cash = Num(o, "cash") ?? 0,
                            supplier = Str(o, "supplier"),
                            amount = Num(o, "amount") ?? 0,
                            qty = (int)(Num(o, "qty") ?? 1),
                        };
                        if (r.kind == "cash" && r.cash <= 0)
                        {
                            Json(ctx, 400, Error("cash must be above 0"));
                            return true;
                        }
                        if (!CrewShared.AddDrop(r))
                        {
                            Json(ctx, 429, Error("too many drops waiting"));
                            return true;
                        }
                        break;
                    case "/mixpick":
                        var s = new PickState
                        {
                            state = Str(o, "state"),
                            endsIn = (int)(Num(o, "ends_in") ?? 0),
                            winner = Str(o, "winner"),
                            place = o.TryGetProperty("place", out var pl) && pl.ValueKind == JsonValueKind.True,
                            takeFrom = Str(o, "take_from"),
                            msg = Str(o, "msg"),
                        };
                        if (o.TryGetProperty("options", out var opts) && opts.ValueKind == JsonValueKind.Array)
                            foreach (var x in opts.EnumerateArray())
                                if (x.ValueKind == JsonValueKind.Object)
                                    s.options.Add(new MixOption { name = Str(x, "name"), votes = (int)(Num(x, "votes") ?? 0) });
                        CrewShared.SetPick(s);
                        break;
                }
            }
            Json(ctx, 200, new Dictionary<string, object> { ["success"] = true });
            return true;
        }

        // {"zackfan99_id": {"first", "last"}, ...} under key, or null when the key is missing (= unchanged).
        private static Dictionary<string, WantedName> NameMap(JsonElement root, string key)
        {
            if (!root.TryGetProperty(key, out var map) || map.ValueKind != JsonValueKind.Object)
                return null;
            var result = new Dictionary<string, WantedName>();
            foreach (var p in map.EnumerateObject())
                if (p.Value.ValueKind == JsonValueKind.Object)
                    result[p.Name] = new WantedName { first = Str(p.Value, "first"), last = Str(p.Value, "last") };
            return result;
        }

        private static double? Num(JsonElement obj, string key) =>
            obj.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble() : (double?)null;
    }
}
