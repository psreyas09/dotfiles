#!/usr/bin/env python3
import os
import sys
import time
import json
import signal
import threading
import subprocess

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GtkLayerShell, GLib, GdkPixbuf

PID_FILE = "/tmp/macos_dock.pid"

def enforce_single_instance():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, signal.SIGTERM)
            time.sleep(0.1)
        except (OSError, ValueError):
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

def format_app_name(app_id, title=""):
    if not app_id:
        return title or "Window"
    aid = app_id.lower()
    if "zen" in aid:
        return "Zen Browser"
    if "kitty" in aid or "alacritty" in aid or "foot" in aid or "wezterm" in aid:
        return "Terminal"
    if "nautilus" in aid:
        return "Files"
    if "rambox" in aid:
        return "Rambox"
    if "code" in aid or "codium" in aid:
        return "Visual Studio Code"
    if "lutris" in aid:
        return "Lutris"
    if "tauon" in aid:
        return "Tauon Music"
    if "firefox" in aid:
        return "Firefox"
    if "chrome" in aid or "chromium" in aid:
        return "Google Chrome"
    if "discord" in aid or "vesktop" in aid:
        return "Discord"
    if "spotify" in aid:
        return "Spotify"
    if "steam" in aid:
        return "Steam"
    last = app_id.split(".")[-1]
    return last.replace("-", " ").replace("_", " ").title()

def get_app_icon_pixbuf(app_id, title="", size=44):
    theme = Gtk.IconTheme.get_default()
    candidates = []
    if app_id:
        aid = app_id.lower()
        candidates.append(app_id)
        candidates.append(aid)
        candidates.append(app_id.split(".")[-1])
        candidates.append(aid.split(".")[-1])
        if "zen" in aid:
            candidates.extend(["app.zen_browser.zen", "zen-browser", "zen"])
        if "nautilus" in aid:
            candidates.extend(["org.gnome.Nautilus", "system-file-manager"])
        if "rambox" in aid:
            candidates.extend(["rambox", "com.rambox.Rambox"])
        if "code" in aid:
            candidates.extend(["vscode", "/usr/share/pixmaps/vscode.png", "com.visualstudio.code", "code"])
        if "lutris" in aid:
            candidates.extend(["net.lutris.Lutris", "lutris"])
        if "kitty" in aid:
            candidates.extend(["kitty", "utilities-terminal"])
        if "tauon" in aid:
            candidates.extend(["com.github.taiko2k.tauonmb", "tauonmb", "tauon"])

    if title:
        candidates.append(title.lower().split()[0])

    candidates.extend(["application-x-executable", "preferences-system-windows", "window", "system-run"])

    for c in candidates:
        if not c:
            continue
        # Direct file path
        if os.path.exists(c):
            try:
                return GdkPixbuf.Pixbuf.new_from_file_at_scale(c, size, size, True)
            except Exception:
                pass
        # Pixmap file
        pixmap = f"/usr/share/pixmaps/{c}.png"
        if os.path.exists(pixmap):
            try:
                return GdkPixbuf.Pixbuf.new_from_file_at_scale(pixmap, size, size, True)
            except Exception:
                pass
        # GTK IconTheme
        if theme.has_icon(c):
            try:
                return theme.load_icon(c, size, Gtk.IconLookupFlags.FORCE_SIZE)
            except Exception:
                pass
    return None

# User's exact requested pinned apps
PINNED_APPS = [
    {
        "name": "Zen Browser",
        "icon": ["app.zen_browser.zen", "zen-browser", "zen"],
        "cmd": "flatpak run app.zen_browser.zen",
        "app_ids": ["app.zen_browser.zen", "zen"]
    },
    {
        "name": "Nautilus",
        "icon": ["org.gnome.Nautilus", "system-file-manager"],
        "cmd": "nautilus",
        "app_ids": ["org.gnome.nautilus", "nautilus"]
    },
    {
        "name": "Rambox",
        "icon": ["rambox", "com.rambox.Rambox"],
        "cmd": "rambox",
        "app_ids": ["rambox"]
    },
    {
        "name": "Visual Studio Code",
        "icon": ["vscode", "/usr/share/pixmaps/vscode.png", "com.visualstudio.code", "code"],
        "cmd": "code",
        "app_ids": ["code", "com.visualstudio.code"]
    },
    {
        "name": "Lutris",
        "icon": ["net.lutris.Lutris", "lutris"],
        "cmd": "lutris",
        "app_ids": ["net.lutris.lutris", "lutris"]
    },
]


