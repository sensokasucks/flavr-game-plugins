using HarmonyLib;

namespace FridgeGranvirStats
{
    /// <summary>
    /// Placeholder Harmony targets.
    /// After dnSpy: patch mission-start / rest-enter / pilot-death to
    /// refresh GameProbe caches. Keep patches read-only.
    /// </summary>
    internal static class HarmonyPatches
    {
        // Example once the type exists:
        // [HarmonyPatch(typeof(SomeMissionManager), "StartMission")]
        // static void Postfix() { /* bump phase = mission */ }
    }
}
