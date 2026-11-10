// Backup click check for our two chat buttons ("Let chat name it" in MixNamer.cs, "Let chat pick" in
// MixPicker.cs).
//
// Why: in a co-op game (2026-11-10, Sen hosting) pressing either button did nothing at all, and the
// game never ran the button's click (no log line, no event for Stream Core), while the same buttons
// worked in a solo game the same evening. Something in co-op stops Unity's click from reaching our
// copied button. This class watches the mouse itself:
//   - When the left button is let go over our button and the button's own click didn't run in that
//     frame or the next, it runs the click for it (Fire), so the vote starts anyway.
//   - The first few times that happens per game run, it logs which UI objects were under the mouse
//     (Unity's EventSystem raycast), so the MelonLoader log names what is covering the button.
//
// Callers: MixNamer.Tick / MixPicker.Tick call Tick() every frame while their screen is open, and
// their own click handler calls Clicked() so a normal click isn't run twice. Main thread only.
// Mouse input comes from Unity's Input System package (Unity.InputSystem.dll, the one the game uses);
// if reading it fails, the check switches itself off for the run with one warning and the buttons
// work exactly as before.

using System;
using MelonLoader;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;
using UnityEngine.UI;

namespace FridgeSchedule1
{
    internal sealed class ButtonWatch
    {
        private const int MaxDiagnoseLogs = 3;     // raycast reports per button per game run

        private readonly MelonLogger.Instance _log;
        private readonly string _what;             // button name for log lines ("Let chat pick")
        private readonly Action _fire;             // the button's click handler (OnButton)
        private int _clickedFrame = -10;           // Time.frameCount of the last real click (Clicked)
        private int _releasedFrame = -1;           // frame the mouse was let go over our button, -1 = none
        private int _diagnosed;
        private bool _off;                         // input reading failed once: stop for this run

        public ButtonWatch(MelonLogger.Instance log, string what, Action fire)
        {
            _log = log;
            _what = what;
            _fire = fire;
        }

        /// <summary>From the button's own onClick (before it does anything else): the click arrived the
        /// normal way, so Tick must not run it again.</summary>
        public void Clicked() => _clickedFrame = Time.frameCount;

        /// <summary>Every frame while the screen holding <paramref name="button"/> is open.</summary>
        public void Tick(GameObject button)
        {
            if (_off || button == null || !button.activeInHierarchy)
                return;
            try
            {
                // A release seen two frames ago with no real click since: Unity's click never came.
                if (_releasedFrame >= 0 && Time.frameCount >= _releasedFrame + 2)
                {
                    int released = _releasedFrame;
                    _releasedFrame = -1;
                    if (_clickedFrame < released)
                    {
                        Diagnose();
                        _log.Msg($"'{_what}': the game didn't pass the click on, pressing it for you");
                        _fire();
                    }
                }

                var mouse = Mouse.current;
                if (mouse == null || !mouse.leftButton.wasReleasedThisFrame)
                    return;
                if (Over(button, mouse.position.ReadValue()))
                    _releasedFrame = Time.frameCount;
            }
            catch (Exception ex)
            {
                _off = true;
                _log.Warning($"'{_what}' backup click check off for this run: {ex.Message}");
            }
        }

        // Is the screen point inside the button's rectangle? The camera is null for an overlay canvas
        // (Unity's rule for RectangleContainsScreenPoint), else the canvas's own camera.
        private static bool Over(GameObject button, Vector2 point)
        {
            var rt = button.GetComponent<RectTransform>();
            var canvas = button.GetComponentInParent<Canvas>();
            if (rt == null)
                return false;
            Camera cam = null;
            if (canvas != null && canvas.renderMode != RenderMode.ScreenSpaceOverlay)
                cam = canvas.worldCamera;
            return RectTransformUtility.RectangleContainsScreenPoint(rt, point, cam);
        }

        // Log what Unity's EventSystem finds under the mouse, top first, and whether our button can take
        // clicks at all (interactable, raycast target, the CanvasGroups above it).
        private void Diagnose()
        {
            if (_diagnosed >= MaxDiagnoseLogs)
                return;
            _diagnosed++;
            try
            {
                var es = EventSystem.current;
                var mouse = Mouse.current;
                if (es == null || mouse == null)
                {
                    _log.Msg($"'{_what}' click check: no EventSystem ({es == null}) or mouse ({mouse == null})");
                    return;
                }
                var data = new PointerEventData(es) { position = mouse.position.ReadValue() };
                var hits = new Il2CppSystem.Collections.Generic.List<RaycastResult>();
                es.RaycastAll(data, hits);
                var names = "";
                for (int i = 0; i < hits.Count && i < 6; i++)
                {
                    var go = hits[i].gameObject;
                    names += (i > 0 ? "  |  " : "") + (go != null ? Path(go.transform) : "?");
                }
                _log.Msg($"'{_what}' click check: {hits.Count} UI object(s) under the mouse, top first: " +
                         (names.Length > 0 ? names : "(none)") +
                         $"; selected: {(es.currentSelectedGameObject != null ? es.currentSelectedGameObject.name : "none")}");
            }
            catch (Exception ex)
            {
                _log.Msg($"'{_what}' click check couldn't list what's under the mouse: {ex.Message}");
            }
        }

        // "Canvas/Panel/Button" (last three levels), enough to recognise the object in the log.
        private static string Path(Transform t)
        {
            var path = t.name;
            for (int i = 0; i < 2 && t.parent != null; i++)
            {
                t = t.parent;
                path = t.name + "/" + path;
            }
            return path;
        }

        /// <summary>One log line about why our button might not take clicks, from EnsureUi after it is
        /// built: interactable, its picture's raycastTarget, and any CanvasGroup above it that blocks.</summary>
        public static string Describe(GameObject button)
        {
            try
            {
                var btn = button.GetComponent<Button>();
                var img = button.GetComponent<Graphic>();
                var groups = button.GetComponentsInParent<CanvasGroup>(true);
                var blocked = "";
                for (int i = 0; groups != null && i < groups.Length; i++)
                    if (groups[i] != null && (!groups[i].interactable || !groups[i].blocksRaycasts))
                        blocked += $" {groups[i].name}(interactable {groups[i].interactable}, blocks {groups[i].blocksRaycasts})";
                return $"interactable {btn != null && btn.interactable}, raycast target {img != null && img.raycastTarget}" +
                       (blocked.Length > 0 ? ", canvas groups off:" + blocked : "");
            }
            catch (Exception ex)
            {
                return "couldn't read: " + ex.Message;
            }
        }
    }
}
