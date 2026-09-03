#!/usr/bin/python3
import os
import sys
import signal
import threading
import subprocess

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GtkLayerShell, GLib, Gio, GdkPixbuf, GLibUnix

PID_FILE = "/tmp/gnome_app_grid.pid"
THEME_CSS_PATH = "/home/sreyas/.config/waybar/current-theme.css"

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


class AppTile(Gtk.Button):
    def __init__(self, app_info):
        super().__init__()
        self.app_info = app_info
        self.set_name("app-tile")
        self.set_relief(Gtk.ReliefStyle.NONE)
        self.set_size_request(124, 124)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)

        # App Icon (64px)
        gicon = app_info.get_icon()
        img = None
        if gicon:
            img = Gtk.Image.new_from_gicon(gicon, Gtk.IconSize.DIALOG)
        else:
            img = Gtk.Image.new_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)
        img.set_pixel_size(64)
        box.pack_start(img, False, False, 0)

        # App Title
        name = app_info.get_display_name() or app_info.get_name() or "App"
        label = Gtk.Label(label=name)
        label.set_name("app-label")
        label.set_justify(Gtk.Justification.CENTER)
        label.set_line_wrap(True)
        label.set_max_width_chars(14)
        label.set_ellipsize(3) # PANGO_ELLIPSIZE_END
        box.pack_start(label, False, False, 0)

        self.add(box)
        self.connect("clicked", self.on_tile_clicked)

    def on_tile_clicked(self, *_):
        try:
            self.app_info.launch([], None)
        except Exception as e:
            cmd = self.app_info.get_commandline()
            if cmd:
                # Clean cmdline (remove %u, %F, etc.)
                clean_cmd = " ".join([p for p in cmd.split() if not p.startswith("%")])
                subprocess.Popen(clean_cmd, shell=True)
        GLib.idle_add(AppGridOverlay.instance.close_animated)


