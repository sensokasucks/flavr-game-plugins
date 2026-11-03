// Reading and changing an NPC's shown name for Crew.cs (workers and dealers).
//
// Story NPCs (dealers such as Benji Coleman, suppliers) have S1API wrappers, and S1API knows where the
// current game version keeps names (NPC.FirstName / LastName), so those go through S1API like the
// customers in CustomerWatcher.cs. Workers are spawned by the game when hired and have no S1API
// wrapper (NPC.Get returns null for them). For them, in this order:
//   1. S1API's own name code (internal class S1API.Internal.Entities.NPCDataAccess, ApplyFirstName /
//      ApplyLastName / GetFirstName / GetLastName taking the game NPC), found by reflection. Current
//      game builds keep names in NPC.NPCData.BasicInfo (NPC.FirstName is read-only there), and S1API
//      handles the case where BasicInfo is a shared preset (writing that would rename every NPC using it).
//   2. The game NPC's own FirstName / LastName members (older builds had them as writable fields).
// A game or S1API update that moves both makes Set return false (Crew.cs then logs one warning)
// instead of failing to load the whole mod.
//
// Main thread only. Renaming is local to this PC and Crew.cs puts every own name back while the game
// saves, so chatter names never reach the save file.

using System;
using System.Reflection;
using S1NPC = Il2CppScheduleOne.NPCs.NPC;

namespace FridgeSchedule1
{
    internal static class NpcNames
    {
        private const BindingFlags Any = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;

        /// <summary>(first, last) the game shows for <paramref name="npc"/>; ("", "") when unknown.</summary>
        public static (string first, string last) Get(S1NPC npc)
        {
            if (npc == null)
                return ("", "");
            var w = Wrapper(npc);
            if (w != null)
                return (w.FirstName ?? "", w.LastName ?? "");
            var f = DataAccess("GetFirstName", npc) as string;
            var l = DataAccess("GetLastName", npc) as string;
            if (f != null)
                return (f, l ?? "");
            return (Read(npc, "FirstName"), Read(npc, "LastName"));
        }

        /// <summary>Show <paramref name="first"/> <paramref name="last"/> on <paramref name="npc"/>.
        /// False when this game version keeps names somewhere we can't reach.</summary>
        public static bool Set(S1NPC npc, string first, string last)
        {
            if (npc == null)
                return false;
            var w = Wrapper(npc);
            if (w != null)
            {
                w.FirstName = first ?? "";
                w.LastName = last ?? "";
                return true;
            }
            if (DataAccess("ApplyFirstName", npc, first ?? "") is bool a && a &&
                DataAccess("ApplyLastName", npc, last ?? "") is bool b && b)
                return true;
            bool ok = Write(npc, "FirstName", first ?? "");
            ok &= Write(npc, "LastName", last ?? "");
            Write(npc, "hasLastName", !string.IsNullOrEmpty(last));   // older builds hide the last name without it
            return ok;
        }

        // S1API's internal NPCDataAccess.<method>(game NPC[, text]) by reflection; null when this S1API has
        // no such method or it threw. Looked up once per method name.
        private static readonly System.Collections.Generic.Dictionary<string, MethodInfo> _access =
            new System.Collections.Generic.Dictionary<string, MethodInfo>();

        private static object DataAccess(string method, S1NPC npc, string text = null)
        {
            try
            {
                if (!_access.TryGetValue(method, out var m))
                {
                    var type = typeof(S1API.Entities.NPC).Assembly.GetType("S1API.Internal.Entities.NPCDataAccess");
                    var args = text == null ? new[] { typeof(S1NPC) } : new[] { typeof(S1NPC), typeof(string) };
                    m = type?.GetMethod(method, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static, null, args, null);
                    _access[method] = m;
                }
                if (m == null)
                    return null;
                return m.Invoke(null, text == null ? new object[] { npc } : new object[] { npc, text });
            }
            catch
            {
                return null;
            }
        }

        // S1API's wrapper, only for NPCs it knows (story characters); null for workers.
        private static S1API.Entities.NPC Wrapper(S1NPC npc)
        {
            try
            {
                return string.IsNullOrEmpty(npc.ID) ? null : S1API.Entities.NPC.Get(npc.ID);
            }
            catch
            {
                return null;
            }
        }

        private static string Read(S1NPC npc, string member)
        {
            try
            {
                var p = npc.GetType().GetProperty(member, Any);
                if (p != null)
                    return p.GetValue(npc) as string ?? "";
                var f = npc.GetType().GetField(member, Any);
                return f?.GetValue(npc) as string ?? "";
            }
            catch
            {
                return "";
            }
        }

        private static bool Write(S1NPC npc, string member, object value)
        {
            try
            {
                var p = npc.GetType().GetProperty(member, Any);
                if (p != null && p.CanWrite)
                {
                    p.SetValue(npc, value);
                    return true;
                }
                var f = npc.GetType().GetField(member, Any);
                if (f == null)
                    return false;
                f.SetValue(npc, value);
                return true;
            }
            catch
            {
                return false;
            }
        }
    }
}
