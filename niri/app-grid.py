#!/usr/bin/python3
import os
import sys
import signal

PID_FILE = "/tmp/gnome_app_grid.pid"

def is_pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

# Fast-path IPC: If daemon is running, toggle via signal and exit in <15ms without loading GTK
if os.path.exists(PID_FILE):
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        if is_pid_alive(pid):
            if "--daemon" in sys.argv:
                sys.exit(0)
            os.kill(pid, signal.SIGUSR1)
            sys.exit(0)
    except (OSError, ValueError):
        pass
    try:
        os.remove(PID_FILE)
    except OSError:
        pass

import time
import subprocess

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GtkLayerShell, GLib, Gio, GdkPixbuf, GLibUnix

THEME_CSS_PATH = "/home/sreyas/.config/waybar/current-theme.css"
BLURRED_WALL_PATH = "/home/sreyas/.cache/current_wallpaper_blurred.png"

CATS_MAP = {
    "Internet": ["network", "webbrowser", "email", "chat", "instantmessaging", "feed", "filetransfer", "p2p", "remoteaccess", "videoconference"],
    "Development": ["development", "ide", "debugger", "texteditor", "webdevelopment", "science"],
    "Media": ["audiovideo", "audio", "video", "graphics", "2dgraphics", "3dgraphics", "rastergraphics", "vectorgraphics", "photography", "recorder", "music", "player", "audiovideoediting", "viewer"],
    "Games": ["game", "emulator", "simulation", "logicgame", "amusement"],
    "Office": ["office", "calendar", "contactmanagement", "spreadsheet", "wordprocessor", "presentation"],
    "Utilities": ["utility", "calculator", "clock", "scanning", "printing", "x-gnome-utilities", "accessories", "archiving"],
    "System": ["system", "settings", "desktopsettings", "hardwaresettings", "filemanager", "terminalemulator", "monitor", "packagemanager", "filesystem"]
}

def handle_cli_and_ipc():
    try:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except Exception as e:
        print(f"Failed to write PID file: {e}")

def cleanup():
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except OSError:
        pass
    Gtk.main_quit()


def get_app_image(app_info, size=72):
    gicon = app_info.get_icon()
    if gicon:
        img = Gtk.Image.new_from_gicon(gicon, Gtk.IconSize.DIALOG)
        img.set_pixel_size(size)
        return img
    img = Gtk.Image.new_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)
    img.set_pixel_size(size)
    return img


class AppTile(Gtk.Button):
    def __init__(self, app_info):
        super().__init__()
        self.app_info = app_info
        self.set_name("app-tile")
        self.set_relief(Gtk.ReliefStyle.NONE)
        self.set_size_request(140, 136)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        box.set_can_focus(False)

        # 72px Pre-rendered Crisp Vector Icon
        img = get_app_image(app_info, 72)
        img.set_can_focus(False)
        box.pack_start(img, False, False, 0)

        # App Label
        name = app_info.get_display_name() or app_info.get_name() or "App"
        label = Gtk.Label(label=name)
        label.set_name("app-label")
        label.set_justify(Gtk.Justification.CENTER)
        label.set_line_wrap(True)
        label.set_max_width_chars(15)
        label.set_ellipsize(3) # PANGO_ELLIPSIZE_END
        label.set_can_focus(False)
        box.pack_start(label, False, False, 0)

        self.add(box)
        self.connect("clicked", self.on_tile_clicked)

    def on_tile_clicked(self, *_):
        try:
            self.app_info.launch([], None)
        except Exception:
            cmd = self.app_info.get_commandline()
            if cmd:
                clean_cmd = " ".join([p for p in cmd.split() if not p.startswith("%")])
                subprocess.Popen(clean_cmd, shell=True)
        if AppGridOverlay.instance:
            GLib.idle_add(AppGridOverlay.instance.hide_overlay)


