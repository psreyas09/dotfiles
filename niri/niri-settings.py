#!/usr/bin/env python3
import os
import sys
import glob
import json
import re
import subprocess
import threading

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf

GLib.set_prgname("niri-settings")
GLib.set_application_name("Niri Settings")

APP_TITLE = "Niri Settings"
THEME_CSS_PATH = "/home/sreyas/.config/waybar/current-theme.css"
WALLPAPER_DIR = "/home/sreyas/wall"
CONFIG_KDL_PATH = "/home/sreyas/.config/niri/config.kdl"
CURRENT_WALL_CACHE = "/home/sreyas/.cache/current_wallpaper"

def run_cmd(cmd):
    try:
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
        return res.stdout.strip()
    except Exception:
        return ""

def async_cmd(cmd):
    threading.Thread(target=lambda: subprocess.run(cmd, shell=True), daemon=True).start()

def update_niri_output(output_name="eDP-1", mode=None, scale=None, vrr=None):
    try:
        with open(CONFIG_KDL_PATH, "r") as f:
            content = f.read()

        pat = rf'output\s+\"{output_name}\"\s*\{{([^}}]*)\}}'
        match = re.search(pat, content)
        if match:
            body = match.group(1)
            if mode:
                if re.search(r'mode\s+\"[^\"]+\"', body):
                    body = re.sub(r'mode\s+\"[^\"]+\"', f'mode \"{mode}\"', body)
                else:
                    body += f'\n    mode \"{mode}\"'
            if scale is not None:
                if re.search(r'scale\s+[\d.]+', body):
                    body = re.sub(r'scale\s+[\d.]+', f'scale {scale}', body)
                else:
                    body += f'\n    scale {scale}'
            if vrr is not None:
                if vrr:
                    if 'variable-refresh-rate' not in body:
                        body += '\n    variable-refresh-rate'
                else:
                    body = re.sub(r'\s*variable-refresh-rate(\s+on|\s+off)?', '', body)
            new_content = re.sub(pat, f'output \"{output_name}\" {{{body}\n}}', content)
        else:
            new_block = f'\noutput \"{output_name}\" {{\n'
            if mode: new_block += f'    mode \"{mode}\"\n'
            if scale: new_block += f'    scale {scale}\n'
            if vrr: new_block += '    variable-refresh-rate\n'
            new_block += '}\n'
            new_content = content + new_block

        with open(CONFIG_KDL_PATH, "w") as f:
            f.write(new_content)

        dotfile_kdl = "/home/sreyas/dotfile/niri/config.kdl"
        if os.path.exists(dotfile_kdl):
            with open(dotfile_kdl, "w") as f:
                f.write(new_content)

        subprocess.run(["niri", "msg", "action", "load-config-file"])
    except Exception as e:
        print(f"Error updating niri output: {e}")


class SettingsCard(Gtk.Box):
    """Modern iOS / macOS styled card container with 14px rounded corners"""
    def __init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=0):
        super().__init__(orientation=orientation, spacing=spacing)
        self.set_name("settings-card")

    def add_row(self, widget, add_separator=True):
        if len(self.get_children()) > 0 and add_separator:
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.set_name("card-separator")
            self.pack_start(sep, False, False, 0)
        self.pack_start(widget, False, False, 0)


def create_setting_row(icon_name, title, subtitle="", control_widget=None):
    """Creates a standard settings row with icon, title, description and control widget"""
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
    row.set_name("settings-row")

    # Icon badge
    if icon_name:
        theme = Gtk.IconTheme.get_default()
        icon_box = Gtk.Box()
        icon_box.set_name("icon-badge")
        if theme.has_icon(icon_name):
            img = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DND)
        else:
            img = Gtk.Image.new_from_icon_name("preferences-system", Gtk.IconSize.DND)
        icon_box.pack_start(img, True, True, 0)
        row.pack_start(icon_box, False, False, 0)

    # Title & Subtitle
    text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    text_box.set_valign(Gtk.Align.CENTER)
    title_lbl = Gtk.Label(label=title)
    title_lbl.set_name("row-title")
    title_lbl.set_xalign(0)
    text_box.pack_start(title_lbl, False, False, 0)

    if subtitle:
        sub_lbl = Gtk.Label(label=subtitle)
        sub_lbl.set_name("row-subtitle")
        sub_lbl.set_xalign(0)
        sub_lbl.set_line_wrap(True)
        sub_lbl.set_max_width_chars(45)
        text_box.pack_start(sub_lbl, False, False, 0)

    row.pack_start(text_box, True, True, 0)

    # Right control widget
    if control_widget:
        control_widget.set_valign(Gtk.Align.CENTER)
        row.pack_end(control_widget, False, False, 0)

    return row


