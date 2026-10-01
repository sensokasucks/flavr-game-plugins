using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;

namespace FridgeGranvirStats
{
    /// <summary>
    /// Best-effort snapshot via reflection. Missing types become nulls, never a crash.
    /// Replace heuristics with real field paths after dnSpy work.
    /// </summary>
    internal static class GameProbe
    {
        internal static Dictionary<string, object> Snapshot()
        {
            var pilot = new Dictionary<string, object>
            {
                ["name"] = "",
                ["alive"] = true,
                ["health"] = null,
                ["health_max"] = null,
                ["heat"] = null,
                ["heat_max"] = null,
                ["ammo"] = null,
                ["kills"] = 0,
                ["deaths"] = 0,
            };

            var campaign = new Dictionary<string, object>
            {
                ["name"] = "",
                ["region"] = "",
                ["hours_left"] = null,
                ["credits"] = null,
                ["threat"] = null,
            };

            var squad = new Dictionary<string, object>
            {
                ["count"] = 1,
                ["max"] = 10,
                ["players"] = new List<object>(),
            };

            var parts = new Dictionary<string, object>
            {
                ["equipped"] = 0,
                ["depot"] = 0,
                ["codex_found"] = 0,
                ["codex_total"] = 0,
            };

            var notes = new List<string>();
            var isHost = GuessIsHost();
            var phase = "unknown";

            TryFill(pilot, campaign, squad, parts, notes, ref phase);

            return new Dictionary<string, object>
            {
                ["ok"] = true,
                ["source"] = "plugin",
                ["plugin_version"] = Plugin.PluginVersion,
                ["game_version"] = UnityEngine.Application.version ?? "",
                ["ts"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
                ["online"] = true,
                ["is_host"] = isHost,
                ["phase"] = phase,
                ["campaign"] = campaign,
                ["squad"] = squad,
                ["pilot"] = pilot,
                ["parts"] = parts,
                ["notes"] = notes,
            };
        }

        internal static bool GuessIsHost()
        {
            try
            {
                foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
                {
                    var t = asm.GetType("Mirror.NetworkServer") ?? asm.GetType("Mirror.NetworkManager");
                    if (t == null) continue;
                    var active = t.GetProperty("active", BindingFlags.Public | BindingFlags.Static)
                                 ?? t.GetField("active", BindingFlags.Public | BindingFlags.Static);
                    if (active == null) continue;
                    var val = active is PropertyInfo p ? p.GetValue(null) : ((FieldInfo)active).GetValue(null);
                    if (val is bool b) return b;
                }
            }
            catch
            {
                // ignore
            }
            return true;
        }

        private static void TryFill(
            Dictionary<string, object> pilot,
            Dictionary<string, object> campaign,
            Dictionary<string, object> squad,
            Dictionary<string, object> parts,
            List<string> notes,
            ref string phase)
        {
            try
            {
                // Intentionally empty until Assembly-CSharp field paths are known.
                // Hook candidates: Granvir, Pilot, Mech, Campaign, Depot, PartCodex.
                notes.Add("reflection hooks not bound yet — overlay will show empty bars until GameProbe is filled");
            }
            catch (Exception ex)
            {
                notes.Add("probe error: " + ex.GetType().Name);
            }
        }
    }
}
