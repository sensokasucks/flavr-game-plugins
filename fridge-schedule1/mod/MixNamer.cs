// "Let chat name it": a button on Schedule I's new-mix naming screen that hands the name to chat.
//
// The game opens its naming screen (NewMixScreen) when a mixing station makes a mix nobody has made
// before. This file adds two things under the game's Confirm button: our button, and a short status
// text (time left, chat's ideas or the vote so far).
//
// Flow (each player's own screen and own Stream Core, host or co-op guest alike, since the game's
// naming already goes through its own server call):
//   1. Button pressed -> event "mix_vote" for Core (GET /events) with the game's own name ideas (its
//      pick for this mix first), the product names already in the save, the effects and the value.
//   2. Core (plugins/schedule1/plugin.py _mix_start, mixvote.py) runs ideas (!mixname) and the vote
//      (!1 !2 ...) and keeps sending where it is (POST /mixvote -> Shared.SetMixState).
//   3. State "done": the ranked names are typed into the game's name box one by one until the game
//      accepts one (its Confirm button lights up: the name isn't taken), then Confirm is pressed for
//      the streamer when Core's mix_auto_confirm setting is on.
// Pressing the button again, or closing the screen (naming it yourself, Esc), sends "mix_vote_stop".
//
// Callers: Core.OnUpdate calls Tick() every frame. Everything here runs on the main thread (Unity UI).
// State names ("off", "suggest", "vote", "done", "stopped") must match plugins/schedule1/mixvote.py.
// The game's own names for the screen's parts (nameInputField, confirmButton, marketValueLabel,
// propertiesLabels, name1Library ...) come from its NewMixScreen class; a game update that renames them makes Tick
// log one warning and leaves the screen as the game made it.

using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using MelonLoader;
using S1API.UI;
using S1API.Utils;   // ButtonUtils.AddListener (same helper ChatApp.cs uses)
using UnityEngine;
using UnityEngine.UI;
using S1Screen = Il2CppScheduleOne.UI.NewMixScreen;
using S1Products = Il2CppScheduleOne.Product.ProductManager;
using TMPText = Il2CppTMPro.TextMeshProUGUI;

namespace FridgeSchedule1
{
    internal sealed class MixNamer
    {
        private const string ButtonText = "Let chat name it";
        private const float AnswerTimeoutSec = 6f;   // Core polls events every poll_sec (2 s by default)
        private const int GameIdeas = 6;             // game name ideas sent with "mix_vote" (its own pick + 5)
        private const int MaxTaken = 400;            // product names sent as "taken" (a save has far fewer)

        private readonly MelonLogger.Instance _log;
        private bool _wasOpen;
        private bool _warned;                        // one warning per game run when the screen can't be used
        // "idle" (button offers chat), "asking" (pressed, Core hasn't answered yet), "suggest", "vote"
        private string _mode = "idle";
        private float _askedAt;                      // realtime when the button was pressed
        private float _endsAt;                       // realtime the current phase ends (Core's ends_in)
        private List<MixOption> _rows = new List<MixOption>();
        private string _note = "";                   // status text while idle ("Chat picked ...", Core's "off" message)
        private string _gamePick = "";               // the game's own name for this mix (put back if chat's are all taken)

        // Our UI, built once per naming screen object (the screen lives in the Main scene, so a new
        // one comes with each save load).
        private S1Screen _builtFor;
        private GameObject _button;
        private TMPText _buttonLabel;
        private TMPText _status;
        private string _shownLabel, _shownStatus;   // last texts set, so the UI is only touched on change
        // Backup click check (ButtonWatch.cs): runs OnButton when co-op swallows the button's own click.
        private readonly ButtonWatch _watch;

        public MixNamer(MelonLogger.Instance log)
        {
            _log = log;
            _watch = new ButtonWatch(log, ButtonText, OnButton);
        }

        /// <summary>Every frame from Core.OnUpdate: notice the screen opening / closing, apply Core's
        /// latest vote state, redraw the button and status text.</summary>
        public void Tick()
        {
            var state = Shared.TakeMixState();      // taken every frame so an old state never lingers
            S1Screen screen;
            bool open;
            try
            {
                screen = Il2CppScheduleOne.DevUtilities.Singleton<S1Screen>.Instance;
                open = screen != null && screen.IsOpen;
            }
            catch
            {
                return;                              // main menu: no naming screen
            }
            try
            {
                if (open && !_wasOpen)
                    OnOpened(screen);
                else if (!open && _wasOpen)
                    OnClosed();
                _wasOpen = open;
                if (!open)
                    return;
                _watch.Tick(_button);              // may call OnButton when the real click never came
                if (state != null)
                    Apply(screen, state);
                if (_mode == "asking" && Time.realtimeSinceStartup - _askedAt > AnswerTimeoutSec)
                {
                    _mode = "idle";
                    _note = "Stream Core didn't answer. Is it running with the Schedule I plugin on?";
                }
                Redraw();
            }
            catch (Exception ex)
            {
                if (!_warned)
                {
                    _warned = true;
                    _log.Warning("'Let chat name it' button off for this run: " + ex.Message);
                }
            }
        }

