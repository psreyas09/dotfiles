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

PID_FILE = "/tmp/waybar_wifi_popup.pid"
CACHE_FILE = "/tmp/waybar_wifi_cache.json"

def toggle_or_exit():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            # Check if process is alive
            os.kill(pid, 0)
            # Send SIGUSR1 to request a smooth, animated exit
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

# --- NetworkManager CLI & Sysfs Helpers ---

def run_nmcli(args, timeout=10):
    try:
        res = subprocess.run(
            ["nmcli"] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return 1, "", str(e)

def get_wifi_interface():
    try:
        for d in os.listdir("/sys/class/net"):
            if os.path.exists(f"/sys/class/net/{d}/wireless") or os.path.exists(f"/sys/class/net/{d}/phy80211"):
                return d
    except Exception:
        pass
    code, out, _ = run_nmcli(["-t", "-f", "DEVICE,TYPE", "dev", "status"], timeout=2)
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[1] == "wifi":
            return parts[0]
    return ""

def get_wifi_radio():
    code, out, _ = run_nmcli(["-t", "-f", "WIFI", "g"], timeout=3)
    return out.lower() == "enabled"

def set_wifi_radio(enabled):
    action = "on" if enabled else "off"
    run_nmcli(["radio", "wifi", action], timeout=5)

def get_active_connection(iface):
    if not iface:
        return None
    code, out, _ = run_nmcli(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"], timeout=3)
    active_conn = None
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 4 and parts[0] == iface and parts[2] == "connected":
            active_conn = parts[3]
            break
    if not active_conn:
        return None

    # Get IP
    ip = ""
    code, out, _ = run_nmcli(["-t", "-f", "IP4.ADDRESS", "dev", "show", iface], timeout=3)
    for line in out.splitlines():
        if line.startswith("IP4.ADDRESS"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                ip = parts[1].split("/")[0].strip()
                break

    # Get active SSID & signal
    code, out, _ = run_nmcli(["-t", "-e", "yes", "-f", "IN-USE,SSID,SIGNAL", "dev", "wifi", "list"], timeout=4)
    active_ssid = active_conn
    signal_pct = 0
    for line in out.splitlines():
        if line.startswith("*"):
            parts = line.split(":")
            if len(parts) >= 3:
                active_ssid = parts[1] or active_conn
                try:
                    signal_pct = int(parts[2])
                except ValueError:
                    signal_pct = 0
            break

    return {
        "connection": active_conn,
        "ssid": active_ssid,
        "ip": ip,
        "signal": signal_pct,
        "iface": iface
    }

def get_saved_connections():
    code, out, _ = run_nmcli(["-t", "-f", "NAME,TYPE", "con", "show"], timeout=3)
    saved = set()
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[1] in ("802-11-wireless", "wifi"):
            saved.add(parts[0])
    return saved

def get_wifi_networks():
    code, out, _ = run_nmcli(["-t", "-e", "yes", "-f", "IN-USE,SSID,SIGNAL,SECURITY,BSSID", "dev", "wifi", "list"], timeout=5)
    networks = []
    seen = {}
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 4:
            in_use = parts[0].strip() == "*"
            ssid = parts[1].strip()
            if not ssid or ssid == "--":
                continue
            try:
                signal_pct = int(parts[2].strip())
            except ValueError:
                signal_pct = 0
            security = parts[3].strip()
            
            if ssid not in seen:
                net = {
                    "in_use": in_use,
                    "ssid": ssid,
                    "signal": signal_pct,
                    "security": security,
                    "secured": bool(security and security != "--")
                }
                seen[ssid] = net
                networks.append(net)
            else:
                existing = seen[ssid]
                if in_use:
                    existing["in_use"] = True
                if signal_pct > existing["signal"]:
                    existing["signal"] = signal_pct
                if security and security != "--":
                    existing["security"] = security
                    existing["secured"] = True

    networks.sort(key=lambda n: (not n["in_use"], -n["signal"]))
    return networks

def get_signal_icon(signal_pct):
    if signal_pct >= 75:
        return "󰤨"
    elif signal_pct >= 50:
        return "󰤥"
    elif signal_pct >= 25:
        return "󰤢"
    else:
        return "󰤟"

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return None

def save_cache(radio_on, iface, active_info, saved_conns, networks):
    try:
        data = {
            "radio_on": radio_on,
            "iface": iface,
            "active_info": active_info,
            "saved_conns": list(saved_conns),
            "networks": networks,
            "timestamp": time.time()
        }
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


class WifiPopup(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("Wi-Fi Quick Settings")
        self.set_default_size(360, 440)
        self.set_resizable(False)

        # Layer Shell Setup
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)

        # Animation parameters
        self.target_margin_top = 8
        self.start_margin_top = -12
        self.target_margin_right = 160

        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, self.start_margin_top)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, self.target_margin_right)
        Gtk.Widget.set_opacity(self,0.0)

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
        self.active_iface = get_wifi_interface()

        # UI Build
        self.setup_ui()
        self.apply_css()

        # Load instant cache so opening animation is already fully populated
        cache = load_cache()
        if cache:
            self.update_ui_state(
                cache.get("radio_on", True),
                cache.get("iface", self.active_iface),
                cache.get("active_info"),
                set(cache.get("saved_conns", [])),
                cache.get("networks", [])
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
        Gtk.Widget.set_opacity(self,min(1.0, ease * 1.1))

        # Slide in from top
        curr_margin = int(self.start_margin_top + (self.target_margin_top - self.start_margin_top) * ease)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, curr_margin)

        if progress >= 1.0:
            Gtk.Widget.set_opacity(self,1.0)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, self.target_margin_top)
            # Trigger background scan AFTER entrance animation completes
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
        self.card.set_name("wifi-card")
        self.add(self.card)

        # 1. Header: Icon + Title + Rescan + Close
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_box.set_name("header-box")
        self.card.pack_start(header_box, False, False, 0)

        header_icon = Gtk.Label(label="󰤨")
        header_icon.set_name("header-icon")
        header_box.pack_start(header_icon, False, False, 0)

        header_title = Gtk.Label(label="Wi-Fi Networks")
        header_title.set_name("header-title")
        header_title.set_xalign(0)
        header_box.pack_start(header_title, True, True, 0)

        self.btn_rescan = Gtk.Button(label="󰑐")
        self.btn_rescan.set_name("btn-icon")
        self.btn_rescan.set_tooltip_text("Rescan Wi-Fi networks")
        self.btn_rescan.connect("clicked", self.on_rescan_clicked)
        header_box.pack_end(self.btn_rescan, False, False, 0)

        btn_close = Gtk.Button(label="󰅖")
        btn_close.set_name("btn-close")
        btn_close.set_tooltip_text("Close")
        btn_close.connect("clicked", self.close_animated)
        header_box.pack_end(btn_close, False, False, 0)

        # 2. Wi-Fi Toggle Pill
        self.toggle_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.toggle_box.set_name("toggle-pill")
        self.card.pack_start(self.toggle_box, False, False, 0)

        self.toggle_icon = Gtk.Label(label="󰖩")
        self.toggle_icon.set_name("toggle-icon")
        self.toggle_box.pack_start(self.toggle_icon, False, False, 0)

        toggle_labels_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        toggle_title = Gtk.Label(label="Wi-Fi")
        toggle_title.set_name("toggle-title")
        toggle_title.set_xalign(0)
        toggle_labels_box.pack_start(toggle_title, False, False, 0)

        self.toggle_sub = Gtk.Label(label="Enabled")
        self.toggle_sub.set_name("toggle-sub")
        self.toggle_sub.set_xalign(0)
        toggle_labels_box.pack_start(self.toggle_sub, False, False, 0)
        self.toggle_box.pack_start(toggle_labels_box, True, True, 0)

        self.wifi_switch = Gtk.Switch()
        self.wifi_switch.set_name("wifi-switch")
        self.wifi_switch.set_valign(Gtk.Align.CENTER)
        self.wifi_switch.connect("state-set", self.on_switch_toggled)
        self.toggle_box.pack_end(self.wifi_switch, False, False, 0)

        # 3. Active Connection Card (Shown when connected)
        self.active_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.active_card.set_name("active-card")
        self.active_card.set_no_show_all(True)
        self.card.pack_start(self.active_card, False, False, 0)

        self.active_icon = Gtk.Label(label="󰤨")
        self.active_icon.set_name("active-icon")
        self.active_card.pack_start(self.active_icon, False, False, 0)

        active_info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.active_ssid_label = Gtk.Label(label="")
        self.active_ssid_label.set_name("active-ssid")
        self.active_ssid_label.set_xalign(0)
        self.active_ssid_label.set_ellipsize(3)
        active_info_box.pack_start(self.active_ssid_label, False, False, 0)

        self.active_details_label = Gtk.Label(label="")
        self.active_details_label.set_name("active-details")
        self.active_details_label.set_xalign(0)
        active_info_box.pack_start(self.active_details_label, False, False, 0)
        self.active_card.pack_start(active_info_box, True, True, 0)

        self.btn_disconnect = Gtk.Button(label="Disconnect")
        self.btn_disconnect.set_name("btn-disconnect")
        self.btn_disconnect.set_valign(Gtk.Align.CENTER)
        self.btn_disconnect.connect("clicked", self.on_disconnect_clicked)
        self.active_card.pack_end(self.btn_disconnect, False, False, 0)

        # 4. Status / Feedback Banner
        self.status_banner = Gtk.Label(label="")
        self.status_banner.set_name("status-banner")
        self.status_banner.set_xalign(0)
        self.status_banner.set_no_show_all(True)
        self.card.pack_start(self.status_banner, False, False, 0)

        # 5. Section Header
        sec_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sec_label = Gtk.Label(label="AVAILABLE NETWORKS")
        sec_label.set_name("section-title")
        sec_label.set_xalign(0)
        sec_box.pack_start(sec_label, True, True, 0)

        self.count_badge = Gtk.Label(label="0")
        self.count_badge.set_name("count-badge")
        sec_box.pack_end(self.count_badge, False, False, 0)
        self.card.pack_start(sec_box, False, False, 0)

        # 6. Scrolled Window with Network List
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_name("networks-scroll")
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_min_content_height(180)
        self.scroll.set_max_content_height(240)
        self.card.pack_start(self.scroll, True, True, 0)

        self.networks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.networks_box.set_name("networks-box")
        self.scroll.add(self.networks_box)

        # 7. Footer Row: Settings + Interface Badge
        footer_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer_box.set_name("footer-box")
        self.card.pack_start(footer_box, False, False, 0)

        btn_settings = Gtk.Button(label="󰒓 Network Settings")
        btn_settings.set_name("btn-settings")
        btn_settings.connect("clicked", self.on_settings_clicked)
        footer_box.pack_start(btn_settings, False, False, 0)

        self.iface_label = Gtk.Label(label=f"󰖩 {self.active_iface or 'N/A'}")
        self.iface_label.set_name("iface-badge")
        footer_box.pack_end(self.iface_label, False, False, 0)

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

    def on_rescan_clicked(self, *_):
        if self.is_scanning:
            return
        self.set_status_message("Scanning for networks...")
        self.btn_rescan.set_sensitive(False)
        self.trigger_refresh(scan=True)

    def on_switch_toggled(self, switch, state):
        def worker():
            set_wifi_radio(state)
            time.sleep(0.5)
            GLib.idle_add(self.trigger_refresh, False)
        threading.Thread(target=worker, daemon=True).start()
        return False

    def on_disconnect_clicked(self, *_):
        if not self.active_iface:
            return
        self.set_status_message("Disconnecting...")
        def worker():
            run_nmcli(["dev", "disconnect", self.active_iface])
            time.sleep(0.5)
            GLib.idle_add(self.trigger_refresh, False)
        threading.Thread(target=worker, daemon=True).start()

    def on_settings_clicked(self, *_):
        subprocess.Popen(["nm-connection-editor"])
        self.close_animated()

    def trigger_refresh(self, scan=False):
        if self.is_scanning:
            return
        self.is_scanning = True
        def worker():
            if scan:
                run_nmcli(["dev", "wifi", "rescan"])
                time.sleep(1.0)
            
            radio_on = get_wifi_radio()
            iface = get_wifi_interface()
            active_info = get_active_connection(iface) if radio_on else None
            saved_conns = get_saved_connections() if radio_on else set()
            networks = get_wifi_networks() if radio_on else []

            # Save to fast cache
            save_cache(radio_on, iface, active_info, saved_conns, networks)

            GLib.idle_add(self.update_ui_state, radio_on, iface, active_info, saved_conns, networks)

        threading.Thread(target=worker, daemon=True).start()

    def update_ui_state(self, radio_on, iface, active_info, saved_conns, networks):
        self.is_scanning = False
        self.btn_rescan.set_sensitive(True)
        self.active_iface = iface
        self.iface_label.set_text(f"󰖩 {iface or 'None'}")

        # Update switch without triggering state-set signal
        self.wifi_switch.handler_block_by_func(self.on_switch_toggled)
        self.wifi_switch.set_active(radio_on)
        self.wifi_switch.handler_unblock_by_func(self.on_switch_toggled)

        self.toggle_icon.set_text("󰖩" if radio_on else "󰖪")
        self.toggle_sub.set_text("Enabled" if radio_on else "Disabled")

        # Update Active Card
        if radio_on and active_info:
            self.active_card.show()
            self.active_ssid_label.set_text(active_info["ssid"])
            ip_text = f"• {active_info['ip']} " if active_info['ip'] else ""
            self.active_details_label.set_text(f"Connected {ip_text}• {active_info['signal']}% signal")
            self.active_icon.set_text(get_signal_icon(active_info["signal"]))
        else:
            self.active_card.hide()

        # Update Available Networks List
        for child in self.networks_box.get_children():
            self.networks_box.remove(child)

        if not radio_on:
            self.count_badge.set_text("0")
            empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            empty_box.set_valign(Gtk.Align.CENTER)
            empty_box.set_margin_top(30)
            empty_icon = Gtk.Label(label="󰖪")
            empty_icon.set_name("empty-icon")
            empty_label = Gtk.Label(label="Wi-Fi is turned off")
            empty_label.set_name("empty-label")
            empty_box.pack_start(empty_icon, False, False, 0)
            empty_box.pack_start(empty_label, False, False, 0)
            self.networks_box.pack_start(empty_box, True, True, 0)
            self.networks_box.show_all()
            return

        self.count_badge.set_text(str(len(networks)))

        if not networks:
            empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            empty_box.set_valign(Gtk.Align.CENTER)
            empty_box.set_margin_top(30)
            empty_icon = Gtk.Label(label="󰤭")
            empty_icon.set_name("empty-icon")
            empty_label = Gtk.Label(label="No networks found nearby")
            empty_label.set_name("empty-label")
            empty_box.pack_start(empty_icon, False, False, 0)
            empty_box.pack_start(empty_label, False, False, 0)
            self.networks_box.pack_start(empty_box, True, True, 0)
            self.networks_box.show_all()
            return

        for net in networks:
            ssid = net["ssid"]
            is_active = net["in_use"]
            is_saved = ssid in saved_conns or is_active
            is_secured = net["secured"]
            signal_pct = net["signal"]

            # Row container
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            row.set_name("network-row")
            if is_active:
                row.get_style_context().add_class("row-active")

            # Main click item
            item_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            item_box.set_name("network-item")
            row.pack_start(item_box, False, False, 0)

            # Signal icon
            sig_icon = Gtk.Label(label=get_signal_icon(signal_pct))
            sig_icon.set_name("signal-icon")
            item_box.pack_start(sig_icon, False, False, 0)

            # SSID label
            name_label = Gtk.Label(label=ssid)
            name_label.set_name("ssid-label")
            name_label.set_xalign(0)
            name_label.set_ellipsize(3)
            name_label.set_max_width_chars(20)
            item_box.pack_start(name_label, True, True, 0)

            # Security lock icon
            if is_secured:
                lock_icon = Gtk.Label(label="󰌾")
                lock_icon.set_name("lock-icon")
                lock_icon.set_tooltip_text(net["security"])
                item_box.pack_start(lock_icon, False, False, 0)

            # Action / Badge
            if is_active:
                badge = Gtk.Label(label="󰄬 Connected")
                badge.set_name("badge-connected")
                item_box.pack_end(badge, False, False, 0)
            else:
                btn_action = Gtk.Button(label="Connect")
                btn_action.set_name("btn-connect-row")
                btn_action.connect("clicked", self.on_network_connect_clicked, net, is_saved, row)
                item_box.pack_end(btn_action, False, False, 0)

            # Inline Password Box (revealed when needed)
            pwd_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            pwd_box.set_name("pwd-box")
            pwd_box.set_no_show_all(True)
            row.pack_start(pwd_box, False, False, 0)

            # Store references on row
            row.pwd_box = pwd_box
            row.net_info = net
            row.is_saved = is_saved

            self.networks_box.pack_start(row, False, False, 0)

        self.networks_box.show_all()

    def on_network_connect_clicked(self, button, net, is_saved, row):
        ssid = net["ssid"]
        is_secured = net["secured"]

        # If saved connection or open network: connect directly!
        if is_saved or not is_secured:
            self.connect_to_ssid(ssid, password=None)
            return

        # Otherwise expand inline password entry
        pwd_box = row.pwd_box
        if pwd_box.get_visible():
            pwd_box.hide()
            return

        for c in pwd_box.get_children():
            pwd_box.remove(c)

        entry_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pwd_entry = Gtk.Entry()
        pwd_entry.set_name("pwd-entry")
        pwd_entry.set_placeholder_text("Enter Wi-Fi password...")
        pwd_entry.set_visibility(False)
        entry_row.pack_start(pwd_entry, True, True, 0)

        btn_eye = Gtk.Button(label="󰈈")
        btn_eye.set_name("btn-icon-sm")
        btn_eye.set_tooltip_text("Show/Hide password")
        btn_eye.connect("clicked", lambda b: pwd_entry.set_visibility(not pwd_entry.get_visibility()))
        entry_row.pack_start(btn_eye, False, False, 0)

        btn_confirm = Gtk.Button(label="Connect")
        btn_confirm.set_name("btn-confirm")
        entry_row.pack_start(btn_confirm, False, False, 0)

        btn_cancel = Gtk.Button(label="󰅖")
        btn_cancel.set_name("btn-cancel")
        btn_cancel.connect("clicked", lambda b: pwd_box.hide())
        entry_row.pack_start(btn_cancel, False, False, 0)

        pwd_box.pack_start(entry_row, False, False, 0)

        def do_connect(*_):
            pwd = pwd_entry.get_text().strip()
            if not pwd:
                self.set_status_message("Password cannot be empty", is_error=True)
                return
            pwd_box.hide()
            self.connect_to_ssid(ssid, password=pwd)

        pwd_entry.connect("activate", do_connect)
        btn_confirm.connect("clicked", do_connect)

        pwd_box.show_all()
        pwd_entry.grab_focus()

    def connect_to_ssid(self, ssid, password=None):
        if self.is_connecting:
            return
        self.is_connecting = True
        self.set_status_message(f"Connecting to '{ssid}'...")

        def worker():
            if password:
                cmd = ["dev", "wifi", "connect", ssid, "password", password]
            else:
                cmd = ["dev", "wifi", "connect", ssid]

            code, out, err = run_nmcli(cmd, timeout=20)
            time.sleep(1.0)

            def finish():
                self.is_connecting = False
                if code == 0:
                    self.set_status_message(f"Connected to '{ssid}'!", is_error=False)
                else:
                    msg = err or out or "Failed to connect"
                    if "Secrets were required" in msg:
                        msg = "Password required or incorrect"
                    self.set_status_message(f"Connection failed: {msg}", is_error=True)
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

        #wifi-card {{
            background-color: alpha(@bg-color, 0.96);
            border: 1.5px solid alpha(@accent-purple, 0.85);
            border-radius: 14px;
            padding: 14px 16px;
        }}

        /* Header */
        #header-box {{
            padding-bottom: 2px;
        }}

        #header-icon {{
            font-size: 16px;
            color: @accent-purple;
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
            color: @accent-purple;
            background-color: alpha(@accent-purple, 0.2);
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
            color: @accent-purple;
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

        #wifi-switch {{
            border-radius: 14px;
        }}

        /* Active Connection Card */
        #active-card {{
            background-color: alpha(@accent-purple, 0.15);
            border: 1.2px solid alpha(@accent-purple, 0.6);
            border-radius: 10px;
            padding: 8px 12px;
        }}

        #active-icon {{
            font-size: 20px;
            color: @accent-purple;
        }}

        #active-ssid {{
            font-size: 13px;
            font-weight: 800;
            color: @fg-color;
        }}

        #active-details {{
            font-size: 10.5px;
            color: @accent-purple;
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
            background-color: alpha(@accent-purple, 0.2);
            border: 1px solid alpha(@accent-purple, 0.4);
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

        /* Networks Scroll & List */
        #networks-scroll {{
            border-radius: 8px;
            background: transparent;
        }}

        #networks-box {{
            padding-right: 4px;
        }}

        #network-row {{
            background-color: alpha(@fg-color, 0.04);
            border: 1px solid alpha(@border-color, 0.3);
            border-radius: 8px;
            padding: 6px 10px;
            margin-bottom: 3px;
        }}

        #network-row:hover {{
            background-color: alpha(@accent-purple, 0.12);
            border-color: alpha(@accent-purple, 0.4);
        }}

        #network-row.row-active {{
            border-color: alpha(@accent-purple, 0.6);
            background-color: alpha(@accent-purple, 0.15);
        }}

        #signal-icon {{
            font-size: 14px;
            color: @accent-purple;
        }}

        #ssid-label {{
            font-size: 12.5px;
            font-weight: 600;
            color: @fg-color;
        }}

        #lock-icon {{
            font-size: 11px;
            color: @comment-color;
        }}

        #badge-connected {{
            font-size: 11px;
            font-weight: bold;
            color: @accent-green;
            background-color: alpha(@accent-green, 0.15);
            padding: 2px 8px;
            border-radius: 6px;
        }}

        #btn-connect-row {{
            font-size: 11px;
            font-weight: bold;
            color: @accent-purple;
            background-color: alpha(@accent-purple, 0.15);
            border: 1px solid alpha(@accent-purple, 0.3);
            border-radius: 6px;
            padding: 3px 10px;
        }}

        #btn-connect-row:hover {{
            background-color: @accent-purple;
            color: @bg-color;
        }}

        /* Inline Password Box */
        #pwd-box {{
            padding-top: 8px;
            margin-top: 4px;
            border-top: 1px dashed alpha(@border-color, 0.4);
        }}

        #pwd-entry {{
            font-size: 11.5px;
            background-color: alpha(@bg-color, 0.9);
            color: @fg-color;
            border: 1px solid alpha(@accent-purple, 0.5);
            border-radius: 6px;
            padding: 4px 8px;
        }}

        #pwd-entry:focus {{
            border-color: @accent-purple;
        }}

        #btn-icon-sm {{
            font-size: 12px;
            color: @comment-color;
            background: transparent;
            border: 1px solid alpha(@border-color, 0.4);
            border-radius: 6px;
            padding: 2px 6px;
        }}

        #btn-icon-sm:hover {{
            color: @fg-color;
            background-color: alpha(@fg-color, 0.15);
        }}

        #btn-confirm {{
            font-size: 11px;
            font-weight: bold;
            color: @bg-color;
            background-color: @accent-purple;
            border: 1px solid @accent-purple;
            border-radius: 6px;
            padding: 3px 10px;
        }}

        #btn-confirm:hover {{
            background-color: alpha(@accent-purple, 0.85);
        }}

        #btn-cancel {{
            font-size: 11px;
            color: @comment-color;
            background: transparent;
            border: 1px solid alpha(@border-color, 0.4);
            border-radius: 6px;
            padding: 2px 6px;
        }}

        #btn-cancel:hover {{
            color: @accent-red;
            border-color: @accent-red;
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
            border-color: @accent-purple;
        }}

        #iface-badge {{
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
            background-color: alpha(@accent-purple, 0.6);
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

    app = WifiPopup()
    # Intercept SIGUSR1 to trigger a smooth animated close when toggled via Waybar click
    signal.signal(signal.SIGUSR1, lambda *_: GLib.idle_add(app.close_animated))

    app.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
