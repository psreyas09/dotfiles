#!/usr/bin/env python3
import os
import sys
import time
import math
import cairo
import signal
import urllib.request
import urllib.parse

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
gi.require_version('Playerctl', '2.0')
from gi.repository import Gtk, Gdk, GtkLayerShell, Playerctl, GLib, GdkPixbuf

PID_FILE = "/tmp/waybar_media_popup.pid"

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

def parse_theme_colors():
    colors = {
        "accent-purple": (0.09, 0.64, 0.65, 1.0),
        "fg-color": (1.0, 0.92, 0.79, 1.0),
        "bg-color": (0.13, 0.13, 0.13, 1.0),
        "comment-color": (0.68, 0.60, 0.46, 1.0),
    }
    path = "/home/sreyas/.config/waybar/current-theme.css"
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
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


class MaterialWavySeekBar(Gtk.DrawingArea):
    """
    Material You (Android 13/14/15) style squiggly wave seekbar:
    - Flowing animated sine wave for elapsed track when playing.
    - Smoothly flattens to a straight line when paused.
    - Smoothly expands and flows when resumed.
    - Interactive seeking with click & scrub.
    - Enlarges thumb knob smoothly on hover and drag.
    """
    def __init__(self, min_val=0, max_val=100):
        super().__init__()
        self.min_val = float(min_val)
        self.max_val = float(max_val)
        self.value = 0.0
        self.is_playing = False
        self.is_dragging = False
        self.is_hovered = False

        self.set_size_request(-1, 24)
        self.set_can_focus(True)

        # Animation states
        self.phase = 0.0
        self.target_amplitude = 3.2
        self.current_amplitude = 0.0
        self.thumb_radius = 5.5
        self.wavelength = 24.0 # pixels per cycle

        self.colors = parse_theme_colors()

        self.on_seek_press = None
        self.on_seek_release = None
        self.on_seek_change = None

        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
        )

        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self._on_button_press)
        self.connect("button-release-event", self._on_button_release)
        self.connect("motion-notify-event", self._on_motion_notify)
        self.connect("enter-notify-event", self._on_enter)
        self.connect("leave-notify-event", self._on_leave)

        self.last_frame_time = None
        self.add_tick_callback(self.on_tick)

    def set_range(self, min_val, max_val):
        self.min_val = float(min_val)
        self.max_val = max(float(max_val), self.min_val + 0.001)
        self.value = max(self.min_val, min(self.max_val, self.value))
        self.queue_draw()

    def set_value(self, val):
        if not self.is_dragging:
            self.value = max(self.min_val, min(self.max_val, float(val)))
            self.queue_draw()

    def get_value(self):
        return self.value

    def set_playing(self, is_playing):
        self.is_playing = is_playing

    def on_tick(self, widget, frame_clock):
        now = frame_clock.get_frame_time() / 1_000_000
        if self.last_frame_time is None:
            self.last_frame_time = now
        dt = min(0.05, now - self.last_frame_time)
        self.last_frame_time = now

        need_redraw = False

        if self.is_playing and not self.is_dragging:
            # Shift wave phase forward smoothly
            self.phase = (self.phase + 2.0 * math.pi * 1.3 * dt) % (2.0 * math.pi)
            need_redraw = True

        # Amplitude transition (wave ripples up on play, flattens smoothly on pause)
        target_amp = self.target_amplitude if (self.is_playing and not self.is_dragging) else 0.0
        if abs(self.current_amplitude - target_amp) > 0.02:
            self.current_amplitude += (target_amp - self.current_amplitude) * min(1.0, dt * 10.0)
            need_redraw = True
        else:
            self.current_amplitude = target_amp

        # Thumb radius transition on hover / drag
        target_radius = 8.0 if (self.is_hovered or self.is_dragging) else 5.5
        if abs(self.thumb_radius - target_radius) > 0.05:
            self.thumb_radius += (target_radius - self.thumb_radius) * min(1.0, dt * 14.0)
            need_redraw = True
        else:
            self.thumb_radius = target_radius

        if need_redraw:
            self.queue_draw()

        return True

    def _val_from_x(self, x):
        alloc = self.get_allocation()
        pad = 8.0
        track_start = pad
        track_end = alloc.width - pad
        track_len = max(1.0, track_end - track_start)
        norm = max(0.0, min(1.0, (x - track_start) / track_len))
        return self.min_val + norm * (self.max_val - self.min_val)

    def _on_button_press(self, widget, event):
        if event.button == 1:
            self.is_dragging = True
            val = self._val_from_x(event.x)
            self.value = val
            self.queue_draw()
            if self.on_seek_press:
                self.on_seek_press(val)
            if self.on_seek_change:
                self.on_seek_change(val)
            return True
        return False

    def _on_motion_notify(self, widget, event):
        if self.is_dragging:
            val = self._val_from_x(event.x)
            self.value = val
            self.queue_draw()
            if self.on_seek_change:
                self.on_seek_change(val)
            return True
        return False

    def _on_button_release(self, widget, event):
        if event.button == 1 and self.is_dragging:
            self.is_dragging = False
            val = self._val_from_x(event.x)
            self.value = val
            self.queue_draw()
            if self.on_seek_release:
                self.on_seek_release(val)
            return True
        return False

    def _on_enter(self, widget, event):
        self.is_hovered = True
        return False

    def _on_leave(self, widget, event):
        self.is_hovered = False
        return False

    def on_draw(self, widget, cr):
        alloc = self.get_allocation()
        w = alloc.width
        h = alloc.height
        y_center = h / 2.0

        pad = 8.0
        track_start = pad
        track_end = w - pad
        track_len = max(1.0, track_end - track_start)

        val_range = max(0.001, self.max_val - self.min_val)
        norm_val = max(0.0, min(1.0, (self.value - self.min_val) / val_range))
        thumb_x = track_start + norm_val * track_len

        accent = self.colors.get("accent-purple", (0.09, 0.64, 0.65, 1.0))
        fg = self.colors.get("fg-color", (1.0, 0.92, 0.79, 1.0))

        # 1. Inactive Track (Remaining)
        if track_end > thumb_x:
            cr.set_source_rgba(fg[0], fg[1], fg[2], 0.20)
            cr.set_line_width(4.0)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.move_to(thumb_x, y_center)
            cr.line_to(track_end, y_center)
            cr.stroke()

        # 2. Active Track (Wave!)
        if thumb_x > track_start:
            cr.set_source_rgba(accent[0], accent[1], accent[2], 1.0)
            cr.set_line_width(4.0)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.set_line_join(cairo.LINE_JOIN_ROUND)

            active_len = thumb_x - track_start
            if self.current_amplitude > 0.05 and active_len > 8.0:
                cr.move_to(track_start, y_center)
                step = 2.0
                x = track_start
                while x <= thumb_x:
                    t_start = min(1.0, (x - track_start) / 14.0)
                    t_end = min(1.0, (thumb_x - x) / 14.0)
                    amp = self.current_amplitude * t_start * t_end
                    y = y_center + amp * math.sin(2.0 * math.pi * (x - track_start) / self.wavelength - self.phase)
                    cr.line_to(x, y)
                    x += step
                cr.line_to(thumb_x, y_center)
                cr.stroke()
            else:
                cr.move_to(track_start, y_center)
                cr.line_to(thumb_x, y_center)
                cr.stroke()

        # 3. Thumb (Scrubber Knob)
        cr.set_source_rgba(accent[0], accent[1], accent[2], 1.0)
        cr.arc(thumb_x, y_center, self.thumb_radius, 0, 2.0 * math.pi)
        cr.fill()

        # Subtle inner light dot
        inner_r = max(1.5, self.thumb_radius - 3.5)
        cr.set_source_rgba(fg[0], fg[1], fg[2], 0.90)
        cr.arc(thumb_x, y_center, inner_r, 0, 2.0 * math.pi)
        cr.fill()