        private void OnOpened(S1Screen screen)
        {
            EnsureUi(screen);
            _mode = "idle";
            _note = "";
            _rows.Clear();
        }

        // The screen closed while chat was busy: the streamer named it (Confirm / Enter) or left with Esc.
        // Not called after our own Confirm press: _mode is already "idle" then.
        private void OnClosed()
        {
            if (_mode != "idle")
                Shared.AddEvent("mix_vote_stop", new Dictionary<string, object> { ["reason"] = "closed" });
            _mode = "idle";
        }

        // Our button's click, or ButtonWatch's stand-in for it. Errors are logged here because one thrown
        // inside a Unity button click can vanish without a trace (the button then just "does nothing").
        private void OnButton()
        {
            try
            {
                Press();
            }
            catch (Exception ex)
            {
                _log.Warning("'Let chat name it' press failed: " + ex);
                _mode = "idle";
                _note = "That didn't work (see the MelonLoader log).";
            }
        }

        private void Press()
        {
            var screen = Il2CppScheduleOne.DevUtilities.Singleton<S1Screen>.Instance;
            if (screen == null || !screen.IsOpen)
                return;
            _log.Msg($"'Let chat name it' pressed ({(_mode == "idle" ? "start" : "stop")})");
            if (_mode != "idle")
            {
                // second press: take the naming back
                Shared.AddEvent("mix_vote_stop", new Dictionary<string, object> { ["reason"] = "button" });
                _mode = "idle";
                _note = "You stopped chat's vote. Name it yourself or press the button again.";
                return;
            }
            _gamePick = screen.nameInputField.text ?? "";
            Shared.AddEvent("mix_vote", new Dictionary<string, object>
            {
                ["game_names"] = GameNames(screen),
                ["taken"] = TakenNames(),
                ["effects"] = Lines(EffectsText(screen)),
                ["value"] = Strip(screen.marketValueLabel.text).Replace("Market Value:", "").Trim(),
                ["current"] = _gamePick,
            });
            _mode = "asking";
            _askedAt = Time.realtimeSinceStartup;
            _note = "";
            Shared.AddFeed("You asked chat to name your new mix");
        }

        // Core's latest POST /mixvote (Shared.MixState). Ignored while idle: it belongs to a vote the
        // streamer already stopped, or to another screen.
        private void Apply(S1Screen screen, MixState s)
        {
            if (_mode == "idle")
                return;
            switch (s.state)
            {
                case "off":
                    _mode = "idle";
                    _note = string.IsNullOrEmpty(s.msg) ? "Chat naming is off in Stream Core" : s.msg;
                    break;
                case "suggest":
                case "vote":
                    _mode = s.state;
                    _endsAt = Time.realtimeSinceStartup + s.endsIn;
                    _rows = s.options ?? new List<MixOption>();
                    break;
                case "stopped":
                    _mode = "idle";
                    _note = "Chat's vote stopped.";
                    break;
                case "done":
                    _mode = "idle";
                    UseChatsPick(screen, s.ranked ?? new List<string>(), s.confirm);
                    break;
            }
        }

        // Type chat's names into the box, best first, until the game takes one (Confirm becomes
        // pressable: the name isn't already a product). Then press Confirm, or leave it to the streamer.
        private void UseChatsPick(S1Screen screen, List<string> ranked, bool confirm)
        {
            foreach (var name in ranked)
            {
                if (string.IsNullOrWhiteSpace(name))
                    continue;
                screen.nameInputField.text = name;   // the game re-checks the name (OnNameValueChanged)
                if (!screen.confirmButton.interactable)
                    continue;
                if (confirm)
                {
                    Shared.AddFeed($"Chat named your new mix {name}");
                    screen.ConfirmButtonClicked();   // names the mix and closes the screen, as a click would
                }
                else
                {
                    _note = $"Chat picked {Esc(name)}. Press Confirm (or change it).";
                }
                return;
            }
            screen.nameInputField.text = _gamePick;
            _note = "Every name chat picked is already taken: name it yourself.";
        }

        // The game's own name for this mix first (what the box shows when the screen opens), then a few
        // more from the game's two word lists (like its dice button), none already in the save.
        private List<string> GameNames(S1Screen screen)
        {
            var names = new List<string>();
            if (!string.IsNullOrWhiteSpace(_gamePick))
                names.Add(_gamePick);
            var first = screen.name1Library;
            var second = screen.name2Library;
            var products = Products();
            if (first == null || second == null || first.Count == 0 || second.Count == 0)
                return names;
            var rand = new System.Random();
            for (int tries = 0; tries < 50 && names.Count < GameIdeas; tries++)
            {
                var n = first[rand.Next(first.Count)] + " " + second[rand.Next(second.Count)];
                if (!names.Contains(n) && (products == null || !products.ProductNames.Contains(n)))
                    names.Add(n);
            }
            return names;
        }

        private static S1Products Products() =>
            Il2CppScheduleOne.DevUtilities.NetworkSingleton<S1Products>.Instance;

