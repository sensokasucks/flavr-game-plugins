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
//   Mugger.cs          !mug: cartel goons sent after a player (host only)
//   LobbySync.cs       co-op: the host shares names / lists, clients forward joins and mugs
//
// Unity and game objects may only be used on the main thread, so the HTTP thread only reads and
// writes Shared; OnUpdate below moves data between Shared and the game.

using System;
using MelonLoader;

[assembly: MelonInfo(typeof(FridgeSchedule1.Core), "FridgeSchedule1", "0.3.0", "sensokasucks",
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
        private Mugger _mugger;
        private LobbySync _lobby;
        private bool _inWorld;                // a save is loaded (scene "Main")
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
            _mugger = new Mugger(LoggerInstance);
            _lobby = new LobbySync(LoggerInstance, _watcher, _mugger);
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
            _inWorld = sceneName == "Main";
            if (_inWorld)
                _watcher.OnWorldLoaded();
            else
                _watcher.OnWorldUnloaded();
            _mugger.Clear();
            _nextRefresh = 0f;
        }

        public override void OnUpdate()
        {
            // Names Core sent since the last frame (POST /names), applied here on the main thread.
            // On a co-op client the host's names come through LobbySync instead (BridgeServer refuses /names).
            var names = Shared.TakePendingNames();
            if (names != null)
                _watcher.ApplyNames(names);

            // A !mug or a client's join / leave from this player's Core, one per frame.
            var request = Shared.TakeRequest();
            if (request != null)
                HandleRequest(request);

            // Stream alerts Core sent (POST /notify), one per frame, and the phone app's redraw.
            var notice = Shared.TakeNotice();
            if (notice != null)
                ShowNotice(notice);
            ChatApp.Current?.Tick();

            if (UnityEngine.Time.realtimeSinceStartup < _nextRefresh)
                return;
            _nextRefresh = UnityEngine.Time.realtimeSinceStartup + RefreshEverySec;
            if (_inWorld)
                _lobby.Tick();     // before Refresh, so a client applies the host's latest names
            _watcher.Refresh();
            _mugger.Tick();
        }

        // A request from this player's Core (BridgeServer POST /mug, /remote). On a co-op client every
        // request goes to the host (LobbySync.Send); the host answers mugs in lobby data, which
        // LobbySync turns into the same mug_result / mug_outcome events as below.
        private void HandleRequest(CoreRequest r)
        {
            if (Shared.Role == "client")
            {
                _lobby.Send(r);
                return;
            }
            if (r.type != "mug")
                return;            // join / leave on the host: its own Core handles those
            if (!_inWorld)
            {
                Shared.AddEvent("mug_result", new System.Collections.Generic.Dictionary<string, object>
                    { ["mug"] = r.id, ["ok"] = false, ["msg"] = "no save is loaded" });
                return;
            }
            var player = Il2CppScheduleOne.PlayerScripts.Player.Local;
            var why = _mugger.Start(player, r.by, r.goons, outcome =>
                Shared.AddEvent("mug_outcome", new System.Collections.Generic.Dictionary<string, object>
                    { ["mug"] = r.id, ["outcome"] = outcome }));
            Shared.AddEvent("mug_result", new System.Collections.Generic.Dictionary<string, object>
                { ["mug"] = r.id, ["ok"] = why.Length == 0, ["msg"] = why });
            Shared.AddFeed(why.Length == 0 ? $"{r.by} sent goons after you" : $"{r.by} tried to mug you: {why}");
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
