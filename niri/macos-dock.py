#!/usr/bin/env python3
import os
import sys
import time
import json
import signal
import threading
import subprocess
import re
import math
import shutil

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
gi.require_version('Gio', '2.0')
from gi.repository import Gtk, Gdk, GtkLayerShell, GLib, GdkPixbuf, Gio, cairo
import cairo

PID_FILE = "/tmp/macos_dock.pid"
PINNED_CONFIG_FILE = os.path.expanduser("~/.config/niri/dock-pinned.json")
DOTFILE_PINNED_FILE = os.path.expanduser("~/dotfile/niri/dock-pinned.json")

def enforce_single_instance():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            if old_pid != os.getpid():
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
    if "niri-settings" in aid or "settings" in aid:
        return "Niri Settings"
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
    aid = (app_id or "").lower()

    # 1. Direct DesktopAppInfo resolution
    desktop_cands = [
        f"{app_id}.desktop" if app_id else "",
        f"{aid}.desktop" if aid else "",
        "google-chrome.desktop" if "chrome" in aid else "",
        "com.google.Chrome.desktop" if "chrome" in aid else "",
        "code.desktop" if "code" in aid else "",
        "discord.desktop" if "discord" in aid else "",
        "com.spotify.Client.desktop" if "spotify" in aid else "",
        "steam.desktop" if "steam" in aid else "",
    ]
    for d in desktop_cands:
        if not d:
            continue
        try:
            dinfo = Gio.DesktopAppInfo.new(d)
            if dinfo and dinfo.get_icon():
                gicon = dinfo.get_icon()
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
        if "zen" in aid:
            candidates.extend(["app.zen_browser.zen", "zen-browser", "zen"])
        if "nautilus" in aid:
            candidates.extend(["org.gnome.Nautilus", "system-file-manager"])
        if "rambox" in aid:
            candidates.extend(["rambox", "com.rambox.Rambox"])
        if "code" in aid:
            candidates.extend(["vscode", "/usr/share/pixmaps/vscode.png", "com.visualstudio.code", "code"])
        if "chrome" in aid or "chromium" in aid:
            candidates.extend(["google-chrome", "google-chrome-stable", "com.google.Chrome", "chromium", "chromium-browser"])
        if "discord" in aid or "vesktop" in aid:
            candidates.extend(["discord", "vesktop", "com.discordapp.Discord"])
        if "spotify" in aid:
            candidates.extend(["com.spotify.Client", "spotify"])
        if "steam" in aid:
            candidates.extend(["steam", "com.valvesoftware.Steam"])
        if "lutris" in aid:
            candidates.extend(["net.lutris.Lutris", "lutris"])
        if "niri-settings" in aid or "settings" in aid:
            candidates.extend(["preferences-system", "org.gnome.Settings", "preferences-desktop"])
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
        # Pixmap file (.png and .svg)
        for ext in [".png", ".svg"]:
            pixmap = f"/usr/share/pixmaps/{c}{ext}"
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


_DESKTOP_INFO_CACHE = {}

def find_desktop_info(item):
    app_ids = tuple(item.get("app_ids", []))
    name = item.get("name", "")
    cache_key = (app_ids, name)
    if cache_key in _DESKTOP_INFO_CACHE:
        return _DESKTOP_INFO_CACHE[cache_key]

    candidates = []
    for aid in app_ids:
        if not aid:
            continue
        candidates.extend([aid, aid + ".desktop", aid.lower(), aid.lower() + ".desktop"])
        candidates.append(aid.split(".")[-1] + ".desktop")
    if name:
        n = name.lower().replace(" ", "-")
        candidates.append(n + ".desktop")

    seen = set()
    for c in candidates:
        if not c.endswith(".desktop"):
            c += ".desktop"
        if c in seen:
            continue
        seen.add(c)
        try:
            info = Gio.DesktopAppInfo.new(c)
            if info:
                _DESKTOP_INFO_CACHE[cache_key] = info
                return info
        except (TypeError, Exception):
            pass

    # Search standard flatpak and system directories
    search_dirs = [
        "/var/lib/flatpak/exports/share/applications",
        os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
        "/usr/share/applications",
        os.path.expanduser("~/.local/share/applications")
    ]
    for d in search_dirs:
        if not os.path.exists(d):
            continue
        try:
            for root, _, files in os.walk(d):
                for f in files:
                    if not f.endswith(".desktop"):
                        continue
                    fl = f.lower()
                    for aid in app_ids:
                        if aid and aid.lower() in fl:
                            try:
                                info = Gio.DesktopAppInfo.new_from_filename(os.path.join(root, f))
                                if info:
                                    _DESKTOP_INFO_CACHE[cache_key] = info
                                    return info
                            except Exception:
                                pass
        except Exception:
            pass
    _DESKTOP_INFO_CACHE[cache_key] = None
    return None

DEFAULT_PINNED_APPS = [
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
    {
        "name": "Settings",
        "icon": ["preferences-system", "org.gnome.Settings", "preferences-desktop"],
        "cmd": "/usr/bin/python3 /home/sreyas/.config/niri/niri-settings.py",
        "app_ids": ["niri-settings", "niri-settings.py"]
    },
]


_ALL_DESKTOP_APPS = None

def get_all_desktop_apps():
    global _ALL_DESKTOP_APPS
    if _ALL_DESKTOP_APPS is not None:
        return _ALL_DESKTOP_APPS

    apps = Gio.AppInfo.get_all()
    res = []
    seen = set()
    for app in apps:
        if not app.should_show():
            continue
        name = app.get_name()
        if not name or name in seen:
            continue
        seen.add(name)

        cmd_raw = app.get_commandline() or ""
        cmd = re.sub(r'@@.*?@@|%[a-zA-Z]', '', cmd_raw).strip()

        icon_str = ""
        if app.has_key("Icon"):
            icon_str = app.get_string("Icon") or ""
        elif app.get_icon():
            icon_str = app.get_icon().to_string()

        d_id = (app.get_id() or "").replace(".desktop", "")
        desc = app.get_description() or ""

        icons = []
        if icon_str:
            icons.append(icon_str)
        if d_id and d_id not in icons:
            icons.append(d_id)

        item = {
            "name": name,
            "desc": desc,
            "icon": icons,
            "gicon": app.get_icon(),
            "cmd": cmd,
            "app_ids": [d_id] if d_id else []
        }
        res.append(item)

    res.sort(key=lambda x: x["name"].lower())
    _ALL_DESKTOP_APPS = res
    return res


class StandaloneDockManager:
    def __init__(self):
        self.pinned_apps = self.load_pinned_apps()

    def load_pinned_apps(self):
        for path in [PINNED_CONFIG_FILE, DOTFILE_PINNED_FILE]:
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            return data
                except Exception:
                    pass
        return list(DEFAULT_PINNED_APPS)

    def save_pinned_apps(self):
        for path in [PINNED_CONFIG_FILE, DOTFILE_PINNED_FILE]:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    json.dump(self.pinned_apps, f, indent=2)
            except Exception:
                pass

    def is_app_pinned(self, app_id, name):
        name_lower = (name or "").lower()
        aid_lower = (app_id or "").lower()
        for p in self.pinned_apps:
            p_name = (p.get("name") or "").lower()
            p_aids = [a.lower() for a in p.get("app_ids", []) if a]
            if p_name == name_lower:
                return True
            if aid_lower and (aid_lower in p_aids or any(aid_lower in a or a in aid_lower for a in p_aids)):
                return True
        return False

    def pin_app(self, item):
        dinfo = find_desktop_info(item)
        name = (dinfo.get_name() if dinfo else None) or item.get("name") or "App"
        cmd = item.get("cmd") or ""

        if dinfo:
            if not cmd:
                cmd_raw = dinfo.get_commandline() or ""
                cmd = re.sub(r'@@.*?@@|%[a-zA-Z]', '', cmd_raw).strip()
            d_id = (dinfo.get_id() or "").replace(".desktop", "")
            icon_str = dinfo.get_string("Icon") if dinfo.has_key("Icon") else ""
        else:
            d_id = ""
            icon_str = ""

        if not cmd:
            app_ids = item.get("app_ids", [])
            for aid in app_ids:
                if shutil.which(aid):
                    cmd = aid
                    break
                elif "." in aid:
                    cmd = f"flatpak run {aid}"
                    break
            if not cmd:
                cand = item.get("name", "").lower()
                if shutil.which(cand):
                    cmd = cand

        icons = []
        if icon_str:
            icons.append(icon_str)
        for ic in item.get("icon", []):
            if ic and ic not in icons:
                icons.append(ic)
        if d_id and d_id not in icons:
            icons.append(d_id)

        app_ids = list(item.get("app_ids", []))
        if d_id and d_id not in app_ids:
            app_ids.append(d_id)

        entry = {
            "name": name,
            "icon": icons,
            "cmd": cmd,
            "app_ids": app_ids
        }

        name_lower = name.lower()
        aid_lowers = [a.lower() for a in app_ids if a]

        exists_idx = None
        for idx, p in enumerate(self.pinned_apps):
            p_name = (p.get("name") or "").lower()
            p_aids = [a.lower() for a in p.get("app_ids", []) if a]
            if p_name == name_lower or (aid_lowers and any(a in p_aids for a in aid_lowers)):
                exists_idx = idx
                break

        if exists_idx is None:
            self.pinned_apps.append(entry)
        else:
            self.pinned_apps[exists_idx] = entry

        self.save_pinned_apps()

    def unpin_app(self, item):
        name_lower = (item.get("name") or "").lower()
        app_ids = [a.lower() for a in item.get("app_ids", []) if a]

        self.pinned_apps = [
            p for p in self.pinned_apps
            if not (
                (p.get("name") or "").lower() == name_lower
                or any(aid in [a.lower() for a in p.get("app_ids", [])] for aid in app_ids if aid)
            )
        ]
        self.save_pinned_apps()