        // Product names already in this save: chat's ideas can't use them (the game refuses doubles).
        private static List<string> TakenNames()
        {
            var list = new List<string>();
            var names = Products()?.ProductNames;
            if (names == null)
                return list;
            for (int i = 0; i < names.Count && list.Count < MaxTaken; i++)
                list.Add(names[i]);
            return list;
        }

        private void Redraw()
        {
            string label, status;
            int secs = Mathf.Max(0, Mathf.CeilToInt(_endsAt - Time.realtimeSinceStartup));
            switch (_mode)
            {
                case "asking":
                    label = "Asking chat...";
                    status = "";
                    break;
                case "suggest":
                    label = $"Stop chat ({secs}s)";
                    status = $"Chat is suggesting names (!mixname): {secs}s";
                    foreach (var r in _rows)
                        status += $"\n{Esc(r.name)}  <color=#9A9AA8>x{r.votes}</color>";
                    break;
                case "vote":
                    label = $"Stop chat ({secs}s)";
                    status = $"Chat is voting: {secs}s";
                    for (int i = 0; i < _rows.Count; i++)
                        status += $"\n!{i + 1}  {Esc(_rows[i].name)}  <color=#54E717>{_rows[i].votes}</color>";
                    break;
                default:
                    label = ButtonText;
                    status = _note;
                    break;
            }
            if (_buttonLabel != null && label != _shownLabel)
            {
                _buttonLabel.text = label;
                _shownLabel = label;
            }
            if (_status != null && status != _shownStatus)
            {
                _status.text = status;
                _shownStatus = status;
            }
        }

        // Our button is a copy of the game's Confirm button (same look), placed just under it with its
        // click swapped for OnButton; the status text is a copy of the screen's "Market Value" label
        // under our button.
        private void EnsureUi(S1Screen screen)
        {
            if (_builtFor != null && _builtFor == screen && _button != null)
                return;
            var confirm = screen.confirmButton;
            var parent = confirm.transform.parent;
            var crt = confirm.GetComponent<RectTransform>();
            float h = crt.rect.height > 1f ? crt.rect.height : 50f;

            _button = UnityEngine.Object.Instantiate(confirm.gameObject, parent);
            _button.name = "FridgeChatNameButton";
            var btn = _button.GetComponent<Button>();
            btn.onClick = new Button.ButtonClickedEvent();   // drop the copied Confirm click
            btn.interactable = true;
            ButtonUtils.AddListener(btn, () => { _watch.Clicked(); OnButton(); });
            var rt = _button.GetComponent<RectTransform>();
            rt.anchoredPosition = crt.anchoredPosition + new Vector2(0f, -(h + 14f));
            _buttonLabel = _button.GetComponentInChildren<TMPText>(true);

            var statusGo = UnityEngine.Object.Instantiate(screen.marketValueLabel.gameObject, parent);
            statusGo.name = "FridgeChatNameStatus";
            _status = statusGo.GetComponent<TMPText>();
            _status.richText = true;
            _status.alignment = Il2CppTMPro.TextAlignmentOptions.Top;
            var srt = _status.rectTransform;
            srt.anchorMin = srt.anchorMax = crt.anchorMin;
            srt.pivot = new Vector2(0.5f, 1f);
            srt.sizeDelta = new Vector2(Mathf.Max(crt.rect.width * 2.5f, 460f), 280f);
            srt.anchoredPosition = rt.anchoredPosition + new Vector2(0f, -(h * 0.5f + 10f));

            _builtFor = screen;
            _shownLabel = _shownStatus = null;
            _log.Msg("'Let chat name it' button added to the new mix screen (" + ButtonWatch.Describe(_button) + ")");
        }

        // All effect lines on the screen as one newline-joined rich text, for Lines() below. The game
        // keeps one label per effect in propertiesLabels (up to NewMixScreen.MaxDisplayedProperties)
        // and hides the unused ones, so only the active labels count. Called from OnButton.
        private static string EffectsText(S1Screen screen)
        {
            var labels = screen.propertiesLabels;
            if (labels == null)
                return "";
            var parts = new List<string>();
            for (int i = 0; i < labels.Length; i++)
            {
                var l = labels[i];
                if (l != null && l.gameObject.activeSelf && !string.IsNullOrEmpty(l.text))
                    parts.Add(l.text);
            }
            return string.Join("\n", parts);
        }

        // The game's coloured "• Effect" lines as plain effect names.
        private static List<string> Lines(string richText)
        {
            var list = new List<string>();
            foreach (var line in Strip(richText).Split('\n'))
            {
                var t = line.Trim().TrimStart('•').Trim();
                if (t.Length > 0 && !t.EndsWith("more..."))
                    list.Add(t);
            }
            return list;
        }

        private static string Strip(string richText) => Regex.Replace(richText ?? "", "<.*?>", "");

        // Chat text shown in rich text: no tags of its own.
        private static string Esc(string s) => (s ?? "").Replace("<", "‹").Replace(">", "›");
    }
}
