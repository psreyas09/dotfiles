#!/usr/bin/env python3
import os
import sys
import time
import json
import signal
import subprocess
import threading

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GtkLayerShell, GLib

PID_FILE = "/tmp/waybar_bluetooth_popup.pid"
CACHE_FILE = "/tmp/waybar_bluetooth_cache.json"

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

def cleanup(*_):
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except OSError:
        pass
    Gtk.main_quit()

# --- Bluetooth CLI Helpers ---

def run_bt(args, timeout=6):
    try:
        res = subprocess.run(
            ["bluetoothctl"] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return 1, "", str(e)

def get_bt_power():
    code, out, _ = run_bt(["show"], timeout=2)
    return "Powered: yes" in out

def set_bt_power(enabled):
    action = "on" if enabled else "off"
    run_bt(["power", action], timeout=3)

def get_adapter_name():
    code, out, _ = run_bt(["show"], timeout=2)
    for line in out.splitlines():
        if line.strip().startswith("Alias:"):
            return line.split(":", 1)[1].strip()
    return "Adapter"

def get_connected_macs():
    code, out, _ = run_bt(["devices", "Connected"], timeout=2)
    connected = set()
    for line in out.splitlines():
        if line.startswith("Device "):
            parts = line.split(" ", 2)
            if len(parts) >= 2:
                connected.add(parts[1].strip())
    return connected

def get_device_info(mac):
    code, out, _ = run_bt(["info", mac], timeout=2)
    icon_type = "generic"
    battery = None
    connected = False
    name = mac

    for line in out.splitlines():
        line_s = line.strip()
        if line_s.startswith("Name:"):
            name = line_s.split(":", 1)[1].strip()
        elif line_s.startswith("Icon:"):
            icon_type = line_s.split(":", 1)[1].strip()
        elif line_s.startswith("Connected:"):
            connected = line_s.split(":", 1)[1].strip().lower() == "yes"
        elif "Battery Percentage:" in line_s:
            try:
                # e.g. "Battery Percentage: 0x50 (80)" or "80%"
                parts = line_s.split(":")
                val_str = parts[1].strip()
                if "(" in val_str and ")" in val_str:
                    battery = int(val_str.split("(")[1].split(")")[0])
                else:
                    battery = int(val_str.replace("%", "").strip())
            except Exception:
                battery = None

    return {
        "mac": mac,
        "name": name,
        "icon_type": icon_type,
        "connected": connected,
        "battery": battery
    }

def get_paired_devices():
    code, out, _ = run_bt(["devices", "Paired"], timeout=3)
    devices = []
    connected_macs = get_connected_macs()

    for line in out.splitlines():
        if line.startswith("Device "):
            parts = line.split(" ", 2)
            if len(parts) >= 2:
                mac = parts[1].strip()
                name = parts[2].strip() if len(parts) > 2 else mac
                info = get_device_info(mac)
                is_conn = mac in connected_macs or info["connected"]
                devices.append({
                    "mac": mac,
                    "name": info["name"] or name,
                    "icon_type": info["icon_type"],
                    "connected": is_conn,
                    "battery": info["battery"]
                })

    # Sort connected first, then alphabetically
    devices.sort(key=lambda d: (not d["connected"], d["name"].lower()))
    return devices

def get_device_glyph(icon_type):
    it = icon_type.lower()
    if "headset" in it or "headphones" in it:
        return "󰋋"
    elif "mouse" in it:
        return "󰍽"
    elif "keyboard" in it:
        return "󰌌"
    elif "phone" in it:
        return "󰄜"
    elif "speaker" in it or "audio" in it:
        return "󰓃"
    elif "gamepad" in it or "joystick" in it:
        return "󰊴"
    else:
        return "󰂯"

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return None

def save_cache(power_on, adapter_name, paired_devices):
    try:
        data = {
            "power_on": power_on,
            "adapter_name": adapter_name,
            "paired_devices": paired_devices,
            "timestamp": time.time()
        }
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


class BluetoothPopup(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("Bluetooth Quick Settings")
        self.set_default_size(360, 440)
        self.set_resizable(False)

        # Layer Shell Setup
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)

        # Position right under bluetooth module (margin right ~210px)
        self.target_margin_top = 8
        self.start_margin_top = -12
        self.target_margin_right = 210

        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, self.start_margin_top)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, self.target_margin_right)
        Gtk.Widget.set_opacity(self, 0.0)

        self.connect("destroy", cleanup)
        self.connect("key-press-event", self.on_key_press)

        # Animation states
        self.anim_start = None
        self.close_start = None
        self.is_closing = False
        self.add_tick_callback(self.on_animate_in)

        # State tracking
        self.is_scanning = False
        self.is_connecting = False
        self.adapter_name = "Bluetooth"

        # UI Build
        self.setup_ui()
        self.apply_css()

        # Load instant cache so opening animation is already populated
        cache = load_cache()
        if cache:
            self.update_ui_state(
                cache.get("power_on", True),
                cache.get("adapter_name", "Bluetooth"),
                cache.get("paired_devices", [])
            )

    # --- Smooth Animations (60Hz / 120Hz native) ---
    def on_animate_in(self, widget, frame_clock):
        now = frame_clock.get_frame_time() / 1_000_000
        if self.anim_start is None:
            self.anim_start = now
        elapsed = now - self.anim_start
        duration = 0.20 # 200ms
        progress = min(1.0, elapsed / duration)
        
        # Smooth cubic ease-out
        ease = 1.0 - (1.0 - progress) ** 3

        # Fade in
        Gtk.Widget.set_opacity(self, min(1.0, ease * 1.1))

        # Slide in from top
        curr_margin = int(self.start_margin_top + (self.target_margin_top - self.start_margin_top) * ease)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, curr_margin)

        if progress >= 1.0:
            Gtk.Widget.set_opacity(self, 1.0)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, self.target_margin_top)
            # Trigger background refresh AFTER entrance animation completes
            GLib.timeout_add(30, lambda: self.trigger_refresh(scan=False))
            return False
        return True

    def close_animated(self, *_):
        if self.is_closing:
            return
        self.is_closing = True
        self.close_start = None
        # Clean up PID file right away so rapid subsequent clicks open cleanly
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
        duration = 0.16 # 160ms
        progress = min(1.0, elapsed / duration)
        
        # Cubic ease-in
        ease = progress ** 2.5

        # Fade out
        Gtk.Widget.set_opacity(self, max(0.0, 1.0 - ease))

        # Slide out toward top
        curr_margin = int(self.target_margin_top - 18 * ease)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, curr_margin)

        if progress >= 1.0:
            cleanup()
            return False
        return True

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_animated()
            return True
        return False

    # --- UI Setup ---
    def setup_ui(self):
        # Outer Card Container
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.card.set_name("bt-card")
        self.add(self.card)

        # 1. Header: Icon + Title + Rescan + Close
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_box.set_name("header-box")
        self.card.pack_start(header_box, False, False, 0)

        header_icon = Gtk.Label(label="")
        header_icon.set_name("header-icon")
        header_box.pack_start(header_icon, False, False, 0)

        header_title = Gtk.Label(label="Bluetooth Devices")
        header_title.set_name("header-title")
        header_title.set_xalign(0)
        header_box.pack_start(header_title, True, True, 0)

        self.btn_rescan = Gtk.Button(label="󰑐")
        self.btn_rescan.set_name("btn-icon")
        self.btn_rescan.set_tooltip_text("Scan for nearby devices")
        self.btn_rescan.connect("clicked", self.on_scan_clicked)
        header_box.pack_end(self.btn_rescan, False, False, 0)

        btn_close = Gtk.Button(label="󰅖")
        btn_close.set_name("btn-close")
        btn_close.set_tooltip_text("Close")
        btn_close.connect("clicked", self.close_animated)
        header_box.pack_end(btn_close, False, False, 0)

        # 2. Bluetooth Toggle Pill
        self.toggle_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.toggle_box.set_name("toggle-pill")
        self.card.pack_start(self.toggle_box, False, False, 0)

        self.toggle_icon = Gtk.Label(label="󰂯")
        self.toggle_icon.set_name("toggle-icon")
        self.toggle_box.pack_start(self.toggle_icon, False, False, 0)

        toggle_labels_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        toggle_title = Gtk.Label(label="Bluetooth")
        toggle_title.set_name("toggle-title")
        toggle_title.set_xalign(0)
        toggle_labels_box.pack_start(toggle_title, False, False, 0)

        self.toggle_sub = Gtk.Label(label="Enabled")
        self.toggle_sub.set_name("toggle-sub")
        self.toggle_sub.set_xalign(0)
        toggle_labels_box.pack_start(self.toggle_sub, False, False, 0)
        self.toggle_box.pack_start(toggle_labels_box, True, True, 0)

        self.bt_switch = Gtk.Switch()
        self.bt_switch.set_name("bt-switch")
        self.bt_switch.set_valign(Gtk.Align.CENTER)
        self.bt_switch.connect("state-set", self.on_switch_toggled)
        self.toggle_box.pack_end(self.bt_switch, False, False, 0)

        # 3. Active Connection Card (Shown when connected)
        self.active_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.active_card.set_name("active-card")
        self.active_card.set_no_show_all(True)
        self.card.pack_start(self.active_card, False, False, 0)

        self.active_icon = Gtk.Label(label="󰋋")
        self.active_icon.set_name("active-icon")
        self.active_card.pack_start(self.active_icon, False, False, 0)

        active_info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.active_name_label = Gtk.Label(label="")
        self.active_name_label.set_name("active-name")
        self.active_name_label.set_xalign(0)
        self.active_name_label.set_ellipsize(3)
        active_info_box.pack_start(self.active_name_label, False, False, 0)

        self.active_details_label = Gtk.Label(label="")
        self.active_details_label.set_name("active-details")
        self.active_details_label.set_xalign(0)
        active_info_box.pack_start(self.active_details_label, False, False, 0)
        self.active_card.pack_start(active_info_box, True, True, 0)

        self.btn_disconnect = Gtk.Button(label="Disconnect")
        self.btn_disconnect.set_name("btn-disconnect")
        self.btn_disconnect.set_valign(Gtk.Align.CENTER)
        self.btn_disconnect.connect("clicked", self.on_disconnect_active_clicked)
        self.active_card.pack_end(self.btn_disconnect, False, False, 0)

        # 4. Status / Feedback Banner
        self.status_banner = Gtk.Label(label="")
        self.status_banner.set_name("status-banner")
        self.status_banner.set_xalign(0)
        self.status_banner.set_no_show_all(True)
        self.card.pack_start(self.status_banner, False, False, 0)

        # 5. Section Header
        sec_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sec_label = Gtk.Label(label="PAIRED DEVICES")
        sec_label.set_name("section-title")
        sec_label.set_xalign(0)
        sec_box.pack_start(sec_label, True, True, 0)

        self.count_badge = Gtk.Label(label="0")
        self.count_badge.set_name("count-badge")
        sec_box.pack_end(self.count_badge, False, False, 0)
        self.card.pack_start(sec_box, False, False, 0)

        # 6. Scrolled Window with Devices List
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_name("devices-scroll")
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_min_content_height(180)
        self.scroll.set_max_content_height(240)
        self.card.pack_start(self.scroll, True, True, 0)

        self.devices_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.devices_box.set_name("devices-box")
        self.scroll.add(self.devices_box)

        # 7. Footer Row: Settings + Adapter Badge
        footer_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer_box.set_name("footer-box")
        self.card.pack_start(footer_box, False, False, 0)

        btn_settings = Gtk.Button(label="󰒓 Bluetooth Manager")
        btn_settings.set_name("btn-settings")
        btn_settings.connect("clicked", self.on_settings_clicked)
        footer_box.pack_start(btn_settings, False, False, 0)

        self.adapter_label = Gtk.Label(label=f" {self.adapter_name}")
        self.adapter_label.set_name("adapter-badge")
        footer_box.pack_end(self.adapter_label, False, False, 0)

    # --- Actions & Event Handlers ---
    def set_status_message(self, text, is_error=False, timeout_sec=4):
        if not text:
            self.status_banner.hide()
            return
        self.status_banner.set_text(text)
        ctx = self.status_banner.get_style_context()
        if is_error:
            ctx.add_class("status-error")
        else:
            ctx.remove_class("status-error")
        self.status_banner.show()
        if timeout_sec > 0:
            GLib.timeout_add_seconds(timeout_sec, lambda: self.status_banner.hide() or False)

    def on_scan_clicked(self, *_):
        if self.is_scanning:
            return
        self.is_scanning = True
        self.btn_rescan.set_sensitive(False)
        self.set_status_message("Scanning for nearby devices (5s)...")

        def worker():
            run_bt(["--timeout", "5", "scan", "on"], timeout=7)
            time.sleep(0.5)
            self.trigger_refresh(scan=False)

        threading.Thread(target=worker, daemon=True).start()

    def on_switch_toggled(self, switch, state):
        def worker():
            set_bt_power(state)
            time.sleep(0.5)
            GLib.idle_add(self.trigger_refresh, False)
        threading.Thread(target=worker, daemon=True).start()
        return False

    def on_disconnect_active_clicked(self, *_):
        if not hasattr(self, 'active_device_mac') or not self.active_device_mac:
            return
        mac = self.active_device_mac
        self.set_status_message("Disconnecting...")
        def worker():
            run_bt(["disconnect", mac], timeout=5)
            time.sleep(0.5)
            GLib.idle_add(self.trigger_refresh, False)
        threading.Thread(target=worker, daemon=True).start()

    def on_settings_clicked(self, *_):
        subprocess.Popen(["blueman-manager"])
        self.close_animated()

    def trigger_refresh(self, scan=False):
        def worker():
            power_on = get_bt_power()
            adapter_name = get_adapter_name() if power_on else "Bluetooth"
            paired = get_paired_devices() if power_on else []

            save_cache(power_on, adapter_name, paired)
            GLib.idle_add(self.update_ui_state, power_on, adapter_name, paired)

        threading.Thread(target=worker, daemon=True).start()

    def update_ui_state(self, power_on, adapter_name, paired_devices):
        self.is_scanning = False
        self.btn_rescan.set_sensitive(True)
        self.adapter_name = adapter_name
        self.adapter_label.set_text(f" {adapter_name}")

        # Update switch without triggering state-set
        self.bt_switch.handler_block_by_func(self.on_switch_toggled)
        self.bt_switch.set_active(power_on)
        self.bt_switch.handler_unblock_by_func(self.on_switch_toggled)

        self.toggle_icon.set_text("󰂯" if power_on else "󰂲")
        self.toggle_sub.set_text("Enabled" if power_on else "Disabled")

        # Find any connected device
        connected_dev = next((d for d in paired_devices if d["connected"]), None)
        if power_on and connected_dev:
            self.active_device_mac = connected_dev["mac"]
            self.active_card.show()
            self.active_name_label.set_text(connected_dev["name"])
            bat_text = f" • 󰁹 {connected_dev['battery']}%" if connected_dev["battery"] is not None else ""
            self.active_details_label.set_text(f"Connected{bat_text}")
            self.active_icon.set_text(get_device_glyph(connected_dev["icon_type"]))
        else:
            self.active_device_mac = None
            self.active_card.hide()

        # Update Paired Devices List
        for child in self.devices_box.get_children():
            self.devices_box.remove(child)

        if not power_on:
            self.count_badge.set_text("0")
            empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            empty_box.set_valign(Gtk.Align.CENTER)
            empty_box.set_margin_top(30)
            empty_icon = Gtk.Label(label="󰂲")
            empty_icon.set_name("empty-icon")
            empty_label = Gtk.Label(label="Bluetooth is turned off")
            empty_label.set_name("empty-label")
            empty_box.pack_start(empty_icon, False, False, 0)
            empty_box.pack_start(empty_label, False, False, 0)
            self.devices_box.pack_start(empty_box, True, True, 0)
            self.devices_box.show_all()
            return

        self.count_badge.set_text(str(len(paired_devices)))

        if not paired_devices:
            empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            empty_box.set_valign(Gtk.Align.CENTER)
            empty_box.set_margin_top(30)
            empty_icon = Gtk.Label(label="󰂯")
            empty_icon.set_name("empty-icon")
            empty_label = Gtk.Label(label="No paired devices found")
            empty_label.set_name("empty-label")
            empty_box.pack_start(empty_icon, False, False, 0)
            empty_box.pack_start(empty_label, False, False, 0)
            self.devices_box.pack_start(empty_box, True, True, 0)
            self.devices_box.show_all()
            return

        for dev in paired_devices:
            mac = dev["mac"]
            name = dev["name"]
            is_connected = dev["connected"]
            icon_glyph = get_device_glyph(dev["icon_type"])
            battery = dev["battery"]

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.set_name("device-row")
            if is_connected:
                row.get_style_context().add_class("row-active")

            # Icon
            dev_icon = Gtk.Label(label=icon_glyph)
            dev_icon.set_name("device-icon")
            row.pack_start(dev_icon, False, False, 0)

            # Name & info box
            name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            name_label = Gtk.Label(label=name)
            name_label.set_name("device-name")
            name_label.set_xalign(0)
            name_label.set_ellipsize(3)
            name_label.set_max_width_chars(18)
            name_box.pack_start(name_label, False, False, 0)

            if battery is not None:
                sub_label = Gtk.Label(label=f"󰁹 {battery}%")
                sub_label.set_name("device-sub")
                sub_label.set_xalign(0)
                name_box.pack_start(sub_label, False, False, 0)

            row.pack_start(name_box, True, True, 0)

            # Action Buttons
            if is_connected:
                btn_disc = Gtk.Button(label="Disconnect")
                btn_disc.set_name("btn-disconnect-row")
                btn_disc.connect("clicked", self.on_device_disconnect_clicked, dev)
                row.pack_end(btn_disc, False, False, 0)

                badge = Gtk.Label(label="󰄬")
                badge.set_name("badge-connected-icon")
                row.pack_end(badge, False, False, 0)
            else:
                btn_conn = Gtk.Button(label="Connect")
                btn_conn.set_name("btn-connect-row")
                btn_conn.connect("clicked", self.on_device_connect_clicked, dev)
                row.pack_end(btn_conn, False, False, 0)

            self.devices_box.pack_start(row, False, False, 0)

        self.devices_box.show_all()

    def on_device_connect_clicked(self, button, dev):
        mac = dev["mac"]
        name = dev["name"]
        if self.is_connecting:
            return
        self.is_connecting = True
        self.set_status_message(f"Connecting to '{name}'...")

        def worker():
            code, out, err = run_bt(["connect", mac], timeout=15)
            time.sleep(0.5)

            def finish():
                self.is_connecting = False
                if code == 0 and "Successful" in out or "Connection successful" in out:
                    self.set_status_message(f"Connected to '{name}'!", is_error=False)
                else:
                    msg = err or out or "Failed to connect"
                    if "Failed to connect" in msg:
                        msg = "Device unreachable or powered off"
                    self.set_status_message(f"Failed: {msg}", is_error=True)
                self.trigger_refresh(scan=False)

            GLib.idle_add(finish)

        threading.Thread(target=worker, daemon=True).start()

    def on_device_disconnect_clicked(self, button, dev):
        mac = dev["mac"]
        name = dev["name"]
        self.set_status_message(f"Disconnecting from '{name}'...")

        def worker():
            run_bt(["disconnect", mac], timeout=5)
            time.sleep(0.5)

            def finish():
                self.set_status_message(f"Disconnected from '{name}'", is_error=False)
                self.trigger_refresh(scan=False)

            GLib.idle_add(finish)

        threading.Thread(target=worker, daemon=True).start()

    # --- Styling ---
    def apply_css(self):
        theme_path = "/home/sreyas/.config/waybar/current-theme.css"
        css_provider = Gtk.CssProvider()
        css = f"""
        @import url('{theme_path}');

        * {{
            font-family: "Symbols Nerd Font", "JetBrains Mono", sans-serif;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }}

        window {{
            background: transparent;
        }}

        #bt-card {{
            background-color: alpha(@bg-color, 0.96);
            border: 1.5px solid alpha(@accent-blue, 0.85);
            border-radius: 14px;
            padding: 14px 16px;
        }}

        /* Header */
        #header-box {{
            padding-bottom: 2px;
        }}

        #header-icon {{
            font-size: 16px;
            color: @accent-blue;
        }}

        #header-title {{
            font-size: 14px;
            font-weight: 800;
            color: @fg-color;
        }}

        #btn-icon {{
            color: @comment-color;
            background: transparent;
            border: none;
            font-size: 14px;
            padding: 3px 6px;
            border-radius: 6px;
        }}

        #btn-icon:hover {{
            color: @accent-blue;
            background-color: alpha(@accent-blue, 0.2);
        }}

        #btn-close {{
            color: @comment-color;
            background: transparent;
            border: none;
            font-size: 12px;
            padding: 3px 6px;
            border-radius: 6px;
        }}

        #btn-close:hover {{
            color: @fg-color;
            background-color: alpha(@accent-red, 0.75);
        }}

        /* Toggle Card */
        #toggle-pill {{
            background-color: alpha(@fg-color, 0.08);
            border: 1px solid alpha(@border-color, 0.4);
            border-radius: 10px;
            padding: 8px 12px;
        }}

        #toggle-icon {{
            font-size: 18px;
            color: @accent-blue;
        }}

        #toggle-title {{
            font-size: 13px;
            font-weight: bold;
            color: @fg-color;
        }}

        #toggle-sub {{
            font-size: 10.5px;
            color: @comment-color;
        }}

        #bt-switch {{
            border-radius: 14px;
        }}

        /* Active Connection Card */
        #active-card {{
            background-color: alpha(@accent-blue, 0.15);
            border: 1.2px solid alpha(@accent-blue, 0.6);
            border-radius: 10px;
            padding: 8px 12px;
        }}

        #active-icon {{
            font-size: 20px;
            color: @accent-blue;
        }}

        #active-name {{
            font-size: 13px;
            font-weight: 800;
            color: @fg-color;
        }}

        #active-details {{
            font-size: 10.5px;
            color: @accent-blue;
        }}

        #btn-disconnect {{
            font-size: 11px;
            font-weight: bold;
            color: @accent-red;
            background-color: alpha(@accent-red, 0.15);
            border: 1px solid alpha(@accent-red, 0.35);
            border-radius: 6px;
            padding: 3px 8px;
        }}

        #btn-disconnect:hover {{
            background-color: alpha(@accent-red, 0.85);
            color: @bg-color;
        }}

        /* Status / Banner */
        #status-banner {{
            background-color: alpha(@accent-blue, 0.2);
            border: 1px solid alpha(@accent-blue, 0.4);
            border-radius: 8px;
            padding: 6px 10px;
            font-size: 11.5px;
            color: @fg-color;
        }}

        #status-banner.status-error {{
            background-color: alpha(@accent-red, 0.25);
            border-color: alpha(@accent-red, 0.6);
            color: @fg-color;
        }}

        /* Section Title */
        #section-title {{
            font-size: 10.5px;
            font-weight: 800;
            color: @comment-color;
            letter-spacing: 0.5px;
        }}

        #count-badge {{
            font-size: 10px;
            font-weight: bold;
            color: @comment-color;
            background-color: alpha(@fg-color, 0.1);
            border-radius: 10px;
            padding: 1px 6px;
        }}

        /* Devices Scroll & List */
        #devices-scroll {{
            border-radius: 8px;
            background: transparent;
        }}

        #devices-box {{
            padding-right: 4px;
        }}

        #device-row {{
            background-color: alpha(@fg-color, 0.04);
            border: 1px solid alpha(@border-color, 0.3);
            border-radius: 8px;
            padding: 6px 10px;
            margin-bottom: 3px;
        }}

        #device-row:hover {{
            background-color: alpha(@accent-blue, 0.12);
            border-color: alpha(@accent-blue, 0.4);
        }}

        #device-row.row-active {{
            border-color: alpha(@accent-blue, 0.6);
            background-color: alpha(@accent-blue, 0.15);
        }}

        #device-icon {{
            font-size: 16px;
            color: @accent-blue;
        }}

        #device-name {{
            font-size: 12.5px;
            font-weight: 600;
            color: @fg-color;
        }}

        #device-sub {{
            font-size: 10px;
            color: @comment-color;
        }}

        #badge-connected-icon {{
            font-size: 13px;
            font-weight: bold;
            color: @accent-green;
        }}

        #btn-connect-row {{
            font-size: 11px;
            font-weight: bold;
            color: @accent-blue;
            background-color: alpha(@accent-blue, 0.15);
            border: 1px solid alpha(@accent-blue, 0.3);
            border-radius: 6px;
            padding: 3px 10px;
        }}

        #btn-connect-row:hover {{
            background-color: @accent-blue;
            color: @bg-color;
        }}

        #btn-disconnect-row {{
            font-size: 11px;
            font-weight: bold;
            color: @accent-red;
            background-color: alpha(@accent-red, 0.15);
            border: 1px solid alpha(@accent-red, 0.3);
            border-radius: 6px;
            padding: 3px 8px;
        }}

        #btn-disconnect-row:hover {{
            background-color: @accent-red;
            color: @bg-color;
        }}

        /* Empty states */
        #empty-icon {{
            font-size: 28px;
            color: alpha(@comment-color, 0.6);
        }}

        #empty-label {{
            font-size: 12px;
            color: @comment-color;
        }}

        /* Footer */
        #footer-box {{
            padding-top: 4px;
            border-top: 1px solid alpha(@border-color, 0.3);
        }}

        #btn-settings {{
            font-size: 11px;
            font-weight: 600;
            color: @comment-color;
            background: transparent;
            border: 1px solid alpha(@border-color, 0.4);
            border-radius: 6px;
            padding: 4px 10px;
        }}

        #btn-settings:hover {{
            color: @fg-color;
            background-color: alpha(@fg-color, 0.1);
            border-color: @accent-blue;
        }}

        #adapter-badge {{
            font-size: 10.5px;
            font-family: "JetBrains Mono", monospace;
            color: @comment-color;
        }}

        /* Scrollbar styling */
        scrollbar trough {{
            background: transparent;
            border: none;
        }}

        scrollbar slider {{
            background-color: alpha(@comment-color, 0.3);
            border-radius: 4px;
            min-width: 4px;
        }}

        scrollbar slider:hover {{
            background-color: alpha(@accent-blue, 0.6);
        }}
        """
        css_provider.load_from_data(css.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

def main():
    toggle_or_exit()
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    app = BluetoothPopup()
    signal.signal(signal.SIGUSR1, lambda *_: GLib.idle_add(app.close_animated))

    app.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
