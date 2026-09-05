#!/usr/bin/env python3
import os
import sys
import signal
import subprocess
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GtkLayerShell, GLib, GdkPixbuf

PID_FILE = "/tmp/waybar_power_menu.pid"
ASSETS_DIR = "/home/sreyas/.config/waybar/assets"
GIF_PATH = os.path.join(ASSETS_DIR, "kurukuru_76.gif")
FALLBACK_GIF_PATH = os.path.join(ASSETS_DIR, "kurukuru.gif")

app_instance = None

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

class CaelestiaPowerMenu(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("Caelestia Power Menu")
        self.set_resizable(False)

        # Layer Shell Setup
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_namespace(self, "power-menu")
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        # Anchored to the RIGHT edge of the screen, vertically centered (Caelestia signature)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, False)

        # Animation parameters: slide in from right margin
        self.target_margin_right = 20
        self.start_margin_right = -110

        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, self.start_margin_right)
        Gtk.Widget.set_opacity(self, 0.0)

        # Event mask
        self.add_events(
            Gdk.EventMask.KEY_PRESS_MASK
            | Gdk.EventMask.KEY_RELEASE_MASK
            | Gdk.EventMask.FOCUS_CHANGE_MASK
        )

        self.connect("destroy", cleanup)
        self.connect("key-press-event", self.on_key_press)
        self.connect("focus-out-event", self.on_focus_out)

        # Animation states
        self.anim_start = None
        self.close_start = None
        self.is_closing = False
        self.pending_action = None
        self.add_tick_callback(self.on_animate_in)

        # UI Build
        self.setup_ui()
        self.apply_css()

    def on_focus_out(self, widget, event):
        # Prevent immediate dismiss if focus shifts during initial map
        if self.anim_start:
            now = GLib.get_monotonic_time() / 1_000_000
            if (now - self.anim_start) < 0.25:
                return False
        self.close_animated()
        return False

    # --- Caelestia Smooth Animations ---
    def on_animate_in(self, widget, frame_clock):
        now = frame_clock.get_frame_time() / 1_000_000
        if self.anim_start is None:
            self.anim_start = now
        elapsed = now - self.anim_start
        progress = min(1.0, elapsed / 0.26)
        # Material 3 Expressive Spatial deceleration ease-out
        ease = 1.0 - (1.0 - progress) ** 3

        Gtk.Widget.set_opacity(self, ease)
        curr_margin = int(self.start_margin_right + (self.target_margin_right - self.start_margin_right) * ease)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, curr_margin)

        if progress >= 1.0:
            Gtk.Widget.set_opacity(self, 1.0)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, self.target_margin_right)
            return False
        return True

    def close_animated(self, action=None, *_):
        if self.is_closing:
            return
        self.is_closing = True
        self.pending_action = action
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
        progress = min(1.0, elapsed / 0.18)
        # Smooth ease-in slide out
        ease = progress ** 2

        Gtk.Widget.set_opacity(self, max(0.0, 1.0 - ease))
        curr_margin = int(self.target_margin_right - 130 * ease)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, curr_margin)

        if progress >= 1.0:
            act = self.pending_action
            cleanup()
            if act:
                try:
                    subprocess.Popen(act, shell=isinstance(act, str))
                except Exception as e:
                    print("Failed to run action:", e, file=sys.stderr)
            return False
        return True

    def on_key_press(self, widget, event):
        key = event.keyval
        # Hotkeys
        if key == Gdk.KEY_Escape:
            self.close_animated()
            return True
        elif key in (Gdk.KEY_l, Gdk.KEY_L):
            self.action_lock()
            return True
        elif key in (Gdk.KEY_s, Gdk.KEY_S):
            self.action_suspend()
            return True
        elif key in (Gdk.KEY_e, Gdk.KEY_E):
            self.action_logout()
            return True
        elif key in (Gdk.KEY_r, Gdk.KEY_R):
            self.action_reboot()
            return True
        elif key in (Gdk.KEY_p, Gdk.KEY_P, Gdk.KEY_q, Gdk.KEY_Q):
            self.action_shutdown()
            return True
        return False

    # --- Actions ---
    def action_lock(self, *_):
        self.close_animated(action=["swaylock"])

    def action_suspend(self, *_):
        self.close_animated(action=["systemctl", "suspend"])

    def action_logout(self, *_):
        self.close_animated(action=["niri", "msg", "action", "quit", "--skip-confirmation"])

    def action_reboot(self, *_):
        self.close_animated(action=["systemctl", "reboot"])

    def action_shutdown(self, *_):
        self.close_animated(action=["systemctl", "poweroff"])

    # --- UI Construction ---
    def setup_ui(self):
        # Vertical card container
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.card.set_name("power-card")
        self.add(self.card)

        # 1. Lock Screen (L)
        self.btn_lock = self.create_button("", "Lock Screen (L)", "session-btn-lock", self.action_lock)
        self.card.pack_start(self.btn_lock, False, False, 0)

        # 2. Suspend / Sleep (S)
        self.btn_suspend = self.create_button("󰤄", "Suspend (S)", "session-btn-suspend", self.action_suspend)
        self.card.pack_start(self.btn_suspend, False, False, 0)

        # 3. Log Out (E)
        self.btn_logout = self.create_button("󰍃", "Log Out (E)", "session-btn-logout", self.action_logout)
        self.card.pack_start(self.btn_logout, False, False, 0)

        # 4. Animated GIF in the Center (Authentic Caelestia Kurukuru / Herta spinning)
        gif_file = GIF_PATH if os.path.exists(GIF_PATH) else FALLBACK_GIF_PATH
        if os.path.exists(gif_file):
            try:
                anim_event = Gtk.EventBox()
                anim_event.set_visible_window(False)
                anim_event.set_tooltip_text("Kuru Kuru ~")

                anim_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                anim_box.set_name("session-gif-box")
                anim_box.set_size_request(76, 76)
                anim_box.set_halign(Gtk.Align.CENTER)
                anim_box.set_valign(Gtk.Align.CENTER)

                anim = GdkPixbuf.PixbufAnimation.new_from_file(gif_file)
                gif_img = Gtk.Image.new_from_animation(anim)
                anim_box.pack_start(gif_img, True, True, 0)
                anim_event.add(anim_box)
                self.card.pack_start(anim_event, False, False, 0)
            except Exception as e:
                print("Failed to load GIF:", e, file=sys.stderr)

        # 5. Reboot (R)
        self.btn_reboot = self.create_button("󰜉", "Restart (R)", "session-btn-reboot", self.action_reboot)
        self.card.pack_start(self.btn_reboot, False, False, 0)

        # 6. Power Off (P)
        self.btn_power = self.create_button("⏻", "Power Off (P)", "session-btn-power", self.action_shutdown)
        self.card.pack_start(self.btn_power, False, False, 0)

    def create_button(self, icon_str, tooltip, class_name, callback):
        btn = Gtk.Button()
        btn.set_name(class_name)
        btn.get_style_context().add_class("caelestia-session-btn")
        btn.set_tooltip_text(tooltip)
        btn.set_size_request(76, 76)

        lbl = Gtk.Label(label=icon_str)
        lbl.set_name("btn-icon")
        btn.add(lbl)

        btn.connect("clicked", callback)
        return btn

    def apply_css(self):
        css_provider = Gtk.CssProvider()
        theme_path = "/home/sreyas/.config/waybar/current-theme.css"

        css = f"""
        @import url('{theme_path}');

        * {{
            font-family: "Symbols Nerd Font", "JetBrains Mono", sans-serif;
            transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
        }}

        window {{
            background: transparent;
        }}

        #power-card {{
            background-color: alpha(@bg-color, 0.90);
            border: 1.5px solid alpha(@accent-purple, 0.35);
            border-radius: 28px;
            padding: 16px 12px;
            box-shadow: 0 12px 36px rgba(0, 0, 0, 0.65);
        }}

        /* Session Buttons */
        .caelestia-session-btn {{
            background-image: none;
            background-color: alpha(@fg-color, 0.08);
            border: 1px solid alpha(@fg-color, 0.08);
            border-radius: 20px;
            min-width: 76px;
            min-height: 76px;
            padding: 0;
            margin: 0;
            outline: none;
            box-shadow: none;
        }}

        .caelestia-session-btn #btn-icon {{
            font-size: 26px;
            color: @fg-color;
            transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
        }}

        /* Hover & Focus state: Material 3 radius morphing (20px -> 28px) & accent color */
        .caelestia-session-btn:hover,
        .caelestia-session-btn:focus {{
            background-color: @accent-purple;
            border-color: alpha(@accent-purple, 0.85);
            border-radius: 28px;
            box-shadow: 0 6px 20px alpha(@accent-purple, 0.55);
        }}

        .caelestia-session-btn:hover #btn-icon,
        .caelestia-session-btn:focus #btn-icon {{
            color: @bg-color;
            font-size: 28px;
        }}

        /* Active / Pressed state: compresses corner radius to 12px */
        .caelestia-session-btn:active {{
            background-color: alpha(@accent-purple, 0.80);
            border-radius: 12px;
            box-shadow: 0 2px 8px alpha(@accent-purple, 0.40);
        }}

        /* Special styling for Power Off Button */
        #session-btn-power:hover,
        #session-btn-power:focus {{
            background-color: @accent-red;
            border-color: alpha(@accent-red, 0.85);
            box-shadow: 0 6px 20px alpha(@accent-red, 0.55);
        }}

        #session-btn-power:hover #btn-icon,
        #session-btn-power:focus #btn-icon {{
            color: #ffffff;
            font-size: 28px;
        }}

        #session-btn-power:active {{
            background-color: alpha(@accent-red, 0.80);
            border-radius: 12px;
        }}

        /* Central Animated GIF Container */
        #session-gif-box {{
            background-color: alpha(@accent-purple, 0.12);
            border: 1px solid alpha(@accent-purple, 0.25);
            border-radius: 22px;
            min-width: 76px;
            min-height: 76px;
            padding: 0;
            margin: 0;
        }}

        /* Tooltips */
        tooltip {{
            background-color: alpha(@bg-color, 0.96);
            border: 1px solid alpha(@accent-purple, 0.4);
            border-radius: 10px;
            padding: 4px 8px;
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.5);
        }}

        tooltip * {{
            background-color: transparent;
            color: @fg-color;
            font-size: 11.5px;
            font-weight: 600;
        }}
        """
        css_provider.load_from_data(css.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

def main():
    global app_instance
    toggle_or_exit()
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    app = CaelestiaPowerMenu()
    app_instance = app
    signal.signal(signal.SIGUSR1, lambda *_: GLib.idle_add(app.close_animated))

    app.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
