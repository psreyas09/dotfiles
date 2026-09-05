#!/usr/bin/python3
"""
Caelestia Dashboard for Niri & Waybar
Provides:
  1. HoverTriggerWindow: Invisible layer-shell strip over center Waybar clock module that
     instantly glides the dashboard down when mouse pointer touches it.
  2. DashboardWindow: Fluid drop-down card below Waybar with 3 tabs:
     - Dashboard: User Profile, Weather, Digital Clock/Date, Monthly Calendar, Quick Meters
     - Performance: CPU Hero Card, GPU Hero Card, RAM Memory, Storage, Battery, Network
     - Workspaces: Interactive Niri workspaces & windows visualizer (click to switch/focus)
"""

import os
import sys
import time
import math
import json
import signal
import calendar
import datetime
import subprocess
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import threading
import cairo
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Gdk, GtkLayerShell, GLib, Pango, PangoCairo, GdkPixbuf

PID_FILE = "/tmp/waybar_dashboard.pid"
TAB_FILE = "/tmp/waybar_dashboard_tab"
THEME_CSS = "/home/sreyas/.config/waybar/current-theme.css"
app_instance = None

def parse_theme_colors():
    colors = {
        "accent-purple": (0.44, 0.42, 0.63, 1.0),
        "fg-color": (0.93, 0.99, 1.0, 1.0),
        "bg-color": (0.05, 0.05, 0.07, 1.0),
        "comment-color": (0.61, 0.67, 0.67, 1.0),
        "accent-red": (0.35, 0.34, 0.57, 1.0),
    }
    if os.path.exists(THEME_CSS):
        try:
            with open(THEME_CSS, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("@define-color"):
                        parts = line.replace(";", "").split()
                        if len(parts) >= 3:
                            name = parts[1]
                            hex_c = parts[2].lstrip("#")
                            if len(hex_c) == 6:
                                r = int(hex_c[0:2], 16) / 255.0
                                g = int(hex_c[2:4], 16) / 255.0
                                b = int(hex_c[4:6], 16) / 255.0
                                colors[name] = (r, g, b, 1.0)
        except Exception:
            pass
    return colors

def check_single_instance():
    req_tab = None
    if "--tab" in sys.argv:
        try:
            req_tab = int(sys.argv[sys.argv.index("--tab") + 1])
        except (ValueError, IndexError):
            pass

    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            if req_tab is not None:
                with open(TAB_FILE, "w") as f:
                    f.write(str(req_tab))
                os.kill(pid, signal.SIGUSR2)
            else:
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

class DashboardWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.app = app
        self.set_title("Caelestia Dashboard")
        self.set_resizable(False)

        # Layer Shell setup - placed on OVERLAY so it sits directly on top of client windows
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_namespace(self, "dashboard")
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        # Centered horizontally, anchored to TOP below Waybar
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, False)

        # Drop down animation parameters (Waybar height is 34px + margin)
        self.target_margin_top = 46
        self.start_margin_top = 10
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, self.start_margin_top)
        Gtk.Widget.set_opacity(self, 0.0)

        # State tracking
        self.is_open = False
        self.pinned = False
        self.anim_tick_id = None
        self.anim_direction = 0     # +1 opening, -1 closing, 0 idle
        self.anim_progress = 0.0    # 0.0 closed, 1.0 open
        self.anim_last_time = None
        self.current_tab = 0

        # Calendar state
        now = datetime.datetime.now()
        self.cal_year = now.year
        self.cal_month = now.month

        # CPU previous counters for real-time CPU delta calculation
        self.last_cpu_idle, self.last_cpu_total = self.get_cpu_times()
        self.last_cpu_time = time.time()
        self.current_cpu_pct = 0

        # Network previous counters for bandwidth calculation
        self.last_net_bytes = self.get_net_bytes()
        self.last_net_time = time.time()
        self.net_down_str = "0.0 KB/s"
        self.net_up_str = "0.0 KB/s"

        # Avatar state
        self.in_dialog = False
        self.avatar_pixbuf_60 = None
        self.avatar_pixbuf_90 = None
        self.reload_avatar_images()

        self.connect("destroy", cleanup)
        self.connect("key-press-event", self.on_key_press)
        self.connect("focus-out-event", self.on_focus_out)

        self.add_events(
            Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
            | Gdk.EventMask.KEY_PRESS_MASK
        )
        self.connect("enter-notify-event", self.on_mouse_enter)
        self.connect("leave-notify-event", self.on_mouse_leave)

        self.setup_ui()
        self.apply_css()

        # Regular refresh timer (every 1.5 seconds)
        GLib.timeout_add(1500, self.on_refresh_tick)

    def on_mouse_enter(self, widget, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        self.app.on_dashboard_enter()
        return False

    def on_mouse_leave(self, widget, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        self.app.on_dashboard_leave()
        return False

    def on_focus_out(self, widget, event):
        return False

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_animated()
            return True
        elif event.keyval in (Gdk.KEY_1, Gdk.KEY_exclam):
            self.switch_tab(0)
            return True
        elif event.keyval in (Gdk.KEY_2, Gdk.KEY_at):
            self.switch_tab(1)
            return True
        elif event.keyval in (Gdk.KEY_3, Gdk.KEY_numbersign):
            self.switch_tab(2)
            return True
        return False

    def on_pin_clicked(self, *_):
        self.pinned = not self.pinned
        self.update_pin_button_state()
        if not self.pinned:
            if not self.app.mouse_in_dashboard and not self.app.mouse_in_trigger:
                self.app.schedule_hide_check()

    def update_pin_button_state(self):
        if hasattr(self, 'btn_pin'):
            ctx = self.btn_pin.get_style_context()
            if self.pinned:
                self.btn_pin.set_label("󰤰")
                self.btn_pin.set_tooltip_text("Unpin (auto-hide on mouse leave)")
                if not ctx.has_class("pinned"):
                    ctx.add_class("pinned")
            else:
                self.btn_pin.set_label("󰤱")
                self.btn_pin.set_tooltip_text("Pin Dashboard open")
                if ctx.has_class("pinned"):
                    ctx.remove_class("pinned")

    def open_animated(self, pinned=False):
        if pinned:
            self.pinned = True
        self.update_pin_button_state()

        if self.is_open and self.anim_direction >= 0 and self.anim_progress >= 1.0:
            return

        self.is_open = True
        self.reload_avatar_images()
        self.refresh_all_data()

        if not self.get_visible() or self.anim_progress <= 0.0:
            self.anim_progress = 0.0
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, self.start_margin_top)
            Gtk.Widget.set_opacity(self, 0.0)

        self.show_all()
        self.switch_tab(self.current_tab)

        self.anim_direction = 1
        self.anim_last_time = time.time()
        if self.anim_tick_id is None:
            self.anim_tick_id = self.add_tick_callback(self.on_anim_tick)

    def close_animated(self, *_):
        if not self.is_open and self.anim_direction <= 0 and self.anim_progress <= 0.0:
            return

        self.is_open = False
        self.pinned = False
        self.update_pin_button_state()

        self.anim_direction = -1
        self.anim_last_time = time.time()
        if self.anim_tick_id is None:
            self.anim_tick_id = self.add_tick_callback(self.on_anim_tick)

    def on_anim_tick(self, widget, frame_clock):
        now = time.time()
        if self.anim_last_time is None:
            self.anim_last_time = now
        dt = max(0.0, min(0.1, now - self.anim_last_time))
        self.anim_last_time = now

        duration = 0.18 if self.anim_direction > 0 else 0.14
        delta = dt / duration if duration > 0 else 1.0

        if self.anim_direction > 0:
            self.anim_progress = min(1.0, self.anim_progress + delta)
            # Ease out cubic: 1 - (1 - p)^3
            ease = 1.0 - (1.0 - self.anim_progress) ** 3
        else:
            self.anim_progress = max(0.0, self.anim_progress - delta)
            # Ease in quadratic: p^2
            ease = self.anim_progress ** 2

        ease_clamped = max(0.0, min(1.0, ease))
        Gtk.Widget.set_opacity(self, ease_clamped)
        curr_margin = int(self.start_margin_top + (self.target_margin_top - self.start_margin_top) * ease_clamped)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, curr_margin)

        if self.anim_direction > 0 and self.anim_progress >= 1.0:
            self.anim_direction = 0
            self.anim_tick_id = None
            self.anim_last_time = None
            Gtk.Widget.set_opacity(self, 1.0)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, self.target_margin_top)
            return False

        if self.anim_direction < 0 and self.anim_progress <= 0.0:
            self.anim_direction = 0
            self.anim_tick_id = None
            self.anim_last_time = None
            self.hide()
            return False

        return True

    # --- UI Setup ---
    def setup_ui(self):
        # Outer Card
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.card.set_name("dashboard-card")
        self.add(self.card)

        # Header Bar: Tabs & Close Button
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_name("dash-header")
        self.card.pack_start(header, False, False, 0)

        # Tab Pill Container
        tabs_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        tabs_box.set_name("dash-tabs-box")
        header.pack_start(tabs_box, False, False, 0)

        self.tab_btn_dash = self.create_tab_button("󰕮  Dashboard", 0)
        self.tab_btn_perf = self.create_tab_button("󰓅  Performance", 1)
        self.tab_btn_work = self.create_tab_button("󱂬  Workspaces", 2)

        tabs_box.pack_start(self.tab_btn_dash, False, False, 0)
        tabs_box.pack_start(self.tab_btn_perf, False, False, 0)
        tabs_box.pack_start(self.tab_btn_work, False, False, 0)

        # Actions box (Pin and Close)
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.pack_end(actions_box, False, False, 0)

        # Close button
        btn_close = Gtk.Button(label="󰅖")
        btn_close.set_name("btn-dash-close")
        btn_close.set_tooltip_text("Close Dashboard (Esc)")
        btn_close.connect("clicked", self.close_animated)
        actions_box.pack_end(btn_close, False, False, 0)

        # Pin toggle button
        self.btn_pin = Gtk.Button(label="󰤱")
        self.btn_pin.set_name("btn-dash-pin")
        self.btn_pin.set_tooltip_text("Pin Dashboard open")
        self.btn_pin.connect("clicked", self.on_pin_clicked)
        actions_box.pack_end(self.btn_pin, False, False, 0)

        # Stack container for tabs
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(150)
        self.card.pack_start(self.stack, True, True, 0)

        # 1. Dashboard Tab View
        self.view_dashboard = self.build_dashboard_tab()
        self.stack.add_named(self.view_dashboard, "dash")

        # 2. Performance Tab View
        self.view_performance = self.build_performance_tab()
        self.stack.add_named(self.view_performance, "perf")

        # 3. Workspaces Tab View
        self.view_workspaces = self.build_workspaces_tab()
        self.stack.add_named(self.view_workspaces, "work")

        self.switch_tab(0)

    def create_tab_button(self, label_text, tab_idx):
        btn = Gtk.Button(label=label_text)
        btn.get_style_context().add_class("dash-tab-btn")
        btn.connect("clicked", lambda b: self.switch_tab(tab_idx))
        return btn

    def switch_tab(self, idx):
        self.current_tab = idx
        tabs = [self.tab_btn_dash, self.tab_btn_perf, self.tab_btn_work]
        for i, b in enumerate(tabs):
            if i == idx:
                b.get_style_context().add_class("dash-tab-active")
            else:
                b.get_style_context().remove_class("dash-tab-active")

        names = ["dash", "perf", "work"]
        views = [self.view_dashboard, self.view_performance, self.view_workspaces]
        for i, v in enumerate(views):
            if i == idx:
                v.show_all()
            else:
                v.hide()
        self.stack.set_visible_child_name(names[idx])
        if idx == 2:
            self.refresh_workspaces()

    # --- Tab 1: Dashboard View ---
    def build_dashboard_tab(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        root.set_name("dash-content-box")

        # Row 1: User Profile Card & Weather Card
        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        root.pack_start(row1, False, False, 0)

        # User Card
        user_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        user_card.set_name("dash-user-card")
        row1.pack_start(user_card, True, True, 0)

        # Avatar (Clickable button to open Settings app & display profile picture)
        self.avatar_btn_dash = Gtk.Button()
        self.avatar_btn_dash.set_name("dash-avatar-btn")
        self.avatar_btn_dash.set_tooltip_text("Profile Picture • Click to open Settings")
        self.avatar_btn_dash.connect("clicked", lambda *_: subprocess.Popen(["/usr/bin/python3", "/home/sreyas/.config/niri/niri-settings.py", "--page", "users"]))

        self.avatar_draw_dash = Gtk.DrawingArea()
        self.avatar_draw_dash.set_size_request(60, 60)
        self.avatar_draw_dash.connect("draw", lambda w, cr: self.draw_avatar_surface(w, cr, self.avatar_pixbuf_60, 60))
        self.avatar_btn_dash.add(self.avatar_draw_dash)
        user_card.pack_start(self.avatar_btn_dash, False, False, 0)

        # User Info Details
        user_details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        user_details.set_valign(Gtk.Align.CENTER)
        user_card.pack_start(user_details, True, True, 0)

        self.lbl_greeting = Gtk.Label(label=self.get_greeting())
        self.lbl_greeting.set_name("dash-greeting")
        self.lbl_greeting.set_xalign(0)
        user_details.pack_start(self.lbl_greeting, False, False, 0)

        user_name_str = f"@{os.getenv('USER', 'user')} • {os.uname().nodename}"
        lbl_user_name = Gtk.Label(label=user_name_str)
        lbl_user_name.set_name("dash-username")
        lbl_user_name.set_xalign(0)
        user_details.pack_start(lbl_user_name, False, False, 0)

        self.lbl_uptime = Gtk.Label(label=f"󱑂 {self.get_uptime()}")
        self.lbl_uptime.set_name("dash-uptime-chip")
        self.lbl_uptime.set_xalign(0)
        user_details.pack_start(self.lbl_uptime, False, False, 2)

        # Weather Card
        weather_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        weather_card.set_name("dash-weather-card")
        row1.pack_start(weather_card, True, True, 0)

        self.lbl_weather_icon = Gtk.Label(label="󰖙")
        self.lbl_weather_icon.set_name("dash-weather-icon")
        weather_card.pack_start(self.lbl_weather_icon, False, False, 0)

        weather_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        weather_info.set_valign(Gtk.Align.CENTER)
        weather_card.pack_start(weather_info, True, True, 0)

        self.lbl_weather_temp = Gtk.Label(label="--°C")
        self.lbl_weather_temp.set_name("dash-weather-temp")
        self.lbl_weather_temp.set_xalign(0)
        weather_info.pack_start(self.lbl_weather_temp, False, False, 0)

        self.lbl_weather_desc = Gtk.Label(label="Weather Standby")
        self.lbl_weather_desc.set_name("dash-weather-desc")
        self.lbl_weather_desc.set_xalign(0)
        weather_info.pack_start(self.lbl_weather_desc, False, False, 0)

        # Row 2: Clock & Date, Monthly Calendar, Quick Resource Meters
        row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        root.pack_start(row2, True, True, 0)

        # Big Clock & Date Card
        clock_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        clock_card.set_name("dash-clock-card")
        clock_card.set_valign(Gtk.Align.CENTER)
        row2.pack_start(clock_card, False, False, 0)

        now = datetime.datetime.now()
        self.lbl_big_time = Gtk.Label(label=now.strftime("%I:%M"))
        self.lbl_big_time.set_name("dash-big-time")
        clock_card.pack_start(self.lbl_big_time, False, False, 0)

        self.lbl_am_pm = Gtk.Label(label=now.strftime("%p"))
        self.lbl_am_pm.set_name("dash-ampm-badge")
        clock_card.pack_start(self.lbl_am_pm, False, False, 0)

        self.lbl_full_date = Gtk.Label(label=now.strftime("%A\n%B %d, %Y"))
        self.lbl_full_date.set_name("dash-full-date")
        self.lbl_full_date.set_justify(Gtk.Justification.CENTER)
        clock_card.pack_start(self.lbl_full_date, False, False, 4)

        # Monthly Calendar Card
        self.cal_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.cal_card.set_name("dash-cal-card")
        row2.pack_start(self.cal_card, True, True, 0)

        cal_nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.cal_card.pack_start(cal_nav, False, False, 0)

        btn_prev_month = Gtk.Button(label="")
        btn_prev_month.get_style_context().add_class("cal-nav-btn")
        btn_prev_month.connect("clicked", self.on_cal_prev)
        cal_nav.pack_start(btn_prev_month, False, False, 0)

        self.lbl_cal_month = Gtk.Label(label=now.strftime("%B %Y"))
        self.lbl_cal_month.set_name("cal-month-title")
        cal_nav.pack_start(self.lbl_cal_month, True, True, 0)

        btn_next_month = Gtk.Button(label="")
        btn_next_month.get_style_context().add_class("cal-nav-btn")
        btn_next_month.connect("clicked", self.on_cal_next)
        cal_nav.pack_end(btn_next_month, False, False, 0)

        # Calendar Grid
        self.cal_grid_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.cal_card.pack_start(self.cal_grid_box, True, True, 0)
        self.rebuild_calendar_grid()

        # Quick System Resource Rings Card
        res_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        res_card.set_name("dash-res-card")
        row2.pack_start(res_card, False, False, 0)

        self.res_cpu = self.create_resource_gauge("󰻠", "CPU", "0%")
        self.res_ram = self.create_resource_gauge("󰍛", "RAM", "0%")
        self.res_disk = self.create_resource_gauge("󰋊", "Disk", "0%")

        res_card.pack_start(self.res_cpu[0], False, False, 0)
        res_card.pack_start(self.res_ram[0], False, False, 0)
        res_card.pack_start(self.res_disk[0], False, False, 0)

        return root

    def create_resource_gauge(self, icon, label, val_text):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        box.set_name("res-gauge-box")

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl_i = Gtk.Label(label=f"{icon} {label}")
        lbl_i.set_name("res-label")
        top_row.pack_start(lbl_i, False, False, 0)

        lbl_v = Gtk.Label(label=val_text)
        lbl_v.set_name("res-value")
        top_row.pack_end(lbl_v, False, False, 0)
        box.pack_start(top_row, False, False, 0)

        prog = Gtk.ProgressBar()
        prog.get_style_context().add_class("res-prog-bar")
        prog.set_fraction(0.0)
        box.pack_start(prog, False, False, 0)

        return box, lbl_v, prog

    def rebuild_calendar_grid(self):
        for child in self.cal_grid_box.get_children():
            self.cal_grid_box.remove(child)

        grid = Gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(6)
        grid.set_halign(Gtk.Align.CENTER)
        self.cal_grid_box.pack_start(grid, True, True, 0)

        days = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        for col, d in enumerate(days):
            lbl = Gtk.Label(label=d)
            lbl.get_style_context().add_class("cal-header-day")
            grid.attach(lbl, col, 0, 1, 1)

        cal = calendar.monthcalendar(self.cal_year, self.cal_month)
        today = datetime.datetime.now()

        for row, week in enumerate(cal):
            for col, day in enumerate(week):
                if day == 0:
                    lbl = Gtk.Label(label="")
                else:
                    lbl = Gtk.Label(label=str(day))
                    if day == today.day and self.cal_month == today.month and self.cal_year == today.year:
                        lbl.get_style_context().add_class("cal-today-cell")
                    else:
                        lbl.get_style_context().add_class("cal-day-cell")
                grid.attach(lbl, col, row + 1, 1, 1)

        grid.show_all()

    def on_cal_prev(self, btn):
        if self.cal_month == 1:
            self.cal_month = 12
            self.cal_year -= 1
        else:
            self.cal_month -= 1
        dt = datetime.datetime(self.cal_year, self.cal_month, 1)
        self.lbl_cal_month.set_text(dt.strftime("%B %Y"))
        self.rebuild_calendar_grid()

    def on_cal_next(self, btn):
        if self.cal_month == 12:
            self.cal_month = 1
            self.cal_year += 1
        else:
            self.cal_month += 1
        dt = datetime.datetime(self.cal_year, self.cal_month, 1)
        self.lbl_cal_month.set_text(dt.strftime("%B %Y"))
        self.rebuild_calendar_grid()

    # --- Tab 2: Performance View ---
    def build_performance_tab(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        root.set_name("perf-content-box")

        # Row 1: CPU Hero Card & GPU Hero Card
        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        root.pack_start(row1, False, False, 0)

        # CPU Card
        self.perf_cpu_card = self.create_hero_card("󰻠", "CPU", "AMD Ryzen 5", "0%", "0.0°C")
        row1.pack_start(self.perf_cpu_card[0], True, True, 0)

        # GPU Card
        self.perf_gpu_card = self.create_hero_card("󰢮", "GPU", "NVIDIA GTX 1650", "0%", "0.0°C")
        row1.pack_start(self.perf_gpu_card[0], True, True, 0)

        # Row 2: Memory, Storage, Battery
        row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        root.pack_start(row2, True, True, 0)

        # Memory Card
        self.perf_mem_box = self.create_metric_card("󰍛", "RAM Memory", "0.0 GB / 0.0 GB", "0%")
        row2.pack_start(self.perf_mem_box[0], True, True, 0)

        # Storage Card
        self.perf_disk_box = self.create_metric_card("󰋊", "Root Storage (/)", "0.0 GB / 0.0 GB", "0%")
        row2.pack_start(self.perf_disk_box[0], True, True, 0)

        # Battery Card
        self.perf_bat_box = self.create_metric_card("󰂀", "Battery (BAT0)", "--% • Status", "0%")
        row2.pack_start(self.perf_bat_box[0], True, True, 0)

        # Row 3: Network Activity Card
        row3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        root.pack_start(row3, False, False, 0)

        net_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        net_card.set_name("perf-subcard")
        row3.pack_start(net_card, True, True, 0)

        net_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl_net_i = Gtk.Label(label="󰖩")
        lbl_net_i.set_name("perf-card-icon")
        lbl_net_t = Gtk.Label(label="Network Traffic")
        lbl_net_t.set_name("perf-card-title")
        net_header.pack_start(lbl_net_i, False, False, 0)
        net_header.pack_start(lbl_net_t, False, False, 0)
        net_card.pack_start(net_header, False, False, 0)

        net_stats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        net_stats.set_halign(Gtk.Align.END)
        self.lbl_net_down = Gtk.Label(label="↓ 0.0 KB/s")
        self.lbl_net_down.set_name("perf-net-down")
        self.lbl_net_up = Gtk.Label(label="↑ 0.0 KB/s")
        self.lbl_net_up.set_name("perf-net-up")
        net_stats.pack_start(self.lbl_net_down, False, False, 0)
        net_stats.pack_start(self.lbl_net_up, False, False, 0)
        net_card.pack_end(net_stats, True, True, 0)

        return root

    def create_hero_card(self, icon, title, subtitle, val_text, temp_text):
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        card.set_name("perf-hero-card")

        left_icon = Gtk.Label(label=icon)
        left_icon.set_name("perf-hero-icon")
        card.pack_start(left_icon, False, False, 0)

        mid_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        mid_box.set_valign(Gtk.Align.CENTER)
        lbl_t = Gtk.Label(label=title)
        lbl_t.set_name("perf-hero-title")
        lbl_t.set_xalign(0)

        lbl_sub = Gtk.Label(label=subtitle)
        lbl_sub.set_name("perf-hero-sub")
        lbl_sub.set_xalign(0)
        lbl_sub.set_ellipsize(Pango.EllipsizeMode.END)
        lbl_sub.set_max_width_chars(26)

        mid_box.pack_start(lbl_t, False, False, 0)
        mid_box.pack_start(lbl_sub, False, False, 0)
        card.pack_start(mid_box, True, True, 0)

        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        right_box.set_valign(Gtk.Align.CENTER)

        lbl_v = Gtk.Label(label=val_text)
        lbl_v.set_name("perf-hero-val")
        lbl_v.set_xalign(1)

        lbl_tmp = Gtk.Label(label=temp_text)
        lbl_tmp.set_name("perf-hero-temp")
        lbl_tmp.set_xalign(1)

        right_box.pack_start(lbl_v, False, False, 0)
        right_box.pack_start(lbl_tmp, False, False, 0)
        card.pack_end(right_box, False, False, 0)

        return card, lbl_sub, lbl_v, lbl_tmp

    def create_metric_card(self, icon, title, details_text, pct_text):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.set_name("perf-subcard")

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl_i = Gtk.Label(label=icon)
        lbl_i.set_name("perf-card-icon")
        lbl_t = Gtk.Label(label=title)
        lbl_t.set_name("perf-card-title")
        head.pack_start(lbl_i, False, False, 0)
        head.pack_start(lbl_t, False, False, 0)
        card.pack_start(head, False, False, 0)

        mid_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl_d = Gtk.Label(label=details_text)
        lbl_d.set_name("perf-card-details")
        lbl_d.set_xalign(0)

        lbl_p = Gtk.Label(label=pct_text)
        lbl_p.set_name("perf-card-pct")
        lbl_p.set_xalign(1)

        mid_row.pack_start(lbl_d, True, True, 0)
        mid_row.pack_end(lbl_p, False, False, 0)
        card.pack_start(mid_row, False, False, 0)

        prog = Gtk.ProgressBar()
        prog.get_style_context().add_class("perf-prog-bar")
        prog.set_fraction(0.0)
        card.pack_start(prog, False, False, 0)

        return card, lbl_d, lbl_p, prog

    # --- Tab 3: Workspaces View ---
    def build_workspaces_tab(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        root.set_name("work-content-box")

        # Top Control Bar
        ctrl_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        root.pack_start(ctrl_bar, False, False, 0)

        lbl_info = Gtk.Label(label="󱂬  Niri Workspaces & Active Windows")
        lbl_info.set_name("work-header-title")
        ctrl_bar.pack_start(lbl_info, False, False, 0)

        btn_prev_ws = Gtk.Button(label=" Prev Workspace")
        btn_prev_ws.get_style_context().add_class("work-step-btn")
        btn_prev_ws.connect("clicked", lambda b: self.action_workspace_step("up"))

        btn_next_ws = Gtk.Button(label="Next Workspace ")
        btn_next_ws.get_style_context().add_class("work-step-btn")
        btn_next_ws.connect("clicked", lambda b: self.action_workspace_step("down"))

        ctrl_bar.pack_end(btn_next_ws, False, False, 0)
        ctrl_bar.pack_end(btn_prev_ws, False, False, 0)

        # Workspaces Container
        self.workspaces_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.workspaces_container.set_name("workspaces-container")
        root.pack_start(self.workspaces_container, True, True, 0)

        return root

    def refresh_workspaces(self):
        for child in self.workspaces_container.get_children():
            self.workspaces_container.remove(child)

        try:
            ws_out = subprocess.check_output(["niri", "msg", "-j", "workspaces"], text=True)
            workspaces = json.loads(ws_out)
        except Exception:
            workspaces = []

        try:
            win_out = subprocess.check_output(["niri", "msg", "-j", "windows"], text=True)
            windows = json.loads(win_out)
        except Exception:
            windows = []

        if not workspaces:
            lbl = Gtk.Label(label="No Workspaces Available")
            lbl.get_style_context().add_class("work-empty-lbl")
            self.workspaces_container.pack_start(lbl, True, True, 0)
            self.workspaces_container.show_all()
            return

        # Sort workspaces by idx
        workspaces.sort(key=lambda w: w.get("idx", 0))

        for ws in workspaces:
            ws_id = ws.get("id")
            ws_idx = ws.get("idx")
            is_active = ws.get("is_active", False)

            # Workspace Card Button
            ws_btn = Gtk.Button()
            ws_btn.get_style_context().add_class("workspace-card-btn")
            if is_active:
                ws_btn.get_style_context().add_class("workspace-card-active")

            ws_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            ws_card.set_size_request(145, 230)

            # Workspace Header
            ws_head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            lbl_ws_num = Gtk.Label(label=f"Workspace {ws_idx}")
            lbl_ws_num.get_style_context().add_class("ws-num-label")
            ws_head.pack_start(lbl_ws_num, True, True, 0)

            if is_active:
                lbl_badge = Gtk.Label(label="● Active")
                lbl_badge.get_style_context().add_class("ws-active-badge")
                ws_head.pack_end(lbl_badge, False, False, 0)

            ws_card.pack_start(ws_head, False, False, 0)

            # Separator
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.get_style_context().add_class("ws-sep")
            ws_card.pack_start(sep, False, False, 0)

            # Windows in this workspace
            ws_wins = [w for w in windows if w.get("workspace_id") == ws_id]
            win_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

            if not ws_wins:
                lbl_empty = Gtk.Label(label="Empty")
                lbl_empty.get_style_context().add_class("ws-empty-text")
                win_list.pack_start(lbl_empty, True, True, 0)
            else:
                for win in ws_wins:
                    win_id = win.get("id")
                    app_id = (win.get("app_id") or "app").lower()
                    title = win.get("title") or "Window"
                    is_focused = win.get("is_focused", False)

                    icon = "󰈹" if "zen" in app_id or "firefox" in app_id else "" if "kitty" in app_id else "󰝚" if "tauon" in app_id else "󰗃" if "rambox" in app_id else "󰣆"
                    app_clean = "Zen" if "zen" in app_id else "Terminal" if "kitty" in app_id else "Tauon" if "tauon" in app_id else "Rambox" if "rambox" in app_id else app_id[:9]

                    # Interactive Window Button inside Workspace
                    w_item = Gtk.Button()
                    w_item.get_style_context().add_class("ws-win-btn")
                    if is_focused:
                        w_item.get_style_context().add_class("ws-win-focused")

                    w_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                    lbl_icon = Gtk.Label(label=icon)
                    lbl_icon.get_style_context().add_class("ws-win-icon")
                    w_box.pack_start(lbl_icon, False, False, 0)

                    lbl_title = Gtk.Label(label=app_clean)
                    lbl_title.get_style_context().add_class("ws-win-title")
                    lbl_title.set_xalign(0)
                    w_box.pack_start(lbl_title, True, True, 0)

                    w_item.add(w_box)
                    w_item.connect("clicked", lambda b, wid=win_id: self.action_focus_window(wid))
                    win_list.pack_start(w_item, False, False, 0)

            ws_card.pack_start(win_list, True, True, 0)
            ws_btn.add(ws_card)

            ws_btn.connect("clicked", lambda b, idx=ws_idx: self.action_focus_workspace(idx))
            self.workspaces_container.pack_start(ws_btn, True, True, 0)

        self.workspaces_container.show_all()

    def action_focus_workspace(self, ws_idx):
        try:
            subprocess.run(["niri", "msg", "action", "focus-workspace", str(ws_idx)])
        except Exception:
            pass
        self.close_animated()

    def action_focus_window(self, win_id):
        try:
            subprocess.run(["niri", "msg", "action", "focus-window", "--id", str(win_id)])
        except Exception:
            pass
        self.close_animated()

    def action_workspace_step(self, direction):
        action = "focus-workspace-down" if direction == "down" else "focus-workspace-up"
        try:
            subprocess.run(["niri", "msg", "action", action])
        except Exception:
            pass
        self.refresh_workspaces()

    # --- Tab 4: Settings View & Profile Picture Management ---
    def get_current_avatar_path(self):
        paths = [
            os.path.expanduser("~/.config/waybar/avatar.png"),
            os.path.expanduser("~/.face"),
            os.path.expanduser("~/.face.icon"),
            f"/var/lib/AccountsService/icons/{os.getenv('USER', 'sreyas')}"
        ]
        for p in paths:
            if os.path.exists(p) and os.path.isfile(p):
                return p
        return None

    def get_avatar_pixbuf(self, size):
        path = self.get_current_avatar_path()
        if not path:
            return None
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file(path)
            pw, ph = pb.get_width(), pb.get_height()
            if pw <= 0 or ph <= 0:
                return None
            scale = max(size / float(pw), size / float(ph))
            nw = max(1, int(round(pw * scale)))
            nh = max(1, int(round(ph * scale)))
            scaled = pb.scale_simple(nw, nh, GdkPixbuf.InterpType.BILINEAR)
            src_x = max(0, (nw - size) // 2)
            src_y = max(0, (nh - size) // 2)
            cropped = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, size, size)
            scaled.copy_area(src_x, src_y, size, size, cropped, 0, 0)
            return cropped
        except Exception as e:
            print("Error loading avatar pixbuf:", e, file=sys.stderr)
            return None

    def reload_avatar_images(self):
        self.avatar_pixbuf_60 = self.get_avatar_pixbuf(60)
        if hasattr(self, "avatar_draw_dash") and self.avatar_draw_dash:
            self.avatar_draw_dash.queue_draw()

    def draw_avatar_surface(self, widget, cr, pixbuf, size):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        if w <= 0 or h <= 0:
            return False

        cx = w / 2.0
        cy = h / 2.0
        radius = min(w, h) / 2.0 - 2.0

        colors = parse_theme_colors()
        accent = colors.get("accent-purple", (0.44, 0.42, 0.63, 1.0))

        cr.save()
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.clip()

        if pixbuf:
            pw = pixbuf.get_width()
            ph = pixbuf.get_height()
            Gdk.cairo_set_source_pixbuf(cr, pixbuf, cx - pw / 2.0, cy - ph / 2.0)
            cr.paint()
        else:
            # Fallback stylish avatar background
            cr.set_source_rgba(accent[0] * 0.35, accent[1] * 0.35, accent[2] * 0.35, 0.85)
            cr.paint()
            # Draw fallback icon ''
            layout = widget.create_pango_layout("")
            font_size = max(10, int(size * 0.40))
            desc = Pango.FontDescription(f"Symbols Nerd Font {font_size}")
            layout.set_font_description(desc)
            _, logical = layout.get_pixel_extents()
            cr.set_source_rgba(accent[0], accent[1], accent[2], 0.95)
            cr.move_to(cx - logical.width / 2.0, cy - logical.height / 2.0)
            PangoCairo.show_layout(cr, layout)

        cr.restore()

        # Draw outer ring with theme accent
        cr.set_source_rgba(accent[0], accent[1], accent[2], 0.9)
        cr.set_line_width(2.0)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()
        return False

    # --- Data Fetching & Periodic Refresh ---
    def get_greeting(self):
        h = datetime.datetime.now().hour
        if 5 <= h < 12:
            return "Good Morning"
        elif 12 <= h < 17:
            return "Good Afternoon"
        elif 17 <= h < 22:
            return "Good Evening"
        else:
            return "Good Night"

    def get_uptime(self):
        try:
            with open("/proc/uptime") as f:
                secs = float(f.read().split()[0])
            hrs = int(secs // 3600)
            mins = int((secs % 3600) // 60)
            return f"up {hrs}h {mins}m"
        except Exception:
            return "up system"

    def get_cpu_times(self):
        try:
            with open("/proc/stat") as f:
                line = f.readline()
            flds = [float(x) for x in line.split()[1:8]]
            idle = flds[3] + flds[4]  # idle + iowait
            total = sum(flds)
            return idle, total
        except Exception:
            return 0.0, 0.0

    def update_cpu_stats(self):
        now = time.time()
        if not hasattr(self, "last_cpu_time"):
            self.last_cpu_idle, self.last_cpu_total = self.get_cpu_times()
            self.last_cpu_time = now
            self.current_cpu_pct = 0
            return 0

        dt = now - self.last_cpu_time
        if dt < 0.8:
            return self.current_cpu_pct

        cur_idle, cur_total = self.get_cpu_times()
        diff_idle = cur_idle - self.last_cpu_idle
        diff_total = cur_total - self.last_cpu_total
        if diff_total > 0:
            pct = int(round(((diff_total - diff_idle) / diff_total) * 100.0))
            self.current_cpu_pct = max(0, min(100, pct))
            self.last_cpu_idle = cur_idle
            self.last_cpu_total = cur_total
            self.last_cpu_time = now
        return self.current_cpu_pct

    def get_net_bytes(self):
        total_in, total_out = 0, 0
        try:
            with open("/proc/net/dev") as f:
                for line in f.readlines()[2:]:
                    parts = line.split(":")
                    if len(parts) == 2 and parts[0].strip() != "lo":
                        stats = parts[1].split()
                        total_in += int(stats[0])
                        total_out += int(stats[8])
        except Exception:
            pass
        return total_in, total_out

    def update_network_rates(self):
        now = time.time()
        dt = now - self.last_net_time
        if dt < 0.8:
            return
        curr_in, curr_out = self.get_net_bytes()
        d_in = (curr_in - self.last_net_bytes[0]) / dt
        d_out = (curr_out - self.last_net_bytes[1]) / dt
        self.last_net_bytes = (curr_in, curr_out)
        self.last_net_time = now

        def fmt(b):
            if b >= 1024 * 1024:
                return f"{b / (1024*1024):.1f} MB/s"
            else:
                return f"{b / 1024:.1f} KB/s"

        self.net_down_str = fmt(d_in)
        self.net_up_str = fmt(d_out)
        if hasattr(self, "lbl_net_down"):
            self.lbl_net_down.set_text(f"↓ {self.net_down_str}")
            self.lbl_net_up.set_text(f"↑ {self.net_up_str}")

    def refresh_weather(self):
        now = time.time()
        if hasattr(self, "_last_weather_time") and (now - self._last_weather_time < 300):
            return
        self._last_weather_time = now

        def fetch():
            try:
                out = subprocess.check_output(["/home/sreyas/.config/waybar/weather.sh"], text=True, timeout=3)
                data = json.loads(out)
                text = data.get("text", "")
                parts = text.split(maxsplit=1)
                icon = parts[0] if parts else "󰖙"
                temp = parts[1] if len(parts) > 1 else ""
                desc = data.get("tooltip", "").replace("Current Weather:", "").strip()

                def update_ui():
                    if hasattr(self, "lbl_weather_icon"):
                        self.lbl_weather_icon.set_text(icon)
                        self.lbl_weather_temp.set_text(temp or "28°C")
                        self.lbl_weather_desc.set_text(desc or "Partly Cloudy")
                    return False
                GLib.idle_add(update_ui)
            except Exception:
                pass

        threading.Thread(target=fetch, daemon=True).start()

    def refresh_all_data(self):
        # Update clock
        now = datetime.datetime.now()
        self.lbl_big_time.set_text(now.strftime("%I:%M"))
        self.lbl_am_pm.set_text(now.strftime("%p"))
        self.lbl_full_date.set_text(now.strftime("%A\n%B %d, %Y"))
        self.lbl_greeting.set_text(self.get_greeting())
        self.lbl_uptime.set_text(f"󱑂 {self.get_uptime()}")

        # Weather (async)
        self.refresh_weather()

        # CPU info (real-time delta matching Waybar and btop)
        cpu_pct = self.update_cpu_stats()

        cpu_model = "AMD Ryzen 5"
        try:
            with open("/proc/cpuinfo") as f:
                for l in f:
                    if "model name" in l:
                        cpu_model = l.split(":", 1)[1].strip()
                        break
        except Exception:
            pass

        cpu_temp = "48.0°C"
        try:
            import glob
            t_files = glob.glob("/sys/class/hwmon/hwmon*/temp*_input")
            if t_files:
                with open(t_files[0]) as f:
                    val = float(f.read().strip()) / 1000.0
                    cpu_temp = f"{val:.1f}°C"
        except Exception:
            pass

        # Update Quick Meters & CPU Hero card
        self.res_cpu[1].set_text(f"{cpu_pct}%")
        self.res_cpu[2].set_fraction(cpu_pct / 100.0)

        self.perf_cpu_card[1].set_text(cpu_model)
        self.perf_cpu_card[2].set_text(f"{cpu_pct}%")
        self.perf_cpu_card[3].set_text(cpu_temp)

        # RAM info
        try:
            with open("/proc/meminfo") as f:
                mem = {}
                for l in f:
                    p = l.split(":")
                    if len(p) == 2:
                        mem[p[0].strip()] = p[1].strip()
            total_r = int(mem.get("MemTotal", "0 kB").split()[0]) / 1024 / 1024
            avail_r = int(mem.get("MemAvailable", "0 kB").split()[0]) / 1024 / 1024
            used_r = total_r - avail_r
            r_pct = int((used_r / (total_r or 1)) * 100)

            self.res_ram[1].set_text(f"{r_pct}%")
            self.res_ram[2].set_fraction(r_pct / 100.0)

            self.perf_mem_box[1].set_text(f"{used_r:.1f} GB / {total_r:.1f} GB")
            self.perf_mem_box[2].set_text(f"{r_pct}%")
            self.perf_mem_box[3].set_fraction(r_pct / 100.0)
        except Exception:
            pass

        # Disk info
        try:
            st = os.statvfs("/")
            tot_d = (st.f_blocks * st.f_frsize) / (1024**3)
            free_d = (st.f_bavail * st.f_frsize) / (1024**3)
            used_d = tot_d - free_d
            d_pct = int((used_d / (tot_d or 1)) * 100)

            self.res_disk[1].set_text(f"{d_pct}%")
            self.res_disk[2].set_fraction(d_pct / 100.0)

            self.perf_disk_box[1].set_text(f"{used_d:.1f} GB / {tot_d:.1f} GB")
            self.perf_disk_box[2].set_text(f"{d_pct}%")
            self.perf_disk_box[3].set_fraction(d_pct / 100.0)
        except Exception:
            pass

        # GPU info (via background worker to prevent UI lag)
        now_gpu = time.time()
        if not hasattr(self, "_last_gpu_time") or (now_gpu - self._last_gpu_time >= 2.0):
            self._last_gpu_time = now_gpu
            def fetch_gpu():
                gpu_name = "NVIDIA GeForce GTX 1650"
                gpu_temp = "48.0°C"
                gpu_usage = "Active"
                try:
                    smi_out = subprocess.check_output(
                        ["nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu", "--format=csv,noheader,nounits"],
                        text=True, timeout=1
                    )
                    parts = [p.strip() for p in smi_out.strip().split(",")]
                    if len(parts) >= 3:
                        gpu_name = parts[0]
                        gpu_temp = f"{parts[1]}.0°C"
                        gpu_usage = f"{parts[2]}%"
                except Exception:
                    pass

                def update_gpu_ui():
                    if hasattr(self, "perf_gpu_card"):
                        self.perf_gpu_card[1].set_text(gpu_name)
                        self.perf_gpu_card[2].set_text(gpu_usage)
                        self.perf_gpu_card[3].set_text(gpu_temp)
                    return False
                GLib.idle_add(update_gpu_ui)

            threading.Thread(target=fetch_gpu, daemon=True).start()

        # Battery info
        try:
            with open("/sys/class/power_supply/BAT0/capacity") as f:
                bat_cap = int(f.read().strip())
            with open("/sys/class/power_supply/BAT0/status") as f:
                bat_stat = f.read().strip()
            self.perf_bat_box[1].set_text(f"{bat_cap}% • {bat_stat}")
            self.perf_bat_box[2].set_text(f"{bat_cap}%")
            self.perf_bat_box[3].set_fraction(bat_cap / 100.0)
        except Exception:
            pass

        # Network rates
        self.update_network_rates()

    def on_refresh_tick(self):
        if self.is_open:
            self.refresh_all_data()
        else:
            self.update_cpu_stats()
            self.update_network_rates()
        return True

    def apply_css(self):
        css_provider = Gtk.CssProvider()
        css = f"""
        @import url('{THEME_CSS}');

        * {{
            font-family: "Google Sans Flex", "Rubik", "Symbols Nerd Font", "JetBrains Mono", sans-serif;
            transition: all 0.20s cubic-bezier(0.16, 1, 0.3, 1);
        }}

        window {{
            background: transparent;
        }}

        #hover-trigger-win {{
            background-color: rgba(0, 0, 0, 0.001);
        }}

        #dashboard-card {{
            background-color: alpha(@bg-color, 0.94);
            border: 1.5px solid alpha(@accent-purple, 0.35);
            border-radius: 26px;
            padding: 16px 20px 20px 20px;
            min-width: 820px;
            box-shadow: 0 16px 48px rgba(0, 0, 0, 0.75);
        }}

        /* Header Tabs */
        #dash-tabs-box {{
            background-color: alpha(@accent-purple, 0.10);
            border: 1px solid alpha(@accent-purple, 0.22);
            border-radius: 9999px;
            padding: 2px 4px;
        }}

        .dash-tab-btn {{
            background-image: none;
            background-color: transparent;
            border: none;
            border-radius: 9999px;
            padding: 5px 16px;
            color: @comment-color;
            font-size: 13px;
            font-weight: 600;
            outline: none;
        }}

        .dash-tab-btn:hover {{
            background-color: alpha(@accent-purple, 0.18);
            color: @fg-color;
        }}

        .dash-tab-active {{
            background-color: @accent-purple;
            color: @bg-color;
            box-shadow: 0 2px 10px alpha(@accent-purple, 0.5);
        }}

        #btn-dash-close {{
            background-image: none;
            background-color: transparent;
            border: none;
            color: @comment-color;
            font-size: 14px;
            border-radius: 9999px;
            min-width: 28px;
            min-height: 28px;
            padding: 2px 6px;
        }}

        #btn-dash-close:hover {{
            background-color: alpha(@accent-red, 0.6);
            color: #ffffff;
        }}

        #btn-dash-pin {{
            background-image: none;
            background-color: transparent;
            border: none;
            color: @comment-color;
            font-size: 14px;
            border-radius: 9999px;
            min-width: 28px;
            min-height: 28px;
            padding: 2px 6px;
        }}

        #btn-dash-pin:hover {{
            background-color: alpha(@accent-purple, 0.25);
            color: @accent-purple;
        }}

        #btn-dash-pin.pinned {{
            background-color: alpha(@accent-purple, 0.35);
            color: @accent-purple;
        }}

        /* User Card */
        #dash-user-card {{
            background-color: alpha(@fg-color, 0.05);
            border: 1px solid alpha(@fg-color, 0.08);
            border-radius: 20px;
            padding: 12px 16px;
        }}

        #dash-avatar-box {{
            background-color: alpha(@accent-purple, 0.25);
            border: 1.5px solid @accent-purple;
            border-radius: 9999px;
        }}

        #dash-avatar-icon {{
            font-size: 26px;
            color: @accent-purple;
        }}

        #dash-greeting {{
            font-size: 16px;
            font-weight: 700;
            color: @fg-color;
        }}

        #dash-username {{
            font-size: 12px;
            color: @comment-color;
        }}

        #dash-uptime-chip {{
            font-size: 11px;
            font-weight: 600;
            color: @accent-purple;
        }}

        /* Weather Card */
        #dash-weather-card {{
            background-color: alpha(@fg-color, 0.05);
            border: 1px solid alpha(@fg-color, 0.08);
            border-radius: 20px;
            padding: 12px 16px;
        }}

        #dash-weather-icon {{
            font-size: 38px;
            color: @accent-purple;
        }}

        #dash-weather-temp {{
            font-size: 24px;
            font-weight: 700;
            color: @fg-color;
        }}

        #dash-weather-desc {{
            font-size: 12px;
            color: @comment-color;
        }}

        /* Clock Card */
        #dash-clock-card {{
            background-color: alpha(@fg-color, 0.05);
            border: 1px solid alpha(@fg-color, 0.08);
            border-radius: 20px;
            padding: 16px 20px;
            min-width: 155px;
        }}

        #dash-big-time {{
            font-size: 36px;
            font-weight: 800;
            color: @fg-color;
            letter-spacing: -1px;
        }}

        #dash-ampm-badge {{
            font-size: 12px;
            font-weight: 700;
            color: @accent-purple;
            letter-spacing: 1px;
        }}

        #dash-full-date {{
            font-size: 12px;
            font-weight: 600;
            color: @comment-color;
        }}

        /* Calendar Card */
        #dash-cal-card {{
            background-color: alpha(@fg-color, 0.05);
            border: 1px solid alpha(@fg-color, 0.08);
            border-radius: 20px;
            padding: 12px 16px;
        }}

        #cal-month-title {{
            font-size: 14px;
            font-weight: 700;
            color: @fg-color;
        }}

        .cal-nav-btn {{
            background-image: none;
            background-color: transparent;
            border: none;
            border-radius: 9999px;
            color: @accent-purple;
            min-width: 22px;
            min-height: 22px;
            padding: 1px 6px;
        }}

        .cal-nav-btn:hover {{
            background-color: alpha(@accent-purple, 0.2);
        }}

        .cal-header-day {{
            font-size: 11px;
            font-weight: 700;
            color: @comment-color;
            padding: 2px 4px;
        }}

        .cal-day-cell {{
            font-size: 12px;
            font-weight: 500;
            color: @fg-color;
            padding: 2px 5px;
        }}

        .cal-today-cell {{
            font-size: 12px;
            font-weight: 800;
            background-color: @accent-purple;
            color: @bg-color;
            border-radius: 9999px;
            padding: 2px 5px;
        }}

        /* Resource Meters */
        #dash-res-card {{
            background-color: alpha(@fg-color, 0.05);
            border: 1px solid alpha(@fg-color, 0.08);
            border-radius: 20px;
            padding: 14px 16px;
            min-width: 150px;
        }}

        #res-label {{
            font-size: 11.5px;
            font-weight: 600;
            color: @comment-color;
        }}

        #res-value {{
            font-size: 12px;
            font-weight: 700;
            color: @fg-color;
        }}

        .res-prog-bar trough {{
            background-color: alpha(@fg-color, 0.08);
            border-radius: 6px;
            min-height: 6px;
        }}

        .res-prog-bar progress {{
            background-color: @accent-purple;
            border-radius: 6px;
        }}

        /* Performance Hero Cards */
        #perf-hero-card {{
            background-color: alpha(@fg-color, 0.05);
            border: 1px solid alpha(@fg-color, 0.08);
            border-radius: 20px;
            padding: 16px 20px;
        }}

        #perf-hero-icon {{
            font-size: 32px;
            color: @accent-purple;
        }}

        #perf-hero-title {{
            font-size: 15px;
            font-weight: 700;
            color: @fg-color;
        }}

        #perf-hero-sub {{
            font-size: 11.5px;
            color: @comment-color;
        }}

        #perf-hero-val {{
            font-size: 22px;
            font-weight: 800;
            color: @accent-purple;
        }}

        #perf-hero-temp {{
            font-size: 12px;
            font-weight: 600;
            color: @comment-color;
        }}

        #perf-subcard {{
            background-color: alpha(@fg-color, 0.05);
            border: 1px solid alpha(@fg-color, 0.08);
            border-radius: 20px;
            padding: 14px 16px;
        }}

        #perf-card-icon {{
            font-size: 18px;
            color: @accent-purple;
        }}

        #perf-card-title {{
            font-size: 13.5px;
            font-weight: 700;
            color: @fg-color;
        }}

        #perf-card-details {{
            font-size: 11.5px;
            color: @comment-color;
        }}

        #perf-card-pct {{
            font-size: 12px;
            font-weight: 700;
            color: @accent-purple;
        }}

        .perf-prog-bar trough {{
            background-color: alpha(@fg-color, 0.08);
            border-radius: 6px;
            min-height: 6px;
        }}

        .perf-prog-bar progress {{
            background-color: @accent-purple;
            border-radius: 6px;
        }}

        #perf-net-down {{
            font-size: 13px;
            font-weight: 700;
            color: @accent-cyan;
        }}

        #perf-net-up {{
            font-size: 13px;
            font-weight: 700;
            color: @accent-purple;
        }}

        /* Workspaces Tab */
        #work-header-title {{
            font-size: 14px;
            font-weight: 700;
            color: @fg-color;
        }}

        .work-step-btn {{
            background-image: none;
            background-color: alpha(@accent-purple, 0.15);
            border: 1px solid alpha(@accent-purple, 0.3);
            border-radius: 9999px;
            padding: 3px 10px;
            color: @accent-purple;
            font-size: 11.5px;
            font-weight: 600;
        }}

        .work-step-btn:hover {{
            background-color: alpha(@accent-purple, 0.3);
            color: @fg-color;
        }}

        .workspace-card-btn {{
            background-image: none;
            background-color: alpha(@fg-color, 0.04);
            border: 1px solid alpha(@fg-color, 0.08);
            border-radius: 16px;
            padding: 10px 10px;
            outline: none;
        }}

        .workspace-card-btn:hover {{
            background-color: alpha(@accent-purple, 0.12);
            border-color: alpha(@accent-purple, 0.4);
        }}

        .workspace-card-active {{
            background-color: alpha(@accent-purple, 0.16);
            border: 1.5px solid @accent-purple;
            box-shadow: 0 4px 16px alpha(@accent-purple, 0.35);
        }}

        .ws-num-label {{
            font-size: 12px;
            font-weight: 700;
            color: @fg-color;
        }}

        .ws-active-badge {{
            font-size: 10px;
            font-weight: 700;
            color: @accent-purple;
        }}

        .ws-sep {{
            background-color: alpha(@fg-color, 0.08);
            min-height: 1px;
        }}

        .ws-empty-text {{
            font-size: 11px;
            color: @comment-color;
        }}

        .ws-win-btn {{
            background-image: none;
            background-color: alpha(@fg-color, 0.04);
            border: 1px solid transparent;
            border-radius: 8px;
            padding: 4px 6px;
            outline: none;
        }}

        .ws-win-btn:hover {{
            background-color: alpha(@accent-purple, 0.2);
            border-color: alpha(@accent-purple, 0.35);
        }}

        .ws-win-focused {{
            background-color: alpha(@accent-purple, 0.28);
            border: 1px solid alpha(@accent-purple, 0.55);
        }}

        .ws-win-icon {{
            font-size: 13px;
            color: @accent-purple;
        }}

        .ws-win-title {{
            font-size: 10.5px;
            font-weight: 600;
            color: @fg-color;
        }}

        #dash-avatar-btn {{
            background-image: none;
            background-color: transparent;
            border: none;
            padding: 0;
            margin: 0;
            border-radius: 9999px;
            min-width: 60px;
            min-height: 60px;
        }}

        #dash-avatar-btn:hover {{
            box-shadow: 0 0 14px alpha(@accent-purple, 0.7);
        }}
        """
        css_provider.load_from_data(css.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


class HoverTriggerWindow(Gtk.Window):
    """
    Transparent hover strip anchored over the center of Waybar (clock module).
    Touching or hovering over this area immediately slides down the Caelestia Dashboard!
    """
    def __init__(self, app):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.app = app
        self.set_name("hover-trigger-win")
        self.set_title("Waybar Clock Hover Trigger")
        self.set_resizable(False)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_namespace(self, "dashboard-trigger")
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_exclusive_zone(self, -1)

        # Centered horizontally, anchored to TOP over Waybar's clock
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, False)

        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 0)
        self.set_size_request(240, 46)

        # Fully transparent visual
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.connect("draw", self.on_draw)

        ev_box = Gtk.EventBox()
        ev_box.set_visible_window(False)
        ev_box.set_size_request(240, 46)
        self.add(ev_box)

        # Event masks for hover and click
        self.add_events(
            Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
            | Gdk.EventMask.BUTTON_PRESS_MASK
        )

        self.connect("enter-notify-event", self.on_mouse_enter)
        self.connect("leave-notify-event", self.on_mouse_leave)
        self.connect("button-press-event", self.on_button_press)

    def on_draw(self, widget, cr):
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        return False

    def on_mouse_enter(self, widget, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        self.app.on_trigger_enter()
        return False

    def on_mouse_leave(self, widget, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        self.app.on_trigger_leave()
        return False

    def on_button_press(self, widget, event):
        self.app.on_trigger_click()
        return True


class DashboardApp:
    def __init__(self):
        self.mouse_in_trigger = False
        self.mouse_in_dashboard = False
        self.hide_timer_id = None

        self.dashboard_win = DashboardWindow(self)
        self.trigger_win = HoverTriggerWindow(self)
        self.trigger_win.show_all()

    def cancel_hide_timer(self):
        if self.hide_timer_id is not None:
            GLib.source_remove(self.hide_timer_id)
            self.hide_timer_id = None

    def schedule_hide_check(self):
        self.cancel_hide_timer()
        # Only auto-hide if not pinned, not choosing file, and currently open (or opening)
        if not self.dashboard_win.pinned and not getattr(self.dashboard_win, "in_dialog", False) and self.dashboard_win.is_open:
            self.hide_timer_id = GLib.timeout_add(350, self._on_hide_timer_fired)

    def _on_hide_timer_fired(self):
        self.hide_timer_id = None
        if not self.mouse_in_trigger and not self.mouse_in_dashboard:
            if not self.dashboard_win.pinned and not getattr(self.dashboard_win, "in_dialog", False):
                self.dashboard_win.close_animated()
        return False

    def on_trigger_enter(self):
        self.mouse_in_trigger = True
        self.cancel_hide_timer()
        if not self.dashboard_win.is_open or self.dashboard_win.anim_direction < 0:
            self.dashboard_win.open_animated(pinned=False)

    def on_trigger_leave(self):
        self.mouse_in_trigger = False
        self.schedule_hide_check()

    def on_dashboard_enter(self):
        self.mouse_in_dashboard = True
        self.cancel_hide_timer()

    def on_dashboard_leave(self):
        self.mouse_in_dashboard = False
        self.schedule_hide_check()

    def on_trigger_click(self):
        self.toggle()

    def toggle(self):
        self.cancel_hide_timer()
        if self.dashboard_win.is_open:
            self.dashboard_win.close_animated()
        else:
            self.dashboard_win.open_animated(pinned=True)

    def handle_tab_switch(self):
        try:
            if os.path.exists(TAB_FILE):
                with open(TAB_FILE, "r") as f:
                    t = int(f.read().strip())
                self.dashboard_win.switch_tab(t)
                self.cancel_hide_timer()
                self.dashboard_win.open_animated(pinned=True)
        except Exception:
            pass


def main():
    global app_instance
    check_single_instance()

    app = DashboardApp()
    app_instance = app

    def on_sigusr1():
        app.toggle()
        return True

    def on_sigusr2():
        app.handle_tab_switch()
        return True

    def on_sigterm():
        cleanup()
        return False

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, on_sigusr1)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, on_sigusr2)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, on_sigterm)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, on_sigterm)

    if "--daemon" not in sys.argv:
        app.dashboard_win.open_animated(pinned=True)

    Gtk.main()

if __name__ == "__main__":
    main()
