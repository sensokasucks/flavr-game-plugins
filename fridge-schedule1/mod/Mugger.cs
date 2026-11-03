// "The mugger": a chatter's !mug sends cartel goons after a player. Runs on the host only (the
// host's game owns the goons); co-op clients ask the host through LobbySync.cs.
//
// Callers: Core.OnUpdate -> Start() for this player's own !mug (when this game is the host), and
// LobbySync (host) -> Start() for a client player's !mug. Core.OnUpdate calls Tick() once a second.
// Points, cooldown and price are Stream Core's business (plugins/schedule1/plugin.py _mug); this
// file only says whether the goons came (result) and how it ended (outcome).
//
// It uses the game's own goon pool (Cartel.GoonPool), the same goons as the cartel's ambushes:
// they come out of the building nearest the player and attack. That works anywhere, whether or
// not the cartel is active in the area. Goons carry the redeemer's name on this PC only (like
// customer names, nothing saved); their own name comes back when the mugging ends.

using System;
using System.Collections.Generic;
using MelonLoader;
using UnityEngine;
using S1Player = Il2CppScheduleOne.PlayerScripts.Player;
using S1Goon = Il2CppScheduleOne.Cartel.CartelGoon;
using S1Cartel = Il2CppScheduleOne.Cartel.Cartel;
using S1Targetable = Il2CppScheduleOne.Combat.ICombatTargetable;

namespace FridgeSchedule1
{
    internal sealed class Mugger
    {
        private const float GiveUpAfterSec = 180f;   // goons that haven't won or lost by then leave
        private const int MaxGoons = 4;              // upper bound for Core's mug_goons setting

        // One mugging in progress.
        private sealed class Job
        {
            public S1Player target;
            public List<S1Goon> goons = new List<S1Goon>();
            public List<(string first, string last)> ownNames = new List<(string, string)>();
            public float startedAt;
            public Action<string> outcome;   // "won" (player beat them), "lost" (player knocked out), "left" (time up)
        }

        private readonly MelonLogger.Instance _log;
        private readonly List<Job> _jobs = new List<Job>();

        public Mugger(MelonLogger.Instance log)
        {
            _log = log;
        }

        /// <summary>Send goons after <paramref name="target"/>. Returns "" when they're on their way,
        /// else why not (said in chat by Core, which then refunds). <paramref name="outcome"/> is
        /// called once later from Tick.</summary>
        public string Start(S1Player target, string by, int goonCount, Action<string> outcome)
        {
            try
            {
                if (target == null)
                    return "that player isn't in the game";
                if (target.IsArrested || target.IsUnconscious || target.Health == null || !target.Health.IsAlive)
                    return "the player can't be mugged right now";
                if (_jobs.Exists(j => j.target == target))
                    return "a mugging is already under way";
                var cartel = Il2CppScheduleOne.DevUtilities.NetworkSingleton<S1Cartel>.Instance;
                var pool = cartel != null ? cartel.GoonPool : null;
                if (pool == null)
                    return "no goons in this save";

                var at = target.transform.position;
                var spawn = at - target.transform.forward * 12f;          // fallback: behind the player
                var building = pool.GetNearestExitBuilding(at);
                var door = building != null ? building.GetClosestDoor(at, false) : null;
                if (door != null && door.AccessPoint != null)
                    spawn = door.AccessPoint.position;

                int n = Mathf.Clamp(goonCount, 1, MaxGoons);
                var spawned = pool.SpawnMultipleGoons(spawn, n, false);
                if (spawned == null || spawned.Count == 0)
                    return "no goons free right now";

                var targetable = target.GetComponent<S1Targetable>();
                var job = new Job { target = target, startedAt = Time.realtimeSinceStartup, outcome = outcome };
                for (int i = 0; i < spawned.Count; i++)
                {
                    var g = spawned[i];
                    if (g == null)
                        continue;
                    job.goons.Add(g);
                    job.ownNames.Add((g.FirstName, g.LastName));
                    if (!string.IsNullOrEmpty(by))
                        SetName(g, by + "'s", "crew");   // shows as "zackfan99's crew", this PC only
                    if (targetable != null)
                        g.AttackEntity(targetable, true);
                }
                _jobs.Add(job);
                _log.Msg($"mugging: {job.goons.Count} goon(s) sent after {target.PlayerName} for {by}");
                return "";
            }
            catch (Exception ex)
            {
                _log.Warning("mugging failed to start: " + ex.Message);
                return "the game refused";
            }
        }

        /// <summary>Once a second from Core.OnUpdate: finish muggings that are won, lost or too long.</summary>
        public void Tick()
        {
            for (int i = _jobs.Count - 1; i >= 0; i--)
            {
                var job = _jobs[i];
                string result = null;
                try
                {
                    bool playerDown = job.target == null || job.target.IsUnconscious
                                      || job.target.Health == null || !job.target.Health.IsAlive;
                    bool goonsDown = job.goons.TrueForAll(g => g == null || !g.IsConscious);
                    if (playerDown)
                        result = "lost";
                    else if (goonsDown)
                        result = "won";
                    else if (Time.realtimeSinceStartup - job.startedAt > GiveUpAfterSec)
                        result = "left";
                }
                catch (Exception ex)
                {
                    _log.Warning("mugging check failed: " + ex.Message);
                    result = "left";
                }
                if (result == null)
                    continue;
                Finish(job, result == "left");
                _jobs.RemoveAt(i);
                try { job.outcome?.Invoke(result); } catch { /* reporting only */ }
            }
        }

        // The game's NPC.FirstName / LastName are read-only; S1API writes names into the NPC's data
        // with its internal NPCDataAccess.ApplyFirstName / ApplyLastName (the same way S1API's
        // NPC.FirstName setter does, which CustomerWatcher uses for customers). Goons have no S1API
        // wrapper, so call those by reflection; if a newer S1API renames them the goons keep their
        // own names (only cosmetic).
        private static System.Reflection.MethodInfo _applyFirst, _applyLast;
        private static bool _lookedUp;

        private static void SetName(S1Goon g, string first, string last)
        {
            if (!_lookedUp)
            {
                _lookedUp = true;
                var t = typeof(S1API.Entities.NPC).Assembly.GetType("S1API.Internal.Entities.NPCDataAccess");
                const System.Reflection.BindingFlags flags = System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic;
                _applyFirst = t?.GetMethod("ApplyFirstName", flags);
                _applyLast = t?.GetMethod("ApplyLastName", flags);
            }
            try
            {
                _applyFirst?.Invoke(null, new object[] { g, first ?? "" });
                _applyLast?.Invoke(null, new object[] { g, last ?? "" });
            }
            catch { /* cosmetic only */ }
        }

        /// <summary>World unloaded (Core.OnSceneWasInitialized): forget muggings without reporting.</summary>
        public void Clear() => _jobs.Clear();

        // Put the goons' own names back; send them home when time ran out.
        private void Finish(Job job, bool despawn)
        {
            for (int i = 0; i < job.goons.Count; i++)
            {
                var g = job.goons[i];
                if (g == null)
                    continue;
                try
                {
                    SetName(g, job.ownNames[i].first, job.ownNames[i].last);
                    if (despawn && g.IsConscious)
                        g.Despawn();
                }
                catch { /* goon already gone */ }
            }
        }
    }
}
