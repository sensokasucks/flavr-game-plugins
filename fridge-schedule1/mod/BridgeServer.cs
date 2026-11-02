// The HTTP server Stream Core's Schedule I plugin talks to (plugins/schedule1/bridge.py).
// Runs on its own background thread and only reads / writes Shared (never game objects).
//
//   GET  /health, /ping        {"ok": true}                      open, for "is it running?"
//   GET  /customers            {"loaded", "boot", "customers": [{"id", "first", "last", "shown", "unlocked"}]}
//   POST /names                {"names": {npc id: {"first", "last"}}} -> {"success", "applied", "missing"}
//   GET  /events?after=<seq>   {"boot", "last", "events": [{"seq", "type", "id", "name", "qty", "products", "payment"}]}
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
        private const int MaxBodyBytes = 256 * 1024;   // a full set of names is a few KB

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
                Json(ctx, 200, new Dictionary<string, object>
                {
                    ["loaded"] = loaded,
                    ["boot"] = Shared.Boot,
                    ["source"] = "mod",
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

            Json(ctx, 404, Error("not found"));
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
            if (req.ContentLength64 > MaxBodyBytes)
                throw new InvalidDataException("too large");
            string body;
            using (var reader = new StreamReader(req.InputStream, Encoding.UTF8))
                body = reader.ReadToEnd();
            var result = new Dictionary<string, WantedName>();
            using var doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(body) ? "{}" : body);
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
