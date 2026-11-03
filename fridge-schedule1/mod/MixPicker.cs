// "Let chat pick": a button on Schedule I's mixing station screen that lets chat vote on the next
// ingredient to mix in.
//
// The game's mixing station screen (MixingStationInterface, a Singleton like the other station
// screens; older game builds called it MixingStationCanvas) has a product slot, an ingredient slot and a
// Begin button. This file adds our button next to Begin and a short status text under it.
//
// Flow (each player's own screen and own Stream Core, host or co-op guest alike):
//   1. Button pressed -> event "mixpick" {"product", "carried", "nearby", "owned", "all"} for Core
//      (GET /events): the product in the station, the mixing ingredients on the player / also in
//      storage near the station / also in storage at any owned property, and every mixing ingredient
//      in the game (ProductManager.ValidMixIngredients).
//   2. Core (plugins/schedule1/mixpick.py) runs the vote (!1 !2 ...) and keeps sending where it is
//      (POST /mixpick -> CrewShared.SetPick).
//   3. State "done": the status text says "Chat picked Gasoline". With Core's mixpick_auto_place on
//      ("place": true) the winner is moved into the ingredient slot (Place) from the player's
//      inventory, or also from storage ("take_from": "nearby" / "owned", IngredientSources.cs);
//      otherwise the streamer puts it in. Begin is never pressed for them.
// Pressing the button again, or closing the screen, sends "mixpick_stop".
//
// Callers: Core.OnUpdate calls Tick() every frame. Main thread only (Unity UI). State names ("off",
// "vote", "done", "stopped") must match mixpick.py. The game's names for the screen's parts
// (IsOpen, BeginButton, InstructionLabel, Station.ProductSlot) come from its MixingStationInterface class;
// a game update that renames them makes Tick log one warning and leaves the screen as the game made it.

using System;
using System.Collections.Generic;
using MelonLoader;
using S1API.Utils;   // ButtonUtils (same as MixNamer.cs / ChatApp.cs)
using UnityEngine;
using UnityEngine.UI;
using S1Canvas = Il2CppScheduleOne.UI.Stations.MixingStationInterface;
using S1Products = Il2CppScheduleOne.Product.ProductManager;
using S1Inventory = Il2CppScheduleOne.PlayerScripts.PlayerInventory;
using TMPText = Il2CppTMPro.TextMeshProUGUI;

namespace FridgeSchedule1
{
    internal sealed class MixPicker
    {
        private const string ButtonText = "Let chat pick";
        private const float AnswerTimeoutSec = 6f;   // Core polls events every poll_sec (2 s by default)

        private readonly MelonLogger.Instance _log;
        private bool _wasOpen;
        private bool _warned;
        private string _mode = "idle";               // "idle", "asking" (pressed, no answer yet), "vote"
        private float _askedAt, _endsAt;             // realtime of the press / the vote's end
        private List<MixOption> _rows = new List<MixOption>();
        private string _note = "";                   // status text while idle

        private S1Canvas _builtFor;
        private GameObject _button;
        private TMPText _buttonLabel, _status;
        private string _shownLabel, _shownStatus;

        public MixPicker(MelonLogger.Instance log)
        {
            _log = log;
        }

        /// <summary>Every frame from Core.OnUpdate: notice the screen opening / closing, apply Core's
        /// latest vote state, redraw the button and status text.</summary>
        public void Tick()
        {
            var state = CrewShared.TakePick();
            S1Canvas canvas;
            bool open;
            try
            {
                canvas = Il2CppScheduleOne.DevUtilities.Singleton<S1Canvas>.Instance;
                open = canvas != null && canvas.IsOpen;
            }
            catch
            {
                return;                              // main menu: no station screen
            }
            try
            {
                if (open && !_wasOpen)
                {
                    EnsureUi(canvas);
                    _mode = "idle";
                    _note = "";
                }
                else if (!open && _wasOpen && _mode != "idle")
                {
                    Shared.AddEvent("mixpick_stop", new Dictionary<string, object> { ["reason"] = "closed" });
                    _mode = "idle";
                }
                _wasOpen = open;
                if (!open)
                    return;
                if (state != null)
                    Apply(state);
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
                    _log.Warning("'Let chat pick' button off for this run: " + ex.Message);
                }
            }
        }