class AppGridOverlay(Gtk.Window):
    instance = None

    def __init__(self, start_hidden=False):
        AppGridOverlay.instance = self
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("Applications")
        self.set_name("gnome-app-grid-window")
        self.active_category = "All"

        # Layer Shell Setup for Fullscreen Overlay
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "app-grid")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)

        self.connect("destroy", lambda *_: cleanup())
        self.connect("key-press-event", self.on_key_press)
        self.connect("button-press-event", self.on_backdrop_clicked)
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, self.on_sigusr1)
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (cleanup(), False)[1])
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: (cleanup(), False)[1])

        self.apply_css()
        self.setup_ui()

        # Realize widgets into GPU/Wayland buffer caches
        self.show_all()
        if start_hidden:
            self.hide()
        else:
            self.show_overlay()

    def on_sigusr1(self):
        self.toggle_overlay()
        return True

    def toggle_overlay(self):
        if self.get_visible():
            self.hide_overlay()
        else:
            self.show_overlay()

    def hide_overlay(self, *_):
        self.hide()
        self.search_entry.set_text("")
        self.on_category_clicked(None, "All")

    def show_overlay(self, *_):
        self.show_all()
        self.present()
        self.search_entry.set_text("")
        self.on_category_clicked(None, "All")
        self.search_entry.grab_focus()

    def on_backdrop_clicked(self, widget, event):
        if event.window == self.get_window():
            self.hide_overlay()
            return True
        return False

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.hide_overlay()
            return True
        elif event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            for name, exec_name, cats, tile in self.app_items:
                if tile.is_visible():
                    tile.on_tile_clicked()
                    return True
        elif event.keyval == Gdk.KEY_Down and self.search_entry.has_focus():
            for name, exec_name, cats, tile in self.app_items:
                if tile.is_visible():
                    tile.grab_focus()
                    return True
        elif event.keyval in (Gdk.KEY_Page_Down, Gdk.KEY_KP_Page_Down):
            self.scroll_by(self.vadj.get_page_size() * 0.8)
            return True
        elif event.keyval in (Gdk.KEY_Page_Up, Gdk.KEY_KP_Page_Up):
            self.scroll_by(-self.vadj.get_page_size() * 0.8)
            return True
        elif event.keyval in (Gdk.KEY_Home, Gdk.KEY_KP_Home):
            self.scroll_to(0.0)
            return True
        elif event.keyval in (Gdk.KEY_End, Gdk.KEY_KP_End):
            max_y = max(0.0, self.vadj.get_upper() - self.vadj.get_page_size())
            self.scroll_to(max_y)
            return True
        return False

    def scroll_by(self, amount):
        max_y = max(0.0, self.vadj.get_upper() - self.vadj.get_page_size())
        self.velocity = 0.0
        self.target_y = max(0.0, min(max_y, self.target_y + amount))
        if not self.is_animating:
            self.is_animating = True
            self.last_frame_time = time.perf_counter()
            self.add_tick_callback(self.on_physics_tick)

    def scroll_to(self, pos):
        max_y = max(0.0, self.vadj.get_upper() - self.vadj.get_page_size())
        self.velocity = 0.0
        self.target_y = max(0.0, min(max_y, pos))
        if not self.is_animating:
            self.is_animating = True
            self.last_frame_time = time.perf_counter()
            self.add_tick_callback(self.on_physics_tick)

    def on_vadj_changed(self, adj):
        if not self.is_animating:
            val = adj.get_value()
            self.current_y = val
            self.target_y = val
            self.velocity = 0.0

    def setup_ui(self):
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        main_vbox.set_halign(Gtk.Align.CENTER)
        main_vbox.set_valign(Gtk.Align.FILL)
        main_vbox.set_margin_top(28)
        main_vbox.set_margin_bottom(28)
        main_vbox.set_size_request(1140, -1)
        self.add(main_vbox)

        # Top Bar: Spacer Left, Search Center, Close Right
        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        top_bar.set_size_request(1140, -1)
        main_vbox.pack_start(top_bar, False, False, 0)

        spacer_left = Gtk.Box()
        spacer_left.set_size_request(48, -1)
        top_bar.pack_start(spacer_left, False, False, 0)

        # GNOME Search Capsule
        search_center_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        search_center_box.set_halign(Gtk.Align.CENTER)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_name("gnome-search-entry")
        self.search_entry.set_placeholder_text("Type to search...")
        self.search_entry.set_size_request(460, 46)
        self.search_entry.connect("search-changed", self.on_search_changed)
        search_center_box.pack_start(self.search_entry, True, True, 0)
        top_bar.pack_start(search_center_box, True, True, 0)

        # Minimal Circular Close Button
        btn_close = Gtk.Button(label="󰅖")
        btn_close.set_name("btn-grid-close")
        btn_close.set_tooltip_text("Close (Esc)")
        btn_close.set_valign(Gtk.Align.CENTER)
        btn_close.connect("clicked", lambda *_: self.hide_overlay())
        top_bar.pack_end(btn_close, False, False, 0)

        # GNOME Category Filter Bar
        cat_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cat_box.set_halign(Gtk.Align.CENTER)
        cat_box.set_name("cat-bar")
        main_vbox.pack_start(cat_box, False, False, 0)

        categories = ["All", "Internet", "Development", "Media", "Games", "Office", "Utilities", "System"]
        self.cat_buttons = {}
        for cat in categories:
            btn = Gtk.Button(label=cat)
            btn.set_name("cat-btn")
            if cat == "All":
                btn.get_style_context().add_class("cat-btn-active")
            btn.connect("clicked", self.on_category_clicked, cat)
            cat_box.pack_start(btn, False, False, 0)
            self.cat_buttons[cat] = btn

        # Scrolled Grid Container
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_name("app-grid-scroll")
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_propagate_natural_height(True)
        self.scroll.set_overlay_scrolling(True)
        self.scroll.set_kinetic_scrolling(False)
        main_vbox.pack_start(self.scroll, True, True, 0)

        # Smooth 120Hz Scrolling Physics State
        self.vadj = self.scroll.get_vadjustment()
        self.current_y = 0.0
        self.target_y = 0.0
        self.velocity = 0.0
        self.last_scroll_time = 0.0
        self.last_frame_time = 0.0
        self.is_animating = False

        self.scroll.connect("scroll-event", self.on_smooth_scroll)
        self.vadj.connect("value-changed", self.on_vadj_changed)

        # FlowBox for Multi-column Application Grid (6 columns centered)
        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_name("app-flowbox")
        self.flowbox.set_valign(Gtk.Align.START)
        self.flowbox.set_halign(Gtk.Align.CENTER)
        self.flowbox.set_column_spacing(26)
        self.flowbox.set_row_spacing(26)
        self.flowbox.set_max_children_per_line(6)
        self.flowbox.set_min_children_per_line(6)
        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flowbox.set_homogeneous(True)
        self.scroll.add(self.flowbox)

        # Empty Search State Label
        self.empty_label = Gtk.Label(label="No Matching Applications Found")
        self.empty_label.set_name("empty-search-label")
        self.empty_label.set_no_show_all(True)
        main_vbox.pack_start(self.empty_label, False, False, 20)

        self.app_items = []
        self.load_applications()

    def on_smooth_scroll(self, widget, event):
        max_y = max(0.0, self.vadj.get_upper() - self.vadj.get_page_size())
        if max_y <= 0.0:
            return False

        dev = event.get_source_device()
        source = dev.get_source() if dev else None

        is_stop = False
        if hasattr(event, "is_stop"):
            try:
                is_stop = event.is_stop()
            except Exception:
                pass

        has_deltas, dx, dy = event.get_scroll_deltas()

        # Discriminate between Touchpad vs Mouse Wheel
        is_touchpad = (source == Gdk.InputSource.TOUCHPAD) or is_stop
        if not is_touchpad and source != Gdk.InputSource.MOUSE:
            if has_deltas and abs(dy) > 0 and abs(dy) != 1.0 and abs(dy) != 2.0 and abs(dy) != 3.0:
                is_touchpad = True

        if is_stop:
            self.last_scroll_time = 0.0
            if abs(self.velocity) > 60.0:
                if not self.is_animating:
                    self.is_animating = True
                    self.last_frame_time = time.perf_counter()
                    self.add_tick_callback(self.on_physics_tick)
            else:
                self.velocity = 0.0
            return True

        if is_touchpad:
            now = time.perf_counter()
            dt = now - self.last_scroll_time if self.last_scroll_time > 0 else 0.016
            if dt > 0.15:
                self.velocity = 0.0
            self.last_scroll_time = now

            delta_px = dy * 22.0
            if 0.001 < dt < 0.15:
                inst_v = delta_px / dt
                self.velocity = self.velocity * 0.4 + inst_v * 0.6

            self.current_y = max(0.0, min(max_y, self.current_y + delta_px))
            self.target_y = self.current_y
            self.vadj.set_value(self.current_y)
            return True

        # Mouse wheel: accumulate targets & animate smoothly at 120Hz
        self.velocity = 0.0
        step = 150.0  # Approx 1 row of application cards
        if has_deltas:
            self.target_y += dy * step
        elif event.direction == Gdk.ScrollDirection.UP:
            self.target_y -= step
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.target_y += step

        self.target_y = max(0.0, min(max_y, self.target_y))
        if not self.is_animating:
            self.is_animating = True
            self.last_frame_time = time.perf_counter()
            self.add_tick_callback(self.on_physics_tick)
        return True

    def on_physics_tick(self, widget, frame_clock):
        max_y = max(0.0, self.vadj.get_upper() - self.vadj.get_page_size())
        now = time.perf_counter()
        dt = min(0.03, max(0.001, now - self.last_frame_time))
        self.last_frame_time = now

        # 1. Kinetic glide (touchpad flick inertia)
        if abs(self.velocity) > 15.0:
            self.current_y += self.velocity * dt
            self.velocity *= 0.93  # Exponential friction decay

            if self.current_y <= 0.0:
                self.current_y = 0.0
                self.velocity = 0.0
            elif self.current_y >= max_y:
                self.current_y = max_y
                self.velocity = 0.0

            self.target_y = self.current_y
            self.vadj.set_value(self.current_y)

            if abs(self.velocity) < 15.0:
                self.velocity = 0.0
                self.is_animating = False
                return False
            return True

        # 2. Smooth Lerp to target_y (mouse wheel / keyboard)
        diff = self.target_y - self.current_y
        if abs(diff) < 0.6:
            self.current_y = self.target_y
            self.vadj.set_value(self.current_y)
            self.is_animating = False
            return False

        # 120Hz critically damped interpolation (0.22/frame reaches target in ~80-100ms)
        self.current_y += diff * 0.22
        self.vadj.set_value(self.current_y)
        return True

    def on_category_clicked(self, button, cat_name):
        self.active_category = cat_name
        self.velocity = 0.0
        self.current_y = 0.0
        self.target_y = 0.0
        self.vadj.set_value(0.0)
        self.is_animating = False
        for cat, btn in self.cat_buttons.items():
            ctx = btn.get_style_context()
            if cat == cat_name:
                ctx.add_class("cat-btn-active")
            else:
                ctx.remove_class("cat-btn-active")
        self.filter_apps()

    def on_search_changed(self, entry):
        self.velocity = 0.0
        self.current_y = 0.0
        self.target_y = 0.0
        self.vadj.set_value(0.0)
        self.is_animating = False
        self.filter_apps()

    def filter_apps(self):
        query = self.search_entry.get_text().strip().lower()
        visible_count = 0

        for name, exec_name, cats, tile in self.app_items:
            # Query match
            query_match = not query or query in name or query in exec_name

            # Category match
            if self.active_category == "All" or query:
                cat_match = True
            else:
                cat_match = False
                cats_lower = [c.lower() for c in cats]
                cat_keys = CATS_MAP.get(self.active_category, [])
                if any(k in cats_lower for k in cat_keys):
                    cat_match = True

            match = query_match and cat_match
            tile.set_visible(match)
            parent = tile.get_parent()
            if parent:
                parent.set_visible(match)
            if match:
                visible_count += 1

        if visible_count == 0:
            self.empty_label.show()
        else:
            self.empty_label.hide()

    def load_applications(self):
        apps = Gio.AppInfo.get_all()
        seen = set()
        valid = []

        for app in apps:
            if not app.should_show():
                continue
            name = app.get_display_name() or app.get_name()
            app_id = app.get_id()
            if not name or app_id in seen:
                continue
            seen.add(app_id)
            valid.append(app)

        valid.sort(key=lambda a: (a.get_display_name() or a.get_name()).lower())

        for app in valid:
            tile = AppTile(app)
            self.flowbox.add(tile)
            name = (app.get_display_name() or app.get_name() or "").lower()
            exec_name = (app.get_executable() or "").lower()
            raw_cats = app.get_categories() if hasattr(app, "get_categories") and app.get_categories() else ""
            cats = [c.strip() for c in raw_cats.split(";") if c.strip()]
            self.app_items.append((name, exec_name, cats, tile))

        self.flowbox.show_all()

    def apply_css(self):
        css_provider = Gtk.CssProvider()
        css = f"""
        @import url('{THEME_CSS_PATH}');

        #gnome-app-grid-window,
        #gnome-app-grid-window label,
        #gnome-app-grid-window button,
        #gnome-app-grid-window entry {{
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Cantarell", "Symbols Nerd Font", "JetBrains Mono", sans-serif;
            color: #ffffff;
        }}

        #gnome-app-grid-window {{
            background-color: alpha(@bg-color, 0.90);
        }}

        /* GNOME Centered Search Pill */
        #gnome-search-entry {{
            background-color: rgba(255, 255, 255, 0.12);
            border: 1px solid rgba(255, 255, 255, 0.22);
            border-radius: 23px;
            padding: 8px 22px;
            font-size: 14.5px;
            font-weight: 500;
            color: #ffffff;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }}

        #gnome-search-entry:focus {{
            border-color: rgba(255, 255, 255, 0.50);
            background-color: rgba(255, 255, 255, 0.18);
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.50);
        }}

        /* Circular Close Button */
        #btn-grid-close {{
            background-color: rgba(255, 255, 255, 0.10);
            border: 1px solid rgba(255, 255, 255, 0.20);
            border-radius: 50%;
            min-width: 38px;
            min-height: 38px;
            padding: 0;
            font-size: 15px;
            color: #ffffff;
            transition: all 0.15s ease;
        }}

        #btn-grid-close:hover {{
            background-color: rgba(235, 77, 75, 0.85);
            border-color: rgba(235, 77, 75, 1.0);
            color: #ffffff;
        }}

        /* Category Filter Pills */
        #cat-bar {{
            margin-top: 4px;
            margin-bottom: 8px;
        }}

        #cat-btn {{
            background-color: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 16px;
            padding: 5px 14px;
            font-size: 12.5px;
            font-weight: 600;
            color: rgba(255, 255, 255, 0.75);
            transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1);
        }}

        #cat-btn:hover {{
            background-color: rgba(255, 255, 255, 0.16);
            color: #ffffff;
        }}

        .cat-btn-active, #cat-btn.cat-btn-active {{
            background-color: @accent-color;
            border-color: @accent-color;
            color: #ffffff;
            box-shadow: 0 4px 14px alpha(@accent-color, 0.40);
        }}

        /* App FlowBox & Tiles */
        #app-flowbox {{
            background: transparent;
            padding: 12px;
        }}

        flowboxchild {{
            background: transparent;
            border-radius: 22px;
            padding: 0;
            margin: 0;
        }}

        #app-tile {{
            background-color: transparent;
            border: 1.5px solid transparent;
            border-radius: 22px;
            padding: 14px 10px;
            transition: background-color 0.12s ease, border-color 0.12s ease;
        }}

        #app-tile:hover, flowboxchild:selected #app-tile {{
            background-color: rgba(255, 255, 255, 0.16);
            border-color: rgba(255, 255, 255, 0.30);
        }}

        #app-tile:active {{
            background-color: rgba(255, 255, 255, 0.28);
            border-color: rgba(255, 255, 255, 0.50);
        }}

        #app-label {{
            font-size: 12.5px;
            font-weight: 600;
            color: #ffffff;
            text-shadow: 0 1px 2px rgba(0, 0, 0, 0.80);
        }}

        #empty-search-label {{
            font-size: 16px;
            font-weight: 600;
            color: rgba(255, 255, 255, 0.60);
        }}

        #app-grid-scroll scrollbar {{
            background: transparent;
        }}

        #app-grid-scroll scrollbar slider {{
            background-color: rgba(255, 255, 255, 0.28);
            border-radius: 6px;
            min-width: 6px;
        }}
        """
        try:
            css_provider.load_from_data(css.encode('utf-8'))
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        except Exception as e:
            print(f"Error loading CSS: {e}")


def main():
    handle_cli_and_ipc()
    is_daemon = "--daemon" in sys.argv
    app = AppGridOverlay(start_hidden=is_daemon)
    Gtk.main()

if __name__ == "__main__":
    main()