class MediaPopup(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("Waybar Media Overview")
        self.set_default_size(360, 140)
        self.set_resizable(False)

        # Layer Shell Setup
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)

        # Position directly underneath group/media with an 8px gap
        self.target_margin_top = 8
        self.start_margin_top = -6
        self.target_margin_right = 470

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

        # Playerctl setup
        self.manager = Playerctl.PlayerManager()
        self.manager.connect("name-appeared", self.on_player_appeared)
        self.manager.connect("player-vanished", self.on_player_vanished)

        self.player = None
        self.is_seeking = False
        self.last_art_url = ""

        # Find active player
        for name in self.manager.props.player_names:
            self.setup_player(name)
            break

        # UI Build
        self.setup_ui()
        self.apply_css()
        self.update_all()

        # Update timer for seekbar & time (every 500ms)
        GLib.timeout_add(500, self.on_timer_tick)

    # --- Entrance and Exit Animations ---
    def on_animate_in(self, widget, frame_clock):
        now = frame_clock.get_frame_time() / 1_000_000
        if self.anim_start is None:
            self.anim_start = now
        elapsed = now - self.anim_start
        progress = min(1.0, elapsed / 0.20)
        ease = 1.0 - (1.0 - progress) ** 3

        Gtk.Widget.set_opacity(self, ease)
        curr_margin = int(self.start_margin_top + (self.target_margin_top - self.start_margin_top) * ease)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, curr_margin)

        if progress >= 1.0:
            Gtk.Widget.set_opacity(self, 1.0)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, self.target_margin_top)
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
        progress = min(1.0, elapsed / 0.15)
        ease = progress ** 2

        Gtk.Widget.set_opacity(self, max(0.0, 1.0 - ease))
        curr_margin = int(self.target_margin_top - 12 * ease)
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

    def setup_player(self, name):
        try:
            self.player = Playerctl.Player.new_from_name(name)
            self.player.connect("metadata", self.on_metadata_changed)
            self.player.connect("playback-status", self.on_status_changed)
            self.player.connect("seeked", self.on_seeked)
            self.manager.manage_player(self.player)
        except Exception:
            self.player = None

    def on_player_appeared(self, manager, name):
        if not self.player:
            self.setup_player(name)
            self.update_all()

    def on_player_vanished(self, manager, player):
        if self.player and self.player.props.player_name == player.props.player_name:
            self.player = None
            self.update_all()

    def on_metadata_changed(self, player, metadata):
        GLib.idle_add(self.update_all)

    def on_status_changed(self, player, status):
        GLib.idle_add(self.update_play_icon)

    def on_seeked(self, player, position):
        GLib.idle_add(self.update_seekbar)

    def setup_ui(self):
        # Main Container
        self.card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.card.set_name("media-card")
        self.add(self.card)

        # Left Column: Album Art
        art_frame = Gtk.Frame()
        art_frame.set_name("art-frame")
        art_frame.set_shadow_type(Gtk.ShadowType.NONE)
        art_frame.set_valign(Gtk.Align.CENTER)
        self.art_image = Gtk.Image()
        self.art_image.set_size_request(90, 90)
        art_frame.add(self.art_image)
        self.card.pack_start(art_frame, False, False, 0)

        # Right Column: Track Info + Seekbar + Controls
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.card.pack_start(right_box, True, True, 0)

        # Title row with Close button
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        right_box.pack_start(top_row, False, False, 0)

        self.title_label = Gtk.Label(label="No Media Playing")
        self.title_label.set_name("media-title")
        self.title_label.set_xalign(0)
        self.title_label.set_ellipsize(3) # PANGO_ELLIPSIZE_END
        self.title_label.set_max_width_chars(24)
        top_row.pack_start(self.title_label, True, True, 0)

        btn_close = Gtk.Button(label="󰅖")
        btn_close.set_name("btn-close")
        btn_close.set_relief(Gtk.ReliefStyle.NONE)
        btn_close.connect("clicked", self.close_animated)
        top_row.pack_end(btn_close, False, False, 0)

        # Artist & Album
        self.artist_label = Gtk.Label(label="")
        self.artist_label.set_name("media-artist")
        self.artist_label.set_xalign(0)
        self.artist_label.set_ellipsize(3)
        self.artist_label.set_max_width_chars(28)
        right_box.pack_start(self.artist_label, False, False, 0)

        self.album_label = Gtk.Label(label="")
        self.album_label.set_name("media-album")
        self.album_label.set_xalign(0)
        self.album_label.set_ellipsize(3)
        self.album_label.set_max_width_chars(28)
        right_box.pack_start(self.album_label, False, False, 0)

        # Seekbar Row with Material You Wavy Seekbar
        seek_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        seek_row.set_name("seek-row")
        right_box.pack_start(seek_row, False, False, 2)

        self.time_cur = Gtk.Label(label="0:00")
        self.time_cur.set_name("time-label")
        seek_row.pack_start(self.time_cur, False, False, 0)

        self.seekbar = MaterialWavySeekBar(0, 100)
        self.seekbar.set_name("media-seekbar")
        self.seekbar.on_seek_press = self.on_seek_press
        self.seekbar.on_seek_change = self.on_seek_change
        self.seekbar.on_seek_release = self.on_seek_release
        seek_row.pack_start(self.seekbar, True, True, 0)

        self.time_tot = Gtk.Label(label="0:00")
        self.time_tot.set_name("time-label")
        seek_row.pack_end(self.time_tot, False, False, 0)

        # Player Controls Row
        ctrl_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        ctrl_row.set_name("ctrl-row")
        ctrl_row.set_halign(Gtk.Align.CENTER)
        right_box.pack_start(ctrl_row, False, False, 4)

        self.btn_prev = Gtk.Button(label="󰒮")
        self.btn_prev.set_name("media-ctrl-btn")
        self.btn_prev.connect("clicked", self.on_prev_clicked)
        ctrl_row.pack_start(self.btn_prev, False, False, 0)

        self.btn_play = Gtk.Button(label="󰐎")
        self.btn_play.set_name("media-play-btn")
        self.btn_play.connect("clicked", self.on_play_clicked)
        ctrl_row.pack_start(self.btn_play, False, False, 0)

        self.btn_next = Gtk.Button(label="󰒭")
        self.btn_next.set_name("media-ctrl-btn")
        self.btn_next.connect("clicked", self.on_next_clicked)
        ctrl_row.pack_start(self.btn_next, False, False, 0)

    def on_prev_clicked(self, btn):
        if self.player:
            self.player.previous()

    def on_play_clicked(self, btn):
        if self.player:
            self.player.play_pause()

    def on_next_clicked(self, btn):
        if self.player:
            self.player.next()

    def on_seek_press(self, val):
        self.is_seeking = True
        self.time_cur.set_text(self.format_seconds(val))

    def on_seek_change(self, val):
        if self.is_seeking:
            self.time_cur.set_text(self.format_seconds(val))

    def on_seek_release(self, val):
        self.is_seeking = False
        self.time_cur.set_text(self.format_seconds(val))
        if self.player:
            try:
                self.player.set_position(int(val * 1_000_000))
            except Exception:
                pass

    def format_seconds(self, secs):
        secs = max(0, int(secs))
        m = secs // 60
        s = secs % 60
        return f"{m}:{s:02d}"

    def update_all(self):
        if not self.player:
            self.title_label.set_text("No Media Playing")
            self.artist_label.set_text("")
            self.album_label.set_text("")
            self.load_placeholder_art()
            self.update_play_icon()
            self.seekbar.set_range(0, 100)
            self.seekbar.set_value(0)
            self.time_cur.set_text("0:00")
            self.time_tot.set_text("0:00")
            return

        # Title
        title = self.player.get_title() or "Unknown Title"
        self.title_label.set_text(title)

        # Artist
        artist = self.player.get_artist() or ""
        self.artist_label.set_text(f" {artist}" if artist else "")

        # Album
        album = self.player.get_album() or ""
        self.album_label.set_text(f"󰀥 {album}" if album else "")

        # Album Art
        art_url = self.player.print_metadata_prop("mpris:artUrl") or ""
        if art_url != self.last_art_url:
            self.last_art_url = art_url
            self.load_art(art_url)

        # Play/Pause Icon and Wave state
        self.update_play_icon()

        # Seekbar Range and Value
        self.update_seekbar_range()
        self.update_seekbar()

    def update_play_icon(self):
        if not self.player:
            self.btn_play.set_label("󰐎")
            self.seekbar.set_playing(False)
            return
        status = self.player.get_property("playback-status")
        is_playing = (status == Playerctl.PlaybackStatus.PLAYING)
        if is_playing:
            self.btn_play.set_label("󰏤")
        else:
            self.btn_play.set_label("󰐊")
        self.seekbar.set_playing(is_playing)

    def update_seekbar_range(self):
        if not self.player:
            return
        try:
            length_us = self.player.props.metadata["mpris:length"]
            length_s = length_us / 1_000_000
            self.seekbar.set_range(0, length_s)
            self.time_tot.set_text(self.format_seconds(length_s))
        except Exception:
            self.seekbar.set_range(0, 100)
            self.time_tot.set_text("0:00")

    def update_seekbar(self):
        if not self.player or self.is_seeking:
            return
        try:
            pos_us = self.player.get_position()
            pos_s = pos_us / 1_000_000
            self.seekbar.set_value(pos_s)
            self.time_cur.set_text(self.format_seconds(pos_s))
        except Exception:
            pass

    def on_timer_tick(self):
        if self.player:
            status = self.player.get_property("playback-status")
            if status == Playerctl.PlaybackStatus.PLAYING:
                self.update_seekbar()
        return True

    def get_square_pixbuf(self, path, size=90):
        orig = GdkPixbuf.Pixbuf.new_from_file(path)
        w, h = orig.get_width(), orig.get_height()
        if w == h:
            return orig.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
        min_dim = min(w, h)
        src_x = (w - min_dim) // 2
        src_y = (h - min_dim) // 2
        cropped = orig.new_subpixbuf(src_x, src_y, min_dim, min_dim)
        return cropped.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)

    def load_art(self, art_url):
        if not art_url:
            self.load_placeholder_art()
            return

        try:
            if art_url.startswith("file://"):
                path = urllib.parse.unquote(art_url[7:])
                pixbuf = self.get_square_pixbuf(path, 90)
                self.art_image.set_from_pixbuf(pixbuf)
            elif art_url.startswith("http://") or art_url.startswith("https://"):
                import hashlib
                cache_dir = "/tmp/waybar_art_cache"
                os.makedirs(cache_dir, exist_ok=True)
                cache_key = hashlib.md5(art_url.encode('utf-8')).hexdigest()
                cached_file = os.path.join(cache_dir, f"{cache_key}.img")

                if not os.path.exists(cached_file):
                    urllib.request.urlretrieve(art_url, cached_file)

                pixbuf = self.get_square_pixbuf(cached_file, 90)
                self.art_image.set_from_pixbuf(pixbuf)
            else:
                self.load_placeholder_art()
        except Exception:
            self.load_placeholder_art()

    def load_placeholder_art(self):
        self.art_image.set_from_icon_name("audio-x-generic", Gtk.IconSize.DIALOG)

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

        #media-card {{
            background-color: alpha(@bg-color, 0.96);
            border: 1.5px solid alpha(@accent-purple, 0.85);
            border-radius: 14px;
            padding: 12px 14px;
        }}

        #art-frame {{
            border-radius: 10px;
            border: 1px solid alpha(@border-color, 0.5);
            background-color: alpha(@bg-color, 0.6);
            padding: 2px;
        }}

        #media-title {{
            font-size: 13.5px;
            font-weight: 800;
            color: @fg-color;
        }}

        #media-artist {{
            font-size: 12px;
            font-weight: 600;
            color: @accent-purple;
        }}

        #media-album {{
            font-size: 11px;
            color: @comment-color;
        }}

        #time-label {{
            font-size: 10.5px;
            font-family: "JetBrains Mono", monospace;
            color: @comment-color;
        }}

        #btn-close {{
            color: @comment-color;
            padding: 2px 6px;
            font-size: 11px;
            border: none;
            background: transparent;
            border-radius: 6px;
        }}

        #btn-close:hover {{
            color: @fg-color;
            background-color: alpha(@accent-red, 0.7);
        }}

        /* Playback Control Buttons with smooth animations */
        #media-ctrl-btn {{
            color: @accent-purple;
            background-color: alpha(@accent-purple, 0.15);
            border: 1px solid alpha(@accent-purple, 0.3);
            font-size: 13px;
            font-weight: bold;
            padding: 4px 12px;
            border-radius: 8px;
        }}

        #media-ctrl-btn:hover {{
            background-color: alpha(@accent-purple, 0.35);
            color: @fg-color;
        }}

        #media-play-btn {{
            color: @bg-color;
            background-color: @accent-purple;
            border: 1px solid @accent-purple;
            font-size: 14px;
            font-weight: bold;
            padding: 4px 16px;
            border-radius: 8px;
        }}

        #media-play-btn:hover {{
            background-color: alpha(@accent-purple, 0.85);
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

    app = MediaPopup()
    signal.signal(signal.SIGUSR1, lambda *_: GLib.idle_add(app.close_animated))

    app.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