        private void OnButton()
        {
            var canvas = Il2CppScheduleOne.DevUtilities.Singleton<S1Canvas>.Instance;
            if (canvas == null || !canvas.IsOpen)
                return;
            if (_mode != "idle")
            {
                Shared.AddEvent("mixpick_stop", new Dictionary<string, object> { ["reason"] = "button" });
                _mode = "idle";
                _note = "You stopped chat's vote.";
                return;
            }
            var (carried, nearby, owned, all) = Ingredients(canvas);
            Shared.AddEvent("mixpick", new Dictionary<string, object>
            {
                ["product"] = ProductName(canvas),
                ["carried"] = carried,
                ["nearby"] = nearby,
                ["owned"] = owned,
                ["all"] = all,
            });
            _mode = "asking";
            _askedAt = Time.realtimeSinceStartup;
            _note = "";
            Shared.AddFeed("You asked chat to pick an ingredient");
        }

        // Core's latest POST /mixpick. Ignored while idle (an old vote's leftovers).
        private void Apply(PickState s)
        {
            if (_mode == "idle")
                return;
            switch (s.state)
            {
                case "off":
                    _mode = "idle";
                    _note = string.IsNullOrEmpty(s.msg) ? "Chat picking is off in Stream Core" : s.msg;
                    break;
                case "vote":
                    _mode = "vote";
                    _endsAt = Time.realtimeSinceStartup + s.endsIn;
                    _rows = s.options ?? new List<MixOption>();
                    break;
                case "stopped":
                    _mode = "idle";
                    _note = "Chat's vote stopped.";
                    break;
                case "done":
                    _mode = "idle";
                    Shared.AddFeed($"Chat picked {s.winner} for your mix");
                    var placed = s.place ? Place(s.winner, s.takeFrom) : "";
                    _note = $"Chat picked <color=#54E717>{Esc(s.winner)}</color>. " +
                            (placed.Length > 0 ? placed : "Put it in and press Begin.");
                    break;
            }
        }

        // Core's mixpick_auto_place: move the winner into the station's ingredient slot
        // (MixingStation.MixerSlot), as many as there is product (capped by what fits and what there is),
        // from the places Core's mixpick_take_from names (IngredientSources: the player's inventory, then
        // storage near the station or at every owned property). The game then updates its preview by itself; StationContentsChanged
        // is called as well in case this build doesn't. Never presses Begin. Returns the status words.
        private string Place(string winner, string takeFrom)
        {
            try
            {
                var canvas = Il2CppScheduleOne.DevUtilities.Singleton<S1Canvas>.Instance;
                var station = canvas != null ? canvas.Station : null;
                var mixer = station != null ? station.MixerSlot : null;
                if (mixer == null)
                    return "Put it in and press Begin.";
                var id = IngredientId(winner);
                if (id == null)
                    return "Put it in and press Begin.";
                var inMixer = mixer.ItemInstance;
                if (inMixer != null && inMixer.Definition != null && inMixer.Definition.ID != id)
                    return $"Take {Esc(inMixer.Definition.Name)} out first, then put it in.";
                int product = station.ProductSlot != null ? station.ProductSlot.Quantity : 0;
                int want = Math.Max(1, product) - mixer.Quantity;
                if (want <= 0)
                    return "It's already in: press Begin.";
                int moved = 0;
                var slots = IngredientSources.Slots(takeFrom, station);   // the player's own slots first
                for (int i = 0; i < slots.Count && moved < want; i++)
                {
                    var slot = slots[i];
                    if (slot == null || slot.IsLocked || slot.IsRemovalLocked)
                        continue;                    // someone has that shelf open, or the game froze it
                    var item = slot?.ItemInstance;
                    if (item == null || item.Definition == null || item.Definition.ID != id || slot.Quantity <= 0)
                        continue;
                    int take = Math.Min(want - moved, slot.Quantity);
                    var copy = item.GetCopy(take);
                    take = Math.Min(take, mixer.GetCapacityForItem(copy, true));
                    if (take <= 0)
                        break;
                    if (mixer.ItemInstance == null)
                        mixer.InsertItem(item.GetCopy(take));
                    else
                        mixer.ChangeQuantity(take, false);
                    slot.ChangeQuantity(-take, false);
                    moved += take;
                }
                try { canvas.StationContentsChanged(); } catch { /* the game redraws on its own */ }
                if (moved == 0)
                    return takeFrom == "carried" || string.IsNullOrEmpty(takeFrom)
                        ? "You don't carry any: go get some, then press Begin."
                        : "None in your inventory or storage: go get some, then press Begin.";
                Shared.AddFeed($"Put {moved}x {winner} in the mixing station");
                return moved < want ? $"Put in the {moved} you have. Press Begin." : "It's in: press Begin.";
            }
            catch (Exception ex)
            {
                _log.Warning("couldn't put chat's ingredient in: " + ex.Message);
                return "Put it in and press Begin.";
            }
        }

