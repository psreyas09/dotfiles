#!/usr/bin/env python3
import os
import sys
import subprocess
import json
import time
import math
import cairo
import random
import signal
import urllib.request
import urllib.parse

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
gi.require_version('Playerctl', '2.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Gdk, GtkLayerShell, Playerctl, GLib, GdkPixbuf, Pango, PangoCairo

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


class CircularCoverVisualizer(Gtk.DrawingArea):
    """
    Caelestia-style circular cover art with 360-degree radial audio visualizer:
    - Center: Album art clipped to a circle with smooth Wallust accent ring.
    - Outer: Radial audio spectrum bars radiating outward in a circle.
    - Reactively pulses with music when playing; smoothly retracts when paused.
    """
    def __init__(self):
        super().__init__()
        self.set_size_request(148, 148)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)

        self.phase = 0.0
        self.is_playing = False
        self.num_bars = 44
        self.bars = [0.08] * self.num_bars
        self.colors = parse_theme_colors()
        self.last_frame_time = None
        self.art_pixbuf = None
        self.scaled_art = None
        self.current_r_art = 45.0
        self.on_cover_clicked = None

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("button-press-event", self.on_clicked)
        self.connect("draw", self.on_draw)
        self.add_tick_callback(self.on_tick)

    def on_clicked(self, widget, event):
        if event.button == 1 and self.on_cover_clicked:
            self.on_cover_clicked(None)
            return True
        return False

    def set_playing(self, is_playing):
        self.is_playing = is_playing

    def set_art_pixbuf(self, pixbuf):
        self.art_pixbuf = pixbuf
        self.scaled_art = None
        self.queue_draw()

    def on_tick(self, widget, frame_clock):
        now = frame_clock.get_frame_time() / 1_000_000
        if self.last_frame_time is None:
            self.last_frame_time = now
        dt = min(0.05, now - self.last_frame_time)
        self.last_frame_time = now

        need_redraw = False

        if self.is_playing:
            self.phase = (self.phase + 4.8 * dt) % (2.0 * math.pi)
            for i in range(self.num_bars):
                h1 = math.sin(self.phase * 1.5 + i * 0.55)**2
                h2 = math.cos(self.phase * 0.9 + i * 0.35)**2
                target = 0.12 + 0.88 * (h1 * 0.65 + h2 * 0.35)
                self.bars[i] += (target - self.bars[i]) * min(1.0, dt * 14.0)
            need_redraw = True
        else:
            decaying = False
            for i in range(self.num_bars):
                if self.bars[i] > 0.02:
                    self.bars[i] += (0.01 - self.bars[i]) * min(1.0, dt * 8.0)
                    decaying = True
            if decaying:
                need_redraw = True

        if need_redraw:
            self.queue_draw()
        return True

    def on_draw(self, widget, cr):
        alloc = self.get_allocation()
        w = alloc.width
        h = alloc.height
        cx = w / 2.0
        cy = h / 2.0

        r_art = self.current_r_art
        r_start = r_art + 5.0
        max_len = 16.0

        accent = self.colors.get('accent-purple', (0.71, 0.34, 0.36, 1.0))
        accent_blue = self.colors.get('accent-blue', (0.39, 0.43, 0.55, 1.0))

        # 1. Draw radial visualizer bars around circle
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_width(2.5)

        for i in range(self.num_bars):
            theta = i * 2.0 * math.pi / self.num_bars - math.pi / 2.0
            val = self.bars[i]
            bar_len = 2.0 + val * max_len

            t = (math.sin(theta) + 1.0) / 2.0
            r = accent[0] * (1.0 - t) + accent_blue[0] * t
            g = accent[1] * (1.0 - t) + accent_blue[1] * t
            b = accent[2] * (1.0 - t) + accent_blue[2] * t

            cr.set_source_rgba(r, g, b, 0.85 if self.is_playing else 0.30)
            x0 = cx + r_start * math.cos(theta)
            y0 = cy + r_start * math.sin(theta)
            x1 = cx + (r_start + bar_len) * math.cos(theta)
            y1 = cy + (r_start + bar_len) * math.sin(theta)
            cr.move_to(x0, y0)
            cr.line_to(x1, y1)
            cr.stroke()

        # 2. Draw circular album art inside circular mask
        diam = int(r_art * 2)
        if self.art_pixbuf:
            if not self.scaled_art:
                pw, ph = self.art_pixbuf.get_width(), self.art_pixbuf.get_height()
                min_dim = min(pw, ph)
                cropped = self.art_pixbuf.new_subpixbuf((pw - min_dim)//2, (ph - min_dim)//2, min_dim, min_dim)
                self.scaled_art = cropped.scale_simple(diam, diam, GdkPixbuf.InterpType.BILINEAR)

            cr.save()
            cr.new_path()
            cr.arc(cx, cy, r_art, 0, 2.0 * math.pi)
            cr.clip()
            Gdk.cairo_set_source_pixbuf(cr, self.scaled_art, cx - r_art, cy - r_art)
            cr.paint()
            cr.restore()
        else:
            # Placeholder vinyl disc / gradient
            cr.save()
            cr.new_path()
            cr.arc(cx, cy, r_art, 0, 2.0 * math.pi)
            cr.clip()
            pat = cairo.RadialGradient(cx, cy, 2.0, cx, cy, r_art)
            pat.add_color_stop_rgba(0, accent[0]*0.50, accent[1]*0.50, accent[2]*0.50, 0.9)
            pat.add_color_stop_rgba(0.72, 0.12, 0.10, 0.13, 0.95)
            pat.add_color_stop_rgba(1.0, 0.08, 0.07, 0.09, 0.98)
            cr.set_source(pat)
            cr.paint()

            # Concentric vinyl groove rings
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.07)
            cr.set_line_width(1.0)
            cr.new_sub_path()
            cr.arc(cx, cy, r_art * 0.58, 0, 2.0 * math.pi)
            cr.stroke()
            cr.new_sub_path()
            cr.arc(cx, cy, r_art * 0.78, 0, 2.0 * math.pi)
            cr.stroke()

            # Center record label circle
            cr.set_source_rgba(accent[0], accent[1], accent[2], 0.22)
            cr.new_sub_path()
            cr.arc(cx, cy, 18.0, 0, 2.0 * math.pi)
            cr.fill()

            # Center musical glyph with Pango
            layout = self.create_pango_layout("󰝚")
            desc = Pango.FontDescription("Symbols Nerd Font, JetBrains Mono 18")
            layout.set_font_description(desc)
            ink, log = layout.get_pixel_extents()
            cr.set_source_rgba(accent[0], accent[1], accent[2], 0.90)
            cr.move_to(cx - log.width / 2.0, cy - log.height / 2.0)
            PangoCairo.show_layout(cr, layout)
            cr.restore()

        # 3. Outer border ring for album art
        cr.new_path()
        cr.set_source_rgba(accent[0], accent[1], accent[2], 0.75)
        cr.set_line_width(2.0)
        cr.arc(cx, cy, r_art, 0, 2.0 * math.pi)
        cr.stroke()

        return False