class AppGridOverlay(Gtk.Window):
    instance = None

    def __init__(self):
        AppGridOverlay.instance = self
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("Applications")
        self.set_name("gnome-app-grid-window")

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
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, lambda: (self.close_animated(), False)[1])

        # Animation states
        self.anim_start = None
        self.close_start = None
        self.is_closing = False
        Gtk.Widget.set_opacity(self, 0.0)
        self.add_tick_callback(self.on_animate_in)

        self.apply_css()
        self.setup_ui()

    def on_animate_in(self, widget, frame_clock):
        now = frame_clock.get_frame_time() / 1_000_000
        if self.anim_start is None:
            self.anim_start = now
        elapsed = now - self.anim_start
        duration = 0.16 # 160ms fast entrance
        progress = min(1.0, elapsed / duration)
        ease = 1.0 - (1.0 - progress) ** 3
        Gtk.Widget.set_opacity(self, ease)

        if progress >= 1.0:
            Gtk.Widget.set_opacity(self, 1.0)
            self.search_entry.grab_focus()
            return False
        return True

    def close_animated(self, *_):
        if self.is_closing:
            return
        self.is_closing = True
        self.close_start = None
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
        duration = 0.14 # 140ms fast exit
        progress = min(1.0, elapsed / duration)
        ease = progress ** 2
        Gtk.Widget.set_opacity(self, max(0.0, 1.0 - ease))

        if progress >= 1.0:
            cleanup()
            return False
        return True

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_animated()
            return True
        elif event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            # Launch the first visible app if in search entry
            for name, exec_name, tile in self.app_items:
                if tile.is_visible():
                    tile.on_tile_clicked()
                    return True
        elif event.keyval == Gdk.KEY_Down and self.search_entry.has_focus():
            for name, exec_name, tile in self.app_items:
                if tile.is_visible():
                    tile.grab_focus()
                    return True
        return False

    def setup_ui(self):
        # Fullscreen Root Container
        root_overlay = Gtk.EventBox()
        root_overlay.set_name("root-overlay")
        root_overlay.connect("button-press-event", self.on_backdrop_clicked)
        self.add(root_overlay)

        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        main_vbox.set_halign(Gtk.Align.CENTER)
        main_vbox.set_valign(Gtk.Align.FILL)
        main_vbox.set_margin_top(48)
        main_vbox.set_margin_bottom(36)
        main_vbox.set_size_request(1060, -1)
        root_overlay.add(main_vbox)

        # GNOME Search Pill
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        search_box.set_halign(Gtk.Align.CENTER)
        main_vbox.pack_start(search_box, False, False, 0)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_name("gnome-search-entry")
        self.search_entry.set_placeholder_text("Type to search apps...")
        self.search_entry.set_size_request(440, 46)
        self.search_entry.connect("search-changed", self.on_search_changed)
        search_box.pack_start(self.search_entry, True, True, 0)

        # Scrolled Grid Container
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_name("app-grid-scroll")
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_propagate_natural_height(True)
        main_vbox.pack_start(self.scroll, True, True, 0)

        # FlowBox for Multi-column Application Grid
        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_name("app-flowbox")
        self.flowbox.set_valign(Gtk.Align.START)
        self.flowbox.set_halign(Gtk.Align.CENTER)
        self.flowbox.set_column_spacing(24)
        self.flowbox.set_row_spacing(24)
        self.flowbox.set_max_children_per_line(6)
        self.flowbox.set_min_children_per_line(4)
        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flowbox.set_homogeneous(True)
        self.scroll.add(self.flowbox)

        self.app_items = []
        self.load_applications()

    def on_backdrop_clicked(self, widget, event):
        # Clicked empty space outside tiles -> dismiss
        alloc = self.scroll.get_allocation()
        x, y = event.x, event.y
        # If click is above search or outside the grid scroll area, close
        if y < 40 or y > (alloc.y + alloc.height + 60) or x < alloc.x or x > (alloc.x + alloc.width):
            self.close_animated()
            return True
        return False

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
            self.app_items.append((name, exec_name, tile))

        self.flowbox.show_all()

    def on_search_changed(self, entry):
        query = entry.get_text().strip().lower()
        for name, exec_name, tile in self.app_items:
            match = not query or query in name or query in exec_name
            tile.set_visible(match)
            parent = tile.get_parent()
            if parent:
                parent.set_visible(match)

    def apply_css(self):
        css_provider = Gtk.CssProvider()
        css = f"""
        @import url('{THEME_CSS_PATH}');

        * {{
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Symbols Nerd Font", "JetBrains Mono", sans-serif;
            color: @fg-color;
            transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
        }}

        #gnome-app-grid-window {{
            background-color: alpha(@bg-color, 0.88);
        }}

        #root-overlay {{
            background: transparent;
        }}

        /* Search Pill */
        #gnome-search-entry {{
            background-color: alpha(@bg-color, 0.75);
            border: 1.5px solid alpha(@border-color, 0.50);
            border-radius: 24px;
            padding: 8px 20px;
            font-size: 15px;
            font-weight: 500;
            color: @fg-color;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
        }}

        #gnome-search-entry:focus {{
            border-color: @accent-color;
            background-color: alpha(@bg-color, 0.90);
            box-shadow: 0 8px 30px alpha(@accent-color, 0.25);
        }}

        /* App FlowBox & Tiles */
        #app-flowbox {{
            background: transparent;
            padding: 10px;
        }}

        flowboxchild {{
            background: transparent;
            border-radius: 18px;
            padding: 0;
            margin: 0;
        }}

        #app-tile {{
            background-color: transparent;
            border: 1.5px solid transparent;
            border-radius: 18px;
            padding: 10px;
        }}

        #app-tile:hover, flowboxchild:selected #app-tile {{
            background-color: alpha(@accent-color, 0.18);
            border-color: alpha(@accent-color, 0.40);
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.25);
        }}

        #app-tile:active {{
            background-color: alpha(@accent-color, 0.32);
            border-color: @accent-color;
        }}

        #app-label {{
            font-size: 12.5px;
            font-weight: 600;
            color: @fg-color;
            text-shadow: 0 1px 3px rgba(0, 0, 0, 0.6);
        }}

        #app-grid-scroll scrollbar {{
            background: transparent;
        }}

        #app-grid-scroll scrollbar slider {{
            background-color: alpha(@accent-color, 0.35);
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
