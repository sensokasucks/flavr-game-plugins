using System;
using BepInEx;
using BepInEx.Configuration;
using HarmonyLib;
using UnityEngine;

namespace FridgeGranvirStats
{
    [BepInPlugin(PluginGuid, PluginName, PluginVersion)]
    public class Plugin : BaseUnityPlugin
    {
        public const string PluginGuid = "fridge.granvir.stats";
        public const string PluginName = "Fridge Granvir Stats";
        public const string PluginVersion = "0.1.0";

        internal static Plugin Instance { get; private set; }

        internal ConfigEntry<string> BindAddress;
        internal ConfigEntry<int> BindPort;
        internal ConfigEntry<bool> HostOnlyWrites;
        internal ConfigEntry<bool> ServeOverlays;

        private StatsServer _server;
        private Harmony _harmony;

        private void Awake()
        {
            Instance = this;
            BindAddress = Config.Bind("Server", "BindAddress", "127.0.0.1",
                "Loopback only. Do not expose this port.");
            BindPort = Config.Bind("Server", "BindPort", 3855,
                "HTTP port Stream Core polls.");
            HostOnlyWrites = Config.Bind("Safety", "HostOnlyWrites", true,
                "Refuse POST /command unless Mirror reports this process is the host.");
            ServeOverlays = Config.Bind("Server", "ServeOverlays", true,
                "Serve overlay HTML from the www/ folder next to this DLL.");

            try
            {
                _harmony = new Harmony(PluginGuid);
                _harmony.PatchAll();
            }
            catch (Exception ex)
            {
                Logger.LogWarning("Harmony patch-all skipped: " + ex.Message);
            }

            try
            {
                var www = ServeOverlays.Value
                    ? System.IO.Path.Combine(System.IO.Path.GetDirectoryName(Info.Location) ?? ".", "www")
                    : null;
                _server = new StatsServer(BindAddress.Value, BindPort.Value, www, Logger);
                _server.Start();
                Logger.LogInfo($"{PluginName} listening on http://{BindAddress.Value}:{BindPort.Value}/");
            }
            catch (Exception ex)
            {
                Logger.LogError("HTTP server failed to start: " + ex);
            }
        }

        private void OnDestroy()
        {
            try { _server?.Stop(); } catch { /* ignore */ }
            try { _harmony?.UnpatchSelf(); } catch { /* ignore */ }
        }
    }
}