class MacOSDock(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("macOS Dock")
        self.set_resizable(False)

        # Layer Shell Setup
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_namespace(self, "dock")
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_exclusive_zone(self, 0)

        # Centered at bottom
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, False)

        # State tracking
        self.is_mouse_over = False
        self.is_overview_open = False
        self.has_windows_on_workspace = False
        self.running_windows = []
        self.leave_timer_id = None

        # Animation states (0% idle CPU)
        self.current_margin = 0.0
        self.last_anim_time = None
        self.is_animating = False
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, int(self.current_margin))

        # Event mask for hover detection
        self.add_events(
            Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )

        self.connect("destroy", cleanup)
        self.connect("enter-notify-event", self.on_enter_notify)
        self.connect("leave-notify-event", self.on_leave_notify)
        self.connect("motion-notify-event", self.on_motion_notify)

        # UI Build
        self.setup_ui()
        self.apply_css()

        # Immediate state fetch so active apps & running dots display instantly!
        self.fetch_initial_state()

        # Trigger entrance animation
        self.request_animation()

        # Start low-overhead Niri stream listener
        self.start_niri_listener()

    def setup_ui(self):
        self.dock_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.dock_container.set_name("dock-container")
        self.add(self.dock_container)

        # macOS Frosted Glass Capsule
        self.card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.card.set_name("dock-card")
        self.dock_container.pack_start(self.card, False, False, 0)

        # 1. Pinned Apps (Zen, Nautilus, Rambox, VS Code, Lutris)
        self.pinned_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.card.pack_start(self.pinned_box, False, False, 0)

        # 2. Dynamic Running Apps (unpinned active apps, e.g. Kitty, Tauon, etc.)
        self.dynamic_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.card.pack_start(self.dynamic_box, False, False, 0)

        # 3. Glass Separator line before Trash
        self.separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        self.separator.set_name("dock-separator")
        self.card.pack_start(self.separator, False, False, 4)

        # 4. Trash
        self.trash_item = {
            "name": "Trash",
            "icon": ["user-trash"],
            "cmd": "nautilus trash:///",
            "app_ids": []
        }
        self.trash_widget = self.create_dock_item(self.trash_item)
        self.card.pack_start(self.trash_widget, False, False, 0)

        self.pinned_widgets = []
        self.dynamic_widgets = []

        # Populate pinned apps
        for item in PINNED_APPS:
            w = self.create_dock_item(item)
            self.pinned_box.pack_start(w, False, False, 0)
            self.pinned_widgets.append((item, w))

    def create_dock_item(self, item, is_dynamic=False, win_id=None):
        btn = Gtk.Button()
        btn.set_name("dock-item")
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.set_tooltip_text(item["name"])

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.set_valign(Gtk.Align.CENTER)
        vbox.set_halign(Gtk.Align.CENTER)
        btn.add(vbox)

        # App Icon resolution (supports IconTheme, pixmaps, and direct paths)
        pb = None
        size = 44
        theme = Gtk.IconTheme.get_default()

        for cand in item.get("icon", []):
            if not cand:
                continue
            if os.path.exists(cand):
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(cand, size, size, True)
                    break
                except Exception:
                    pass
            pixmap = f"/usr/share/pixmaps/{cand}.png"
            if os.path.exists(pixmap):
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(pixmap, size, size, True)
                    break
                except Exception:
                    pass
            if theme.has_icon(cand):
                try:
                    pb = theme.load_icon(cand, size, Gtk.IconLookupFlags.FORCE_SIZE)
                    break
                except Exception:
                    pass

        if not pb:
            pb = get_app_icon_pixbuf(item.get("app_ids", [""])[0] if item.get("app_ids") else "", size=size)

        img = Gtk.Image.new_from_pixbuf(pb) if pb else Gtk.Image.new_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)
        img.set_name("dock-icon")
        vbox.pack_start(img, False, False, 0)

        # macOS Running Indicator Dot
        dot = Gtk.Label(label="•")
        dot.set_name("running-dot")
        dot.get_style_context().add_class("inactive")
        vbox.pack_start(dot, False, False, 0)

        btn.connect("clicked", self.on_item_clicked, item, win_id)
        btn._dot = dot
        btn._item = item
        return btn

    def on_item_clicked(self, btn, item, win_id=None):
        target_win = None
        if win_id is not None:
            target_win = next((w for w in self.running_windows if w["id"] == win_id), None)

        if not target_win and item.get("app_ids"):
            for w in self.running_windows:
                aid = (w.get("app_id") or "").lower()
                for match_id in item["app_ids"]:
                    if match_id.lower() in aid or aid in match_id.lower():
                        target_win = w
                        break
                if target_win:
                    break

        if target_win and target_win.get("id") is not None:
            subprocess.Popen(["niri", "msg", "action", "focus-window", "--id", str(target_win["id"])])
        else:
            cmd = item.get("cmd")
            if cmd:
                subprocess.Popen(cmd, shell=True)

    # --- Initial State Fetch ---
    def fetch_initial_state(self):
        try:
            ws_res = subprocess.run(["niri", "msg", "-j", "workspaces"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1)
            win_res = subprocess.run(["niri", "msg", "-j", "windows"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1)
            if ws_res.returncode == 0 and win_res.returncode == 0:
                workspaces = json.loads(ws_res.stdout)
                windows = json.loads(win_res.stdout)
                focused_ws = 1
                for ws in workspaces:
                    if ws.get("is_focused"):
                        focused_ws = ws.get("id")
                        break
                count = sum(1 for w in windows if w.get("workspace_id") == focused_ws)
                self.update_dock_data(count > 0, windows)
        except Exception:
            pass

    # --- Hover & Auto-Hide Physics ---
    def on_enter_notify(self, widget, event):
        self.is_mouse_over = True
        if self.leave_timer_id:
            GLib.source_remove(self.leave_timer_id)
            self.leave_timer_id = None
        self.request_animation()
        return False

    def on_motion_notify(self, widget, event):
        if not self.is_mouse_over:
            self.is_mouse_over = True
            self.request_animation()
        if self.leave_timer_id:
            GLib.source_remove(self.leave_timer_id)
            self.leave_timer_id = None
        return False

    def on_leave_notify(self, widget, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        if self.leave_timer_id:
            GLib.source_remove(self.leave_timer_id)
        # 400ms delay before sliding down
        self.leave_timer_id = GLib.timeout_add(400, self._on_delayed_leave)
        return False

    def _on_delayed_leave(self):
        self.is_mouse_over = False
        self.leave_timer_id = None
        self.request_animation()
        return False

    def should_be_visible(self):
        # 1. Always visible during Overview!
        if self.is_overview_open:
            return True
        # 2. Always visible when hovered
        if self.is_mouse_over:
            return True
        # 3. Always visible when current workspace has NO windows (empty desktop)
        if not self.has_windows_on_workspace:
            return True
        # 4. Otherwise hidden (auto-hide)
        return False

    def request_animation(self):
        if not self.is_animating:
            self.is_animating = True
            self.last_anim_time = None
            self.add_tick_callback(self.on_anim_tick)

    def on_anim_tick(self, widget, frame_clock):
        now = frame_clock.get_frame_time() / 1_000_000
        if self.last_anim_time is None:
            self.last_anim_time = now
        dt = min(0.05, now - self.last_anim_time)
        self.last_anim_time = now

        target = 0.0 if self.should_be_visible() else -68.0
        diff = target - self.current_margin

        if abs(diff) > 0.5:
            speed = 14.0
            self.current_margin += diff * min(1.0, dt * speed)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, int(self.current_margin))

            progress = max(0.0, min(1.0, (self.current_margin - (-68.0)) / (0.0 - (-68.0))))
            Gtk.Widget.set_opacity(self.card, progress)
            return True
        else:
            self.current_margin = target
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, int(self.current_margin))
            Gtk.Widget.set_opacity(self.card, 1.0 if target >= 0 else 0.0)
            self.is_animating = False
            return False # Animation complete: unhook callback for 0.0% CPU!

    # --- Live State Updates (Showing All Active Apps) ---
    def update_dock_data(self, has_windows, windows):
        self.has_windows_on_workspace = has_windows
        self.running_windows = windows
        self.request_animation()

        # 1. Update running dots on pinned apps
        running_app_ids = set()
        for w in windows:
            aid = (w.get("app_id") or "").lower()
            if aid:
                running_app_ids.add(aid)

        for item, w in self.pinned_widgets:
            dot = getattr(w, "_dot", None)
            if not dot:
                continue
            is_running = any(
                any(match_id.lower() in aid or aid in match_id.lower() for match_id in item.get("app_ids", []))
                for aid in running_app_ids
            )
            ctx = dot.get_style_context()
            if is_running:
                ctx.remove_class("inactive")
            else:
                ctx.add_class("inactive")

        # 2. Dynamic unpinned running apps (Show ALL open apps!)
        pinned_app_id_list = [aid.lower() for item in PINNED_APPS for aid in item.get("app_ids", [])]
        unpinned_windows = []
        seen_unpinned = set()

        for w in windows:
            aid = (w.get("app_id") or "").lower()
            title = w.get("title") or "Window"
            app_key = aid if aid else title.lower()

            is_pinned = any(p in aid or aid in p for p in pinned_app_id_list) if aid else False
            if not is_pinned:
                if app_key not in seen_unpinned:
                    seen_unpinned.add(app_key)
                    unpinned_windows.append(w)

        current_dynamic_ids = [getattr(w, "_app_key", None) for w in self.dynamic_widgets]
        new_dynamic_ids = [(w.get("app_id") or w.get("title") or "").lower() for w in unpinned_windows]

        if current_dynamic_ids != new_dynamic_ids:
            for child in self.dynamic_box.get_children():
                self.dynamic_box.remove(child)
            self.dynamic_widgets = []

            for w in unpinned_windows:
                aid = w.get("app_id") or ""
                title = w.get("title") or "App"
                app_key = (aid or title).lower()
                display_name = format_app_name(aid, title)
                item = {
                    "name": display_name,
                    "icon": [aid],
                    "cmd": "",
                    "app_ids": [aid] if aid else []
                }
                widget = self.create_dock_item(item, is_dynamic=True, win_id=w.get("id"))
                widget._app_key = app_key
                # Active apps always have the running dot enabled!
                dot = getattr(widget, "_dot", None)
                if dot:
                    dot.get_style_context().remove_class("inactive")

                self.dynamic_box.pack_start(widget, False, False, 0)
                self.dynamic_widgets.append(widget)

            self.dynamic_box.show_all()

    # --- Pure Event-Driven Listener (Zero Subprocess Polling) ---
    def start_niri_listener(self):
        def listener():
            while True:
                proc = None
                try:
                    proc = subprocess.Popen(
                        ["niri", "msg", "--json", "event-stream"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    focused_ws = 1
                    current_windows = list(self.running_windows)

                    for line in proc.stdout:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            changed = False

                            if "OverviewOpenedOrClosed" in data:
                                self.is_overview_open = data["OverviewOpenedOrClosed"].get("is_open", False)
                                changed = True
                            elif "WorkspacesChanged" in data:
                                workspaces = data["WorkspacesChanged"].get("workspaces", [])
                                for ws in workspaces:
                                    if ws.get("is_focused"):
                                        focused_ws = ws.get("id")
                                        changed = True
                            elif "WorkspaceActivated" in data:
                                focused_ws = data["WorkspaceActivated"].get("id")
                                changed = True
                            elif "WindowsChanged" in data:
                                current_windows = data["WindowsChanged"].get("windows", [])
                                changed = True
                            elif "WindowFocusChanged" in data or "WorkspaceActiveWindowChanged" in data:
                                changed = True

                            if changed:
                                count = sum(1 for w in current_windows if w.get("workspace_id") == focused_ws)
                                GLib.idle_add(self.update_dock_data, count > 0, list(current_windows))
                        except Exception:
                            pass
                except Exception:
                    pass
                finally:
                    if proc:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    time.sleep(2)

        t = threading.Thread(target=listener, daemon=True)
        t.start()

    # --- Styling (macOS Frosted Glass) ---
    def apply_css(self):
        theme_path = "/home/sreyas/.config/waybar/current-theme.css"
        css_provider = Gtk.CssProvider()
        css = f"""
        @import url('{theme_path}');

        * {{
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Symbols Nerd Font", "JetBrains Mono", sans-serif;
            transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
        }}

        window {{
            background: transparent;
        }}

        #dock-container {{
            background: transparent;
            padding: 0 0 10px 0;
        }}

        /* macOS Glass Dock Capsule */
        #dock-card {{
            background-color: alpha(@bg-color, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.20);
            border-radius: 22px;
            padding: 5px 10px 2px 10px;
        }}

        #dock-item {{
            background: transparent;
            border: none;
            border-radius: 12px;
            padding: 4px 6px 2px 6px;
            margin: 0 2px;
            min-width: 48px;
        }}

        #dock-item:hover {{
            background-color: rgba(255, 255, 255, 0.18);
        }}

        #dock-icon {{
            -gtk-icon-shadow: 0 4px 10px rgba(0, 0, 0, 0.45);
        }}

        /* Running Indicator Dot (macOS Style) */
        #running-dot {{
            font-size: 8px;
            color: @accent-purple;
            padding: 0;
            margin-top: -3px;
        }}

        #running-dot.inactive {{
            opacity: 0.0;
        }}

        #dock-separator {{
            background-color: rgba(255, 255, 255, 0.22);
            min-width: 1px;
            margin: 8px 6px 10px 6px;
        }}
        """
        css_provider.load_from_data(css.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def main():
    enforce_single_instance()
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    app = MacOSDock()
    app.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
