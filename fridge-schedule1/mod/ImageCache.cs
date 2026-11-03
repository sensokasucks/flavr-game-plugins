// Pictures for the Chat app's Alerts tab: the alert's picture from Stream Core (the kind's picture
// picked on Core's alert page, or a sticker / gift image), downloaded once and kept as a Sprite.
//
// Callers: ChatApp asks Get(url) while drawing an alert card; Core.OnUpdate calls Tick() every frame
// to turn finished downloads into textures (Unity objects only on the main thread). Downloads run
// on a worker thread with a short timeout and a size cap; PNG and JPG only (Unity's LoadImage),
// so a GIF or video picture simply isn't shown. Version goes up when a picture arrives so the app
// redraws the tab.

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading.Tasks;
using UnityEngine;

namespace FridgeSchedule1
{
    internal static class ImageCache
    {
        private const int MaxBytes = 2 * 1024 * 1024;   // a picture bigger than this isn't fetched
        private const int MaxPictures = 40;             // kept sprites; the oldest go first

        private static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
        private static readonly Dictionary<string, Sprite> Sprites = new Dictionary<string, Sprite>();
        private static readonly List<string> Order = new List<string>();
        private static readonly HashSet<string> Asked = new HashSet<string>();     // started or failed
        private static readonly ConcurrentQueue<(string url, byte[] data)> Done = new ConcurrentQueue<(string, byte[])>();

        /// <summary>Goes up whenever a picture becomes ready (ChatApp redraws the Alerts tab).</summary>
        public static int Version { get; private set; }

        /// <summary>The picture, or null while it downloads / when there is none. Main thread.</summary>
        public static Sprite Get(string url)
        {
            if (string.IsNullOrEmpty(url))
                return null;
            if (Sprites.TryGetValue(url, out var s))
                return s;
            if (Asked.Add(url))
                Task.Run(() => Fetch(url));
            return null;
        }

        /// <summary>Every frame from Core.OnUpdate: finished downloads become sprites.</summary>
        public static void Tick()
        {
            while (Done.TryDequeue(out var item))
            {
                try
                {
                    var tex = new Texture2D(2, 2);
                    if (!ImageConversion.LoadImage(tex, item.data))
                        continue;                           // not a PNG / JPG
                    Sprites[item.url] = Sprite.Create(tex, new Rect(0, 0, tex.width, tex.height), new Vector2(0.5f, 0.5f));
                    Order.Add(item.url);
                    if (Order.Count > MaxPictures)
                    {
                        Sprites.Remove(Order[0]);
                        Asked.Remove(Order[0]);
                        Order.RemoveAt(0);
                    }
                    Version++;
                }
                catch (Exception ex)
                {
                    MelonLoader.MelonLogger.Warning("[FridgeSchedule1] alert picture: " + ex.Message);
                }
            }
        }

        // Worker thread: fetch the bytes (no Unity calls here).
        private static async Task Fetch(string url)
        {
            try
            {
                using var resp = await Http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead);
                if (!resp.IsSuccessStatusCode || (resp.Content.Headers.ContentLength ?? 0) > MaxBytes)
                    return;
                var data = await resp.Content.ReadAsByteArrayAsync();
                if (data.Length > 0 && data.Length <= MaxBytes)
                    Done.Enqueue((url, data));
            }
            catch
            {
                // offline / not found: the card shows without a picture
            }
        }
    }
}