class DockAppChooserDialog(Gtk.Window):
    def __init__(self, dock):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.dock = dock
        self.set_title("Pin Applications to Dock")
        self.set_role("dock-pin-manager")
        self.set_default_size(480, 560)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_resizable(True)
        self.get_style_context().add_class("dock-app-dialog")

        # Main Layout
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main_vbox.set_name("dock-app-dialog-content")
        self.add(main_vbox)

        # Header Box
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header_box.set_name("dock-app-dialog-header")
        header_box.set_margin_top(16)
        header_box.set_margin_bottom(12)
        header_box.set_margin_start(20)
        header_box.set_margin_end(20)

        title_lbl = Gtk.Label()
        title_lbl.set_markup("<span weight='bold' size='large' foreground='#FFFFFF'>Pin Applications to Dock</span>")
        title_lbl.set_xalign(0.0)
        header_box.pack_start(title_lbl, False, False, 0)

        sub_lbl = Gtk.Label()
        sub_lbl.set_markup("<span size='small' foreground='#9D9DB0'>Select applications to keep permanently on your bottom dock</span>")
        sub_lbl.set_xalign(0.0)
        header_box.pack_start(sub_lbl, False, False, 0)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_name("dock-app-dialog-search")
        self.search_entry.set_placeholder_text("Search installed applications...")
        self.search_entry.set_margin_top(10)
        self.search_entry.connect("search-changed", self.on_search_changed)
        header_box.pack_start(self.search_entry, False, False, 0)

        main_vbox.pack_start(header_box, False, False, 0)

        # Scrolled List
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_shadow_type(Gtk.ShadowType.NONE)
        self.scroll.set_margin_start(16)
        self.scroll.set_margin_end(16)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.set_filter_func(self.filter_apps)
        self.scroll.add(self.listbox)
        main_vbox.pack_start(self.scroll, True, True, 0)

        # Bottom Bar
        bottom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bottom_box.set_margin_top(12)
        bottom_box.set_margin_bottom(14)
        bottom_box.set_margin_start(20)
        bottom_box.set_margin_end(20)

        self.count_lbl = Gtk.Label()
        self.count_lbl.set_xalign(0.0)
        bottom_box.pack_start(self.count_lbl, True, True, 0)

        done_btn = Gtk.Button(label="Done")
        done_btn.set_name("dock-app-dialog-done")
        done_btn.connect("clicked", lambda *_: self.destroy())
        bottom_box.pack_end(done_btn, False, False, 0)

        main_vbox.pack_start(bottom_box, False, False, 0)

        self.connect("key-press-event", self.on_key_press)

        # Populate
        self.populate_apps()
        self.update_count_label()

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        return False

    def on_search_changed(self, entry):
        self.listbox.invalidate_filter()

    def filter_apps(self, row):
        query = self.search_entry.get_text().strip().lower()
        if not query:
            return True
        item = getattr(row, "_item", {})
        name = (item.get("name") or "").lower()
        desc = (item.get("desc") or "").lower()
        cmd = (item.get("cmd") or "").lower()
        return query in name or query in desc or query in cmd

    def update_count_label(self):
        count = len(getattr(self.dock, "pinned_apps", []))
        self.count_lbl.set_markup(f"<span size='small' foreground='#B5B5BE'><b>{count}</b> apps pinned to dock</span>")

    def populate_apps(self):
        apps = get_all_desktop_apps()
        theme = Gtk.IconTheme.get_default()

        for item in apps:
            row = Gtk.ListBoxRow()
            row._item = item
            row.set_activatable(False)

            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            hbox.set_name("dock-app-row")
            hbox.set_margin_top(4)
            hbox.set_margin_bottom(4)
            hbox.set_margin_start(8)
            hbox.set_margin_end(8)

            # Icon (instant resolution via gicon / icon name)
            img = Gtk.Image()
            size = 36
            img.set_pixel_size(size)
            gicon = item.get("gicon")
            icon_cands = item.get("icon", [])
            icon_name = icon_cands[0] if icon_cands else "application-x-executable"
            if gicon:
                img.set_from_gicon(gicon, Gtk.IconSize.LARGE_TOOLBAR)
            elif icon_name.startswith("/"):
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_name, size, size, True)
                    img.set_from_pixbuf(pb)
                except Exception:
                    img.set_from_icon_name("application-x-executable", Gtk.IconSize.LARGE_TOOLBAR)
            else:
                img.set_from_icon_name(icon_name, Gtk.IconSize.LARGE_TOOLBAR)

            hbox.pack_start(img, False, False, 0)

            # Text
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            vbox.set_valign(Gtk.Align.CENTER)

            name_lbl = Gtk.Label()
            name_lbl.set_markup(f"<span weight='bold' foreground='#FFFFFF'>{GLib.markup_escape_text(item['name'])}</span>")
            name_lbl.set_xalign(0.0)
            vbox.pack_start(name_lbl, False, False, 0)

            desc_text = item.get("desc") or item.get("cmd") or ""
            if len(desc_text) > 46:
                desc_text = desc_text[:44] + "…"
            desc_lbl = Gtk.Label()
            desc_lbl.set_markup(f"<span size='small' foreground='#888896'>{GLib.markup_escape_text(desc_text)}</span>")
            desc_lbl.set_xalign(0.0)
            vbox.pack_start(desc_lbl, False, False, 0)

            hbox.pack_start(vbox, True, True, 0)

            # Toggle Pin Button
            btn = Gtk.Button()
            btn.set_valign(Gtk.Align.CENTER)
            btn.set_name("dock-app-pin-btn")

            app_id = item.get("app_ids", [""])[0] if item.get("app_ids") else ""
            is_pinned = self.dock.is_app_pinned(app_id, item["name"])
            self.style_pin_btn(btn, is_pinned)

            btn.connect("clicked", self.on_toggle_pin, item)
            hbox.pack_end(btn, False, False, 0)

            row.add(hbox)
            row._btn = btn
            self.listbox.add(row)

    def style_pin_btn(self, btn, is_pinned):
        ctx = btn.get_style_context()
        if is_pinned:
            btn.set_label("✓ Pinned")
            ctx.remove_class("unpinned")
            ctx.add_class("pinned")
        else:
            btn.set_label("+ Pin")
            ctx.remove_class("pinned")
            ctx.add_class("unpinned")

    def on_toggle_pin(self, btn, item):
        app_id = item.get("app_ids", [""])[0] if item.get("app_ids") else ""
        name = item["name"]
        is_pinned = self.dock.is_app_pinned(app_id, name)

        if is_pinned:
            self.dock.unpin_app(item)
            self.style_pin_btn(btn, False)
        else:
            self.dock.pin_app(item)
            self.style_pin_btn(btn, True)

        self.update_count_label()


