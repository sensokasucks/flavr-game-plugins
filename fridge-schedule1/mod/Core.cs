// FridgeSchedule1 entry point (MelonLoader mod for Schedule I, IL2CPP build).
//
// What it does: Stream Core's Schedule I plugin (plugins/schedule1 in this repo) sends names of
// chatters who typed !customer; this mod puts those names on customer NPCs in the streamer's
// game and reports the customers' orders and finished deals back, so Core can say them in chat.
//
// Pieces:
//   Core.cs            this file: settings, start/stop, the main-thread loop
//   CustomerWatcher.cs finds customers, renames them, listens for orders / deals (main thread only)
//   BridgeServer.cs    the HTTP server Core talks to (background thread; never touches the game)
//   Shared.cs          what the two threads share: the customer list, events, names to apply,
//                      the phone app's board / feed and alerts waiting to be shown
//   ChatApp.cs         the "Chat" phone app (customers, waiting list, top spenders, feed)
//
// Unity and game objects may only be used on the main thread, so the HTTP thread only reads and
// writes Shared; OnUpdate below moves data between Shared and the game.

using System;
using MelonLoader;

[assembly: MelonInfo(typeof(FridgeSchedule1.Core), "FridgeSchedule1", "0.2.0", "sensokasucks",
    "https://github.com/sensokasucks/flavr-game-plugins/tree/main/fridge-schedule1")]
[assembly: MelonGame("TVGS", "Schedule I")]

namespace FridgeSchedule1
{
    public class Core : MelonMod
    {
        // How often (seconds, real time) OnUpdate refreshes the customer list Core reads.
        private const float RefreshEverySec = 1f;

        private MelonPreferences_Category _prefs;
        private MelonPreferences_Entry<string> _bindAddress;
        private MelonPreferences_Entry<int> _port;
        private MelonPreferences_Entry<string> _token;

        private BridgeServer _server;
        private CustomerWatcher _watcher;
        private float _nextRefresh;

        public override void OnInitializeMelon()
        {
            // Saved in UserData\MelonPreferences.cfg under [FridgeSchedule1].
            _prefs = MelonPreferences.CreateCategory("FridgeSchedule1");
            _bindAddress = _prefs.CreateEntry("BindAddress", "127.0.0.1",
                description: "Loopback only. Do not expose this port to the network.");
            // 3857 must match schedule1.bridge_url in Stream Core (default http://127.0.0.1:3857).
            _port = _prefs.CreateEntry("Port", 3857, description: "HTTP port Stream Core talks to.");
            _token = _prefs.CreateEntry("Token", "",
                description: "Optional shared secret; same text as 'Mod token' on Core's Schedule I card.");

            _watcher = new CustomerWatcher(LoggerInstance);
            try
            {
                _server = new BridgeServer(_bindAddress.Value, _port.Value, _token.Value, LoggerInstance);
                _server.Start();
                LoggerInstance.Msg($"listening on http://{_bindAddress.Value}:{_port.Value}/ for Stream Core");
            }
            catch (Exception ex)
            {
                LoggerInstance.Error("HTTP server failed to start (is the port in use?): " + ex.Message);
            }
        }

        public override void OnSceneWasInitialized(int buildIndex, string sceneName)
        {
            // "Main" is the playable world (a save is loaded); "Menu" is the title screen.
            if (sceneName == "Main")
                _watcher.OnWorldLoaded();
            else
                _watcher.OnWorldUnloaded();
            _nextRefresh = 0f;
        }

        public override void OnUpdate()
        {
            // Names Core sent since the last frame (POST /names), applied here on the main thread.
            var names = Shared.TakePendingNames();
            if (names != null)
                _watcher.ApplyNames(names);

            // Stream alerts Core sent (POST /notify), one per frame, and the phone app's redraw.
            var notice = Shared.TakeNotice();
            if (notice != null)
                ShowNotice(notice);
            ChatApp.Current?.Tick();

            if (UnityEngine.Time.realtimeSinceStartup < _nextRefresh)
                return;
            _nextRefresh = UnityEngine.Time.realtimeSinceStartup + RefreshEverySec;
            _watcher.Refresh();
        }

        // A stream alert as the game's own phone pop-up (top right, like "new message") plus a line in
        // the Chat app's feed. Pop-ups aren't saved, so chatter names never reach the save file (which
        // is why alerts are not sent as text messages: conversations are saved). On the main menu
        // there is no NotificationsManager; the alert then only goes to the feed.
        private void ShowNotice(Notice n)
        {
            var title = string.IsNullOrEmpty(n.title) ? "Stream" : n.title;
            Shared.AddFeed(n.text);
            try
            {
                var manager = Il2CppScheduleOne.DevUtilities.Singleton<Il2CppScheduleOne.UI.NotificationsManager>.Instance;
                if (manager != null)
                    manager.SendNotification(title, n.text, ChatApp.Icon, 6f, true);   // 6 s on screen, with sound
            }
            catch (Exception ex)
            {
                LoggerInstance.Warning("alert pop-up failed: " + ex.Message);
            }
        }

        public override void OnApplicationQuit()
        {
            try { _server?.Stop(); } catch { /* shutting down anyway */ }
        }
    }
}
