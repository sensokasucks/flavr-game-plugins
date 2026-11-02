// The "Chat" app on the in-game phone: which chatter carries which customer, the waiting list,
// the top spenders, and a feed of chatter-customers' orders / deals and stream alerts.
//
// S1API finds this class by itself (any public PhoneApp subclass with a parameterless constructor)
// when the phone's home screen starts in the Main scene, and calls OnCreatedUI once per world load.
// Core.OnUpdate calls Tick() every frame; the lists are only rebuilt while the app is open and
// something changed (Shared's board / feed version numbers, or a tab press).
//
// Data: the lists come from Core (POST /board -> Shared.SetBoard; built by plugin.py's board()), or
// in a friend's co-op game from the host's mod (LobbySync.cs; no Remove / Swap buttons then),
// the feed from CustomerWatcher and Core.ShowNotice (Shared.AddFeed). The Remove and Swap buttons
// don't change anything here: they add "app_remove" / "app_swap" events that Core reads with
// GET /events and acts on (plugin.py handle_event), then sends the new names and board back.
// Everything in this file runs on the main thread (Unity UI).

using System;
using System.Collections.Generic;
using S1API.PhoneApp;
using S1API.UI;
using S1API.Utils;
using UnityEngine;
using UnityEngine.UI;

namespace FridgeSchedule1
{
    public class ChatApp : PhoneApp
    {
        private static readonly string[] Tabs = { "Customers", "Waiting", "Top", "Feed" };
        private static readonly Color Background = new Color(0.09f, 0.09f, 0.11f);
        private static readonly Color RowColor = new Color(0.16f, 0.16f, 0.2f);
        private static readonly Color TabOn = new Color(0.45f, 0.3f, 0.75f);     // matches the icon
        private static readonly Color TabOff = new Color(0.22f, 0.22f, 0.27f);
        private static readonly Color RemoveColor = new Color(0.6f, 0.2f, 0.2f);
        private static readonly Color SwapColor = new Color(0.25f, 0.4f, 0.6f);
        private static readonly Color FindColor = new Color(0.25f, 0.5f, 0.3f);

        /// <summary>The app as S1API created it for the current world; null on the main menu.</summary>
        internal static ChatApp Current { get; private set; }

        private static Sprite _icon;
        /// <summary>The app icon, drawn in code (no image file to ship). Also used for alert pop-ups.</summary>
        internal static Sprite Icon => _icon ??= MakeIcon();

        protected override string AppName => "FridgeChatCustomers";
        protected override string AppTitle => "Chat customers";
        protected override string IconLabel => "Chat";
        protected override string IconFileName => "";   // IconSprite is used instead
        protected override Sprite IconSprite => Icon;

        private RectTransform _list;          // scroll list content; rows are rebuilt into it
        private readonly List<(Image bg, int tab)> _tabButtons = new List<(Image, int)>();
        private int _tab;
        private int _shownBoard = -1;         // Shared versions the list was last built from
        private int _shownFeed = -1;
        private bool _dirty = true;           // tab pressed / Remove asked "Sure?": rebuild next Tick
        private string _confirmKey;           // the row whose Remove was pressed once (press again = remove)

        protected override void OnCreatedUI(GameObject container)
        {
            Current = this;
            _tabButtons.Clear();
            var panel = UIFactory.Panel("FridgeChatPanel", container.transform, Background, fullAnchor: true);

            // Tab row along the top 12% of the app.
            var tabs = UIFactory.Panel("Tabs", panel.transform, Background, new Vector2(0f, 0.88f), new Vector2(1f, 1f));
            var tabsRt = tabs.GetComponent<RectTransform>();
            tabsRt.offsetMin = tabsRt.offsetMax = Vector2.zero;
            UIFactory.HorizontalLayoutOnGO(tabs, 8, 10, 10, 6, 6);
            for (int i = 0; i < Tabs.Length; i++)
            {
                int tab = i;
                var (go, btn, _) = UIFactory.ButtonWithLabel("Tab" + Tabs[i], Tabs[i], tabs.transform, TabOff, 160, 44);
                _tabButtons.Add((go.GetComponent<Image>(), tab));
                ButtonUtils.AddListener(btn, () => { _tab = tab; _confirmKey = null; _dirty = true; });
            }

            // Scrolling list below the tabs.
            var body = UIFactory.Panel("Body", panel.transform, Background, new Vector2(0f, 0f), new Vector2(1f, 0.88f));
            var bodyRt = body.GetComponent<RectTransform>();
            bodyRt.offsetMin = bodyRt.offsetMax = Vector2.zero;
            _list = UIFactory.ScrollableVerticalList("List", body.transform, out _);
            _shownBoard = _shownFeed = -1;
            _dirty = true;
        }

