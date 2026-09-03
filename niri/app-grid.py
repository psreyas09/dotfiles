#!/usr/bin/python3
import os
import sys
import time
import signal
import subprocess

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GtkLayerShell, GLib, Gio, GdkPixbuf, GLibUnix

PID_FILE = "/tmp/gnome_app_grid.pid"
THEME_CSS_PATH = "/home/sreyas/.config/waybar/current-theme.css"
BLURRED_WALL_PATH = "/home/sreyas/.cache/current_wallpaper_blurred.png"

def toggle_or_exit():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            os.kill(pid, signal.SIGUSR1)
            sys.exit(0)
        except (OSError, ValueError):
            try:
                os.remove(PID_FILE)
            except OSError:
                pass

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

def cleanup():
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except OSError:
        pass
    Gtk.main_quit()


def get_app_image(app_info, size=72):
    theme = Gtk.IconTheme.get_default()
    gicon = app_info.get_icon()
    if gicon:
        try:
            if hasattr(gicon, "get_names"):
                for n in gicon.get_names():
                    if theme.has_icon(n):
                        img = Gtk.Image.new_from_icon_name(n, Gtk.IconSize.DIALOG)
                        img.set_pixel_size(size)
                        return img
            elif hasattr(gicon, "to_string"):
                s = gicon.to_string()
                if theme.has_icon(s):
                    img = Gtk.Image.new_from_icon_name(s, Gtk.IconSize.DIALOG)
                    img.set_pixel_size(size)
                    return img
                elif os.path.exists(s):
                    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(s, size, size, True)
                    return Gtk.Image.new_from_pixbuf(pb)
        except Exception:
            pass
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

        # 72px Crisp Vector Icon
        img = get_app_image(app_info, 72)
        box.pack_start(img, False, False, 0)

        # App Label
        name = app_info.get_display_name() or app_info.get_name() or "App"
        label = Gtk.Label(label=name)
        label.set_name("app-label")
        label.set_justify(Gtk.Justification.CENTER)
        label.set_line_wrap(True)
        label.set_max_width_chars(15)
        label.set_ellipsize(3) # PANGO_ELLIPSIZE_END
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
        GLib.idle_add(AppGridOverlay.instance.close_window)


class AppGridOverlay(Gtk.Window):
    instance = None

    def __init__(self):
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
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, lambda: (self.close_window(), False)[1])

        self.apply_css()
        self.setup_ui()

    def close_window(self, *_):
        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        except OSError:
            pass
        cleanup()

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_window()
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
        return False

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
        btn_close.connect("clicked", lambda *_: self.close_window())
        top_bar.pack_end(btn_close, False, False, 0)

        # GNOME Category Filter Bar
        cat_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cat_box.set_halign(Gtk.Align.CENTER)
        cat_box.set_name("cat-bar")
        main_vbox.pack_start(cat_box, False, False, 0)

        categories = ["All", "Internet", "Development", "Media", "Games", "Utilities", "System"]
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

        # Smooth 120Hz Scrolling State
        self.vadj = self.scroll.get_vadjustment()
        self.target_y = 0.0
        self.current_y = 0.0
        self.is_animating_scroll = False
        self.scroll.connect("scroll-event", self.on_smooth_scroll)

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
        has_deltas, dx, dy = event.get_scroll_deltas()
        max_y = max(0.0, self.vadj.get_upper() - self.vadj.get_page_size())

        if has_deltas:
            # Smooth high-precision touchpad swipe
            self.target_y += dy * 60.0
        else:
            # Discrete wheel scroll
            if event.direction == Gdk.ScrollDirection.UP:
                self.target_y -= 110.0
            elif event.direction == Gdk.ScrollDirection.DOWN:
                self.target_y += 110.0

        self.target_y = max(0.0, min(max_y, self.target_y))

        if not self.is_animating_scroll:
            self.is_animating_scroll = True
            self.add_tick_callback(self.on_scroll_physics_tick)
        return True

    def on_scroll_physics_tick(self, widget, frame_clock):
        diff = self.target_y - self.current_y
        if abs(diff) < 0.5:
            self.current_y = self.target_y
            self.vadj.set_value(self.current_y)
            self.is_animating_scroll = False
            return False

        # 120Hz smooth exponential damping lerp
        self.current_y += diff * 0.22
        self.vadj.set_value(self.current_y)
        return True

    def on_category_clicked(self, button, cat_name):
        self.active_category = cat_name
        self.target_y = 0.0
        self.current_y = 0.0
        self.vadj.set_value(0.0)
        for cat, btn in self.cat_buttons.items():
            ctx = btn.get_style_context()
            if cat == cat_name:
                ctx.add_class("cat-btn-active")
            else:
                ctx.remove_class("cat-btn-active")
        self.filter_apps()

    def on_search_changed(self, entry):
        self.target_y = 0.0
        self.current_y = 0.0
        self.vadj.set_value(0.0)
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
                if self.active_category == "Internet" and any(k in cats_lower for k in ["network", "webbrowser", "email", "chat", "feed"]):
                    cat_match = True
                elif self.active_category == "Development" and any(k in cats_lower for k in ["development", "ide", "debugger", "texteditor"]):
                    cat_match = True
                elif self.active_category == "Media" and any(k in cats_lower for k in ["audiovideo", "audio", "video", "graphics", "recorder", "music"]):
                    cat_match = True
                elif self.active_category == "Games" and any(k in cats_lower for k in ["game", "emulator"]):
                    cat_match = True
                elif self.active_category == "Utilities" and any(k in cats_lower for k in ["utility", "accessories", "calculator", "archiving"]):
                    cat_match = True
                elif self.active_category == "System" and any(k in cats_lower for k in ["system", "settings", "hardware", "terminal", "filemanager"]):
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
        bg_rule = ""
        if os.path.exists(BLURRED_WALL_PATH):
            bg_rule = f"""
            background-image: linear-gradient(rgba(10, 12, 16, 0.72), rgba(10, 12, 16, 0.82)), url('{BLURRED_WALL_PATH}');
            background-size: cover;
            background-position: center;
            """
        else:
            bg_rule = "background-color: rgba(12, 14, 20, 0.94);"

        css = f"""
        @import url('{THEME_CSS_PATH}');

        * {{
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Cantarell", "Symbols Nerd Font", "JetBrains Mono", sans-serif;
            color: #ffffff;
        }}

        #gnome-app-grid-window {{
            {bg_rule}
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
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.45);
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }}

        #gnome-search-entry:focus {{
            border-color: rgba(255, 255, 255, 0.50);
            background-color: rgba(255, 255, 255, 0.18);
            box-shadow: 0 10px 36px rgba(0, 0, 0, 0.60);
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
            text-shadow: 0 2px 4px rgba(0, 0, 0, 0.90);
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
    toggle_or_exit()
    app = AppGridOverlay()
    app.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