class BongoCatVisualizer(Gtk.DrawingArea):
    """
    Authentic Caelestia Shell Bongo Cat:
    - Left/Right paws alternate drumming rapidly to music beat when playing.
    - Peaceful resting paws (bongo_rest.png) when paused with zero idle CPU.
    - Floating musical notes (♪, ♫, ♬) drift upwards with crisp Pango glyphs.
    - Interactive: click Bongo Cat for a playful rapid drumroll and heart burst!
    - Borderless and box-free, sitting directly on the card background.
    """
    def __init__(self):
        super().__init__()
        self.set_size_request(135, 110)
        self.set_valign(Gtk.Align.CENTER)
        self.set_can_focus(False)

        self.phase = 0.0
        self.is_playing = False
        self.drumroll_time = 0.0
        self.notes = []
        self.colors = parse_theme_colors()
        self.last_frame_time = None

        # Load authentic Caelestia Bongo Cat frames
        self.pix_f0 = None
        self.pix_f1 = None
        self.pix_rest = None
        self._load_bongo_pixbufs(125, 79)

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("button-press-event", self.on_clicked)
        self.connect("draw", self.on_draw)

        self.add_tick_callback(self.on_tick)

    def _load_bongo_pixbufs(self, target_w, target_h):
        asset_dir = os.path.expanduser("~/.config/waybar/assets")
        p0 = os.path.join(asset_dir, "bongo_0.png")
        p1 = os.path.join(asset_dir, "bongo_1.png")
        pr = os.path.join(asset_dir, "bongo_rest.png")
        try:
            if os.path.exists(p0):
                self.pix_f0 = GdkPixbuf.Pixbuf.new_from_file_at_scale(p0, target_w, target_h, True)
            if os.path.exists(p1):
                self.pix_f1 = GdkPixbuf.Pixbuf.new_from_file_at_scale(p1, target_w, target_h, True)
            if os.path.exists(pr):
                self.pix_rest = GdkPixbuf.Pixbuf.new_from_file_at_scale(pr, target_w, target_h, True)
        except Exception:
            pass

    def set_playing(self, is_playing):
        self.is_playing = is_playing

    def on_clicked(self, widget, event):
        if event.button == 1:
            self.drumroll_time = 1.4
            for _ in range(2):
                char = random.choice(['♥', '♪', '♫', '♬'])
                self.notes.append([random.uniform(-18, 18), 0.0, 1.0, char])
            self.queue_draw()
            return True
        return False

    def on_tick(self, widget, frame_clock):
        now = frame_clock.get_frame_time() / 1_000_000
        if self.last_frame_time is None:
            self.last_frame_time = now
        dt = min(0.05, now - self.last_frame_time)
        self.last_frame_time = now

        need_redraw = False

        if self.is_playing or self.drumroll_time > 0:
            speed = 9.0 if self.drumroll_time > 0 else 5.2
            self.phase = (self.phase + speed * dt) % (2.0 * math.pi)
            if self.drumroll_time > 0:
                self.drumroll_time = max(0.0, self.drumroll_time - dt)

            # Random floating music note
            if random.random() < 0.045 and len(self.notes) < 4:
                char = random.choice(['♪', '♫', '♬'])
                self.notes.append([random.uniform(-18, 18), 0.0, 1.0, char])

            need_redraw = True

        # Float and fade floating music notes
        if self.notes:
            alive_notes = []
            for n in self.notes:
                n[1] -= dt * 26.0
                n[2] -= dt * 0.75
                if n[2] > 0:
                    alive_notes.append(n)
            self.notes = alive_notes
            need_redraw = True

        if need_redraw:
            self.queue_draw()

        return True

    def on_draw(self, widget, cr):
        alloc = self.get_allocation()
        w = alloc.width
        h = alloc.height

        accent = self.colors.get('accent-purple', (0.71, 0.34, 0.36, 1.0))

        # Authentic Caelestia Bongo Cat
        cat_pix = None
        if self.is_playing or self.drumroll_time > 0:
            is_f0 = (math.sin(self.phase * 2.0) >= 0)
            cat_pix = self.pix_f0 if is_f0 else self.pix_f1
        else:
            cat_pix = self.pix_rest or self.pix_f0

        if cat_pix:
            cat_w = cat_pix.get_width()
            cat_h = cat_pix.get_height()
            cat_x = (w - cat_w) / 2.0
            bob = math.sin(self.phase * 4.0) * 1.5 if (self.is_playing or self.drumroll_time > 0) else 0.0
            cat_y = max(4.0, (h - cat_h) / 2.0 + bob)
            Gdk.cairo_set_source_pixbuf(cr, cat_pix, cat_x, cat_y)
            cr.paint()

        # Floating Notes (♪, ♫, ♬, ♥)
        if self.notes:
            layout = self.create_pango_layout("")
            desc = Pango.FontDescription("Symbols Nerd Font, DejaVu Sans 11")
            layout.set_font_description(desc)

            for nx, ny, alpha, char in self.notes:
                cr.set_source_rgba(accent[0], accent[1], accent[2], alpha * 0.9)
                layout.set_text(char, -1)
                cr.move_to(w / 2.0 + nx, 14.0 + ny)
                PangoCairo.show_layout(cr, layout)

        return False