        /// <summary>Every frame from Core.OnUpdate: rebuild the open tab when its data changed.</summary>
        internal void Tick()
        {
            if (_list == null || !IsOpen())
                return;
            var (board, boardVersion) = Shared.GetBoard();
            var (feed, feedVersion) = Shared.GetFeed();
            bool changed = _dirty
                || (_tab != 3 && boardVersion != _shownBoard)
                || (_tab == 3 && feedVersion != _shownFeed);
            if (!changed)
                return;
            _dirty = false;
            _shownBoard = boardVersion;
            _shownFeed = feedVersion;
            try
            {
                Rebuild(board, feed);
            }
            catch (Exception ex)
            {
                MelonLoader.MelonLogger.Warning("[FridgeSchedule1] phone app: " + ex.Message);
            }
        }

        private void Rebuild(Board board, List<string> feed)
        {
            foreach (var (bg, tab) in _tabButtons)
                bg.color = tab == _tab ? TabOn : TabOff;
            UIFactory.ClearChildren(_list);
            switch (_tab)
            {
                case 0:
                    if (board.named.Count == 0)
                        Line("No chatter has a customer yet. They type !customer in chat.");
                    foreach (var r in board.named)
                        CustomerRow(r);
                    break;
                case 1:
                    if (board.waiting.Count == 0)
                        Line("Nobody is waiting.");
                    for (int i = 0; i < board.waiting.Count; i++)
                        Line($"#{i + 1}  {board.waiting[i].name}  ({board.waiting[i].platform})");
                    break;
                case 2:
                    if (board.top.Count == 0)
                        Line("No chatter-customer has bought anything yet.");
                    for (int i = 0; i < board.top.Count; i++)
                    {
                        var r = board.top[i];
                        Line($"{i + 1}. {r.name}   ${r.spent:0}   ({r.deals} deals)");
                    }
                    break;
                default:
                    if (feed.Count == 0)
                        Line("Orders, deals and stream alerts show up here.");
                    foreach (var l in feed)
                        Line(l);
                    break;
            }
        }

        // One plain text row.
        private void Line(string text)
        {
            var row = UIFactory.Panel("Row", _list, RowColor);
            row.AddComponent<LayoutElement>().minHeight = 44;
            var t = UIFactory.Text("Text", text, row.transform, 20, TextAnchor.MiddleLeft);
            Fill(t.rectTransform, 14);
        }

