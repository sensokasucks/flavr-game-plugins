// The HTTP server Stream Core's Schedule I plugin talks to (plugins/schedule1/bridge.py).
// Runs on its own background thread and only reads / writes Shared (never game objects).
//
//   GET  /health, /ping        {"ok": true}                      open, for "is it running?"
//   GET  /customers            {"loaded", "boot", "customers": [{"id", "first", "last", "shown", "unlocked"}]}
//   POST /names                {"names": {npc id: {"first", "last"}}} -> {"success", "applied", "missing"}
//   GET  /events?after=<seq>   {"boot", "last", "events": [{"seq", "type", "id", "name", "qty", "products", "payment"}]}
//                              (type "app_remove" / "app_swap" carry "key": a button in the phone app)
//   POST /board                {"named": [...], "waiting": [...], "top": [...]} rows {"key", "name", "platform",
//                              "customer", "deals", "spent"}: what the phone app lists -> {"success"}
//   POST /notify               {"title", "text"}: a stream alert to pop up on the phone -> {"success"}
//   POST /mug                  {"id", "by", "goons"}: send goons after this player -> {"success", "role"};
//                              the answer comes as events "mug_result" {"mug", "ok", "msg"} and later
//                              "mug_outcome" {"mug", "outcome": "won" | "lost" | "left"}
//   POST /remote               {"type": "join" | "leave", "platform", "user_id", "username", "display_name",
//                              "is_sub"}: co-op client only, passed to the host (LobbySync.cs)
//   GET /customers also says "role" ("host" / "client") and "board" (the lists, the host's on a client).
//   On a client, POST /names and /board answer 409: the host decides.
//
// Safety (same rules as the mock, mock/mock_server.py): listens on loopback only; everything but
// /health needs the header X-Fridge-Core: 1 (Core always sends it); any request with a browser
// Origin header is refused, so a web page open on this PC can't rename customers; and when the
// Token preference is set, X-Fridge-Token must match it. No CORS headers are sent on purpose.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Threading;
using MelonLoader;

namespace FridgeSchedule1
{
    internal sealed class BridgeServer
    {
        private const int MaxBodyBytes = 256 * 1024;   // a full set of names or a board is a few KB

        private readonly HttpListener _listener = new HttpListener();
        private readonly string _token;
        private readonly MelonLogger.Instance _log;
        private Thread _thread;
        private volatile bool _running;

        public BridgeServer(string host, int port, string token, MelonLogger.Instance log)
        {
            _token = token ?? "";
            _log = log;
            _listener.Prefixes.Add($"http://{host}:{port}/");
        }

        public void Start()
        {
            _listener.Start();
            _running = true;
            _thread = new Thread(Loop) { IsBackground = true, Name = "FridgeSchedule1" };
            _thread.Start();
        }

        public void Stop()
        {
            _running = false;
            try { _listener.Stop(); } catch { /* ignore */ }
            try { _listener.Close(); } catch { /* ignore */ }
        }

        private void Loop()
        {
            while (_running)
            {
                HttpListenerContext ctx;
                try
                {
                    ctx = _listener.GetContext();
                }
                catch
                {
                    if (!_running) return;
                    continue;
                }

                try { Handle(ctx); }
                catch (Exception ex)
                {
                    _log.Warning("request failed: " + ex.Message);
                    try { ctx.Response.StatusCode = 500; ctx.Response.Close(); } catch { /* ignore */ }
                }
            }
        }

