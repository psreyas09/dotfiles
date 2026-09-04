#!/usr/bin/env python3
import os
import sys
import time
import json
import signal
import subprocess

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GtkLayerShell, GLib, GdkPixbuf

PID_FILE = "/tmp/niri_window_switcher.pid"

def toggle_or_cycle():
    # If already running, send signal to cycle forward or backward
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            sig = signal.SIGUSR2 if "--prev" in sys.argv else signal.SIGUSR1
            os.kill(pid, sig)
            sys.exit(0)
        except (OSError, ValueError):
            try:
                os.remove(PID_FILE)
            except OSError:
                pass

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

def cleanup(*_):
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except OSError:
        pass
    Gtk.main_quit()

def get_niri_windows():
    """
    Safely query all open windows from Niri without crashing on null fields.
    Sorts in Most-Recently-Used (MRU) order.
    """
    try:
        res = subprocess.run(
            ["niri", "msg", "-j", "windows"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2
        )
        if res.returncode != 0:
            return []
        raw = json.loads(res.stdout)
        windows = []
        for w in raw:
            win_id = w.get("id")
            if win_id is None:
                continue
            title = w.get("title") or ""
            app_id = w.get("app_id") or ""
            ws_id = w.get("workspace_id") or 1
            is_focused = bool(w.get("is_focused", False))
            
            # Safe extraction of focus timestamp (handles null/None)
            ts = w.get("focus_timestamp")
            secs = 0
            nanos = 0
            if isinstance(ts, dict):
                secs = ts.get("secs") or 0
                nanos = ts.get("nanos") or 0

            windows.append({
                "id": win_id,
                "title": title,
                "app_id": app_id,
                "workspace_id": ws_id,
                "is_focused": is_focused,
                "secs": secs,
                "nanos": nanos
            })

        # Sort MRU: most recently focused first
        windows.sort(key=lambda x: (x["secs"], x["nanos"]), reverse=True)
        return windows
    except Exception:
        return []

def format_app_name(app_id, title=""):
    if not app_id:
        return title or "Window"
    aid = app_id.lower()
    if "zen" in aid:
        return "Zen Browser"
    if "kitty" in aid or "alacritty" in aid or "foot" in aid or "wezterm" in aid:
        return "Terminal"
    if "tauon" in aid:
        return "Tauon Music"
    if "rambox" in aid:
        return "Rambox"
    if "nautilus" in aid:
        return "Finder"
    if "chrome" in aid or "chromium" in aid:
        return "Google Chrome"
    if "firefox" in aid:
        return "Firefox"
    if "code" in aid or "codium" in aid:
        return "VS Code"
    if "discord" in aid or "vesktop" in aid:
        return "Discord"
    if "spotify" in aid:
        return "Spotify"
    if "steam" in aid:
        return "Steam"
    if "blueman" in aid:
        return "Bluetooth Settings"
    if "pavucontrol" in aid:
        return "Sound Settings"
    if "settings" in aid:
        return "System Settings"

    last = app_id.split(".")[-1]
    return last.replace("-", " ").replace("_", " ").title()

_APP_MAP = {}
_DESKTOP_INFO_CACHE = {}

def get_app_info_map():
    global _APP_MAP
    if _APP_MAP:
        return _APP_MAP
    try:
        for app in Gio.AppInfo.get_all():
            did = (app.get_id() or "").replace(".desktop", "").lower()
            if did:
                _APP_MAP[did] = app
            if hasattr(app, "get_startup_wm_class"):
                wm = app.get_startup_wm_class()
                if wm:
                    _APP_MAP[wm.lower()] = app
            name = (app.get_name() or "").lower()
            if name and name not in _APP_MAP:
                _APP_MAP[name] = app
    except Exception:
        pass
    return _APP_MAP


def find_desktop_info(item):
    app_ids = tuple(item.get("app_ids", []))
    name = item.get("name", "")
    cache_key = (app_ids, name)
    if cache_key in _DESKTOP_INFO_CACHE:
        return _DESKTOP_INFO_CACHE[cache_key]

    app_map = get_app_info_map()

    for aid in app_ids:
        if not aid:
            continue
        al = aid.lower()
        if al in app_map:
            _DESKTOP_INFO_CACHE[cache_key] = app_map[al]
            return app_map[al]
        al_clean = al.replace(".desktop", "")
        if al_clean in app_map:
            _DESKTOP_INFO_CACHE[cache_key] = app_map[al_clean]
            return app_map[al_clean]
        last = al_clean.split(".")[-1]
        if last in app_map:
            _DESKTOP_INFO_CACHE[cache_key] = app_map[last]
            return app_map[last]

    if name:
        nl = name.lower()
        if nl in app_map:
            _DESKTOP_INFO_CACHE[cache_key] = app_map[nl]
            return app_map[nl]
        nl_slug = nl.replace(" ", "-")
        if nl_slug in app_map:
            _DESKTOP_INFO_CACHE[cache_key] = app_map[nl_slug]
            return app_map[nl_slug]

    for key, app in app_map.items():
        for aid in app_ids:
            if not aid:
                continue
            al = aid.lower()
            if len(al) >= 3 and (al in key or key in al):
                _DESKTOP_INFO_CACHE[cache_key] = app
                return app
        if name and len(name) >= 3:
            nl = name.lower()
            if nl in key or key in nl:
                _DESKTOP_INFO_CACHE[cache_key] = app
                return app

    _DESKTOP_INFO_CACHE[cache_key] = None
    return None


def get_app_icon_pixbuf(app_id, title="", size=64):
    theme = Gtk.IconTheme.get_default()
    aid = (app_id or "").lower()
    t = (title or "").lower()

    # 1. Resolve via DesktopAppInfo / AppInfo map
    dinfo = find_desktop_info({"app_ids": [app_id] if app_id else [], "name": title})
    if dinfo and dinfo.get_icon():
        gicon = dinfo.get_icon()
        info = theme.lookup_by_gicon(gicon, size, 0)
        if info:
            try:
                pb = info.load_icon()
                if pb:
                    return pb
            except Exception:
                pass

    # Direct Desktop candidates fallback
    desktop_cands = [
        f"{app_id}.desktop" if app_id else "",
        f"{aid}.desktop" if aid else "",
        "google-chrome.desktop" if "chrome" in aid or "chrome" in t else "",
        "com.google.Chrome.desktop" if "chrome" in aid or "chrome" in t else "",
        "code.desktop" if "code" in aid or "code" in t else "",
        "discord.desktop" if "discord" in aid or "discord" in t else "",
        "com.spotify.Client.desktop" if "spotify" in aid or "spotify" in t else "",
        "steam.desktop" if "steam" in aid or "steam" in t else "",
    ]
    for d in desktop_cands:
        if not d:
            continue
        try:
            di = Gio.DesktopAppInfo.new(d)
            if di and di.get_icon():
                gicon = di.get_icon()
                info = theme.lookup_by_gicon(gicon, size, 0)
                if info:
                    pb = info.load_icon()
                    if pb:
                        return pb
        except Exception:
            pass

    # 2. Candidate icon names
    candidates = []
    if app_id:
        candidates.append(app_id)
        candidates.append(aid)
        candidates.append(app_id.split(".")[-1])
        candidates.append(aid.split(".")[-1])
    if "zen" in aid or "zen" in t:
        candidates.extend(["app.zen_browser.zen", "zen-browser", "zen"])
    if "tauon" in aid or "tauon" in t:
        candidates.extend(["com.github.taiko2k.tauonmb", "tauonmb", "tauon"])
    if "rambox" in aid or "rambox" in t:
        candidates.extend(["rambox", "com.rambox.Rambox"])
    if "nautilus" in aid or "nautilus" in t or "files" in t:
        candidates.extend(["org.gnome.Nautilus", "system-file-manager"])
    if "kitty" in aid or "terminal" in t:
        candidates.extend(["kitty", "utilities-terminal"])
    if "code" in aid or "code" in t or "vscode" in t:
        candidates.extend(["vscode", "/usr/share/pixmaps/vscode.png", "com.visualstudio.code", "code"])
    if "chrome" in aid or "chromium" in aid or "chrome" in t:
        candidates.extend(["google-chrome", "google-chrome-stable", "com.google.Chrome", "chromium", "chromium-browser"])
    if "discord" in aid or "vesktop" in aid or "discord" in t:
        candidates.extend(["discord", "vesktop", "com.discordapp.Discord"])
    if "spotify" in aid or "spotify" in t:
        candidates.extend(["com.spotify.Client", "spotify"])
    if "steam" in aid or "steam" in t:
        candidates.extend(["steam", "com.valvesoftware.Steam"])
    if "lutris" in aid or "lutris" in t:
        candidates.extend(["net.lutris.Lutris", "lutris"])
    if "gimp" in aid or "gimp" in t:
        candidates.extend(["org.gimp.GIMP", "gimp"])
    if "telegram" in aid or "telegram" in t:
        candidates.extend(["org.telegram.desktop", "telegram"])

    if title:
        candidates.append(title.lower().split()[0])

    candidates.extend(["application-x-executable", "preferences-system-windows", "window", "system-run"])

    for c in candidates:
        if not c:
            continue
        if os.path.exists(c):
            try:
                return GdkPixbuf.Pixbuf.new_from_file_at_scale(c, size, size, True)
            except Exception:
                pass
        for ext in [".png", ".svg"]:
            pixmap = f"/usr/share/pixmaps/{c}{ext}"
            if os.path.exists(pixmap):
                try:
                    return GdkPixbuf.Pixbuf.new_from_file_at_scale(pixmap, size, size, True)
                except Exception:
                    pass
        for ext in [".svg", ".png"]:
            flatpak_ic = f"/var/lib/flatpak/exports/share/icons/hicolor/scalable/apps/{c}{ext}"
            if os.path.exists(flatpak_ic):
                try:
                    return GdkPixbuf.Pixbuf.new_from_file_at_scale(flatpak_ic, size, size, True)
                except Exception:
                    pass
        if theme.has_icon(c):
            try:
                return theme.load_icon(c, size, Gtk.IconLookupFlags.FORCE_SIZE)
            except Exception:
                pass
    return None


class WindowSwitcher(Gtk.Window):
    """
    macOS-Authentic App Switcher:
    - All open app icons visible simultaneously in a single clean row
    - Big prominent 64px application icons
    - Translucent glass selection squircle plate
    - Centered App Name and document title beneath
    - Command+Tab / Super+Tab cycling with instant release-to-switch
    - Command+` / Super+` backtick to cycle backwards
    - Command+Q / Q to quit selected app
    - Auto-dismisses on focus loss so it never gets stuck
    """
    def __init__(self, windows):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.windows = windows
        self.cards = []
        self.is_closing = False
        self.idle_timeout_id = None
        self.last_cycle_time = 0

        # Start on index 1 (previous window) if >= 2 windows, else 0
        if "--prev" in sys.argv and len(self.windows) >= 2:
            self.selected_idx = len(self.windows) - 1
        elif len(self.windows) >= 2:
            self.selected_idx = 1
        else:
            self.selected_idx = 0

        # Layer Shell Setup
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        GtkLayerShell.set_namespace(self, "switcher")

        # Dead center of the screen
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, False)

        self.set_resizable(False)
        Gtk.Widget.set_opacity(self, 0.0)

        # Event mask
        self.add_events(
            Gdk.EventMask.KEY_PRESS_MASK
            | Gdk.EventMask.KEY_RELEASE_MASK
            | Gdk.EventMask.FOCUS_CHANGE_MASK
        )

        self.connect("destroy", cleanup)
        self.connect("key-press-event", self.on_key_press)
        self.connect("key-release-event", self.on_key_release)
        self.connect("focus-out-event", self.on_focus_out)

        # Entrance animation
        self.anim_start = None
        self.add_tick_callback(self.on_animate_in)

        # Build UI
        self.setup_ui()
        self.apply_css()
        self.update_selection()

        # Reset idle timer (4s)
        self.reset_idle_timer()

    def reset_idle_timer(self):
        if self.idle_timeout_id:
            GLib.source_remove(self.idle_timeout_id)
        # Dismiss after 4 seconds of inactivity so it never gets stuck
        self.idle_timeout_id = GLib.timeout_add_seconds(4, self.on_idle_timeout)

    def on_idle_timeout(self):
        self.close_animated()
        return False

    def on_focus_out(self, widget, event):
        # Auto-dismiss if user clicks away or focus is lost
        self.close_animated()
        return False

    # --- Smooth Entrance and Exit Animations ---
    def on_animate_in(self, widget, frame_clock):
        now = frame_clock.get_frame_time() / 1_000_000
        if self.anim_start is None:
            self.anim_start = now
        elapsed = now - self.anim_start
        progress = min(1.0, elapsed / 0.12)
        ease = 1.0 - (1.0 - progress) ** 3

        Gtk.Widget.set_opacity(self, ease)

        if progress >= 1.0:
            Gtk.Widget.set_opacity(self, 1.0)
            return False
        return True

    def close_animated(self, *_):
        if self.is_closing:
            return
        self.is_closing = True
        self.close_start = None
        if self.idle_timeout_id:
            GLib.source_remove(self.idle_timeout_id)
            self.idle_timeout_id = None
        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        except OSError:
            pass
        self.add_tick_callback(self.on_animate_out)

    def on_animate_out(self, widget, frame_clock):
        now = frame_clock.get_frame_time() / 1_000_000
        if self.close_start is None:
            self.close_start = now
        elapsed = now - self.close_start
        progress = min(1.0, elapsed / 0.09)
        ease = progress ** 2

        Gtk.Widget.set_opacity(self, max(0.0, 1.0 - ease))

        if progress >= 1.0:
            cleanup()
            return False
        return True

    # --- UI Construction (macOS Clean Architecture) ---
    def setup_ui(self):
        # macOS Frosted Glass Capsule
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.card.set_name("switcher-card")
        self.add(self.card)

        # Single horizontal row showing ALL icons simultaneously (no scrolled window clipping!)
        self.cards_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.cards_row.set_name("cards-row")
        self.cards_row.set_halign(Gtk.Align.CENTER)
        self.card.pack_start(self.cards_row, False, False, 0)

        for i, win in enumerate(self.windows):
            card_btn = Gtk.Button()
            card_btn.set_name("window-card")
            card_btn.set_relief(Gtk.ReliefStyle.NONE)
            card_btn.connect("clicked", self.on_card_clicked, i)

            inner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            inner_box.set_size_request(84, 84)
            card_btn.add(inner_box)

            pixbuf = get_app_icon_pixbuf(win.get("app_id", ""), win.get("title", ""), size=64)
            img = Gtk.Image.new_from_pixbuf(pixbuf) if pixbuf else Gtk.Image.new_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)
            img.set_name("card-icon")
            img.set_halign(Gtk.Align.CENTER)
            img.set_valign(Gtk.Align.CENTER)
            inner_box.pack_start(img, True, True, 0)

            self.cards_row.pack_start(card_btn, False, False, 0)
            self.cards.append(card_btn)

        # Bottom App & Window Title (macOS style centered text)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_name("title-container")
        title_box.set_halign(Gtk.Align.CENTER)
        self.card.pack_start(title_box, False, False, 0)

        self.app_name_label = Gtk.Label(label="")
        self.app_name_label.set_name("app-name-label")
        self.app_name_label.set_halign(Gtk.Align.CENTER)
        title_box.pack_start(self.app_name_label, False, False, 0)

        self.window_sub_label = Gtk.Label(label="")
        self.window_sub_label.set_name("window-sub-label")
        self.window_sub_label.set_halign(Gtk.Align.CENTER)
        self.window_sub_label.set_ellipsize(3)
        self.window_sub_label.set_max_width_chars(52)
        title_box.pack_start(self.window_sub_label, False, False, 0)

    # --- Navigation & Selection ---
    def on_remote_cycle(self, step):
        # Debounced cycle called from signal (prevents double-jumping)
        self.cycle(step)

    def cycle(self, step=1):
        if not self.windows or len(self.windows) <= 1:
            return

        now = time.time()
        # 60ms debounce to prevent double-skipping from simultaneous compositor hotkey + GTK key_press
        if now - self.last_cycle_time < 0.06:
            return
        self.last_cycle_time = now

        self.reset_idle_timer()
        self.selected_idx = (self.selected_idx + step) % len(self.windows)
        self.update_selection()

    def update_selection(self):
        if not self.windows:
            return

        self.selected_idx = max(0, min(self.selected_idx, len(self.cards) - 1))

        # Instant CSS class toggle (0ms latency, zero widget rebuilds)
        for i, card in enumerate(self.cards):
            ctx = card.get_style_context()
            if i == self.selected_idx:
                ctx.add_class("selected-card")
            else:
                ctx.remove_class("selected-card")

        cur_win = self.windows[self.selected_idx]
        app_name = format_app_name(cur_win.get("app_id", ""), cur_win.get("title", ""))
        self.app_name_label.set_text(app_name)

        doc_title = cur_win.get("title") or ""
        ws_num = cur_win.get("workspace_id", 1)
        if doc_title and doc_title != app_name:
            self.window_sub_label.set_text(f"{doc_title}  •  Workspace {ws_num}")
        else:
            self.window_sub_label.set_text(f"Workspace {ws_num}")

    def activate_selected(self):
        if not self.windows or self.is_closing:
            return
        target_win = self.windows[self.selected_idx]
        win_id = target_win.get("id")

        # Focus window via Niri
        if win_id is not None:
            subprocess.Popen(["niri", "msg", "action", "focus-window", "--id", str(win_id)])

        self.close_animated()

    def on_card_clicked(self, btn, idx):
        self.selected_idx = idx
        self.activate_selected()

    def quit_selected(self):
        if not self.windows:
            return
        cur_win = self.windows[self.selected_idx]
        win_id = cur_win.get("id")
        if win_id is not None:
            subprocess.Popen(["niri", "msg", "action", "close-window"])
            # Remove from active list
            self.windows.pop(self.selected_idx)
            card = self.cards.pop(self.selected_idx)
            self.cards_row.remove(card)
            if not self.windows:
                self.close_animated()
            else:
                self.selected_idx = min(self.selected_idx, len(self.windows) - 1)
                self.update_selection()

    # --- Keyboard Input (macOS Shortcuts) ---
    def on_key_press(self, widget, event):
        self.reset_idle_timer()
        kv = event.keyval

        # Tab, Right, Down: cycle forward
        if kv in (Gdk.KEY_Tab, Gdk.KEY_Right, Gdk.KEY_Down):
            self.cycle(1)
            return True
        # Shift+Tab, Left, Up, Backtick (` / grave): cycle backward like macOS
        elif kv in (Gdk.KEY_ISO_Left_Tab, Gdk.KEY_Left, Gdk.KEY_Up, Gdk.KEY_grave, Gdk.KEY_asciitilde):
            self.cycle(-1)
            return True
        # Return / Space: activate
        elif kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.activate_selected()
            return True
        # Escape: cancel
        elif kv == Gdk.KEY_Escape:
            self.close_animated()
            return True
        # 'q' or 'Q': Quit selected application like macOS Command+Q
        elif kv in (Gdk.KEY_q, Gdk.KEY_Q):
            self.quit_selected()
            return True

        return False

    def on_key_release(self, widget, event):
        kv = event.keyval
        # When Super (Command) or Alt modifier is released, switch immediately
        if kv in (
            Gdk.KEY_Super_L,
            Gdk.KEY_Super_R,
            Gdk.KEY_Alt_L,
            Gdk.KEY_Alt_R,
            Gdk.KEY_Meta_L,
            Gdk.KEY_Meta_R,
        ):
            self.activate_selected()
            return True
        return False

    # --- Styling (macOS Tahoe / Sequoia Frosted Glass) ---
    def apply_css(self):
        theme_path = "/home/sreyas/.config/waybar/current-theme.css"
        css_provider = Gtk.CssProvider()
        css = f"""
        @import url('{theme_path}');

        * {{
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Symbols Nerd Font", "JetBrains Mono", sans-serif;
            transition: all 0.12s cubic-bezier(0.16, 1, 0.3, 1);
        }}

        window {{
            background: transparent;
        }}

        /* macOS Dark Frosted Glass Capsule */
        #switcher-card {{
            background-color: alpha(@bg-color, 0.92);
            border: 1.5px solid rgba(255, 255, 255, 0.18);
            border-radius: 26px;
            padding: 16px 20px 14px 20px;
        }}

        #cards-row {{
            padding: 2px 4px;
        }}

        /* Individual Icon Card (macOS Squircle Plate) */
        #window-card {{
            background: transparent;
            border: 1px solid transparent;
            border-radius: 18px;
            padding: 6px;
            min-width: 84px;
            min-height: 84px;
            opacity: 0.80;
        }}

        #window-card.selected-card {{
            background-color: rgba(255, 255, 255, 0.22);
            border: 1.5px solid rgba(255, 255, 255, 0.45);
            opacity: 1.0;
        }}

        #window-card:hover {{
            background-color: rgba(255, 255, 255, 0.12);
            opacity: 0.95;
        }}

        #card-icon {{
            -gtk-icon-shadow: 0 4px 12px rgba(0, 0, 0, 0.45);
        }}

        /* Centered App Name & Subtitle */
        #title-container {{
            padding-top: 6px;
            padding-bottom: 2px;
        }}

        #app-name-label {{
            font-size: 14.5px;
            font-weight: 700;
            color: #FFFFFF;
            letter-spacing: 0.2px;
            text-shadow: 0 2px 8px rgba(0, 0, 0, 0.6);
        }}

        #window-sub-label {{
            font-size: 11px;
            font-weight: 500;
            color: rgba(255, 255, 255, 0.55);
            text-shadow: 0 1px 4px rgba(0, 0, 0, 0.5);
        }}
        """
        css_provider.load_from_data(css.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

def main():
    toggle_or_cycle()
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    windows = get_niri_windows()
    if not windows:
        sys.exit(0)

    app = WindowSwitcher(windows)
    signal.signal(signal.SIGUSR1, lambda *_: GLib.idle_add(app.on_remote_cycle, 1))
    signal.signal(signal.SIGUSR2, lambda *_: GLib.idle_add(app.on_remote_cycle, -1))

    app.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