        // A named customer with its Remove (press twice) and Swap buttons.
        private void CustomerRow(BoardRow r)
        {
            var row = UIFactory.Panel("Row", _list, RowColor);
            row.AddComponent<LayoutElement>().minHeight = 76;
            UIFactory.HorizontalLayoutOnGO(row, 10, 14, 10, 6, 6);
            var hl = row.GetComponent<HorizontalLayoutGroup>();
            hl.childControlWidth = true;
            hl.childForceExpandWidth = false;

            // Line 2: when they'll turn up (CustomerStatus.Describe, via Core's board) and how far away.
            var npc = CustomerWatcher.Instance?.Find(r.npc).npc;
            var away = CustomerStatus.Distance(npc);
            var t = UIFactory.Text("Text",
                $"{r.name} ({r.platform})  ->  {r.customer}   {r.deals} deals, ${r.spent:0}\n" +
                $"{r.status}{(away.Length > 0 ? "  ·  " + away : "")}",
                row.transform, 17, TextAnchor.MiddleLeft);
            t.gameObject.AddComponent<LayoutElement>().flexibleWidth = 1;

            // Find: a marker that follows the customer on this player's phone map (host and guests).
            var (fgo, fbtn, _) = UIFactory.ButtonWithLabel("Find", "Find", row.transform, FindColor, 80, 44);
            Fixed(fgo, 80, 44);
            ButtonUtils.AddListener(fbtn, () =>
            {
                Shared.AddFeed(CustomerStatus.Mark(CustomerWatcher.Instance?.Find(r.npc).npc, $"{r.name} ({r.customer})")
                    ? $"{r.name} ({r.customer}) is marked on your map" : $"can't find {r.customer} right now");
                _dirty = true;
            });
            if (Shared.Role == "client")
                return;          // co-op guest: the list is the host's (LobbySync.cs), so only the host edits it

            bool confirming = _confirmKey == r.key;
            var (rgo, rbtn, _) = UIFactory.ButtonWithLabel("Remove", confirming ? "Sure?" : "Remove", row.transform,
                RemoveColor, 110, 44);
            Fixed(rgo, 110, 44);
            ButtonUtils.AddListener(rbtn, () =>
            {
                if (_confirmKey != r.key)
                {
                    _confirmKey = r.key;      // first press only asks
                    _dirty = true;
                    return;
                }
                _confirmKey = null;
                Press("app_remove", r, $"Removed {r.name} from the customer list");
            });

            var (sgo, sbtn, _) = UIFactory.ButtonWithLabel("Swap", "Swap", row.transform, SwapColor, 90, 44);
            Fixed(sgo, 90, 44);
            ButtonUtils.AddListener(sbtn, () =>
                Press("app_swap", r, $"{r.name} went to the back of the line ({r.customer} is free for the next one)"));
        }

        protected override void OnDestroyed()
        {
            base.OnDestroyed();
            if (Current == this)
                Current = null;
            _list = null;
        }

        // Tell Core about a button press (an event it reads with GET /events) and note it in the feed.
        private void Press(string type, BoardRow r, string feedLine)
        {
            Shared.AddEvent(type, new Dictionary<string, object> { ["key"] = r.key, ["name"] = r.name });
            Shared.AddFeed(feedLine);
            _dirty = true;
        }

        private static void Fill(RectTransform rt, float padX)
        {
            rt.anchorMin = Vector2.zero;
            rt.anchorMax = Vector2.one;
            rt.offsetMin = new Vector2(padX, 0);
            rt.offsetMax = new Vector2(-padX, 0);
        }

        private static void Fixed(GameObject go, float w, float h)
        {
            var le = go.AddComponent<LayoutElement>();
            le.preferredWidth = le.minWidth = w;
            le.preferredHeight = le.minHeight = h;
        }

        // 128x128 purple rounded square with a white speech bubble.
        private static Sprite MakeIcon()
        {
            const int size = 128;
            var tex = new Texture2D(size, size);
            var bg = new Color(0.45f, 0.3f, 0.75f);
            for (int y = 0; y < size; y++)
            {
                for (int x = 0; x < size; x++)
                {
                    // rounded corners: outside a 24 px radius at each corner is transparent
                    float cx = Mathf.Clamp(x, 24, size - 25), cy = Mathf.Clamp(y, 24, size - 25);
                    bool inside = (x - cx) * (x - cx) + (y - cy) * (y - cy) <= 24 * 24;
                    // bubble: an ellipse in the middle plus a small tail at the bottom left
                    float ex = (x - 64) / 40f, ey = (y - 70) / 28f;
                    bool bubble = ex * ex + ey * ey <= 1f || (x >= 36 && x <= 52 && y >= 30 && y <= 46 && x - 36 >= 46 - y);
                    tex.SetPixel(x, y, !inside ? Color.clear : bubble ? Color.white : bg);
                }
            }
            tex.Apply();
            return Sprite.Create(tex, new Rect(0, 0, size, size), new Vector2(0.5f, 0.5f));
        }
    }
}