class NiriSettingsApp(Gtk.Window):
    def __init__(self):
        super().__init__(title=APP_TITLE)
        self.set_default_size(940, 640)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.apply_css()

        # Main Layout: HeaderBar + (Sidebar + Content Stack)
        self.setup_headerbar()

        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.add(main_box)

        # Left Navigation Sidebar
        self.sidebar_list = Gtk.ListBox()
        self.sidebar_list.set_name("sidebar-list")
        self.sidebar_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.sidebar_list.connect("row-selected", self.on_nav_selected)

        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_size_request(230, -1)
        sidebar_scroll.add(self.sidebar_list)
        main_box.pack_start(sidebar_scroll, False, False, 0)

        # Subtle vertical separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep.set_name("sidebar-divider")
        main_box.pack_start(sep, False, False, 0)

        # Right Content Pages Stack
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(150)
        main_box.pack_start(self.stack, True, True, 0)

        # Page Caching & Lazy Loading
        self.pages_built = {}
        self.page_factories = {
            "display": self.page_display,
            "appearance": self.page_appearance,
            "dock": self.page_dock,
            "sound": self.page_sound,
            "network": self.page_network,
            "keyboard": self.page_keyboard,
            "power": self.page_power,
            "shortcuts": self.page_shortcuts,
            "about": self.page_about,
        }

        # Build Sidebar Navigation
        self.build_sidebar()

        # Build ONLY the initial page so startup takes < 50ms!
        self.load_page("display")
        first_row = self.sidebar_list.get_row_at_index(0)
        if first_row:
            self.sidebar_list.select_row(first_row)

    def setup_headerbar(self):
        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.set_title(APP_TITLE)
        hb.set_subtitle("Niri Wayland Desktop")
        self.set_titlebar(hb)

        # Reload / Refresh button
        refresh_btn = Gtk.Button()
        refresh_btn.set_tooltip_text("Refresh Live Settings")
        refresh_btn.set_image(Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON))
        refresh_btn.connect("clicked", lambda *_: self.reload_all_state())
        hb.pack_end(refresh_btn)

    def add_nav_item(self, id_name, label_text, icon_name):
        row = Gtk.ListBoxRow()
        row.set_name("nav-row")
        row.page_id = id_name

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_name("nav-box")

        theme = Gtk.IconTheme.get_default()
        if theme.has_icon(icon_name):
            img = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU)
        else:
            img = Gtk.Image.new_from_icon_name("preferences-system", Gtk.IconSize.MENU)
        box.pack_start(img, False, False, 0)

        lbl = Gtk.Label(label=label_text)
        lbl.set_name("nav-label")
        lbl.set_xalign(0)
        box.pack_start(lbl, True, True, 0)

        row.add(box)
        self.sidebar_list.add(row)

    def build_sidebar(self):
        self.add_nav_item("display", "Display & Monitor", "video-display")
        self.add_nav_item("appearance", "Appearance & Themes", "preferences-desktop-theme")
        self.add_nav_item("dock", "Dock & Switcher", "user-desktop")
        self.add_nav_item("sound", "Sound & Audio", "audio-volume-high")
        self.add_nav_item("network", "Wi-Fi & Bluetooth", "network-wireless")
        self.add_nav_item("keyboard", "Keyboard & Brightness", "input-keyboard")
        self.add_nav_item("power", "Power & Screen Lock", "system-lock-screen")
        self.add_nav_item("shortcuts", "Shortcuts Reference", "preferences-desktop-keyboard-shortcuts")
        self.add_nav_item("about", "About System", "dialog-information")

    def on_nav_selected(self, listbox, row):
        if row and hasattr(row, "page_id"):
            page_id = row.page_id
            self.load_page(page_id)
            self.stack.set_visible_child_name(page_id)

    def load_page(self, page_id):
        if page_id not in self.pages_built:
            factory = self.page_factories.get(page_id)
            if factory:
                widget = factory()
                self.stack.add_named(widget, page_id)
                widget.show_all()
                self.pages_built[page_id] = widget

    def make_page_container(self, title, description=""):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        vbox.set_name("page-content")
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(24)
        vbox.set_margin_start(28)
        vbox.set_margin_end(28)
        scroll.add(vbox)

        # Section Header
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title_lbl = Gtk.Label(label=title)
        title_lbl.set_name("page-title")
        title_lbl.set_xalign(0)
        title_box.pack_start(title_lbl, False, False, 0)

        if description:
            desc_lbl = Gtk.Label(label=description)
            desc_lbl.set_name("page-description")
            desc_lbl.set_xalign(0)
            title_box.pack_start(desc_lbl, False, False, 0)

        vbox.pack_start(title_box, False, False, 0)
        return scroll, vbox

    # ==========================================
    # PAGE 1: DISPLAY & MONITOR
    # ==========================================
    def page_display(self):
        scroll, vbox = self.make_page_container("Display & Monitor", "Configure monitor refresh rate, resolution and scaling")

        # Monitor Info Card
        info_card = SettingsCard()
        vbox.pack_start(info_card, False, False, 0)

        # Fetch outputs live from Niri
        raw = run_cmd("niri msg -j outputs")
        output_data = {}
        try:
            output_data = json.loads(raw).get("eDP-1", {})
        except Exception:
            pass

        model = output_data.get("model", "AU Optronics eDP-1")
        phys = output_data.get("physical_size", [340, 190])
        diag = round(((phys[0]**2 + phys[1]**2)**0.5) / 25.4, 1)

        info_card.add_row(create_setting_row(
            "video-display",
            "Internal Display",
            f"AU Optronics • {diag}\" 16:9 • eDP-1",
            Gtk.Label(label="Primary Display")
        ))

        # Refresh Rate & Resolution Card
        mode_card = SettingsCard()
        vbox.pack_start(mode_card, False, False, 0)

        # Refresh Rate
        modes = output_data.get("modes", [])
        rates = sorted(list(set(round(m.get("refresh_rate", 120213) / 1000, 2) for m in modes)), reverse=True)
        if not rates:
            rates = [120.21]

        rate_combo = Gtk.ComboBoxText()
        for r in rates:
            rate_combo.append(str(r), f"{r} Hz (Native Timing)")
        rate_combo.set_active_id(str(rates[0]))

        def on_rate_changed(combo):
            val = combo.get_active_id()
            if val:
                update_niri_output("eDP-1", mode=f"1920x1080@{val}")

        rate_combo.connect("changed", on_rate_changed)

        mode_card.add_row(create_setting_row(
            "preferences-desktop-display",
            "Display Refresh Rate",
            f"Hardware panel timing is {rates[0]} Hz. Use VRR below for dynamic 60-120Hz power saving.",
            rate_combo
        ))

        # Display Scale
        cur_scale = str(output_data.get("logical", {}).get("scale", 1.0))
        scale_combo = Gtk.ComboBoxText()
        scale_combo.append("1.0", "100% (Native 1.0x)")
        scale_combo.append("1.25", "125% (Comfortable 1.25x)")
        scale_combo.append("1.5", "150% (High DPI 1.5x)")
        scale_combo.set_active_id(cur_scale if cur_scale in ["1.0", "1.25", "1.5"] else "1.0")

        def on_scale_changed(combo):
            val = combo.get_active_id()
            if val:
                update_niri_output("eDP-1", scale=val)

        scale_combo.connect("changed", on_scale_changed)

        mode_card.add_row(create_setting_row(
            "zoom-fit-best",
            "Desktop Scaling",
            "Scale UI elements proportionally for high resolution visibility",
            scale_combo
        ))

        # VRR / Adaptive Sync (AMD FreeSync)
        vrr_switch = Gtk.Switch()
        vrr_switch.set_active(output_data.get("vrr_enabled", False))

        def on_vrr_toggled(sw, state):
            update_niri_output("eDP-1", vrr=state)
            return False

        vrr_switch.connect("state-set", on_vrr_toggled)

        mode_card.add_row(create_setting_row(
            "applications-games",
            "Variable Refresh Rate (VRR / FreeSync)",
            "Dynamically scales refresh rate between 60 Hz (idle) and 120 Hz (motion) to save battery",
            vrr_switch
        ))

        return scroll

    # ==========================================
    # PAGE 2: APPEARANCE & THEMES
    # ==========================================
    def page_appearance(self):
        scroll, vbox = self.make_page_container("Appearance & Wallpapers", "Personalize desktop wallpapers, dynamic Wallust palette, and themes")

        # Current Wallpaper Card with Thumbnail
        wall_card = SettingsCard()
        vbox.pack_start(wall_card, False, False, 0)

        cur_wall = "/home/sreyas/wall/0anime4.jpg"
        if os.path.exists(CURRENT_WALL_CACHE):
            try:
                with open(CURRENT_WALL_CACHE, "r") as f:
                    w = f.read().strip()
                    if os.path.exists(w):
                        cur_wall = w
            except Exception:
                pass

        thumb_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        thumb_box.set_name("settings-row")

        # Load wallpaper preview
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(cur_wall, 140, 80, False)
            wall_img = Gtk.Image.new_from_pixbuf(pb)
            wall_img.set_name("wallpaper-thumb")
            thumb_box.pack_start(wall_img, False, False, 0)
        except Exception:
            pass

        info_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_vbox.set_valign(Gtk.Align.CENTER)
        wl1 = Gtk.Label(label="Active Wallpaper")
        wl1.set_name("row-title")
        wl1.set_xalign(0)
        info_vbox.pack_start(wl1, False, False, 0)

        wl2 = Gtk.Label(label=os.path.basename(cur_wall))
        wl2.set_name("row-subtitle")
        wl2.set_xalign(0)
        info_vbox.pack_start(wl2, False, False, 0)
        thumb_box.pack_start(info_vbox, True, True, 0)

        pick_btn = Gtk.Button(label="Select Wallpaper...")
        pick_btn.set_valign(Gtk.Align.CENTER)
        pick_btn.connect("clicked", lambda *_: async_cmd("/home/sreyas/.config/niri/wallpaper-picker.sh"))
        thumb_box.pack_end(pick_btn, False, False, 0)

        wall_card.pack_start(thumb_box, False, False, 0)

        # Quick Wallpaper Gallery (Thumbnails)
        vbox.pack_start(Gtk.Label(label="QUICK WALLPAPER PALETTES", xalign=0, name="section-caption"), False, False, 0)

        wall_flow = Gtk.FlowBox()
        wall_flow.set_valign(Gtk.Align.START)
        wall_flow.set_max_children_per_line(4)
        wall_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        vbox.pack_start(wall_flow, False, False, 0)

        def load_gallery_bg():
            wfiles = glob.glob(os.path.join(WALLPAPER_DIR, "*.jpg"))[:8]
            for wfile in wfiles:
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(wfile, 120, 68, False)
                    def add_item(p=wfile, pixbuf=pb):
                        b = Gtk.Button()
                        b.set_name("gallery-btn")
                        b.set_image(Gtk.Image.new_from_pixbuf(pixbuf))
                        b.connect("clicked", lambda _, path=p: async_cmd(f"bash /home/sreyas/.config/niri/wallpaper-picker.sh '{path}'"))
                        wall_flow.add(b)
                        b.show_all()
                        return False
                    GLib.idle_add(add_item)
                except Exception:
                    pass
        threading.Thread(target=load_gallery_bg, daemon=True).start()

        # Desktop Theme Presets
        vbox.pack_start(Gtk.Label(label="DESKTOP THEME PROFILES", xalign=0, name="section-caption"), False, False, 0)
        theme_card = SettingsCard()
        vbox.pack_start(theme_card, False, False, 0)

        themes = ["everforest", "catppuccin-mocha", "gruvbox-material", "nord", "rose-pine", "tokyonight"]
        for t in themes:
            t_btn = Gtk.Button(label="Apply")
            t_btn.connect("clicked", lambda _, th=t: async_cmd(f"bash /home/sreyas/.config/niri/theme-switcher.sh {th}"))
            theme_card.add_row(create_setting_row(
                "preferences-desktop-theme",
                t.replace("-", " ").title(),
                f"Full palette sync: Waybar, Kitty, Fuzzel & SwayNC",
                t_btn
            ))

        return scroll

    # ==========================================
    # PAGE 3: DOCK & APP SWITCHER
    # ==========================================
    def page_dock(self):
        scroll, vbox = self.make_page_container("macOS Dock & Switcher", "Manage the bottom application dock and Super+Tab App Switcher HUD")

        dock_card = SettingsCard()
        vbox.pack_start(dock_card, False, False, 0)

        # Dock restart / status
        restart_btn = Gtk.Button(label="Restart Dock")
        restart_btn.connect("clicked", lambda *_: async_cmd("pkill -9 -f macos-dock.py; rm -f /tmp/macos_dock.pid; sleep 0.2; niri msg action spawn -- /usr/bin/python3 /home/sreyas/.config/niri/macos-dock.py"))
        dock_card.add_row(create_setting_row(
            "user-desktop",
            "Bottom macOS Dock",
            "Floating frosted glass dock with 120Hz smooth physics and auto-hide",
            restart_btn
        ))

        # Auto-hide description
        dock_card.add_row(create_setting_row(
            "go-bottom",
            "Intelligent Auto-Hide",
            "Automatically glides down when windows are open; stays visible on empty desktop",
            Gtk.Label(label="Active")
        ))

        # Overview reveal
        dock_card.add_row(create_setting_row(
            "view-grid",
            "Overview Integration",
            "Smoothly slides up and stays visible whenever Overview (Mod+D) is open",
            Gtk.Label(label="Enabled")
        ))

        # Switcher HUD
        vbox.pack_start(Gtk.Label(label="APP SWITCHER HUD", xalign=0, name="section-caption"), False, False, 0)
        hud_card = SettingsCard()
        vbox.pack_start(hud_card, False, False, 0)

        hud_card.add_row(create_setting_row(
            "preferences-system-windows",
            "Super+Tab / Alt+Tab Switcher",
            "macOS-authentic floating pill with 64px icons, squircle selection plate, and instant switch on key release",
            Gtk.Label(label="Active")
        ))

        hud_card.add_row(create_setting_row(
            "input-keyboard",
            "Reverse Cycle Shortcut",
            "Hold Super and tap ` (grave/tilde) or Shift+Tab to cycle backward",
            Gtk.Label(label="Mod+`")
        ))

        hud_card.add_row(create_setting_row(
            "window-close",
            "Quick App Quit",
            "Press 'Q' while an app is highlighted in the switcher to close it",
            Gtk.Label(label="Q")
        ))

        return scroll

    # ==========================================
    # PAGE 4: SOUND & AUDIO
    # ==========================================
    def page_sound(self):
        scroll, vbox = self.make_page_container("Sound & Audio", "Manage audio outputs, master volume levels, and microphone inputs")

        audio_card = SettingsCard()
        vbox.pack_start(audio_card, False, False, 0)

        # Current volume via wpctl
        cur_vol = 70
        try:
            out = run_cmd("wpctl get-volume @DEFAULT_AUDIO_SINK@")
            if "Volume:" in out:
                cur_vol = int(float(out.split()[1]) * 100)
        except Exception:
            pass

        vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        vol_scale.set_value(cur_vol)
        vol_scale.set_size_request(200, -1)
        vol_scale.connect("value-changed", lambda s: async_cmd(f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {s.get_value()/100:.2f}"))

        audio_card.add_row(create_setting_row(
            "audio-volume-high",
            "Output Volume",
            "Adjust system master playback volume",
            vol_scale
        ))

        # Test audio button
        test_btn = Gtk.Button(label="Play Test Sound")
        test_btn.connect("clicked", lambda *_: async_cmd("paplay /usr/share/sounds/freedesktop/stereo/audio-channel-front-center.oga 2>/dev/null || wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.7"))
        audio_card.add_row(create_setting_row(
            "audio-speakers",
            "Audio Output Device",
            "Built-in Analog Stereo / PipeWire Audio Engine",
            test_btn
        ))

        # Microphone card
        mic_card = SettingsCard()
        vbox.pack_start(mic_card, False, False, 0)

        mic_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        mic_scale.set_value(80)
        mic_scale.set_size_request(200, -1)
        mic_scale.connect("value-changed", lambda s: async_cmd(f"wpctl set-volume @DEFAULT_AUDIO_SOURCE@ {s.get_value()/100:.2f}"))

        mic_card.add_row(create_setting_row(
            "audio-input-microphone",
            "Input Volume (Microphone)",
            "Adjust microphone sensitivity and input gain",
            mic_scale
        ))

        # Audio Sink Switcher Shortcut
        sink_btn = Gtk.Button(label="Switch Audio Sink...")
        sink_btn.connect("clicked", lambda *_: async_cmd("bash ~/.config/waybar/audio-sink-switcher.sh"))
        mic_card.add_row(create_setting_row(
            "audio-card",
            "Audio Sink Switcher",
            "Toggle between built-in speakers, headphones, and HDMI audio",
            sink_btn
        ))

        return scroll

    # ==========================================
    # PAGE 5: NETWORK & BLUETOOTH
    # ==========================================
    def page_network(self):
        scroll, vbox = self.make_page_container("Wi-Fi & Bluetooth", "Control network interfaces, wireless connectivity and Bluetooth accessories")

        net_card = SettingsCard()
        vbox.pack_start(net_card, False, False, 0)

        # Wi-Fi Radio
        wifi_state = run_cmd("nmcli -t -f WIFI g") == "enabled"
        wifi_switch = Gtk.Switch()
        wifi_switch.set_active(wifi_state)
        wifi_switch.connect("state-set", lambda _, state: async_cmd(f"nmcli radio wifi {'on' if state else 'off'}"))

        net_card.add_row(create_setting_row(
            "network-wireless",
            "Wi-Fi Wireless Radio",
            "Enable or disable wireless network hardware",
            wifi_switch
        ))

        # Connected SSID
        ssid = run_cmd("nmcli -t -f ACTIVE,SSID dev wifi | grep '^yes:' | cut -d: -f2") or "Disconnected"
        wifi_btn = Gtk.Button(label="Open Wi-Fi Menu...")
        wifi_btn.connect("clicked", lambda *_: async_cmd("/usr/bin/python3 ~/.config/waybar/scripts/wifi-popup.py"))

        net_card.add_row(create_setting_row(
            "network-wireless-signal-excellent",
            f"Network: {ssid}",
            "Connected network details and nearby access points",
            wifi_btn
        ))

        # Bluetooth Card
        vbox.pack_start(Gtk.Label(label="BLUETOOTH ACCESSORIES", xalign=0, name="section-caption"), False, False, 0)
        bt_card = SettingsCard()
        vbox.pack_start(bt_card, False, False, 0)

        bt_state = "Powered: yes" in run_cmd("bluetoothctl show")
        bt_switch = Gtk.Switch()
        bt_switch.set_active(bt_state)
        bt_switch.connect("state-set", lambda _, state: async_cmd(f"bluetoothctl power {'on' if state else 'off'}"))

        bt_card.add_row(create_setting_row(
            "bluetooth",
            "Bluetooth Controller",
            "Enable or disable Bluetooth device communication",
            bt_switch
        ))

        bt_btn = Gtk.Button(label="Bluetooth Settings...")
        bt_btn.connect("clicked", lambda *_: async_cmd("/usr/bin/python3 ~/.config/waybar/scripts/bluetooth-popup.py"))

        bt_card.add_row(create_setting_row(
            "preferences-system-bluetooth",
            "Paired Devices & Discovery",
            "View battery levels, connect devices, and scan for accessories",
            bt_btn
        ))

        return scroll

    # ==========================================
    # PAGE 6: KEYBOARD & BRIGHTNESS
    # ==========================================
    def page_keyboard(self):
        scroll, vbox = self.make_page_container("Keyboard & Brightness", "Configure screen illumination, keyboard backlighting, and input preferences")

        bright_card = SettingsCard()
        vbox.pack_start(bright_card, False, False, 0)

        # Screen Brightness
        cur_b = 50
        try:
            curr = float(run_cmd("brightnessctl --device='amdgpu_bl1' get"))
            maxx = float(run_cmd("brightnessctl --device='amdgpu_bl1' max"))
            cur_b = int((curr / maxx) * 100)
        except Exception:
            pass

        b_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 1)
        b_scale.set_value(cur_b)
        b_scale.set_size_request(200, -1)
        b_scale.connect("value-changed", lambda s: async_cmd(f"brightnessctl --device='amdgpu_bl1' set {int(s.get_value())}%"))

        bright_card.add_row(create_setting_row(
            "display-brightness",
            "Screen Brightness",
            "Adjust internal laptop display backlight intensity",
            b_scale
        ))

        # Keyboard Backlight
        kbd_on = run_cmd("brightnessctl --device='platform::kbd_backlight' get") == "1"
        kbd_switch = Gtk.Switch()
        kbd_switch.set_active(kbd_on)
        kbd_switch.connect("state-set", lambda _, state: async_cmd(f"brightnessctl --device='platform::kbd_backlight' set {'1' if state else '0'}"))

        bright_card.add_row(create_setting_row(
            "input-keyboard",
            "Keyboard Illumination",
            "Toggle laptop keyboard backlight key illumination",
            kbd_switch
        ))

        # Keyboard repeat info
        info_card = SettingsCard()
        vbox.pack_start(info_card, False, False, 0)

        info_card.add_row(create_setting_row(
            "preferences-desktop-keyboard",
            "Key Repeat & Layout",
            "Layout: English (US) • Repeat Delay: 600ms • Rate: 25 keys/sec",
            Gtk.Label(label="Configured in Niri")
        ))

        return scroll

    # ==========================================
    # PAGE 7: POWER & SCREEN LOCK
    # ==========================================
    def page_power(self):
        scroll, vbox = self.make_page_container("Power & Screen Lock", "Battery conservation mode, automatic screen locking, and system shutdown")

        bat_card = SettingsCard()
        vbox.pack_start(bat_card, False, False, 0)

        bat_info = run_cmd("upower -i /org/freedesktop/UPower/devices/battery_BAT0 | grep -E '(state|percentage)'")
        perc = "56%"
        state = "Plugged in (Conservation Mode)"
        for line in bat_info.splitlines():
            if "percentage:" in line:
                perc = line.split()[-1]
            if "state:" in line:
                state = line.split()[-1].replace("-", " ").title()

        bat_card.add_row(create_setting_row(
            "battery-good",
            f"Battery Level: {perc}",
            f"Status: {state} • Health Optimized",
            Gtk.Label(label=perc)
        ))

        # Auto-lock toggle
        lock_card = SettingsCard()
        vbox.pack_start(lock_card, False, False, 0)

        auto_lock_switch = Gtk.Switch()
        auto_lock_switch.set_active(True)
        auto_lock_switch.connect("state-set", lambda _, state: async_cmd("bash ~/.config/niri/toggle-autolock.sh"))

        lock_card.add_row(create_setting_row(
            "system-lock-screen",
            "Automatic Screen Lock (Swaylock)",
            "Automatically lock session with blurred screenshot after 5 minutes of inactivity",
            auto_lock_switch
        ))

        # Power Action Buttons
        vbox.pack_start(Gtk.Label(label="SYSTEM ACTIONS", xalign=0, name="section-caption"), False, False, 0)
        action_card = SettingsCard()
        vbox.pack_start(action_card, False, False, 0)

        lock_btn = Gtk.Button(label="Lock Screen Now")
        lock_btn.connect("clicked", lambda *_: async_cmd("swaylock"))
        action_card.add_row(create_setting_row("system-lock-screen", "Lock Session", "Instantly lock current display session (Mod+L)", lock_btn))

        menu_btn = Gtk.Button(label="Open Power Matrix...")
        menu_btn.connect("clicked", lambda *_: async_cmd("wlogout"))
        action_card.add_row(create_setting_row("system-shutdown", "Power Menu (Wlogout)", "Suspend, Hibernate, Reboot or Shut down machine (Mod+Shift+E)", menu_btn))

        return scroll

    # ==========================================
    # PAGE 8: SHORTCUTS REFERENCE
    # ==========================================
    def page_shortcuts(self):
        scroll, vbox = self.make_page_container("Shortcuts Reference", "Master cheat sheet of all Niri compositor and desktop shortcuts")

        search_entry = Gtk.SearchEntry()
        search_entry.set_placeholder_text("Search keybindings (e.g. terminal, lock, overview)...")
        vbox.pack_start(search_entry, False, False, 0)

        shortcuts_card = SettingsCard()
        vbox.pack_start(shortcuts_card, False, False, 0)

        shortcuts = [
            ("Mod + Tab", "macOS App Switcher HUD (hold Mod, tap Tab to cycle forward)"),
            ("Mod + ` (tilde)", "Cycle backward through macOS App Switcher"),
            ("Mod + Return", "Open Terminal (Kitty)"),
            ("Mod + Space", "Open Application Launcher (Fuzzel)"),
            ("Mod + D", "Toggle Desktop Overview (reveals macOS dock)"),
            ("Mod + , (comma)", "Open Niri Settings App"),
            ("Mod + W", "Open Dynamic Wallpaper Picker"),
            ("Mod + Shift + T", "Open Desktop Theme Preset Switcher"),
            ("Mod + Shift + N", "Open SwayNC Notification Center"),
            ("Mod + Shift + E", "Open Wlogout Glass Power Menu"),
            ("Mod + L", "Lock Screen Immediately (Swaylock)"),
            ("Mod + Shift + L", "Toggle Automatic Screen Lock On / Off"),
            ("Print", "Interactive Area Screenshot Tool"),
            ("Mod + Q", "Close Focused Window"),
            ("Mod + F", "Maximize Focused Column"),
            ("Mod + R", "Cycle Column Widths (33% / 50% / 67%)"),
            ("Mod + V", "Toggle Window Floating"),
            ("Mod + Shift + V", "Switch Focus Between Floating & Tiling Windows"),
            ("Mod + ← / →", "Focus Column Left / Right"),
            ("Mod + ↑ / ↓", "Focus Workspace Up / Down"),
            ("Mod + 1–9", "Switch Directly to Workspace 1–9"),
            ("Mod + Shift + 1–9", "Move Focused Window to Workspace 1–9"),
        ]

        rows = []
        for keys, desc in shortcuts:
            badge = Gtk.Label(label=keys)
            badge.set_name("key-badge")
            row = create_setting_row("input-keyboard", desc, "", badge)
            shortcuts_card.add_row(row)
            rows.append((keys.lower(), desc.lower(), row))

        def on_search(entry):
            query = entry.get_text().lower().strip()
            for k, d, r in rows:
                r.set_visible(query in k or query in d if query else True)

        search_entry.connect("search-changed", on_search)
        return scroll

    # ==========================================
    # PAGE 9: ABOUT SYSTEM
    # ==========================================
    def page_about(self):
        scroll, vbox = self.make_page_container("About System", "Hardware, kernel and compositor environment details")

        about_card = SettingsCard()
        vbox.pack_start(about_card, False, False, 0)

        # Dynamic OS Detection from /etc/os-release
        os_pretty = "Fedora Linux"
        os_ver = ""
        if os.path.exists("/etc/os-release"):
            try:
                with open("/etc/os-release", "r") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("PRETTY_NAME="):
                            os_pretty = line.split("=", 1)[1].strip('"')
                        elif line.startswith("VERSION="):
                            os_ver = line.split("=", 1)[1].strip('"')
            except Exception:
                pass

        kernel = run_cmd("uname -r")
        cpu = run_cmd("lscpu | grep 'Model name' | cut -d: -f2").strip() or "AMD Ryzen Processor"
        mem = run_cmd("free -h | awk '/^Mem:/ {print $3 \" / \" $2}'")
        niri_ver = run_cmd("niri --version") or "niri"
        gpus = run_cmd("lspci | grep -i -E '(vga|3d)' | cut -d: -f3")
        gpu_lines = [g.strip() for g in gpus.splitlines() if g.strip()]
        gpu_desc = " • ".join(gpu_lines) if gpu_lines else "AMD Radeon Vega / NVIDIA GeForce"

        badge_ver = os_ver if os_ver else os_pretty
        about_card.add_row(create_setting_row("fedora-logo-icon", "Operating System", os_pretty, Gtk.Label(label=badge_ver)))
        about_card.add_row(create_setting_row("preferences-desktop-display", "Window Compositor", f"{niri_ver} (Scrollable Tiling)", Gtk.Label(label="Wayland")))
        about_card.add_row(create_setting_row("cpu", "Processor (CPU)", cpu, Gtk.Label(label="AMD")))
        about_card.add_row(create_setting_row("video-display", "Graphics (GPU)", gpu_desc, Gtk.Label(label="Hybrid")))
        about_card.add_row(create_setting_row("drive-harddisk", "Memory (RAM)", f"Used / Total: {mem}", Gtk.Label(label=mem.split('/')[1].strip() if '/' in mem else "")))
        about_card.add_row(create_setting_row("applications-system", "Linux Kernel", f"Kernel release {kernel}", Gtk.Label(label=kernel)))

        # Dotfiles GitHub Link
        link_card = SettingsCard()
        vbox.pack_start(link_card, False, False, 0)

        git_btn = Gtk.Button(label="Open GitHub Repo")
        git_btn.connect("clicked", lambda *_: async_cmd("xdg-open 'https://github.com/psreyas09/dotfiles'"))
        link_card.add_row(create_setting_row("software-update-available", "Personal Dotfiles Repository", "psreyas09/dotfiles • Managed & Synced", git_btn))

        return scroll

    def reload_all_state(self):
        # Refresh active pages
        self.stack.remove(self.stack.get_child_by_name("display"))
        self.stack.add_named(self.page_display(), "display")
        self.stack.set_visible_child_name("display")

    def apply_css(self):
        css_provider = Gtk.CssProvider()
        css = f"""
        @import url('{THEME_CSS_PATH}');

        * {{
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Symbols Nerd Font", "JetBrains Mono", sans-serif;
            color: @fg-color;
        }}

        window {{
            background-color: alpha(@bg-color, 0.96);
        }}

        headerbar {{
            background-color: alpha(@bg-color, 0.98);
            border-bottom: 1px solid alpha(@border-color, 0.3);
            padding: 6px 12px;
        }}

        headerbar .title {{
            font-weight: 700;
            font-size: 15px;
        }}

        headerbar .subtitle {{
            font-size: 11px;
            color: rgba(255, 255, 255, 0.55);
        }}

        /* Sidebar Navigation */
        #sidebar-list {{
            background-color: alpha(@bg-color, 0.92);
            padding: 8px 6px;
        }}

        #nav-row {{
            border-radius: 10px;
            padding: 8px 12px;
            margin: 2px 4px;
            transition: all 0.12s ease;
        }}

        #nav-row:hover {{
            background-color: rgba(255, 255, 255, 0.08);
        }}

        #nav-row:selected {{
            background-color: alpha(@accent-purple, 0.85);
            color: #FFFFFF;
        }}

        #nav-row:selected * {{
            color: #FFFFFF;
            font-weight: 600;
        }}

        #sidebar-divider {{
            background-color: alpha(@border-color, 0.2);
            min-width: 1px;
        }}

        /* Main Content Pages */
        #page-content {{
            background: transparent;
        }}

        #page-title {{
            font-size: 22px;
            font-weight: 800;
            letter-spacing: -0.3px;
        }}

        #page-description {{
            font-size: 12.5px;
            color: rgba(255, 255, 255, 0.55);
        }}

        #section-caption {{
            font-size: 11px;
            font-weight: 700;
            color: alpha(@accent-purple, 0.9);
            letter-spacing: 0.8px;
            margin-top: 10px;
            margin-bottom: 2px;
        }}

        /* Grouped Settings Cards (iOS/macOS style) */
        #settings-card {{
            background-color: alpha(@bg-color, 0.80);
            border: 1px solid alpha(@border-color, 0.35);
            border-radius: 14px;
            padding: 2px 0px;
            margin-bottom: 8px;
        }}

        #settings-row {{
            padding: 10px 16px;
        }}

        #card-separator {{
            background-color: alpha(@border-color, 0.15);
            min-height: 1px;
            margin: 0 16px;
        }}

        #icon-badge {{
            background-color: alpha(@accent-purple, 0.18);
            border-radius: 10px;
            min-width: 36px;
            min-height: 36px;
            padding: 4px;
        }}

        #row-title {{
            font-size: 13.5px;
            font-weight: 600;
        }}

        #row-subtitle {{
            font-size: 11.5px;
            color: rgba(255, 255, 255, 0.52);
        }}

        /* Keybinding Badges */
        #key-badge {{
            background-color: rgba(255, 255, 255, 0.12);
            border: 1px solid rgba(255, 255, 255, 0.25);
            border-radius: 6px;
            padding: 4px 10px;
            font-family: "JetBrains Mono", monospace;
            font-weight: bold;
            font-size: 11px;
            color: @accent-purple;
        }}

        /* Wallpaper Thumbnails */
        #wallpaper-thumb {{
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.3);
        }}

        #gallery-btn {{
            background: transparent;
            border: 2px solid transparent;
            border-radius: 10px;
            padding: 2px;
            margin: 4px;
        }}

        #gallery-btn:hover {{
            border-color: @accent-purple;
        }}

        /* Buttons & Controls */
        button {{
            border-radius: 8px;
            padding: 6px 14px;
            font-weight: 600;
            font-size: 12.5px;
            transition: all 0.12s ease;
        }}

        button:hover {{
            background-color: alpha(@accent-purple, 0.25);
            border-color: @accent-purple;
        }}

        switch:checked {{
            background-color: @accent-purple;
        }}

        scale highlight {{
            background-color: @accent-purple;
            border-radius: 4px;
        }}
        """
        css_provider.load_from_data(css.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def main():
    app = NiriSettingsApp()
    app.connect("destroy", Gtk.main_quit)
    app.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