        private void Handle(HttpListenerContext ctx)
        {
            var req = ctx.Request;
            var path = (req.Url.AbsolutePath ?? "/").TrimEnd('/');

            if (req.HttpMethod == "GET" && (path == "/health" || path == "/ping"))
            {
                Json(ctx, 200, new Dictionary<string, object> { ["ok"] = true, ["source"] = "mod" });
                return;
            }
            if (!Allowed(ctx))
                return;

            if (req.HttpMethod == "GET" && path == "/customers")
            {
                var (loaded, customers) = Shared.GetCustomers();
                var board = Shared.GetBoard().board;
                Json(ctx, 200, new Dictionary<string, object>
                {
                    ["loaded"] = loaded,
                    ["boot"] = Shared.Boot,
                    ["source"] = "mod",
                    // "client" = a co-op guest: the host decides names; plugin.py then only forwards
                    ["role"] = Shared.Role,
                    ["board"] = new Dictionary<string, object>
                    {
                        ["named"] = board.named.Select(RowJson).ToList(),
                        ["waiting"] = board.waiting.Select(RowJson).ToList(),
                        ["top"] = board.top.Select(RowJson).ToList(),
                    },
                    ["customers"] = customers.Select(c => new Dictionary<string, object>
                    {
                        ["id"] = c.id, ["first"] = c.first, ["last"] = c.last,
                        ["shown"] = c.shown, ["unlocked"] = c.unlocked,
                    }).ToList(),
                });
                return;
            }

            if (req.HttpMethod == "GET" && path == "/events")
            {
                long.TryParse(req.QueryString["after"], out var after);
                var (last, events) = Shared.EventsAfter(after);
                Json(ctx, 200, new Dictionary<string, object> { ["boot"] = Shared.Boot, ["last"] = last, ["events"] = events });
                return;
            }

            if (req.HttpMethod == "POST" && (path == "/names" || path == "/board") && Shared.Role == "client")
            {
                Json(ctx, 409, Error("this game is a co-op client: the host decides names"));
                return;
            }

            if (req.HttpMethod == "POST" && (path == "/mug" || path == "/remote"))
            {
                CoreRequest r;
                try
                {
                    using var doc = JsonDocument.Parse(ReadBody(req));
                    var o = doc.RootElement;
                    r = new CoreRequest
                    {
                        type = path == "/mug" ? "mug" : Str(o, "type"),
                        id = o.TryGetProperty("id", out var id) && id.ValueKind == JsonValueKind.Number ? id.GetInt64() : 0,
                        by = Str(o, "by"),
                        goons = o.TryGetProperty("goons", out var g) && g.ValueKind == JsonValueKind.Number ? g.GetInt32() : 2,
                        platform = Str(o, "platform"),
                        userId = Str(o, "user_id"),
                        username = Str(o, "username"),
                        displayName = Str(o, "display_name"),
                        isSub = o.TryGetProperty("is_sub", out var s) && s.ValueKind == JsonValueKind.True,
                    };
                }
                catch (Exception ex)
                {
                    Json(ctx, 400, Error("bad body: " + ex.Message));
                    return;
                }
                if (r.type != "mug" && r.type != "join" && r.type != "leave")
                {
                    Json(ctx, 400, Error("type must be join or leave"));
                    return;
                }
                if (!Shared.AddRequest(r))       // Core.OnUpdate handles it next frame
                {
                    Json(ctx, 429, Error("too many requests waiting"));
                    return;
                }
                Json(ctx, 200, new Dictionary<string, object> { ["success"] = true, ["role"] = Shared.Role });
                return;
            }

            if (req.HttpMethod == "POST" && path == "/names")
            {
                Dictionary<string, WantedName> names;
                try
                {
                    names = ReadNames(req);
                }
                catch (Exception ex)
                {
                    Json(ctx, 400, Error("bad body: " + ex.Message));
                    return;
                }
                Shared.SetPendingNames(names);     // applied by Core.OnUpdate on the next frame
                var known = new HashSet<string>(Shared.GetCustomers().customers.Select(c => c.id));
                Json(ctx, 200, new Dictionary<string, object>
                {
                    ["success"] = true,
                    ["applied"] = names.Keys.Count(known.Contains),
                    ["missing"] = names.Keys.Where(k => !known.Contains(k)).ToList(),
                });
                return;
            }

            if (req.HttpMethod == "POST" && path == "/board")
            {
                try
                {
                    using var doc = JsonDocument.Parse(ReadBody(req));
                    var root = doc.RootElement;
                    Shared.SetBoard(new Board
                    {
                        named = Rows(root, "named"),
                        waiting = Rows(root, "waiting"),
                        top = Rows(root, "top"),
                    });
                }
                catch (Exception ex)
                {
                    Json(ctx, 400, Error("bad body: " + ex.Message));
                    return;
                }
                Json(ctx, 200, new Dictionary<string, object> { ["success"] = true });
                return;
            }

            if (req.HttpMethod == "POST" && path == "/notify")
            {
                try
                {
                    using var doc = JsonDocument.Parse(ReadBody(req));
                    var n = new Notice { title = Str(doc.RootElement, "title"), text = Str(doc.RootElement, "text") };
                    if (n.text.Length == 0)
                    {
                        Json(ctx, 400, Error("text is empty"));
                        return;
                    }
                    Shared.AddNotice(n);      // shown by Core.OnUpdate on the main thread
                }
                catch (Exception ex)
                {
                    Json(ctx, 400, Error("bad body: " + ex.Message));
                    return;
                }
                Json(ctx, 200, new Dictionary<string, object> { ["success"] = true });
                return;
            }

            Json(ctx, 404, Error("not found"));
        }