class MacOSDock(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("macOS Dock")
        self.set_resizable(False)

        # Layer Shell Setup
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_namespace(self, "dock")
        # ON_DEMAND allows context menu to handle keyboard (Esc to close, Arrow keys to navigate)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
        GtkLayerShell.set_exclusive_zone(self, 0)

        # Centered at bottom
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, False)

        # State tracking
        self.is_mouse_over = False
        self.is_menu_open = False
        self.active_menu = None
        self.is_overview_open = False
        self.has_windows_on_workspace = False
        self.running_windows = []
        self.leave_timer_id = None

        # Icon jumping / bouncing animation state
        self.bouncing_apps = {}
        self.is_bouncing_animating = False

        # Flowing wave hover animation state (0% idle CPU)
        self.is_wave_animating = False
        self.last_wave_time = None

        # Load pinned apps configuration
        self.pinned_apps = self.load_pinned_apps()

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

        # Drag & Reorder state
        self.drag_data = None
        self._just_finished_drag = False

        self.connect("destroy", cleanup)
        self.connect("enter-notify-event", self.on_enter_notify)
        self.connect("leave-notify-event", self.on_leave_notify)
        self.connect("motion-notify-event", self.on_motion_notify)
        self.connect("button-release-event", self.on_window_button_release)

        # UI Build
        self.setup_ui()
        self.apply_css()

        # Immediate state fetch so active apps & running dots display instantly!
        self.fetch_initial_state()

        # Trigger entrance animation
        self.request_animation()

        # Start low-overhead Niri stream listener
        self.start_niri_listener()

        # Monitor dock-pinned.json for external changes
        self.setup_pinned_monitor()

    # --- Pinned Apps Persistence ---
    def load_pinned_apps(self):
        for path in [PINNED_CONFIG_FILE, DOTFILE_PINNED_FILE]:
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            return data
                except Exception:
                    pass
        defaults = list(DEFAULT_PINNED_APPS)
        self.save_pinned_apps_list(defaults)
        return defaults

    def save_pinned_apps(self):
        self._last_internal_save = time.time()
        self.save_pinned_apps_list(self.pinned_apps)

    def save_pinned_apps_list(self, apps):
        for path in [PINNED_CONFIG_FILE, DOTFILE_PINNED_FILE]:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    json.dump(apps, f, indent=2)
            except Exception:
                pass

    def setup_pinned_monitor(self):
        try:
            gfile = Gio.File.new_for_path(PINNED_CONFIG_FILE)
            self.pinned_monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self.pinned_monitor.connect("changed", self.on_pinned_file_changed)
        except Exception:
            pass

    def on_pinned_file_changed(self, monitor, file, other_file, event_type):
        if event_type in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED):
            if time.time() - getattr(self, "_last_internal_save", 0) > 0.3:
                GLib.idle_add(self.reload_pinned_apps)

    def reload_pinned_apps(self):
        self.pinned_apps = self.load_pinned_apps()
        self.rebuild_pinned_dock()

    def is_app_pinned(self, app_id, name):
        name_lower = (name or "").lower()
        aid_lower = (app_id or "").lower()
        for p in self.pinned_apps:
            p_name = (p.get("name") or "").lower()
            p_aids = [a.lower() for a in p.get("app_ids", []) if a]
            if p_name == name_lower:
                return True
            if aid_lower and (aid_lower in p_aids or any(aid_lower in a or a in aid_lower for a in p_aids)):
                return True
        return False

    def pin_app(self, item):
        dinfo = find_desktop_info(item)
        name = (dinfo.get_name() if dinfo else None) or item.get("name") or "App"
        cmd = item.get("cmd") or ""

        if dinfo:
            if not cmd:
                cmd_raw = dinfo.get_commandline() or ""
                cmd = re.sub(r'@@.*?@@|%[a-zA-Z]', '', cmd_raw).strip()
            d_id = (dinfo.get_id() or "").replace(".desktop", "")
            icon_str = dinfo.get_string("Icon") if dinfo.has_key("Icon") else ""
        else:
            d_id = ""
            icon_str = ""

        if not cmd:
            app_ids = item.get("app_ids", [])
            for aid in app_ids:
                if shutil.which(aid):
                    cmd = aid
                    break
                elif "." in aid:
                    cmd = f"flatpak run {aid}"
                    break
            if not cmd:
                cand = item.get("name", "").lower()
                if shutil.which(cand):
                    cmd = cand

        icons = []
        if icon_str:
            icons.append(icon_str)
        for ic in item.get("icon", []):
            if ic and ic not in icons:
                icons.append(ic)
        if d_id and d_id not in icons:
            icons.append(d_id)

        app_ids = list(item.get("app_ids", []))
        if d_id and d_id not in app_ids:
            app_ids.append(d_id)

        entry = {
            "name": name,
            "icon": icons,
            "cmd": cmd,
            "app_ids": app_ids
        }

        name_lower = name.lower()
        aid_lowers = [a.lower() for a in app_ids if a]

        exists_idx = None
        for idx, p in enumerate(self.pinned_apps):
            p_name = (p.get("name") or "").lower()
            p_aids = [a.lower() for a in p.get("app_ids", []) if a]
            if p_name == name_lower or (aid_lowers and any(a in p_aids for a in aid_lowers)):
                exists_idx = idx
                break

        if exists_idx is None:
            self.pinned_apps.append(entry)
        else:
            self.pinned_apps[exists_idx] = entry

        self.save_pinned_apps()
        self.rebuild_pinned_dock()

    def unpin_app(self, item):
        name_lower = (item.get("name") or "").lower()
        app_ids = [a.lower() for a in item.get("app_ids", []) if a]

        self.pinned_apps = [
            p for p in self.pinned_apps
            if not (
                (p.get("name") or "").lower() == name_lower
                or any(aid in [a.lower() for a in p.get("app_ids", [])] for aid in app_ids if aid)
            )
        ]
        self.save_pinned_apps()
        self.rebuild_pinned_dock()

    def rebuild_pinned_dock(self):
        for child in self.pinned_box.get_children():
            self.pinned_box.remove(child)
        self.pinned_widgets = []
        for item in self.pinned_apps:
            w = self.create_dock_item(item, is_dynamic=False)
            self.pinned_box.pack_start(w, False, False, 0)
            self.pinned_widgets.append((item, w))
        self.pinned_box.show_all()
        self.update_dock_data(self.has_windows_on_workspace, self.running_windows)

    def open_pin_app_dialog(self):
        if getattr(self, "pin_dialog", None) and self.pin_dialog.get_visible():
            self.pin_dialog.present()
            return
        self.pin_dialog = DockAppChooserDialog(self)
        self.pin_dialog.show_all()
        self.pin_dialog.present()

    def setup_ui(self):
        self.dock_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.dock_container.set_name("dock-container")
        self.add(self.dock_container)

        # macOS Frosted Glass Capsule
        self.card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.card.set_name("dock-card")
        self.card.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.card.connect("button-press-event", self.on_card_button_press)
        self.dock_container.pack_start(self.card, False, False, 0)

        # 1. Pinned Apps
        self.pinned_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.card.pack_start(self.pinned_box, False, False, 0)

        # 2. Dynamic Running Apps (unpinned active apps)
        self.dynamic_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.card.pack_start(self.dynamic_box, False, False, 0)

        # 3. Glass Separator line before Trash
        self.separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        self.separator.set_name("dock-separator")
        self.card.pack_start(self.separator, False, False, 4)

        # 4. Trash
        trash_files = os.path.expanduser("~/.local/share/Trash/files")
        has_trash = os.path.exists(trash_files) and bool(os.listdir(trash_files))
        self.trash_item = {
            "name": "Trash",
            "icon": ["user-trash-full" if has_trash else "user-trash"],
            "cmd": "nautilus trash:///",
            "app_ids": []
        }
        self.trash_widget = self.create_dock_item(self.trash_item, is_dynamic=False)
        self.card.pack_start(self.trash_widget, False, False, 0)

        self.pinned_widgets = []
        self.dynamic_widgets = []

        # Populate pinned apps
        for item in self.pinned_apps:
            w = self.create_dock_item(item, is_dynamic=False)
            self.pinned_box.pack_start(w, False, False, 0)
            self.pinned_widgets.append((item, w))

    def create_dock_item(self, item, is_dynamic=False, win_id=None):
        btn = Gtk.Button()
        btn.set_name("dock-item")
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.set_can_focus(False)
        btn.set_focus_on_click(False)
        btn.set_tooltip_text(item["name"])

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.set_valign(Gtk.Align.CENTER)
        vbox.set_halign(Gtk.Align.CENTER)
        btn.add(vbox)

        # App Icon resolution (loaded at 64px for razor-sharp magnification rendering)
        pb = None
        size = 64
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

        if not pb:
            try:
                pb = theme.load_icon("application-x-executable", size, Gtk.IconLookupFlags.FORCE_SIZE)
            except Exception:
                pass

        # High-performance Cairo DrawingArea for 120Hz smooth magnification & flowing wave
        da = Gtk.DrawingArea()
        da.set_size_request(48, 68)
        da.set_name("dock-icon-area")
        da.jump_y = 0.0
        da.current_scale = 1.0
        da.target_scale = 1.0
        da.scale_vel = 0.0
        da.current_x_off = 0.0
        da.target_x = 0.0
        da.x_vel = 0.0
        da._pb = pb
        da.connect("draw", self.on_icon_draw)
        vbox.pack_start(da, False, False, 0)

        # macOS Running Indicator Dot
        dot = Gtk.Label(label="•")
        dot.set_name("running-dot")
        dot.get_style_context().add_class("inactive")
        vbox.pack_start(dot, False, False, 0)

        # Event handling: left-click (clicked), right-click (button 3), middle-click (button 2), drag & reorder, hover wave
        btn.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        btn.connect("button-press-event", self.on_item_button_press, item, is_dynamic, win_id)
        btn.connect("button-release-event", self.on_item_button_release, item, is_dynamic)
        btn.connect("motion-notify-event", self.on_item_motion_notify, item, is_dynamic)
        btn.connect("enter-notify-event", self.on_item_enter_notify, item, is_dynamic)
        btn.connect("clicked", self.on_item_clicked, item, win_id)

        btn._dot = dot
        btn._da = da
        btn._item = item
        btn._is_dynamic = is_dynamic
        return btn

    def on_icon_draw(self, widget, cr):
        pb = getattr(widget, "_pb", None)
        if not pb:
            return False
        alloc = widget.get_allocation()
        w = alloc.width if alloc.width > 0 else 48
        h = alloc.height if alloc.height > 0 else 68

        scale = getattr(widget, "current_scale", 1.0)
        x_off = getattr(widget, "current_x_off", 0.0)
        jump = getattr(widget, "jump_y", 0.0)

        # Base icon size is 44px, scaling up with magnification
        target_size = 44.0 * scale
        pb_w = pb.get_width()

        # Center horizontally + BuildUI parting nudge
        x = (w - target_size) / 2.0 + x_off

        # Anchor to bottom baseline:
        # As it scales up, it grows upward and lifts smoothly above the dock
        extra_lift = (scale - 1.0) * 12.0 + jump
        y = (h - 4.0) - target_size - extra_lift

        cr.save()
        cr.reset_clip()  # Allows drawing magnified and parted icons outside the 48px box without clipping
        cr.translate(x, y)
        s = target_size / pb_w
        cr.scale(s, s)
        Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_BILINEAR)
        cr.paint()
        cr.restore()
        return False

    def on_item_button_press(self, btn, event, item, is_dynamic, win_id):
        if event.button == 3:  # Right Click -> Context Menu
            self.show_context_menu(btn, item, is_dynamic, win_id, event)
            return True
        elif event.button == 2:  # Middle Click -> Open New Window
            self.open_new_window(item)
            return True
        elif event.button == 1:  # Left Click -> Prepare drag & reorder
            if item.get("name") != "Trash":
                self.drag_data = {
                    "item": item,
                    "btn": btn,
                    "start_x": event.x_root,
                    "start_y": event.y_root,
                    "is_dragging": False,
                    "is_dynamic": is_dynamic,
                    "win_id": win_id
                }
            return False
        return False

    def on_item_enter_notify(self, btn, event, item, is_dynamic):
        if getattr(self, "drag_data", None) and self.drag_data.get("is_dragging"):
            return False
        self.handle_mouse_motion(event, widget=btn)
        return True

    def on_item_motion_notify(self, btn, event, item, is_dynamic):
        if not self.drag_data:
            self.handle_mouse_motion(event, widget=btn)
            return True
        if not (event.state & Gdk.ModifierType.BUTTON1_MASK):
            self.handle_mouse_motion(event, widget=btn)
            return True

        dx = abs(event.x_root - self.drag_data["start_x"])
        dy = abs(event.y_root - self.drag_data["start_y"])

        if not self.drag_data["is_dragging"]:
            if dx > 8 or dy > 8:
                self.drag_data["is_dragging"] = True
                self.clear_hover_wave()
                btn.get_style_context().add_class("dragging")
            else:
                self.handle_mouse_motion(event, widget=btn)
                return True

        # Live reordering during drag
        if not is_dynamic:
            coords = btn.translate_coordinates(self.pinned_box, event.x, event.y)
            if coords:
                box_x = coords[0]
                children = self.pinned_box.get_children()
                if len(children) > 1 and btn in children:
                    current_idx = children.index(btn)
                    # Find closest slot based on center of other children
                    target_idx = min(
                        range(len(children)),
                        key=lambda i: abs(box_x - (children[i].get_allocation().x + children[i].get_allocation().width / 2))
                    )
                    if target_idx != current_idx:
                        self.pinned_box.reorder_child(btn, target_idx)
                        app_entry = self.pinned_apps.pop(current_idx)
                        self.pinned_apps.insert(target_idx, app_entry)
                        pw_entry = self.pinned_widgets.pop(current_idx)
                        self.pinned_widgets.insert(target_idx, pw_entry)
                        self.pinned_box.queue_draw()
        return True

    def on_item_button_release(self, btn, event, item, is_dynamic):
        if event.button == 1 and self.drag_data:
            was_dragging = self.drag_data.get("is_dragging", False)
            btn.get_style_context().remove_class("dragging")

            if was_dragging:
                self._just_finished_drag = True
                GLib.timeout_add(150, lambda: setattr(self, "_just_finished_drag", False))

                if is_dynamic:
                    coords = btn.translate_coordinates(self.pinned_box, event.x, event.y)
                    if coords:
                        box_x = coords[0]
                        p_alloc = self.pinned_box.get_allocation()
                        if -20 <= box_x <= p_alloc.width + 20:
                            children = self.pinned_box.get_children()
                            target_idx = len(children)
                            if children:
                                target_idx = min(
                                    range(len(children)),
                                    key=lambda i: abs(box_x - (children[i].get_allocation().x + children[i].get_allocation().width / 2))
                                )
                            self.pin_app(item)
                            if target_idx < len(self.pinned_apps):
                                new_item = self.pinned_apps.pop()
                                self.pinned_apps.insert(target_idx, new_item)
                                self.save_pinned_apps()
                                self.rebuild_pinned_dock()
                else:
                    self.save_pinned_apps()

                self.drag_data = None
                return True

            self.drag_data = None
        return False

    def on_window_button_release(self, widget, event):
        if event.button == 1 and self.drag_data:
            btn = self.drag_data.get("btn")
            if btn:
                btn.get_style_context().remove_class("dragging")
            was_dragging = self.drag_data.get("is_dragging", False)
            if was_dragging:
                self._just_finished_drag = True
                GLib.timeout_add(150, lambda: setattr(self, "_just_finished_drag", False))
                if not self.drag_data.get("is_dynamic", False):
                    self.save_pinned_apps()
            self.drag_data = None
        return False

    def on_item_clicked(self, btn, item, win_id=None):
        if getattr(self, "_just_finished_drag", False):
            return
        if self.drag_data and self.drag_data.get("is_dragging"):
            return

        name = item.get("name", "")
        if name in self.bouncing_apps:
            # Already launching and bouncing! Don't spawn multiple instances on rapid clicks
            return

        matching_windows = self.get_windows_for_item(item)

        if matching_windows:
            # If multiple windows exist and one is currently focused, cycle to the next window!
            focused_idx = next((i for i, w in enumerate(matching_windows) if w.get("is_focused")), None)
            if focused_idx is not None and len(matching_windows) > 1:
                next_win = matching_windows[(focused_idx + 1) % len(matching_windows)]
                subprocess.Popen(["niri", "msg", "action", "focus-window", "--id", str(next_win["id"])])
            else:
                target_win = matching_windows[0]
                subprocess.Popen(["niri", "msg", "action", "focus-window", "--id", str(target_win["id"])])
        else:
            # Launch app with bouncing animation until window opens!
            self.start_bouncing(item, btn)
            cmd = item.get("cmd")
            if cmd:
                subprocess.Popen(cmd, shell=True)

    # --- Jumping / Bouncing Physics Engine ---
    def get_button_for_item(self, item):
        name = item.get("name")
        if name == "Trash":
            return getattr(self, "trash_widget", None)
        for itm, btn in self.pinned_widgets:
            if itm.get("name") == name:
                return btn
        for btn in self.dynamic_widgets:
            if getattr(btn, "_item", {}).get("name") == name:
                return btn
        return None

    def start_bouncing(self, item, btn=None):
        if not btn:
            btn = self.get_button_for_item(item)
        if not btn:
            return
        name = item.get("name", "")
        if name in self.bouncing_apps:
            return
        da = getattr(btn, "_da", None)
        if not da:
            return

        prev_ids = {w["id"] for w in self.running_windows if self.matches_item(item, w)}

        self.bouncing_apps[name] = {
            "item": item,
            "btn": btn,
            "da": da,
            "start_time": time.time(),
            "prev_ids": prev_ids
        }

        if not self.is_bouncing_animating:
            self.is_bouncing_animating = True
            self.add_tick_callback(self.on_bounce_tick)

    def stop_bouncing(self, name):
        data = self.bouncing_apps.pop(name, None)
        if data:
            da = data.get("da")
            if da:
                da.jump_y = 0.0
                da.queue_draw()

    def on_bounce_tick(self, widget, frame_clock):
        now = time.time()
        MAX_JUMP = 12.0
        CYCLE = 0.52
        JUMP_DUR = 0.38
        TIMEOUT = 14.0

        to_remove = []
        for name, data in list(self.bouncing_apps.items()):
            elapsed = now - data["start_time"]
            if elapsed > TIMEOUT:
                to_remove.append(name)
                continue

            c = elapsed % CYCLE
            if c < JUMP_DUR:
                progress = c / JUMP_DUR
                jump = MAX_JUMP * math.sin(progress * math.pi)
            else:
                jump = 0.0

            da = data["da"]
            da.jump_y = jump
            da.queue_draw()

        for name in to_remove:
            self.stop_bouncing(name)

        if not self.bouncing_apps:
            self.is_bouncing_animating = False
            return False
        return True

    # --- Flowing Wave & Hover Jump Physics (macOS Style, 0% Idle CPU) ---
    def get_all_icon_buttons(self):
        buttons = []
        if hasattr(self, "pinned_box"):
            buttons.extend(self.pinned_box.get_children())
        if hasattr(self, "dynamic_box"):
            buttons.extend(self.dynamic_box.get_children())
        if hasattr(self, "trash_widget") and self.trash_widget:
            buttons.append(self.trash_widget)
        return [b for b in buttons if hasattr(b, "_da")]

    def start_wave_animation(self):
        if not self.is_wave_animating:
            self.is_wave_animating = True
            self.last_wave_time = None
            self.add_tick_callback(self.on_wave_tick)

    def handle_mouse_motion(self, event, widget=None):
        if getattr(self, "drag_data", None) and self.drag_data.get("is_dragging"):
            return

        if not self.is_mouse_over:
            self.is_mouse_over = True
            self.request_animation()
        if self.leave_timer_id:
            GLib.source_remove(self.leave_timer_id)
            self.leave_timer_id = None

        if widget is None:
            widget = self

        coords = widget.translate_coordinates(self.card, event.x, event.y)
        if not coords:
            return

        card_x, card_y = coords
        alloc = self.card.get_allocation()
        card_w = alloc.width if alloc.width > 0 else 550
        card_h = alloc.height if alloc.height > 0 else 76

        # Tracking within card bounds with generous vertical headroom for lifted icons
        if -15 <= card_x <= card_w + 15 and -45 <= card_y <= card_h + 15:
            self.update_hover_wave(card_x)
        else:
            self.clear_hover_wave()

    def update_hover_wave(self, mouse_card_x):
        if getattr(self, "drag_data", None) and self.drag_data.get("is_dragging"):
            return

        DISTANCE = 110.0  # BuildUI DISTANCE
        SCALE = 1.55      # BuildUI SCALE factor
        NUDGE = 18.0      # BuildUI NUDGE (parting displacement)

        buttons = self.get_all_icon_buttons()
        any_active = False

        for btn in buttons:
            da = getattr(btn, "_da", None)
            if not da:
                continue
            coords = btn.translate_coordinates(self.card, 0, 0)
            if not coords:
                continue
            alloc = btn.get_allocation()
            btn_w = alloc.width if alloc.width > 0 else 48.0
            center_x = coords[0] + btn_w / 2.0
            d = mouse_card_x - center_x
            abs_d = abs(d)

            if abs_d < DISTANCE:
                # Smooth bell curve for scale
                target_scale = 1.0 + (SCALE - 1.0) * 0.5 * (1.0 + math.cos(math.pi * abs_d / DISTANCE))
                # BuildUI parting nudge away from mouse
                target_x = (-d / DISTANCE) * NUDGE * target_scale
            else:
                target_scale = 1.0
                target_x = -1.0 * (1.0 if d > 0 else -1.0) * NUDGE

            da.target_scale = target_scale
            da.target_x = target_x

            cur_s = getattr(da, "current_scale", 1.0)
            cur_x = getattr(da, "current_x_off", 0.0)
            vel_s = getattr(da, "scale_vel", 0.0)
            vel_x = getattr(da, "x_vel", 0.0)
            if abs(target_scale - cur_s) > 0.003 or abs(target_x - cur_x) > 0.05 or abs(vel_s) > 0.01 or abs(vel_x) > 0.5:
                any_active = True

        if any_active:
            self.start_wave_animation()

    def clear_hover_wave(self):
        buttons = self.get_all_icon_buttons()
        any_to_lower = False
        for btn in buttons:
            da = getattr(btn, "_da", None)
            if da:
                da.target_scale = 1.0
                da.target_x = 0.0
                cur_s = getattr(da, "current_scale", 1.0)
                cur_x = getattr(da, "current_x_off", 0.0)
                vel_s = getattr(da, "scale_vel", 0.0)
                vel_x = getattr(da, "x_vel", 0.0)
                if abs(cur_s - 1.0) > 0.003 or abs(cur_x) > 0.05 or abs(vel_s) > 0.01 or abs(vel_x) > 0.5:
                    any_to_lower = True
        if any_to_lower:
            self.start_wave_animation()

    def on_wave_tick(self, widget, frame_clock):
        now = time.time()
        if self.last_wave_time is None:
            dt = 0.016
        else:
            dt = min(0.033, max(0.001, now - self.last_wave_time))
        self.last_wave_time = now

        # BuildUI spring physics (critically damped, snappy)
        STIFFNESS = 280.0
        DAMPING = 28.0

        buttons = self.get_all_icon_buttons()
        any_moving = False

        for btn in buttons:
            da = getattr(btn, "_da", None)
            if not da:
                continue

            # 1. Scale spring physics
            s = getattr(da, "current_scale", 1.0)
            vs = getattr(da, "scale_vel", 0.0)
            ts = getattr(da, "target_scale", 1.0)
            diff_s = ts - s

            if abs(diff_s) > 0.003 or abs(vs) > 0.01:
                any_moving = True
                force_s = diff_s * STIFFNESS - vs * DAMPING
                vs += force_s * dt
                s += vs * dt
                if s < 1.0:
                    s = 1.0
                    vs = 0.0
                da.current_scale = s
                da.scale_vel = vs
            elif s != ts or vs != 0.0:
                da.current_scale = ts
                da.scale_vel = 0.0

            # 2. X offset (BuildUI parting nudge) spring physics
            x = getattr(da, "current_x_off", 0.0)
            vx = getattr(da, "x_vel", 0.0)
            tx = getattr(da, "target_x", 0.0)
            diff_x = tx - x

            if abs(diff_x) > 0.05 or abs(vx) > 0.5:
                any_moving = True
                force_x = diff_x * STIFFNESS - vx * DAMPING
                vx += force_x * dt
                x += vx * dt
                da.current_x_off = x
                da.x_vel = vx
            elif x != tx or vx != 0.0:
                da.current_x_off = tx
                da.x_vel = 0.0

        # Invalidate the card so all nudged and magnified icons repaint smoothly
        self.card.queue_draw()

        if not any_moving:
            all_base = all(
                getattr(btn._da, "target_scale", 1.0) == 1.0 and getattr(btn._da, "target_x", 0.0) == 0.0
                for btn in buttons if hasattr(btn, "_da")
            )
            if all_base:
                for btn in buttons:
                    if hasattr(btn, "_da"):
                        btn._da.current_scale = 1.0
                        btn._da.scale_vel = 0.0
                        btn._da.target_scale = 1.0
                        btn._da.current_x_off = 0.0
                        btn._da.x_vel = 0.0
                        btn._da.target_x = 0.0
                self.card.queue_draw()
            self.is_wave_animating = False
            self.last_wave_time = None
            return False

        return True

    def on_card_motion_notify(self, widget, event):
        self.handle_mouse_motion(event, widget=widget)
        return False

    def on_card_leave_notify(self, widget, event):
        if event.detail != Gdk.NotifyType.INFERIOR:
            self.clear_hover_wave()
        return False

    # --- Windows & Action Discovery ---
    def matches_item(self, item, w):
        win_id = item.get("win_id")
        if win_id is not None and w.get("id") == win_id:
            return True

        name = (item.get("name") or "").lower()
        aid = (w.get("app_id") or "").lower()
        title = (w.get("title") or "").lower()

        # Special case for Trash: file managers like Nautilus open trash:/// with title "Trash"
        if name == "trash":
            fm_ids = ["nautilus", "org.gnome.nautilus", "thunar", "dolphin", "nemo", "caja", "pcmanfm"]
            if any(fm in aid for fm in fm_ids) and "trash" in title:
                return True
            if "trash" in title and not aid:
                return True
            return False

        # If window is specifically a Trash window, do not match regular file manager dock items
        if "trash" in title and any(fm in aid for fm in ["nautilus", "org.gnome.nautilus", "thunar", "dolphin"]):
            return False

        app_ids = [a.lower() for a in item.get("app_ids", []) if a]
        for a in app_ids:
            if a in aid or aid in a:
                return True
        if not app_ids and aid:
            if aid in name or name in aid:
                return True
        return False

    def get_windows_for_item(self, item):
        return [w for w in self.running_windows if self.matches_item(item, w)]

    def supports_new_window(self, item):
        name = (item.get("name") or "").lower()
        app_ids = [a.lower() for a in item.get("app_ids", []) if a]
        known = ["zen", "browser", "firefox", "chrome", "chromium", "nautilus", "files", "code", "codium", "terminal", "kitty", "foot", "alacritty"]
        if any(k in name for k in known):
            return True
        if any(any(k in a for k in known) for a in app_ids):
            return True

        dinfo = find_desktop_info(item)
        if dinfo:
            actions = dinfo.list_actions()
            if "new-window" in actions or "new-empty-window" in actions:
                return True
        return False

    def open_new_window(self, item):
        self.start_bouncing(item)
        name = (item.get("name") or "").lower()
        app_ids = [a.lower() for a in item.get("app_ids", []) if a]

        # Zen Browser
        if "zen" in name or any("zen" in a for a in app_ids):
            subprocess.Popen(["flatpak", "run", "app.zen_browser.zen", "--new-window"])
            return

        # Nautilus
        if "nautilus" in name or "files" in name or any("nautilus" in a for a in app_ids):
            subprocess.Popen(["nautilus", "--new-window"])
            return

        # VS Code
        if "code" in name or any("code" in a for a in app_ids):
            subprocess.Popen(["code", "--new-window"])
            return

        # Terminal
        if "terminal" in name or "kitty" in name or any("kitty" in a for a in app_ids):
            subprocess.Popen(["kitty"])
            return

        # Firefox
        if "firefox" in name or any("firefox" in a for a in app_ids):
            subprocess.Popen(["firefox", "--new-window"])
            return

        # Chrome
        if "chrome" in name or any("chrome" in a for a in app_ids):
            subprocess.Popen(["google-chrome", "--new-window"])
            return

        # Desktop actions lookup
        dinfo = find_desktop_info(item)
        if dinfo:
            for act in ["new-window", "new-empty-window"]:
                if act in dinfo.list_actions():
                    try:
                        dinfo.launch_action(act, None)
                        return
                    except Exception:
                        pass

        cmd = item.get("cmd")
        if cmd:
            subprocess.Popen(cmd, shell=True)

    def get_extra_actions(self, item):
        actions = []
        name = (item.get("name") or "").lower()
        app_ids = [a.lower() for a in item.get("app_ids", []) if a]

        # Zen Browser
        if "zen" in name or any("zen" in a for a in app_ids):
            actions.append((
                "New Private Window",
                "security-high-symbolic",
                lambda _: (self.start_bouncing(item), subprocess.Popen(["flatpak", "run", "app.zen_browser.zen", "--private-window"]))
            ))
            return actions

        # Firefox
        if "firefox" in name or any("firefox" in a for a in app_ids):
            actions.append((
                "New Private Window",
                "security-high-symbolic",
                lambda _: (self.start_bouncing(item), subprocess.Popen(["firefox", "--private-window"]))
            ))
            return actions

        # Chrome
        if "chrome" in name or "chromium" in name or any("chrome" in a for a in app_ids):
            actions.append((
                "New Incognito Window",
                "security-high-symbolic",
                lambda _: (self.start_bouncing(item), subprocess.Popen(["google-chrome", "--incognito"]))
            ))
            return actions

        # Query DesktopAppInfo for any other desktop actions
        dinfo = find_desktop_info(item)
        if dinfo:
            for act in dinfo.list_actions():
                if act in ["new-window", "new-empty-window"]:
                    continue
                act_label = dinfo.get_action_name(act)
                act_icon = "system-run-symbolic"
                act_lower = act.lower()
                if "private" in act_lower or "incognito" in act_lower:
                    act_icon = "security-high-symbolic"
                elif "profile" in act_lower:
                    act_icon = "avatar-default-symbolic"

                def make_launcher(act=act, dinfo=dinfo, item=item):
                    def _launch(_):
                        self.start_bouncing(item)
                        dinfo.launch_action(act, None)
                    return _launch

                actions.append((act_label, act_icon, make_launcher(act, dinfo, item)))

        return actions

    def quit_app(self, item):
        windows = self.get_windows_for_item(item)
        for w in windows:
            wid = w.get("id")
            if wid is not None:
                subprocess.Popen(["niri", "msg", "action", "close-window", "--id", str(wid)])

    def empty_trash(self):
        trash_dir = os.path.expanduser("~/.local/share/Trash")
        for sub in ["files", "info"]:
            path = os.path.join(trash_dir, sub)
            if os.path.exists(path):
                try:
                    for f in os.listdir(path):
                        fp = os.path.join(path, f)
                        try:
                            if os.path.isdir(fp) and not os.path.islink(fp):
                                import shutil
                                shutil.rmtree(fp)
                            else:
                                os.remove(fp)
                        except Exception:
                            pass
                except Exception:
                    pass
        try:
            subprocess.Popen(["gio", "trash", "--empty"])
        except Exception:
            pass

    def create_menu_item(self, label_text, icon_name=None, callback=None, is_header=False, is_danger=False, markup=None):
        item = Gtk.MenuItem()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        if icon_name:
            img = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU)
            box.pack_start(img, False, False, 0)

        lbl = Gtk.Label()
        if markup:
            lbl.set_markup(markup)
        elif is_header:
            lbl.set_markup(f"<span weight='bold' foreground='#FFFFFF'>{GLib.markup_escape_text(label_text)}</span>")
            item.set_sensitive(False)
            item.get_style_context().add_class("menu-header")
        else:
            lbl.set_text(label_text)

        lbl.set_xalign(0.0)
        box.pack_start(lbl, True, True, 0)
        item.add(box)

        if is_danger:
            item.get_style_context().add_class("menu-danger")

        if callback and not is_header:
            item.connect("activate", callback)

        return item

    # --- Context Menu Display ---
    def show_context_menu(self, btn, item, is_dynamic, win_id, event):
        if self.active_menu:
            try:
                self.active_menu.popdown()
            except Exception:
                pass

        menu = Gtk.Menu()
        menu.get_style_context().add_class("dock-menu")
        self.active_menu = menu
        self.is_menu_open = True

        # Set 32-bit RGBA visual so rounded corners have true alpha (no black corners)
        top = menu.get_toplevel()
        screen = Gdk.Screen.get_default()
        if screen:
            rgba = screen.get_rgba_visual()
            if rgba:
                top.set_visual(rgba)
        top.set_app_paintable(True)

        name = item.get("name", "Application")
        is_trash = (name.lower() == "trash")

        if is_trash:
            # Trash Menu
            menu.append(self.create_menu_item("Trash", is_header=True))
            menu.append(Gtk.SeparatorMenuItem())
            menu.append(self.create_menu_item(
                "Open Trash",
                "folder-open-symbolic",
                lambda _: (self.start_bouncing(item), subprocess.Popen("nautilus trash:///", shell=True))
            ))
            menu.append(self.create_menu_item(
                "Empty Trash",
                "edit-delete-symbolic",
                lambda _: self.empty_trash()
            ))
        else:
            windows = self.get_windows_for_item(item)
            is_running = len(windows) > 0

            # 1. Header with App Title & Running State
            escaped_name = GLib.markup_escape_text(name)
            if is_running:
                status_text = f"  <span size='small' foreground='#B5B5BE'>• Running ({len(windows)})</span>" if len(windows) > 1 else "  <span size='small' foreground='#B5B5BE'>• Running</span>"
                header_markup = f"<span weight='bold' foreground='#FFFFFF'>{escaped_name}</span>{status_text}"
            else:
                header_markup = f"<span weight='bold' foreground='#FFFFFF'>{escaped_name}</span>"
            menu.append(self.create_menu_item(name, is_header=True, markup=header_markup))
            menu.append(Gtk.SeparatorMenuItem())

            # 2. Open Windows List (GNOME/macOS Window Switcher)
            if is_running:
                for w in windows:
                    w_title = w.get("title") or "Window"
                    if len(w_title) > 40:
                        w_title = w_title[:38] + "…"
                    w_id = w.get("id")
                    is_focused = w.get("is_focused", False)
                    escaped_title = GLib.markup_escape_text(w_title)
                    if is_focused:
                        w_markup = f"<span foreground='#D6C850'>●</span>  <span foreground='#FFFFFF' weight='bold'>{escaped_title}</span>"
                    else:
                        w_markup = f"<span foreground='#7E7E88'>○</span>  <span foreground='#E6E6EC'>{escaped_title}</span>"
                    menu.append(self.create_menu_item(
                        w_title,
                        "window-restore-symbolic",
                        lambda _, wid=w_id: subprocess.Popen(["niri", "msg", "action", "focus-window", "--id", str(wid)]),
                        markup=w_markup
                    ))
                menu.append(Gtk.SeparatorMenuItem())

            # 3. Main Launch Actions
            # "Open"
            menu.append(self.create_menu_item(
                "Open",
                "media-playback-start-symbolic",
                lambda _: self.on_item_clicked(btn, item, win_id)
            ))

            # "Open in New Window"
            if self.supports_new_window(item):
                menu.append(self.create_menu_item(
                    "Open in New Window",
                    "window-new-symbolic",
                    lambda _: self.open_new_window(item)
                ))

            # Extra Desktop Actions (e.g. New Private Window)
            extra_actions = self.get_extra_actions(item)
            for act_label, act_icon, act_fn in extra_actions:
                menu.append(self.create_menu_item(act_label, act_icon, act_fn))

            # 4. Dock Pinning Section
            menu.append(Gtk.SeparatorMenuItem())
            if is_dynamic:
                menu.append(self.create_menu_item(
                    "Pin to Dock",
                    "view-pin-symbolic",
                    lambda _: self.pin_app(item)
                ))
            else:
                menu.append(self.create_menu_item(
                    "Unpin from Dock",
                    "view-pin-symbolic",
                    lambda _: self.unpin_app(item)
                ))
            menu.append(self.create_menu_item(
                "Pin More Apps...",
                "list-add-symbolic",
                lambda _: self.open_pin_app_dialog()
            ))

            # 5. Quit Option (GNOME Quit)
            if is_running:
                menu.append(Gtk.SeparatorMenuItem())
                quit_label = "Quit" if len(windows) <= 1 else f"Close All Windows ({len(windows)})"
                menu.append(self.create_menu_item(
                    quit_label,
                    "application-exit-symbolic",
                    lambda _: self.quit_app(item),
                    is_danger=True
                ))

        menu.connect("deactivate", self.on_menu_deactivated)
        menu.show_all()
        menu.popup_at_widget(btn, Gdk.Gravity.NORTH, Gdk.Gravity.SOUTH, event)

    def on_card_button_press(self, widget, event):
        if event.button == 3:
            if self.active_menu:
                try:
                    self.active_menu.popdown()
                except Exception:
                    pass

            menu = Gtk.Menu()
            menu.get_style_context().add_class("dock-menu")
            self.active_menu = menu
            self.is_menu_open = True

            top = menu.get_toplevel()
            screen = Gdk.Screen.get_default()
            if screen:
                rgba = screen.get_rgba_visual()
                if rgba:
                    top.set_visual(rgba)
            top.set_app_paintable(True)

            menu.append(self.create_menu_item("macOS Dock", is_header=True))
            menu.append(Gtk.SeparatorMenuItem())
            menu.append(self.create_menu_item(
                "Pin Application to Dock...",
                "list-add-symbolic",
                lambda _: self.open_pin_app_dialog()
            ))
            menu.append(self.create_menu_item(
                "Open App Launcher (Fuzzel)",
                "view-app-grid-symbolic",
                lambda _: subprocess.Popen(["fuzzel"])
            ))
            menu.append(Gtk.SeparatorMenuItem())
            menu.append(self.create_menu_item(
                "Niri Settings",
                "preferences-system",
                lambda _: subprocess.Popen(["/usr/bin/python3", "/home/sreyas/.config/niri/niri-settings.py"])
            ))
            menu.append(self.create_menu_item(
                "Restart Dock",
                "view-refresh-symbolic",
                lambda _: self.restart_dock()
            ))

            menu.connect("deactivate", self.on_menu_deactivated)
            menu.show_all()
            menu.popup_at_pointer(event)
            return True
        return False

    def restart_dock(self):
        cleanup()
        time.sleep(0.1)
        os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)] + sys.argv[1:])

    def on_menu_deactivated(self, menu):
        self.is_menu_open = False
        self.active_menu = None
        GLib.timeout_add(150, self._check_after_menu_closed)

    def _check_after_menu_closed(self):
        if not self.is_mouse_over and not self.is_menu_open:
            self.request_animation()
        return False

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
        self.handle_mouse_motion(event, widget=widget)
        return False

    def on_leave_notify(self, widget, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        self.clear_hover_wave()
        if self.is_menu_open:
            return False
        if self.leave_timer_id:
            GLib.source_remove(self.leave_timer_id)
        # 400ms delay before sliding down
        self.leave_timer_id = GLib.timeout_add(400, self._on_delayed_leave)
        return False

    def _on_delayed_leave(self):
        if self.is_menu_open:
            return False
        self.clear_hover_wave()
        self.is_mouse_over = False
        self.leave_timer_id = None
        self.request_animation()
        return False

    def should_be_visible(self):
        # 1. Always visible during Overview!
        if self.is_overview_open:
            return True
        # 2. Always visible when right-click menu is open!
        if self.is_menu_open:
            return True
        # 3. Always visible when hovered
        if self.is_mouse_over:
            return True
        # 4. Always visible when current workspace has NO windows (empty desktop)
        if not self.has_windows_on_workspace:
            return True
        # 5. Otherwise hidden (auto-hide)
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
            return False  # Animation complete: unhook callback for 0.0% CPU!

    # --- Live State Updates (Showing All Active Apps) ---
    def update_dock_data(self, has_windows, windows):
        self.has_windows_on_workspace = has_windows
        self.running_windows = windows
        self.request_animation()

        # Stop bouncing for apps that now have their new window open
        if self.bouncing_apps:
            for name, data in list(self.bouncing_apps.items()):
                item = data["item"]
                prev_ids = data["prev_ids"]
                new_windows = [w for w in windows if self.matches_item(item, w) and w["id"] not in prev_ids]
                if new_windows:
                    self.stop_bouncing(name)

        # 1. Update running dots on pinned apps
        running_app_ids = set()
        for w in windows:
            aid = (w.get("app_id") or "").lower()
            title = (w.get("title") or "").lower()
            if any(fm in aid for fm in ["nautilus", "org.gnome.nautilus", "thunar", "dolphin"]) and "trash" in title:
                continue
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
        pinned_app_id_list = [aid.lower() for item in self.pinned_apps for aid in item.get("app_ids", [])]
        unpinned_windows = []
        seen_unpinned = set()

        for w in windows:
            aid = (w.get("app_id") or "").lower()
            title = w.get("title") or "Window"
            app_key = aid if aid else title.lower()

            # Trash windows belong to the dedicated Trash item, not dynamic items
            if "trash" in title.lower() and any(fm in aid for fm in ["nautilus", "org.gnome.nautilus", "thunar", "dolphin"]):
                continue

            is_pinned = any(p in aid or aid in p for p in pinned_app_id_list) if aid else False
            if not is_pinned:
                if app_key not in seen_unpinned:
                    seen_unpinned.add(app_key)
                    unpinned_windows.append(w)

        # 3. Dynamic Trash Icon (full vs empty)
        if hasattr(self, "trash_widget"):
            da = getattr(self.trash_widget, "_da", None)
            if da:
                trash_files = os.path.expanduser("~/.local/share/Trash/files")
                is_full = os.path.exists(trash_files) and bool(os.listdir(trash_files))
                target_icon = "user-trash-full" if is_full else "user-trash"
                if getattr(self, "_last_trash_icon", None) != target_icon:
                    self._last_trash_icon = target_icon
                    theme = Gtk.IconTheme.get_default()
                    try:
                        da._pb = theme.load_icon(target_icon, 44, Gtk.IconLookupFlags.FORCE_SIZE)
                        da.queue_draw()
                    except Exception:
                        pass

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
                    "app_ids": [aid] if aid else [],
                    "win_id": w.get("id")
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
                            elif "WindowOpenedOrChanged" in data:
                                w_info = data["WindowOpenedOrChanged"].get("window")
                                if w_info:
                                    idx = next((i for i, w in enumerate(current_windows) if w["id"] == w_info["id"]), None)
                                    if idx is not None:
                                        current_windows[idx] = w_info
                                    else:
                                        current_windows.append(w_info)
                                    changed = True
                            elif "WindowClosed" in data:
                                w_id = data["WindowClosed"].get("id")
                                if w_id is not None:
                                    current_windows = [w for w in current_windows if w["id"] != w_id]
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

    # --- Styling (macOS Frosted Glass & GNOME Context Menu) ---
    def apply_css(self):
        theme_path = "/home/sreyas/.config/waybar/current-theme.css"
        css_provider = Gtk.CssProvider()
        css = f"""
        @import url('{theme_path}');

        * {{
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Symbols Nerd Font", "JetBrains Mono", sans-serif;
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

        #dock-item,
        #dock-item:focus,
        #dock-item:active,
        #dock-item:focus:hover {{
            background: transparent;
            border: none;
            outline: none;
            outline-style: none;
            outline-width: 0;
            -gtk-outline-radius: 0;
            box-shadow: none;
            border-radius: 12px;
            padding: 4px 4px 2px 4px;
            margin: 0 1px;
            min-width: 60px;
            transition: background-color 0.15s cubic-bezier(0.16, 1, 0.3, 1);
        }}

        #dock-item:hover,
        #dock-item:focus:hover {{
            background-color: rgba(255, 255, 255, 0.12);
        }}

        #dock-item.dragging {{
            opacity: 0.50;
            background-color: alpha(@accent-purple, 0.35);
            border-radius: 12px;
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

        /* Context Menu (GNOME / macOS Solid High-Contrast Dark Menu - Completely Opaque & Crisp Visible Border) */
        window.popup,
        window.popup.background,
        window.popup decoration {{
            background: transparent;
            background-color: transparent;
            box-shadow: none;
            border: none;
            margin: 0;
            padding: 0;
        }}

        window.popup menu,
        menu.dock-menu {{
            background-color: #1e1e24;
            border: 1.5px solid rgba(255, 255, 255, 0.32);
            border-radius: 12px;
            padding: 6px;
            margin: 0;
            box-shadow: none;
        }}

        window.popup menu menuitem,
        menu.dock-menu menuitem {{
            background-color: transparent;
            border-radius: 7px;
            padding: 7px 12px;
            color: #FFFFFF;
            font-size: 13px;
            font-weight: 500;
            margin: 1px 0;
        }}

        window.popup menu menuitem:hover,
        menu.dock-menu menuitem:hover {{
            background-color: alpha(@accent-purple, 0.45);
            color: #FFFFFF;
        }}

        window.popup menu menuitem.menu-header,
        menu.dock-menu menuitem.menu-header,
        window.popup menu menuitem.menu-header:disabled,
        menu.dock-menu menuitem.menu-header:disabled {{
            background-color: transparent;
            padding: 5px 12px 3px 12px;
        }}

        window.popup menu menuitem.menu-header label,
        menu.dock-menu menuitem.menu-header label,
        window.popup menu menuitem.menu-header:disabled label,
        menu.dock-menu menuitem.menu-header:disabled label {{
            color: rgba(255, 255, 255, 0.70);
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }}

        window.popup menu menuitem.menu-header:hover,
        menu.dock-menu menuitem.menu-header:hover {{
            background-color: transparent;
        }}

        window.popup menu menuitem.menu-danger:hover,
        menu.dock-menu menuitem.menu-danger:hover {{
            background-color: rgba(235, 77, 75, 0.45);
            color: #FFFFFF;
        }}

        window.popup menu separator,
        menu.dock-menu separator {{
            background-color: rgba(255, 255, 255, 0.18);
            min-height: 1px;
            margin: 4px 6px;
        }}

        /* Add App to Dock Button */
        #dock-add-btn {{
            background: transparent;
            border: none;
            border-radius: 12px;
            padding: 8px 10px;
            margin: 4px 2px;
            color: rgba(255, 255, 255, 0.65);
            min-width: 38px;
            outline: none;
            box-shadow: none;
        }}

        #dock-add-btn:hover {{
            background-color: rgba(255, 255, 255, 0.18);
            color: #FFFFFF;
        }}

        /* App Chooser Dialog Styling */
        window.dock-app-dialog,
        #dock-app-dialog-content {{
            background-color: #1e1e24;
            color: #FFFFFF;
            border-radius: 16px;
        }}

        #dock-app-dialog-header {{
            border-bottom: 1px solid rgba(255, 255, 255, 0.12);
            padding-bottom: 12px;
        }}

        #dock-app-dialog-search {{
            background-color: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 10px;
            color: #FFFFFF;
            padding: 6px 12px;
        }}

        #dock-app-dialog-search:focus {{
            border-color: @accent-purple;
            box-shadow: 0 0 0 1px @accent-purple;
        }}

        #dock-app-row {{
            border-radius: 8px;
            padding: 6px 10px;
        }}

        #dock-app-row:hover {{
            background-color: rgba(255, 255, 255, 0.08);
        }}

        #dock-app-pin-btn {{
            border-radius: 14px;
            padding: 4px 14px;
            font-size: 11px;
            font-weight: 700;
            outline: none;
            box-shadow: none;
        }}

        #dock-app-pin-btn.pinned {{
            background-color: @accent-purple;
            color: #FFFFFF;
            border: 1px solid transparent;
        }}

        #dock-app-pin-btn.pinned:hover {{
            background-color: shade(@accent-purple, 1.2);
        }}

        #dock-app-pin-btn.unpinned {{
            background-color: rgba(255, 255, 255, 0.08);
            color: #E2E2EC;
            border: 1px solid rgba(255, 255, 255, 0.22);
        }}

        #dock-app-pin-btn.unpinned:hover {{
            background-color: rgba(255, 255, 255, 0.18);
            border-color: rgba(255, 255, 255, 0.40);
        }}

        #dock-app-dialog-done {{
            background-color: @accent-purple;
            color: #FFFFFF;
            border-radius: 8px;
            padding: 6px 20px;
            font-weight: 600;
            border: none;
            outline: none;
        }}

        #dock-app-dialog-done:hover {{
            background-color: shade(@accent-purple, 1.2);
        }}
        """
        css_provider.load_from_data(css.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def main():
    if "--pin-dialog" in sys.argv or "--manage-pins" in sys.argv:
        # Run standalone App Chooser Dialog
        MacOSDock.apply_css(None)
        manager = StandaloneDockManager()
        dlg = DockAppChooserDialog(manager)
        dlg.connect("destroy", Gtk.main_quit)
        dlg.show_all()
        Gtk.main()
        return

    enforce_single_instance()
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    app = MacOSDock()
    app.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
