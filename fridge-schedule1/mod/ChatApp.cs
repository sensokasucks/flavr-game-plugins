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
        private const float SafeMargin = 0.035f;   // fraction of the app area kept clear on every side (bezel)
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
        private RectTransform _body;          // the list's area; its height sets row and font sizes (Scale)
        private float _rowH = 76f;            // customer row height in UI units (Scale); other rows are fractions of it
        private bool _loggedSize;             // sizes logged once, to check against the real phone canvas
        private readonly List<(Image bg, int tab)> _tabButtons = new List<(Image, int)>();
        private int _tab;
        private int _shownBoard = -1;         // Shared versions the list was last built from
        private int _shownFeed = -1;
        private int _shownFind = -1;          // CustomerStatus.FindVersion the Finding bar was drawn for
        private bool _dirty = true;           // tab pressed / Remove asked "Sure?": rebuild next Tick
        private string _confirmKey;           // the row whose Remove was pressed once (press again = remove)

        protected override void OnCreatedUI(GameObject container)
        {
            Current = this;
            _tabButtons.Clear();
            // Everything is placed with anchors (fractions of the app area), never fixed pixel widths, so it
            // fits whatever size the phone gives the app. The phone's bezel covers the app's edges a little
            // (Sen's screenshot, 2026-11-02), so the content sits inside a safe margin.
            var back = UIFactory.Panel("FridgeChatBack", container.transform, Background, fullAnchor: true);
            var panel = UIFactory.Panel("FridgeChatPanel", back.transform, Background);
            Place(panel, SafeMargin, SafeMargin, 1f - SafeMargin, 1f - SafeMargin);

            // Tab row: the top 13%, four equal buttons.
            for (int i = 0; i < Tabs.Length; i++)
            {
                int tab = i;
                var (go, btn, _) = UIFactory.ButtonWithLabel("Tab" + Tabs[i], Tabs[i], panel.transform, TabOff, 0, 0);
                Place(go, i / (float)Tabs.Length + 0.005f, 0.87f, (i + 1) / (float)Tabs.Length - 0.005f, 1f);
                _tabButtons.Add((go.GetComponent<Image>(), tab));
                ButtonUtils.AddListener(btn, () => { _tab = tab; _confirmKey = null; _dirty = true; });
            }

            // Scrolling list below the tabs. Rows are stretched to the list's width (the default left them
            // at their own preferred width, centred, so long rows were cut off on both sides).
            var body = UIFactory.Panel("Body", panel.transform, Background);
            Place(body, 0f, 0f, 1f, 0.85f);
            _body = body.GetComponent<RectTransform>();
            _list = UIFactory.ScrollableVerticalList("List", body.transform, out _);
            // The content box is made with a new RectTransform's default 100 px extra width; stretched
            // between the viewport's edges that made it 100 px too wide and, centred, every row lost
            // 50 px on each side (Sen's screenshot, 2026-11-02). Exactly the viewport's width:
            _list.offsetMin = new Vector2(0f, _list.offsetMin.y);
            _list.offsetMax = new Vector2(0f, _list.offsetMax.y);
            _list.sizeDelta = new Vector2(0f, _list.sizeDelta.y);
            var vl = _list.GetComponent<VerticalLayoutGroup>();
            vl.childControlWidth = true;
            vl.childForceExpandWidth = true;
            vl.padding = new RectOffset(4, 4, 4, 4);
            vl.spacing = 6;
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
                || (_tab == 3 && feedVersion != _shownFeed)
                || (_tab == 0 && CustomerStatus.FindVersion != _shownFind);
            _shownFind = CustomerStatus.FindVersion;
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
            Scale();
            UIFactory.ClearChildren(_list);
            switch (_tab)
            {
                case 0:
                    if (CustomerStatus.FindingLabel != null)
                        FindingRow();
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

        // One plain text row: wraps inside the row, shrinks a little rather than spilling out.
        private void Line(string text)
        {
            var row = UIFactory.Panel("Row", _list, RowColor);
            row.AddComponent<LayoutElement>().minHeight = _rowH * 0.6f;
            Label(row, text, Font(), 0f, 1f);
        }

        // "Finding zackfan99 (Kyle Cooley)" with a Stop button, at the top of the Customers tab while
        // CustomerStatus has a Find marker out.
        private void FindingRow()
        {
            var row = UIFactory.Panel("Finding", _list, new Color(0.15f, 0.3f, 0.2f));
            row.AddComponent<LayoutElement>().minHeight = _rowH * 0.7f;
            Label(row, $"Finding {CustomerStatus.FindingLabel}: it's on your map", Font(), 0f, 0.78f);
            var (go, btn, _) = UIFactory.ButtonWithLabel("Stop", "Stop", row.transform, RemoveColor, 0, 0);
            Place(go, 0.8f, 0.15f, 0.99f, 0.85f);
            ButtonUtils.AddListener(btn, () => { CustomerStatus.StopFinding("stopped"); _dirty = true; });
            ScaleButtons(row);
        }

        // A named customer: two lines of text on the left 62%, then Find / Remove (press twice) / Swap
        // in fixed slots on the right. Co-op guests only get Find (the host edits the list).
        private void CustomerRow(BoardRow r)
        {
            var row = UIFactory.Panel("Row", _list, RowColor);
            row.AddComponent<LayoutElement>().minHeight = _rowH;

            // Line 2: when they'll turn up (CustomerStatus.Describe, via Core's board) and how far away.
            var npc = CustomerWatcher.Instance?.Find(r.npc).npc;
            var away = CustomerStatus.Distance(npc);
            bool guest = Shared.Role == "client";
            // Deals / money are the chatter's totals over every customer they've had, hence "total".
            Label(row, $"{r.name} ({r.platform}) · {Deals(r.deals)}, ${r.spent:0} total -> {r.customer}\n" +
                       $"{r.status}{(away.Length > 0 ? "  ·  " + away : "")}", Font(), 0f, guest ? 0.8f : 0.62f);

            // Find: a marker on this player's phone map until Stop, arrival or FindMinutes (CustomerStatus).
            var (fgo, fbtn, _) = UIFactory.ButtonWithLabel("Find", "Find", row.transform, FindColor, 0, 0);
            Place(fgo, guest ? 0.82f : 0.635f, 0.2f, guest ? 0.99f : 0.75f, 0.8f);
            ButtonUtils.AddListener(fbtn, () =>
            {
                Shared.AddFeed(CustomerStatus.Mark(CustomerWatcher.Instance?.Find(r.npc).npc, $"{r.name} ({r.customer})")
                    ? $"{r.name} ({r.customer}) is marked on your map" : $"can't find {r.customer} right now");
                _dirty = true;
            });
            if (guest)
            {
                ScaleButtons(row);
                return;          // co-op guest: the list is the host's (LobbySync.cs), so only the host edits it
            }

            bool confirming = _confirmKey == r.key;
            var (rgo, rbtn, _) = UIFactory.ButtonWithLabel("Remove", confirming ? "Sure?" : "Remove", row.transform,
                RemoveColor, 0, 0);
            Place(rgo, 0.76f, 0.2f, 0.875f, 0.8f);
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

            var (sgo, sbtn, _) = UIFactory.ButtonWithLabel("Swap", "Swap", row.transform, SwapColor, 0, 0);
            Place(sgo, 0.885f, 0.2f, 0.985f, 0.8f);
            ButtonUtils.AddListener(sbtn, () =>
                Press("app_swap", r, $"{r.name} went to the back of the line ({r.customer} is free for the next one)"));
            ScaleButtons(row);
        }

        // UIFactory buttons come with a fixed 16 px label; match the row's font instead.
        private void ScaleButtons(GameObject row)
        {
            foreach (var t in row.GetComponentsInChildren<Text>())
                if (t != null && t.gameObject.name == "Label")
                    t.fontSize = Font();
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

        // Row and font sizes from the list's real height (the phone canvas), worked out on every rebuild:
        // a customer row is 15% of the list area (two to three lines readable at the tabs' scale), the
        // font a quarter of that. Logs the sizes once so a wrong-looking phone can be checked.
        private void Scale()
        {
            float h = _body != null ? _body.rect.height : 0f;
            if (h > 50f)
                _rowH = Mathf.Max(56f, h * 0.15f);
            if (!_loggedSize && _body != null)
            {
                _loggedSize = true;
                MelonLoader.MelonLogger.Msg($"[FridgeSchedule1] phone app list {_body.rect.width:0}x{h:0}, list content " +
                                            $"{_list.rect.width:0} wide, row {_rowH:0}, font {Font()}");
            }
        }

        private int Font() => Mathf.Clamp(Mathf.RoundToInt(_rowH * 0.24f), 14, 40);

        // "1 deal" / "3 deals"
        private static string Deals(int n) => n == 1 ? "1 deal" : $"{n} deals";

        // Text filling the row between the fractions x0..x1 of its width, left-aligned with a left margin;
        // wraps, and shrinks (down to 11) rather than spill out of the row.
        private static void Label(GameObject row, string text, int size, float x0, float x1)
        {
            var t = UIFactory.Text("Text", text, row.transform, size, TextAnchor.MiddleLeft);
            t.resizeTextForBestFit = true;
            t.resizeTextMinSize = 11;
            t.resizeTextMaxSize = size;
            t.verticalOverflow = VerticalWrapMode.Truncate;
            var rt = t.rectTransform;
            rt.anchorMin = new Vector2(x0, 0f);
            rt.anchorMax = new Vector2(x1, 1f);
            rt.offsetMin = new Vector2(10, 2);
            rt.offsetMax = new Vector2(-6, -2);
        }

        // Pin a UI object to fractions of its parent (0..1 on each axis), with no fixed pixel size.
        private static void Place(GameObject go, float x0, float y0, float x1, float y1)
        {
            var rt = go.GetComponent<RectTransform>();
            rt.anchorMin = new Vector2(x0, y0);
            rt.anchorMax = new Vector2(x1, y1);
            rt.offsetMin = rt.offsetMax = Vector2.zero;
            rt.sizeDelta = Vector2.zero;
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