        // One board row for GET /customers (same fields as POST /board).
        private static Dictionary<string, object> RowJson(BoardRow r) => new Dictionary<string, object>
        {
            ["key"] = r.key, ["name"] = r.name, ["platform"] = r.platform, ["customer"] = r.customer,
            ["npc"] = r.npc, ["deals"] = r.deals, ["spent"] = r.spent,
        };

        // The request body as text ("{}" when empty); refuses bodies over MaxBodyBytes.
        private static string ReadBody(HttpListenerRequest req)
        {
            if (req.ContentLength64 > MaxBodyBytes)
                throw new InvalidDataException("too large");
            using var reader = new StreamReader(req.InputStream, Encoding.UTF8);
            var body = reader.ReadToEnd();
            return string.IsNullOrWhiteSpace(body) ? "{}" : body;
        }

        // One list of POST /board rows; field names match plugin.py's board().
        private static List<BoardRow> Rows(JsonElement root, string key)
        {
            var list = new List<BoardRow>();
            if (!root.TryGetProperty(key, out var arr) || arr.ValueKind != JsonValueKind.Array)
                return list;
            foreach (var r in arr.EnumerateArray())
            {
                if (r.ValueKind != JsonValueKind.Object)
                    continue;
                list.Add(new BoardRow
                {
                    key = Str(r, "key"),
                    name = Str(r, "name"),
                    platform = Str(r, "platform"),
                    customer = Str(r, "customer"),
                    npc = Str(r, "npc"),
                    deals = r.TryGetProperty("deals", out var d) && d.ValueKind == JsonValueKind.Number ? d.GetInt32() : 0,
                    spent = r.TryGetProperty("spent", out var s) && s.ValueKind == JsonValueKind.Number ? s.GetDouble() : 0,
                });
            }
            return list;
        }

        // Web pages out, Core's header in, token when one is set.
        private bool Allowed(HttpListenerContext ctx)
        {
            var h = ctx.Request.Headers;
            if (!string.IsNullOrEmpty(h["Origin"]))
            {
                Json(ctx, 403, Error("web pages may not call this"));
                return false;
            }
            if (h["X-Fridge-Core"] != "1")
            {
                Json(ctx, 403, Error("missing X-Fridge-Core header"));
                return false;
            }
            if (_token.Length > 0 && h["X-Fridge-Token"] != _token)
            {
                Json(ctx, 403, Error("wrong token"));
                return false;
            }
            return true;
        }

        // {"names": {"kyle_cooley": {"first": "zackfan99", "last": ""}, ...}}
        private static Dictionary<string, WantedName> ReadNames(HttpListenerRequest req)
        {
            var result = new Dictionary<string, WantedName>();
            using var doc = JsonDocument.Parse(ReadBody(req));
            if (!doc.RootElement.TryGetProperty("names", out var names) || names.ValueKind != JsonValueKind.Object)
                return result;
            foreach (var p in names.EnumerateObject())
            {
                if (p.Value.ValueKind != JsonValueKind.Object)
                    continue;
                result[p.Name] = new WantedName
                {
                    first = Str(p.Value, "first"),
                    last = Str(p.Value, "last"),
                };
            }
            return result;
        }

        private static string Str(JsonElement obj, string key) =>
            obj.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";

        private static Dictionary<string, object> Error(string msg) =>
            new Dictionary<string, object> { ["success"] = false, ["error"] = msg };

        private static void Json(HttpListenerContext ctx, int code, object body)
        {
            var bytes = JsonSerializer.SerializeToUtf8Bytes(body);
            ctx.Response.StatusCode = code;
            ctx.Response.ContentType = "application/json; charset=utf-8";
            ctx.Response.ContentLength64 = bytes.Length;
            ctx.Response.OutputStream.Write(bytes, 0, bytes.Length);
            ctx.Response.Close();
        }
    }
}
