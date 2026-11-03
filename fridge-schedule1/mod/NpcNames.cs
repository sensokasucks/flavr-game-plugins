// Reading and changing an NPC's shown name for Crew.cs (workers and dealers).
//
// Story NPCs (dealers such as Benji Coleman, suppliers) have S1API wrappers, and S1API knows where the
// current game version keeps names (NPC.FirstName / LastName), so those go through S1API like the
// customers in CustomerWatcher.cs. Workers are spawned by the game when hired and have no S1API
// wrapper (NPC.Get returns null for them), so for them the game NPC's own FirstName / LastName members
// are used, found by reflection: older game builds have them as fields (Il2CppInterop turns fields
// into properties), and a game update that moves them makes Set return false (Crew.cs then logs one
// warning) instead of failing to load the whole mod.
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
            bool ok = Write(npc, "FirstName", first ?? "");
            ok &= Write(npc, "LastName", last ?? "");
            Write(npc, "hasLastName", !string.IsNullOrEmpty(last));   // older builds hide the last name without it
            return ok;
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