        // The game id of the mixing ingredient called <paramref name="name"/> (ProductManager.ValidMixIngredients).
        private static string IngredientId(string name)
        {
            var valid = Il2CppScheduleOne.DevUtilities.NetworkSingleton<S1Products>.Instance?.ValidMixIngredients;
            for (int i = 0; valid != null && i < valid.Count; i++)
                if (valid[i] != null && string.Equals(valid[i].Name, name, StringComparison.OrdinalIgnoreCase))
                    return valid[i].ID;
            return null;
        }

        // The product in the station ("" when the slot is empty: chat can still vote ahead).
        private static string ProductName(S1Canvas canvas)
        {
            try
            {
                var item = canvas.Station?.ProductSlot?.ItemInstance;
                return item?.Definition != null ? item.Definition.Name ?? "" : "";
            }
            catch
            {
                return "";
            }
        }

        // Mixing ingredients by display name: on the player ("carried"), on the player + storage near
        // the station ("nearby"), on the player + storage at every owned property ("owned"), and every
        // mixing ingredient in the game ("all"). Core's mixpick_take_from picks which of the first three
        // the vote uses (mixpick.py); the same places are where Place takes the winner from.
        private static (List<string> carried, List<string> nearby, List<string> owned, List<string> all) Ingredients(S1Canvas canvas)
        {
            var all = new List<string>();
            var ids = new Dictionary<string, string>();
            var valid = Il2CppScheduleOne.DevUtilities.NetworkSingleton<S1Products>.Instance?.ValidMixIngredients;
            for (int i = 0; valid != null && i < valid.Count; i++)
            {
                if (valid[i] == null)
                    continue;
                ids[valid[i].ID] = valid[i].Name;
                all.Add(valid[i].Name);
            }
            var station = canvas != null ? canvas.Station : null;
            return (Names(IngredientSources.Slots("carried", station), ids),
                    Names(IngredientSources.Slots("nearby", station), ids),
                    Names(IngredientSources.Slots("owned", station), ids), all);
        }

        private static List<string> Names(List<Il2CppScheduleOne.ItemFramework.ItemSlot> slots, Dictionary<string, string> ids)
        {
            var names = new List<string>();
            foreach (var slot in slots)
            {
                try
                {
                    var def = slot?.ItemInstance?.Definition;
                    if (def != null && slot.Quantity > 0 && ids.TryGetValue(def.ID, out var name) && !names.Contains(name))
                        names.Add(name);
                }
                catch { /* a slot that went away */ }
            }
            return names;
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
                case "vote":
                    label = $"Stop chat ({secs}s)";
                    status = $"Chat is picking: {secs}s";
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

        // Our button is a copy of the game's Begin button placed under it with its click swapped for
        // OnButton; the status text is a copy of the screen's instruction label under our button.
        private void EnsureUi(S1Canvas canvas)
        {
            if (_builtFor != null && _builtFor == canvas && _button != null)
                return;
            var begin = canvas.BeginButton;
            var parent = begin.transform.parent;
            var brt = begin.GetComponent<RectTransform>();
            float h = brt.rect.height > 1f ? brt.rect.height : 50f;

            _button = UnityEngine.Object.Instantiate(begin.gameObject, parent);
            _button.name = "FridgeChatPickButton";
            _button.SetActive(true);
            var btn = _button.GetComponent<Button>();
            btn.onClick = new Button.ButtonClickedEvent();   // drop the copied Begin click
            btn.interactable = true;
            ButtonUtils.AddListener(btn, () => OnButton());
            var rt = _button.GetComponent<RectTransform>();
            rt.anchoredPosition = brt.anchoredPosition + new Vector2(0f, -(h + 14f));
            _buttonLabel = _button.GetComponentInChildren<TMPText>(true);

            var statusGo = UnityEngine.Object.Instantiate(canvas.InstructionLabel.gameObject, parent);
            statusGo.name = "FridgeChatPickStatus";
            statusGo.SetActive(true);
            _status = statusGo.GetComponent<TMPText>();
            _status.richText = true;
            _status.alignment = Il2CppTMPro.TextAlignmentOptions.Top;
            var srt = _status.rectTransform;
            srt.anchorMin = srt.anchorMax = brt.anchorMin;
            srt.pivot = new Vector2(0.5f, 1f);
            srt.sizeDelta = new Vector2(Mathf.Max(brt.rect.width * 2.5f, 420f), 240f);
            srt.anchoredPosition = rt.anchoredPosition + new Vector2(0f, -(h * 0.5f + 10f));

            _builtFor = canvas;
            _shownLabel = _shownStatus = null;
            _log.Msg("'Let chat pick' button added to the mixing station screen");
        }

        private static string Esc(string s) => (s ?? "").Replace("<", "‹").Replace(">", "›");
    }
}
