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
//   CustomerStatus.cs  when a customer will turn up (status words), the order nudge, the Find marker
//   ImageCache.cs      alert pictures for the Alerts tab, downloaded once
//   LobbySync.cs       co-op: the host shares names / lists / drop markers / pop-ups, clients forward joins and mugs
//   MixNamer.cs        "Let chat name it" button on the new mix naming screen (chat votes the name)
//   Crew.cs            workers named after chatters, dealer sponsors, the suppliers list (+ RobPatch)
//   NpcNames.cs        reads / sets a worker's or dealer's shown name
//   Drops.cs           cash drops from donations, supplier !tab / !supply, dead drop markers
//   MixPicker.cs       "Let chat pick" button on the mixing station (chat votes the next ingredient)
//   IngredientSources.cs  where that vote / auto-place look for ingredients (inventory, storage, vehicles)
//   ButtonWatch.cs     backup click check for those two buttons (co-op swallowed their clicks)
//   CrewShared.cs      what the HTTP thread and those four share (BridgeServer.Crew.cs has their routes)
//
// Unity and game objects may only be used on the main thread, so the HTTP thread only reads and
// writes Shared; OnUpdate below moves data between Shared and the game.

using System;
using MelonLoader;

[assembly: MelonInfo(typeof(FridgeSchedule1.Core), "FridgeSchedule1", "0.9.1", "sensokasucks",
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
        private MixNamer _mixNamer;
        private Crew _crew;                   // workers / dealers / suppliers (Crew.cs)
        private Drops _drops;                 // cash drops and supplier jobs (Drops.cs)
        private MixPicker _mixPicker;         // mixing station "Let chat pick" button
        private bool _inWorld;                // a save is loaded (scene "Main")
        // Order nudges waiting for their pause (real-time seconds), from POST /nudge; RunDueNudges.
        private const float NudgeDelaySec = 8f;
        private readonly System.Collections.Generic.List<(float due, string npc)> _nudges =
            new System.Collections.Generic.List<(float, string)>();
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
            // Real minutes a Find marker stays on the phone map (CustomerStatus.TickFind); it also goes
            // when you reach the customer or press Stop in the Chat app.
            CustomerStatus.FindMinutes = _prefs.CreateEntry("FindMinutes", 10f,
                description: "Real minutes a Find marker stays on the phone map.").Value;

            _watcher = new CustomerWatcher(LoggerInstance);
            _mugger = new Mugger(LoggerInstance);
            _mixNamer = new MixNamer(LoggerInstance);
            _crew = new Crew(LoggerInstance);
            _drops = new Drops(LoggerInstance);
            _lobby = new LobbySync(LoggerInstance, _watcher, _mugger, _crew, _drops);   // after the crew and drops it shares
            _mixPicker = new MixPicker(LoggerInstance);
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
            {
                _watcher.OnWorldLoaded();
                _crew.OnWorldLoaded();
            }
            else
            {
                _watcher.OnWorldUnloaded();
                _crew.OnWorldUnloaded();
            }
            _drops.Clear();                      // the old scene's drops and markers are gone
            _lobby.OnSceneChanged();             // and the host's drop markers a co-op guest drew
            _mugger.Clear();
            _nudges.Clear();
            CustomerStatus.StopFinding(null);    // S1API drops map markers with the scene anyway
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
            ImageCache.Tick();        // alert pictures that finished downloading
            ChatApp.Current?.Tick();
            _mixNamer.Tick();         // the naming screen's "Let chat name it" button (every frame: countdown)
            _mixPicker.Tick();        // the mixing station's "Let chat pick" button
            _crew.Tick();             // crew names Core sent (POST /crewnames)
            _drops.Tick(_inWorld);    // one cash drop / supplier job (POST /drop, /supplier)

            if (UnityEngine.Time.realtimeSinceStartup < _nextRefresh)
                return;
            _nextRefresh = UnityEngine.Time.realtimeSinceStartup + RefreshEverySec;
            if (_inWorld)
                _lobby.Tick();     // before Refresh, so a client applies the host's latest names
            _watcher.Refresh();
            _crew.Refresh();          // GET /crew lists, names, dealer sales / empty stock
            _drops.Watch();           // emptied drops -> "drop_taken"
            _mugger.Tick();
            RunDueNudges();
            CustomerStatus.TickFind();
        }

        // Order nudges (POST /nudge) whose pause is over: the customer texts an order now, unless the
        // game's rules say no (CustomerStatus.Nudge). Answer: event "nudge_result" for plugin.py.
        private void RunDueNudges()
        {
            var now = UnityEngine.Time.realtimeSinceStartup;
            for (int i = _nudges.Count - 1; i >= 0; i--)
            {
                if (_nudges[i].due > now)
                    continue;
                var id = _nudges[i].npc;
                _nudges.RemoveAt(i);
                var (customer, npc) = _watcher.Find(id);
                var why = _inWorld ? CustomerStatus.Nudge(customer, npc) : "no save is loaded";
                if (why.Length > 0)
                    LoggerInstance.Msg($"order nudge for {id} skipped: {why}");
                Shared.AddEvent("nudge_result", new System.Collections.Generic.Dictionary<string, object>
                    { ["npc"] = id, ["ok"] = why.Length == 0, ["msg"] = why });
            }
        }

        // A request from this player's Core (BridgeServer POST /mug, /remote). On a co-op client every
        // request goes to the host (LobbySync.Send); the host answers mugs in lobby data, which
        // LobbySync turns into the same mug_result / mug_outcome events as below.
        private void HandleRequest(CoreRequest r)
        {
            if (r.type == "find")
            {
                // this player's own map, host or guest
                var npc = _watcher.Find(r.npc).npc;
                Shared.AddFeed(CustomerStatus.Mark(npc, string.IsNullOrEmpty(r.by) ? npc?.FullName ?? r.npc : r.by)
                    ? $"{r.by} is marked: open the Map app to see them" : $"couldn't find {r.by} in this save");
                return;
            }
            if (r.type == "nudge")
            {
                // host only: a guest's Core never assigns, so never asks. A short pause first so the
                // text doesn't land in the same second as the new name.
                if (Shared.Role != "client")
                    _nudges.Add((UnityEngine.Time.realtimeSinceStartup + NudgeDelaySec, r.npc));
                return;
            }
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

        // A stream alert as the game's own phone pop-up (top right, like "new message") plus a card in
        // the Chat app's Alerts tab (a plain note goes to the Feed). Pop-ups aren't saved, so chatter names never reach the save file (which
        // is why alerts are not sent as text messages: conversations are saved). On the main menu
        // there is no NotificationsManager; the alert then only goes to the feed.
        private void ShowNotice(Notice n)
        {
            _lobby.OnNotice(n);      // a host passes its pop-ups on to co-op guests (LobbySync "fs1.pop")
            var title = string.IsNullOrEmpty(n.title) ? "Stream" : n.title;
            // Stream alerts stay in the Chat app's Alerts tab (with Stream Core's look) so the streamer
            // can read them after the pop-up has gone; other notes go to the Feed as before.
            if (!string.IsNullOrEmpty(n.kind) && n.kind != "system")
                Shared.AddAlert(n);
            else
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
