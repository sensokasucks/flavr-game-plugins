using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using BepInEx.Logging;

namespace FridgeGranvirStats
{
    internal sealed class StatsServer
    {
        private readonly HttpListener _listener = new HttpListener();
        private readonly string _www;
        private readonly ManualLogSource _log;
        private Thread _thread;
        private volatile bool _running;

        public StatsServer(string host, int port, string wwwRoot, ManualLogSource log)
        {
            _www = wwwRoot;
            _log = log;
            var prefix = $"http://{host}:{port}/";
            _listener.Prefixes.Add(prefix);
        }

        public void Start()
        {
            _listener.Start();
            _running = true;
            _thread = new Thread(Loop) { IsBackground = true, Name = "FridgeGranvirStats" };
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
                HttpListenerContext ctx = null;
                try
                {
                    ctx = _listener.GetContext();
                }
                catch (HttpListenerException)
                {
                    if (!_running) return;
                    continue;
                }
                catch
                {
                    if (!_running) return;
                    continue;
                }

                try { Handle(ctx); }
                catch (Exception ex)
                {
                    _log.LogWarning("request failed: " + ex.Message);
                    try { ctx.Response.StatusCode = 500; ctx.Response.Close(); } catch { /* ignore */ }
                }
            }
        }

        private void Handle(HttpListenerContext ctx)
        {
            var req = ctx.Request;
            var path = (req.Url.AbsolutePath ?? "/").TrimEnd('/');
            if (path.Length == 0) path = "/";

            if (req.HttpMethod == "OPTIONS")
            {
                Write(ctx, 204, "text/plain", "");
                return;
            }

            if (req.HttpMethod == "GET" && (path == "/stats" || path == "/health" || path == "/ping"))
            {
                var snap = GameProbe.Snapshot();
                WriteJson(ctx, 200, SimpleJson.Serialize(snap));
                return;
            }

            if (req.HttpMethod == "POST" && path == "/command")
            {
                var hostOnly = Plugin.Instance != null && Plugin.Instance.HostOnlyWrites.Value;
                var isHost = GameProbe.GuessIsHost();
                if (hostOnly && !isHost)
                {
                    WriteJson(ctx, 403, SimpleJson.Serialize(new Dictionary<string, object>
                    {
                        ["success"] = false,
                        ["error"] = "host-only: this client is not the lobby host",
                    }));
                    return;
                }

                WriteJson(ctx, 200, SimpleJson.Serialize(new Dictionary<string, object>
                {
                    ["success"] = false,
                    ["error"] = "no host commands bound yet — stats/overlay only",
                }));
                return;
            }

            if (req.HttpMethod == "GET" && !string.IsNullOrEmpty(_www) && Directory.Exists(_www))
            {
                var rel = path == "/" ? "overlay.html" : path.TrimStart('/').Replace('/', Path.DirectorySeparatorChar);
                var full = Path.GetFullPath(Path.Combine(_www, rel));
                var root = Path.GetFullPath(_www);
                if (full.StartsWith(root) && File.Exists(full))
                {
                    var ext = Path.GetExtension(full).ToLowerInvariant();
                    var mime = ext == ".js" ? "application/javascript"
                        : ext == ".css" ? "text/css"
                        : ext == ".json" ? "application/json"
                        : "text/html; charset=utf-8";
                    var bytes = File.ReadAllBytes(full);
                    ctx.Response.StatusCode = 200;
                    ctx.Response.ContentType = mime;
                    AddCors(ctx.Response);
                    ctx.Response.ContentLength64 = bytes.Length;
                    ctx.Response.OutputStream.Write(bytes, 0, bytes.Length);
                    ctx.Response.Close();
                    return;
                }
            }

            Write(ctx, 404, "text/plain", "not found");
        }

        private static void AddCors(HttpListenerResponse res)
        {
            res.Headers["Access-Control-Allow-Origin"] = "*";
            res.Headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS";
            res.Headers["Access-Control-Allow-Headers"] = "Content-Type";
        }

        private static void Write(HttpListenerContext ctx, int code, string mime, string body)
        {
            var bytes = Encoding.UTF8.GetBytes(body ?? "");
            ctx.Response.StatusCode = code;
            ctx.Response.ContentType = mime;
            AddCors(ctx.Response);
            ctx.Response.ContentLength64 = bytes.Length;
            ctx.Response.OutputStream.Write(bytes, 0, bytes.Length);
            ctx.Response.Close();
        }

        private static void WriteJson(HttpListenerContext ctx, int code, string json)
        {
            Write(ctx, code, "application/json; charset=utf-8", json);
        }
    }

    /// <summary>Tiny serializer so we do not pull Newtonsoft into the plugin.</summary>
    internal static class SimpleJson
    {
        public static string Serialize(object value)
        {
            var sb = new StringBuilder();
            Write(sb, value);
            return sb.ToString();
        }

        private static void Write(StringBuilder sb, object value)
        {
            if (value == null) { sb.Append("null"); return; }
            switch (value)
            {
                case string s:
                    sb.Append('"').Append(Escape(s)).Append('"');
                    break;
                case bool b:
                    sb.Append(b ? "true" : "false");
                    break;
                case int i:
                    sb.Append(i);
                    break;
                case long l:
                    sb.Append(l);
                    break;
                case float f:
                    sb.Append(f.ToString(System.Globalization.CultureInfo.InvariantCulture));
                    break;
                case double d:
                    sb.Append(d.ToString(System.Globalization.CultureInfo.InvariantCulture));
                    break;
                case Dictionary<string, object> dict:
                    sb.Append('{');
                    var first = true;
                    foreach (var kv in dict)
                    {
                        if (!first) sb.Append(',');
                        first = false;
                        sb.Append('"').Append(Escape(kv.Key)).Append("\":");
                        Write(sb, kv.Value);
                    }
                    sb.Append('}');
                    break;
                case System.Collections.IEnumerable list when !(value is string):
                    sb.Append('[');
                    var f2 = true;
                    foreach (var item in list)
                    {
                        if (!f2) sb.Append(',');
                        f2 = false;
                        Write(sb, item);
                    }
                    sb.Append(']');
                    break;
                default:
                    sb.Append('"').Append(Escape(Convert.ToString(value))).Append('"');
                    break;
            }
        }

        private static string Escape(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            return s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n").Replace("\r", "\\r");
        }
    }
}