class MediaPopup(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("Waybar Media Overview")
        self.set_default_size(630, 205)
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
        self.target_margin_right = 430

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

        # UI Build
        self.setup_ui()
        self.apply_css()

        # Multi-Player Management setup
        self.players = {}
        self.player_order = []
        self.current_instance = None
        self.player = None
        self.player_popover = None
        self.is_seeking = False
        self.last_art_url = None
        self.initialized = False

        # Check for saved active player
        saved_player = None
        if os.path.exists("/tmp/waybar_active_player"):
            try:
                with open("/tmp/waybar_active_player", "r") as f:
                    saved_player = f.read().strip()
            except Exception:
                pass

        self.manager = Playerctl.PlayerManager()
        self.manager.connect("name-appeared", self.on_player_appeared)
        self.manager.connect("player-vanished", self.on_player_vanished)

        # Populate all currently available players
        for name in self.manager.props.player_names:
            self.add_player(name)

        if saved_player and saved_player in self.players:
            self.select_player_by_instance(saved_player)
        elif self.player_order:
            # Prefer playing player if available
            chosen = self.player_order[0]
            for inst in self.player_order:
                p = self.players[inst]
                try:
                    if p.get_property("playback-status") == Playerctl.PlaybackStatus.PLAYING:
                        chosen = inst
                        break
                except Exception:
                    pass
            self.select_player_by_instance(chosen)

        self.initialized = True
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

    def get_player_instance(self, player):
        if not player:
            return ""
        return getattr(player.props, "player_instance", None) or getattr(player.props, "player_name", "") or ""

    def add_player(self, name_obj):
        try:
            player = Playerctl.Player.new_from_name(name_obj)
            inst = getattr(name_obj, "instance", None) or self.get_player_instance(player)
            if inst in self.players:
                return
            player.connect("metadata", self.on_metadata_changed)
            player.connect("playback-status", self.on_status_changed)
            player.connect("seeked", self.on_seeked)
            self.manager.manage_player(player)
            self.players[inst] = player
            if inst not in self.player_order:
                self.player_order.append(inst)

            if self.initialized:
                if not self.player:
                    self.select_player_by_instance(inst)
                else:
                    self.update_switcher_ui()
        except Exception:
            pass

    def on_player_appeared(self, manager, name):
        self.add_player(name)

    def on_player_vanished(self, manager, player):
        inst = self.get_player_instance(player)
        if inst in self.players:
            del self.players[inst]
        if inst in self.player_order:
            self.player_order.remove(inst)
        if self.current_instance == inst:
            if self.player_order:
                self.select_player_by_instance(self.player_order[0])
            else:
                self.player = None
                self.current_instance = None
                self.update_all()
        else:
            self.update_switcher_ui()

    def select_player_by_instance(self, instance, auto_resume=False):
        if instance not in self.players:
            return
        self.current_instance = instance
        self.player = self.players[instance]
        self.last_art_url = None
        self.save_active_player(instance)
        if auto_resume:
            try:
                self.player.play()
            except Exception:
                try:
                    self.player.play_pause()
                except Exception:
                    pass
        self.update_all()

    def save_active_player(self, instance):
        try:
            with open("/tmp/waybar_active_player", "w") as f:
                f.write(instance)
            subprocess.run(["pkill", "-USR2", "-f", "mediaplayer.sh"], stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def on_prev_player_clicked(self, widget):
        if not self.player_order:
            return
        try:
            idx = self.player_order.index(self.current_instance)
            new_idx = (idx - 1) % len(self.player_order)
            self.select_player_by_instance(self.player_order[new_idx])
        except ValueError:
            if self.player_order:
                self.select_player_by_instance(self.player_order[0])

    def on_next_player_clicked(self, widget):
        if not self.player_order:
            return
        try:
            idx = self.player_order.index(self.current_instance)
            new_idx = (idx + 1) % len(self.player_order)
            self.select_player_by_instance(self.player_order[new_idx])
        except ValueError:
            if self.player_order:
                self.select_player_by_instance(self.player_order[0])

    def on_player_pill_clicked(self, widget):
        if not self.player_order:
            return
        if hasattr(self, "player_popover") and self.player_popover:
            self.player_popover.popdown()
            self.player_popover = None
            return

        self.player_popover = Gtk.Popover.new(widget)
        self.player_popover.set_position(Gtk.PositionType.BOTTOM)
        self.player_popover.set_name("player-switcher-popover")
        self.player_popover.connect("closed", self.on_popover_closed)

        pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        pop_box.set_margin_start(6)
        pop_box.set_margin_end(6)
        pop_box.set_margin_top(6)
        pop_box.set_margin_bottom(6)

        pop_title = Gtk.Label(label="SELECT MEDIA PLAYER")
        pop_title.set_name("popover-header")
        pop_title.set_xalign(0)
        pop_box.pack_start(pop_title, False, False, 2)

        for inst in self.player_order:
            p = self.players.get(inst)
            if not p:
                continue
            icon, name = self.get_player_info(p)
            status_enum = p.get_property("playback-status")
            is_play = (status_enum == Playerctl.PlaybackStatus.PLAYING)
            status_icon = "󰐊" if is_play else "󰏤"
            track = p.get_title() or "No Track"
            if len(track) > 24:
                track = track[:23] + "…"
            is_active = (inst == self.current_instance)

            item_btn = Gtk.Button()
            item_btn.get_style_context().add_class("popover-player-item")
            if is_active:
                item_btn.get_style_context().add_class("popover-player-item-active")

            item_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            lbl_icon = Gtk.Label(label=icon)
            lbl_icon.get_style_context().add_class("popover-player-icon")
            item_box.pack_start(lbl_icon, False, False, 0)

            details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            lbl_name = Gtk.Label(label=name)
            lbl_name.set_name("popover-item-name")
            lbl_name.set_xalign(0)
            details_box.pack_start(lbl_name, False, False, 0)

            lbl_track = Gtk.Label(label=f"{status_icon} {track}")
            lbl_track.set_name("popover-item-track")
            lbl_track.set_xalign(0)
            details_box.pack_start(lbl_track, False, False, 0)

            item_box.pack_start(details_box, True, True, 0)

            actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            if is_active:
                lbl_active = Gtk.Label(label="✓ Active")
                lbl_active.set_name("popover-active-badge")
                actions_box.pack_start(lbl_active, False, False, 0)
            else:
                btn_play_switch = Gtk.Button(label="󰐊 Resume")
                btn_play_switch.set_name("popover-resume-btn")
                btn_play_switch.connect("clicked", lambda b, i=inst, pl=p: self.on_switch_and_play(i, pl))
                actions_box.pack_start(btn_play_switch, False, False, 0)

            btn_win = Gtk.Button(label="")
            btn_win.get_style_context().add_class("popover-focus-btn")
            btn_win.set_tooltip_text(f"Go to {name} window")
            btn_win.connect("clicked", lambda b, pl=p: self.on_focus_player_from_popover(pl))
            actions_box.pack_start(btn_win, False, False, 0)

            item_box.pack_end(actions_box, False, False, 0)

            item_btn.add(item_box)
            item_btn.connect("clicked", lambda b, i=inst: self.on_select_player_from_popover(i))
            pop_box.pack_start(item_btn, False, False, 0)

        self.player_popover.add(pop_box)
        self.player_popover.show_all()
        self.player_popover.popup()

    def on_select_player_from_popover(self, instance):
        if hasattr(self, "player_popover") and self.player_popover:
            self.player_popover.popdown()
        self.select_player_by_instance(instance)

    def on_switch_and_play(self, instance, player):
        if hasattr(self, "player_popover") and self.player_popover:
            self.player_popover.popdown()
        self.select_player_by_instance(instance, auto_resume=True)

    def on_focus_player_from_popover(self, player):
        if hasattr(self, "player_popover") and self.player_popover:
            self.player_popover.popdown()
        inst = self.get_player_instance(player)
        self.select_player_by_instance(inst)
        self.focus_player_window(player)

    def on_popover_closed(self, popover):
        self.player_popover = None

    def on_focus_window_clicked(self, widget):
        self.focus_player_window(self.player)

    def find_niri_window_id(self, pname, pinst, art=""):
        try:
            out = subprocess.check_output(["niri", "msg", "--json", "windows"], text=True)
            windows = json.loads(out)
        except Exception:
            return None

        if not windows:
            return None

        # 1. Try matching CGroup or UserUnit from busctl for flatpaks/services
        bus_name = f"org.mpris.MediaPlayer2.{pinst or pname}"
        try:
            b_out = subprocess.check_output(["busctl", "--user", "status", bus_name], text=True, stderr=subprocess.DEVNULL)
            for line in b_out.splitlines():
                if line.startswith("UserUnit=") or line.startswith("CGroup="):
                    val = line.split("=", 1)[1].lower()
                    for w in windows:
                        app = (w.get("app_id") or "").lower()
                        if app and app in val:
                            return w["id"]
        except Exception:
            pass

        # 2. Heuristic keyword matching
        pname_l = (pname or "").lower()
        pinst_l = (pinst or "").lower()
        art_l = (art or "").lower()

        keywords = []
        if "zen" in pinst_l or "zen" in art_l:
            keywords = ["zen", "firefox"]
        elif "tauon" in pname_l:
            keywords = ["tauon"]
        elif "spotify" in pname_l:
            keywords = ["spotify"]
        elif "firefox" in pname_l:
            keywords = ["firefox"]
        elif "chromium" in pname_l or "chrome" in pname_l:
            keywords = ["chrome", "chromium"]
        elif "brave" in pname_l:
            keywords = ["brave"]
        elif "vlc" in pname_l:
            keywords = ["vlc"]
        elif "mpv" in pname_l:
            keywords = ["mpv"]
        else:
            keywords = [pname_l]

        for kw in keywords:
            for w in windows:
                app = (w.get("app_id") or "").lower()
                title = (w.get("title") or "").lower()
                if kw in app or kw in title:
                    return w["id"]

        return None

    def focus_player_window(self, target_player=None):
        target = target_player or self.player
        if not target:
            return

        pname = (getattr(target.props, "player_name", "") or "").lower()
        pinst = (getattr(target.props, "player_instance", "") or "").lower()
        art = (target.print_metadata_prop("mpris:artUrl") or "").lower()

        # Try to find window ID in Niri
        win_id = self.find_niri_window_id(pname, pinst, art)
        if win_id is not None:
            try:
                subprocess.run(["niri", "msg", "action", "focus-window", "--id", str(win_id)], check=True)
            except Exception:
                pass

        # Also send MPRIS Raise via DBus as complementary call
        bus_name = f"org.mpris.MediaPlayer2.{pinst or pname}"
        try:
            subprocess.run(["busctl", "--user", "call", bus_name, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2", "Raise"], stderr=subprocess.DEVNULL)
        except Exception:
            pass

        # Close the popup animated
        self.close_animated()

    def on_metadata_changed(self, player, metadata):
        inst = self.get_player_instance(player)
        if inst == self.current_instance:
            GLib.idle_add(self.update_all)
        else:
            GLib.idle_add(self.update_switcher_ui)

    def on_status_changed(self, player, status):
        inst = self.get_player_instance(player)
        if inst == self.current_instance:
            GLib.idle_add(self.update_play_icon)
        else:
            GLib.idle_add(self.update_switcher_ui)

    def on_seeked(self, player, position):
        inst = self.get_player_instance(player)
        if inst == self.current_instance:
            GLib.idle_add(self.update_seekbar)

    def setup_ui(self):
        # Main Container
        self.card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.card.set_name("media-card")
        self.add(self.card)

        # Left Column: Caelestia 360-degree Radial Cover Visualizer
        self.cover_vis = CircularCoverVisualizer()
        self.cover_vis.on_cover_clicked = self.on_play_clicked
        self.card.pack_start(self.cover_vis, False, False, 0)

        # Middle Column: App Badge, Title, Artist, Album, Seekbar, M3 Controls
        middle_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        middle_box.set_valign(Gtk.Align.CENTER)
        self.card.pack_start(middle_box, True, True, 0)

        # Top Header Row: Player Switcher & Close button
        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        middle_box.pack_start(header_row, False, False, 0)

        # Player Switcher Container
        self.switcher_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.switcher_box.set_name("player-switcher-box")
        header_row.pack_start(self.switcher_box, False, False, 0)

        # Previous Player Button (Step left)
        self.btn_player_prev = Gtk.Button(label="")
        self.btn_player_prev.set_name("btn-player-step")
        self.btn_player_prev.get_style_context().add_class("player-step-btn")
        self.btn_player_prev.connect("clicked", self.on_prev_player_clicked)
        self.btn_player_prev.set_tooltip_text("Previous player")
        self.switcher_box.pack_start(self.btn_player_prev, False, False, 0)

        # Active Player Pill Button
        self.btn_player_pill = Gtk.Button()
        self.btn_player_pill.set_name("player-badge-btn")
        self.btn_player_pill.connect("clicked", self.on_player_pill_clicked)

        pill_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        self.app_badge_label = Gtk.Label(label="󰝚 Standby")
        self.app_badge_label.set_name("app-badge-text")

        self.app_badge_arrow = Gtk.Label(label="▾")
        self.app_badge_arrow.set_name("app-badge-arrow")

        pill_content.pack_start(self.app_badge_label, False, False, 0)
        pill_content.pack_start(self.app_badge_arrow, False, False, 0)
        self.btn_player_pill.add(pill_content)
        self.switcher_box.pack_start(self.btn_player_pill, False, False, 0)

        # Next Player Button (Step right)
        self.btn_player_next = Gtk.Button(label="")
        self.btn_player_next.set_name("btn-player-step")
        self.btn_player_next.get_style_context().add_class("player-step-btn")
        self.btn_player_next.connect("clicked", self.on_next_player_clicked)
        self.btn_player_next.set_tooltip_text("Next player")
        self.switcher_box.pack_start(self.btn_player_next, False, False, 0)

        # Player Counter Label (e.g. "1/2")
        self.player_counter_label = Gtk.Label(label="")
        self.player_counter_label.set_name("player-counter-label")
        self.switcher_box.pack_start(self.player_counter_label, False, False, 2)

        # Go to Player Window Button (focus window in Niri / MPRIS raise)
        self.btn_open_window = Gtk.Button(label="")
        self.btn_open_window.set_name("btn-open-window")
        self.btn_open_window.set_relief(Gtk.ReliefStyle.NONE)
        self.btn_open_window.set_tooltip_text("Go to player window")
        self.btn_open_window.connect("clicked", self.on_focus_window_clicked)
        header_row.pack_start(self.btn_open_window, False, False, 0)

        btn_close = Gtk.Button(label="󰅖")
        btn_close.set_name("btn-close")
        btn_close.set_relief(Gtk.ReliefStyle.NONE)
        btn_close.connect("clicked", self.close_animated)
        header_row.pack_end(btn_close, False, False, 0)

        # Title
        self.title_label = Gtk.Label(label="No Media Playing")
        self.title_label.set_name("media-title")
        self.title_label.set_xalign(0)
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_label.set_max_width_chars(25)
        middle_box.pack_start(self.title_label, False, False, 1)

        # Artist & Album
        self.artist_label = Gtk.Label(label="")
        self.artist_label.set_name("media-artist")
        self.artist_label.set_xalign(0)
        self.artist_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.artist_label.set_max_width_chars(28)
        middle_box.pack_start(self.artist_label, False, False, 0)

        self.album_label = Gtk.Label(label="")
        self.album_label.set_name("media-album")
        self.album_label.set_xalign(0)
        self.album_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.album_label.set_max_width_chars(28)
        middle_box.pack_start(self.album_label, False, False, 0)

        # Seekbar Row with Material You Wavy Seekbar
        seek_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        seek_row.set_name("seek-row")
        middle_box.pack_start(seek_row, False, False, 3)

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

        # Player Controls Row (Material 3 UI circular buttons)
        ctrl_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        ctrl_row.set_name("ctrl-row")
        ctrl_row.set_halign(Gtk.Align.CENTER)
        middle_box.pack_start(ctrl_row, False, False, 2)

        self.btn_prev = Gtk.Button(label="󰒮")
        self.btn_prev.set_name("m3-btn-prev")
        self.btn_prev.get_style_context().add_class("m3-tonal-btn")
        self.btn_prev.connect("clicked", self.on_prev_clicked)
        ctrl_row.pack_start(self.btn_prev, False, False, 0)

        self.btn_play = Gtk.Button(label="󰐎")
        self.btn_play.set_name("m3-btn-play")
        self.btn_play.connect("clicked", self.on_play_clicked)
        ctrl_row.pack_start(self.btn_play, False, False, 0)

        self.btn_next = Gtk.Button(label="󰒭")
        self.btn_next.set_name("m3-btn-next")
        self.btn_next.get_style_context().add_class("m3-tonal-btn")
        self.btn_next.connect("clicked", self.on_next_clicked)
        ctrl_row.pack_start(self.btn_next, False, False, 0)

        # Right Column: Bongo Cat Visualizer (No border or box outside!)
        self.bongo_cat = BongoCatVisualizer()
        self.card.pack_end(self.bongo_cat, False, False, 0)

    def on_prev_clicked(self, btn):
        if self.player:
            self.player.previous()

    def on_play_clicked(self, btn=None):
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

    def get_player_info(self, player):
        if not player:
            return "󰝚", "Standby"
        pname = (getattr(player.props, "player_name", "") or "").lower()
        pinst = (getattr(player.props, "player_instance", "") or "").lower()
        url = (player.print_metadata_prop("xesam:url") or "").lower()
        art = (player.print_metadata_prop("mpris:artUrl") or "").lower()

        is_zen = "zen" in pinst or "zen" in art
        is_ytm = "music.youtube.com" in url or "music.youtube" in pinst
        is_yt = "youtube.com" in url

        if is_zen and is_ytm:
            return "󰗃", "YT Music (Zen)"
        elif is_ytm:
            return "󰗃", "YouTube Music"
        elif is_zen and is_yt:
            return "󰗃", "YouTube (Zen)"
        elif is_zen:
            return "󰈹", "Zen Browser"
        elif "tauon" in pname:
            return "󰝚", "Tauon Music"
        elif "spotify" in pname:
            return "󰓇", "Spotify"
        elif "firefox" in pname:
            return "󰈹", "Firefox"
        elif "chromium" in pname:
            return "󰊯", "Chromium"
        elif "chrome" in pname:
            return "󰊯", "Google Chrome"
        elif "brave" in pname:
            return "󰊯", "Brave"
        elif "vlc" in pname:
            return "󰕼", "VLC"
        elif "mpv" in pname:
            return "󰐹", "MPV"
        elif "strawberry" in pname:
            return "󰝚", "Strawberry"
        elif "apple_music" in pname:
            return "󰝚", "Apple Music"
        elif "cider" in pname:
            return "󰝚", "Cider"
        elif "rhythmbox" in pname:
            return "󰝚", "Rhythmbox"
        elif "audacious" in pname:
            return "󰝚", "Audacious"
        else:
            clean = player.props.player_name.split('.')[0].capitalize()
            return "󰝚", clean

    def update_switcher_ui(self):
        if not self.player:
            self.app_badge_label.set_text("󰝚 Standby")
            self.app_badge_arrow.set_visible(False)
            self.btn_player_prev.set_visible(False)
            self.btn_player_next.set_visible(False)
            self.player_counter_label.set_text("")
            if hasattr(self, "btn_open_window"):
                self.btn_open_window.set_sensitive(False)
                self.btn_open_window.set_visible(False)
            return

        icon, name = self.get_player_info(self.player)
        self.app_badge_label.set_text(f"{icon} {name}")
        if hasattr(self, "btn_open_window"):
            self.btn_open_window.set_sensitive(True)
            self.btn_open_window.set_visible(True)
            self.btn_open_window.set_tooltip_text(f"Go to {name} window")

        count = len(self.player_order)
        if count > 1:
            self.app_badge_arrow.set_visible(True)
            self.btn_player_prev.set_visible(True)
            self.btn_player_next.set_visible(True)
            try:
                curr_idx = self.player_order.index(self.current_instance) + 1
            except ValueError:
                curr_idx = 1
            self.player_counter_label.set_text(f"{curr_idx}/{count}")
            self.player_counter_label.set_visible(True)
        else:
            self.app_badge_arrow.set_visible(False)
            self.btn_player_prev.set_visible(False)
            self.btn_player_next.set_visible(False)
            self.player_counter_label.set_text("")
            self.player_counter_label.set_visible(False)

    def update_all(self):
        self.update_switcher_ui()

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
            if hasattr(self, "bongo_cat"):
                self.bongo_cat.set_playing(False)
            if hasattr(self, "cover_vis"):
                self.cover_vis.set_playing(False)
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

        # Play/Pause Icon and Wave/Visualizer state
        self.update_play_icon()

        # Seekbar Range and Value
        self.update_seekbar_range()
        self.update_seekbar()

    def update_play_icon(self):
        if not self.player:
            self.btn_play.set_label("󰐎")
            self.seekbar.set_playing(False)
            if hasattr(self, "bongo_cat"):
                self.bongo_cat.set_playing(False)
            if hasattr(self, "cover_vis"):
                self.cover_vis.set_playing(False)
            return
        status = self.player.get_property("playback-status")
        is_playing = (status == Playerctl.PlaybackStatus.PLAYING)
        if is_playing:
            self.btn_play.set_label("󰏤")
        else:
            self.btn_play.set_label("󰐊")
        self.seekbar.set_playing(is_playing)
        if hasattr(self, "bongo_cat"):
            self.bongo_cat.set_playing(is_playing)
        if hasattr(self, "cover_vis"):
            self.cover_vis.set_playing(is_playing)

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

    def get_square_pixbuf(self, path, size=120):
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
                pixbuf = self.get_square_pixbuf(path, 120)
                self.cover_vis.set_art_pixbuf(pixbuf)
            elif art_url.startswith("http://") or art_url.startswith("https://"):
                import hashlib
                cache_dir = "/tmp/waybar_art_cache"
                os.makedirs(cache_dir, exist_ok=True)
                cache_key = hashlib.md5(art_url.encode('utf-8')).hexdigest()
                cached_file = os.path.join(cache_dir, f"{cache_key}.img")

                if not os.path.exists(cached_file):
                    urllib.request.urlretrieve(art_url, cached_file)

                pixbuf = self.get_square_pixbuf(cached_file, 120)
                self.cover_vis.set_art_pixbuf(pixbuf)
            else:
                self.load_placeholder_art()
        except Exception:
            self.load_placeholder_art()

    def load_placeholder_art(self):
        self.cover_vis.set_art_pixbuf(None)

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
            border-radius: 18px;
            padding: 14px 18px;
        }}

        /* Player Switcher Pill */
        #player-switcher-box {{
            background-color: alpha(@accent-purple, 0.12);
            border: 1px solid alpha(@accent-purple, 0.28);
            border-radius: 9999px;
            padding: 1px 3px;
        }}

        #player-badge-btn {{
            background-color: transparent;
            border: none;
            border-radius: 9999px;
            padding: 2px 7px;
            margin: 0;
        }}

        #player-badge-btn:hover {{
            background-color: alpha(@accent-purple, 0.22);
        }}

        #app-badge-text {{
            font-size: 11px;
            font-weight: 700;
            color: @accent-purple;
        }}

        #app-badge-arrow {{
            font-size: 9.5px;
            color: alpha(@accent-purple, 0.8);
        }}

        .player-step-btn {{
            background-color: transparent;
            border: none;
            border-radius: 9999px;
            color: @accent-purple;
            font-size: 11px;
            font-weight: bold;
            min-width: 20px;
            min-height: 20px;
            padding: 1px 3px;
        }}

        .player-step-btn:hover {{
            background-color: alpha(@accent-purple, 0.3);
            color: @fg-color;
        }}

        #player-counter-label {{
            font-size: 9.5px;
            font-family: "JetBrains Mono", monospace;
            font-weight: 600;
            color: @comment-color;
            padding: 0 4px 0 2px;
        }}

        /* Player Switcher Dropdown Popover */
        popover.background,
        popover contents {{
            background-color: alpha(@bg-color, 0.98);
            border: 1.5px solid alpha(@accent-purple, 0.7);
            border-radius: 14px;
            padding: 6px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.6);
        }}

        #popover-header {{
            font-size: 9.5px;
            font-weight: 800;
            color: @comment-color;
            letter-spacing: 1px;
            padding: 2px 6px 4px 6px;
        }}

        .popover-player-item {{
            background-color: transparent;
            border: 1px solid transparent;
            border-radius: 10px;
            padding: 6px 10px;
            margin: 2px 0;
        }}

        .popover-player-item:hover {{
            background-color: alpha(@accent-purple, 0.15);
            border-color: alpha(@accent-purple, 0.35);
        }}

        .popover-player-item-active {{
            background-color: alpha(@accent-purple, 0.22);
            border-color: alpha(@accent-purple, 0.5);
        }}

        .popover-player-icon {{
            font-size: 16px;
            color: @accent-purple;
        }}

        #popover-item-name {{
            font-size: 12px;
            font-weight: 700;
            color: @fg-color;
        }}

        #popover-item-track {{
            font-size: 10.5px;
            color: @comment-color;
        }}

        #popover-active-badge {{
            font-size: 10px;
            font-weight: 700;
            color: @accent-purple;
            background-color: alpha(@accent-purple, 0.25);
            border-radius: 6px;
            padding: 2px 6px;
        }}

        #popover-resume-btn {{
            font-size: 10px;
            font-weight: 700;
            color: @bg-color;
            background-color: @accent-purple;
            border-radius: 6px;
            padding: 2px 8px;
            border: none;
        }}

        #popover-resume-btn:hover {{
            background-color: alpha(@accent-purple, 0.85);
        }}

        #btn-open-window {{
            background-color: alpha(@accent-purple, 0.12);
            border: 1px solid alpha(@accent-purple, 0.28);
            border-radius: 9999px;
            color: @accent-purple;
            font-size: 13px;
            min-width: 26px;
            min-height: 26px;
            padding: 2px 7px;
            margin: 0;
        }}

        #btn-open-window:hover {{
            background-color: alpha(@accent-purple, 0.32);
            color: @fg-color;
            border-color: alpha(@accent-purple, 0.60);
        }}

        #btn-open-window:active {{
            background-color: alpha(@accent-purple, 0.50);
        }}

        .popover-focus-btn {{
            background-color: alpha(@accent-purple, 0.10);
            border: 1px solid alpha(@accent-purple, 0.28);
            border-radius: 6px;
            color: @accent-purple;
            font-size: 12px;
            padding: 2px 6px;
            margin-left: 4px;
        }}

        .popover-focus-btn:hover {{
            background-color: alpha(@accent-purple, 0.30);
            color: @fg-color;
            border-color: alpha(@accent-purple, 0.55);
        }}

        #media-title {{
            font-size: 14.5px;
            font-weight: 800;
            color: @fg-color;
            font-feature-settings: "liga 0, clig 0, dlig 0, calt 0";
        }}

        #media-artist {{
            font-size: 12px;
            font-weight: 600;
            color: @accent-purple;
            font-feature-settings: "liga 0, clig 0, dlig 0, calt 0";
        }}

        #media-album {{
            font-size: 11px;
            color: @comment-color;
            font-feature-settings: "liga 0, clig 0, dlig 0, calt 0";
        }}

        #time-label {{
            font-size: 10.5px;
            font-family: "JetBrains Mono", monospace;
            color: @comment-color;
        }}

        button {{
            background-image: none;
            outline: none;
            box-shadow: none;
        }}

        #btn-close {{
            background-image: none;
            color: @comment-color;
            padding: 2px 6px;
            font-size: 12px;
            border: none;
            background-color: transparent;
            border-radius: 9999px;
            min-width: 24px;
            min-height: 24px;
        }}

        #btn-close:hover {{
            color: @fg-color;
            background-color: alpha(@accent-red, 0.55);
        }}

        /* Material 3 UI Buttons */
        .m3-tonal-btn {{
            background-image: none;
            border-radius: 9999px;
            min-width: 38px;
            min-height: 38px;
            padding: 0;
            margin: 0;
            background-color: alpha(@accent-purple, 0.20);
            color: @accent-purple;
            border: 1px solid alpha(@accent-purple, 0.35);
            font-size: 16px;
            font-weight: bold;
        }}

        .m3-tonal-btn:hover {{
            background-image: none;
            background-color: alpha(@accent-purple, 0.38);
            color: @fg-color;
            border-color: alpha(@accent-purple, 0.65);
        }}

        .m3-tonal-btn:active {{
            background-image: none;
            background-color: alpha(@accent-purple, 0.55);
        }}

        #m3-btn-play {{
            background-image: none;
            border-radius: 9999px;
            min-width: 48px;
            min-height: 48px;
            padding: 0;
            margin: 0;
            background-color: @accent-purple;
            color: @bg-color;
            border: none;
            font-size: 20px;
            font-weight: bold;
            box-shadow: 0 4px 14px alpha(@accent-purple, 0.55);
        }}

        #m3-btn-play:hover {{
            background-image: none;
            background-color: alpha(@accent-purple, 0.88);
            box-shadow: 0 6px 18px alpha(@accent-purple, 0.75);
        }}

        #m3-btn-play:active {{
            background-image: none;
            background-color: alpha(@accent-purple, 0.72);
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
