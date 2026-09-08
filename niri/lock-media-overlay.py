#!/usr/bin/env python3
"""
macOS Sonoma Lock Screen Media Hub & Canvas Overlay Generator
Designed for Niri Wayland Compositor & Swaylock-Effects.
"""

import os
import sys
import math
import time
import signal
import hashlib
import argparse
import subprocess
import urllib.parse
import urllib.request

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
gi.require_version('Playerctl', '2.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gdk, GtkLayerShell, GLib, GdkPixbuf, Pango, PangoCairo
import cairo

PID_FILE = "/tmp/lock_media_overlay.pid"
ART_CACHE_DIR = "/tmp/swaylock_art_cache"
AVATAR_PATH = os.path.expanduser("~/.face.icon")
if not os.path.exists(AVATAR_PATH):
    AVATAR_PATH = os.path.expanduser("~/.face")

os.makedirs(ART_CACHE_DIR, exist_ok=True)

# -----------------------------------------------------------------------------
# Metadata & Playerctl Query
# -----------------------------------------------------------------------------
def get_active_player_info():
    """
    Queries active MPRIS players via playerctl.
    Returns a dict with status, title, artist, album, art_url, position, length
    or None if no media player is active.
    """
    try:
        cmd = [
            "playerctl", "-a", "metadata",
            "--format", "{{status}};;;{{artist}};;;{{title}};;;{{album}};;;{{mpris:artUrl}};;;{{position}};;;{{mpris:length}}"
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1.5)
        if res.returncode != 0 or not res.stdout.strip():
            return None

        lines = [line.strip() for line in res.stdout.strip().split("\n") if line.strip()]
        selected = None
        for line in lines:
            parts = line.split(";;;")
            if len(parts) >= 7:
                status, artist, title, album, art_url, pos_str, len_str = parts[:7]
                if not title and not artist:
                    continue
                info = {
                    "status": status.strip(),
                    "artist": artist.strip() or "Unknown Artist",
                    "title": title.strip() or "Unknown Track",
                    "album": album.strip(),
                    "art_url": art_url.strip(),
                    "position": int(pos_str) if pos_str.isdigit() else 0,
                    "length": int(len_str) if len_str.isdigit() else 0
                }
                if status.lower() == "playing":
                    return info  # Prioritize actively playing media
                if selected is None:
                    selected = info
        return selected
    except Exception:
        return None

def fetch_art_pixbuf(art_url, size=82):
    """
    Fetches and scales album artwork to a square pixbuf of size x size.
    Handles file://, http(s)://, and local paths.
    """
    if not art_url:
        return None

    local_path = None
    if art_url.startswith("file://"):
        local_path = urllib.parse.unquote(urllib.parse.urlparse(art_url).path)
    elif art_url.startswith("http://") or art_url.startswith("https://"):
        url_hash = hashlib.md5(art_url.encode("utf-8")).hexdigest()
        cached = os.path.join(ART_CACHE_DIR, f"{url_hash}.png")
        if os.path.exists(cached) and os.path.getsize(cached) > 0:
            local_path = cached
        else:
            try:
                req = urllib.request.Request(art_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=2.0) as resp, open(cached, "wb") as f:
                    f.write(resp.read())
                local_path = cached
            except Exception:
                return None
    elif os.path.exists(art_url):
        local_path = art_url

    if local_path and os.path.exists(local_path):
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(local_path, size, size, False)
        except Exception:
            return None
    return None

def is_locker_running():
    """Checks if either swaylock or gtklock is currently active (excluding defunct/zombie processes)."""
    try:
        res = subprocess.run(["pgrep", "-x", "swaylock|gtklock"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if res.returncode != 0 or not res.stdout.strip():
            return False
        for pid_str in res.stdout.strip().split():
            try:
                with open(f"/proc/{pid_str}/stat", "r") as f:
                    state = f.read().split()[2]
                    if state != "Z":
                        return True
            except Exception:
                pass
        return False
    except Exception:
        return False

is_swaylock_running = is_locker_running

def round_rect(cr, x, y, w, h, r):
    """Draws a rounded rectangle path with radius r."""
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()

# -----------------------------------------------------------------------------
# High-Fidelity macOS Sonoma Lockscreen Canvas Generator
# -----------------------------------------------------------------------------
def render_sonoma_overlay(output_path, width=1920, height=1080):
    """
    Renders the complete macOS Sonoma lockscreen typography, avatar, and
    floating music widget into a transparent RGBA PNG canvas.
    """
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)

    # 1. Top Clock & Date (macOS Sonoma Typography)
    now = time.localtime()
    date_str = time.strftime("%A, %B %e", now).replace("  ", " ")
    time_str = time.strftime("%H:%M", now)

    layout = PangoCairo.create_layout(cr)

    # Date Header
    desc_date = Pango.font_description_from_string("Google Sans Flex, -apple-system, Cantarell, Sans Medium 17")
    layout.set_font_description(desc_date)
    layout.set_text(date_str, -1)
    ext_d = layout.get_pixel_extents()[1]

    # Date shadow + crisp white text
    cr.set_source_rgba(0, 0, 0, 0.28)
    cr.move_to((width - ext_d.width) / 2 + 1, 72)
    PangoCairo.show_layout(cr, layout)
    cr.set_source_rgba(1.0, 1.0, 1.0, 0.92)
    cr.move_to((width - ext_d.width) / 2, 70)
    PangoCairo.show_layout(cr, layout)

    # Giant Clock
    desc_time = Pango.font_description_from_string("Google Sans Flex, -apple-system, Cantarell, Sans Bold 92")
    layout.set_font_description(desc_time)
    layout.set_text(time_str, -1)
    ext_t = layout.get_pixel_extents()[1]

    # Clock shadow + crisp text
    cr.set_source_rgba(0, 0, 0, 0.30)
    cr.move_to((width - ext_t.width) / 2 + 2, 107)
    PangoCairo.show_layout(cr, layout)
    cr.set_source_rgba(1.0, 1.0, 1.0, 0.98)
    cr.move_to((width - ext_t.width) / 2, 105)
    PangoCairo.show_layout(cr, layout)

    # 2. User Avatar & Display Name
    avatar_size = 92
    avatar_x = (width - avatar_size) / 2
    avatar_y = 390

    if os.path.exists(AVATAR_PATH):
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(AVATAR_PATH, avatar_size, avatar_size, False)
            # Avatar soft drop shadow
            cr.arc(avatar_x + avatar_size / 2, avatar_y + avatar_size / 2 + 4, avatar_size / 2, 0, 2 * math.pi)
            cr.set_source_rgba(0, 0, 0, 0.35)
            cr.fill()

            # Circular profile picture
            cr.save()
            cr.arc(avatar_x + avatar_size / 2, avatar_y + avatar_size / 2, avatar_size / 2, 0, 2 * math.pi)
            cr.clip()
            Gdk.cairo_set_source_pixbuf(cr, pix, avatar_x, avatar_y)
            cr.paint()
            cr.restore()

            # Elegant white border
            cr.arc(avatar_x + avatar_size / 2, avatar_y + avatar_size / 2, avatar_size / 2, 0, 2 * math.pi)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.40)
            cr.set_line_width(2.0)
            cr.stroke()
        except Exception:
            pass

    # Display Name ("Sreyas")
    desc_user = Pango.font_description_from_string("Google Sans Flex, -apple-system, Cantarell, Sans SemiBold 15")
    layout.set_font_description(desc_user)
    layout.set_text("Sreyas", -1)
    ext_u = layout.get_pixel_extents()[1]

    cr.set_source_rgba(0, 0, 0, 0.30)
    cr.move_to((width - ext_u.width) / 2 + 1, avatar_y + avatar_size + 15)
    PangoCairo.show_layout(cr, layout)
    cr.set_source_rgba(1.0, 1.0, 1.0, 0.95)
    cr.move_to((width - ext_u.width) / 2, avatar_y + avatar_size + 14)
    PangoCairo.show_layout(cr, layout)

    # 3. macOS Sonoma Frosted Password Input Pill
    box_w, box_h, box_r = 240, 38, 19
    box_x = (width - box_w) / 2
    box_y = 534

    # Pill Drop Shadow
    round_rect(cr, box_x, box_y + 2, box_w, box_h, box_r)
    cr.set_source_rgba(0, 0, 0, 0.35)
    cr.fill()

    # Pill Frosted Glass Capsule
    round_rect(cr, box_x, box_y, box_w, box_h, box_r)
    cr.set_source_rgba(0.08, 0.10, 0.14, 0.82)
    cr.fill_preserve()
    cr.set_source_rgba(1.0, 1.0, 1.0, 0.28)
    cr.set_line_width(1.2)
    cr.stroke()

    # Inner Highlight Glow
    round_rect(cr, box_x + 1, box_y + 1, box_w - 2, box_h - 2, box_r - 1)
    cr.set_source_rgba(1.0, 1.0, 1.0, 0.08)
    cr.set_line_width(1.0)
    cr.stroke()

    # Placeholder text ("Enter Password")
    desc_pwd = Pango.font_description_from_string("Google Sans Flex, -apple-system, Cantarell, Sans 12")
    layout.set_font_description(desc_pwd)
    layout.set_text("Enter Password", -1)
    ext_p = layout.get_pixel_extents()[1]
    cr.set_source_rgba(1.0, 1.0, 1.0, 0.45)
    cr.move_to(box_x + 18, box_y + (box_h - ext_p.height) / 2)
    PangoCairo.show_layout(cr, layout)

    # Submit Arrow Button Circle on Right Edge
    btn_cx = box_x + box_w - 19
    btn_cy = box_y + box_h / 2
    btn_r = 13
    cr.new_sub_path()
    cr.arc(btn_cx, btn_cy, btn_r, 0, 2 * math.pi)
    cr.set_source_rgba(1.0, 1.0, 1.0, 0.14)
    cr.fill_preserve()
    cr.set_source_rgba(1.0, 1.0, 1.0, 0.26)
    cr.set_line_width(1.0)
    cr.stroke()

    # Arrow glyph inside circle
    desc_arr = Pango.font_description_from_string("Symbols Nerd Font, Sans 12")
    layout.set_font_description(desc_arr)
    layout.set_text("󰁔", -1)
    ext_a = layout.get_pixel_extents()[1]
    cr.set_source_rgba(1.0, 1.0, 1.0, 0.75)
    cr.move_to(btn_cx - ext_a.width / 2, btn_cy - ext_a.height / 2)
    PangoCairo.show_layout(cr, layout)

    # 4. macOS Sonoma Glassmorphic Music Hub (If Media is Active)
    meta = get_active_player_info()
    if meta:
        card_w, card_h = 520, 114
        card_x = (width - card_w) / 2
        card_y = 820

        # Card Drop Shadow
        round_rect(cr, card_x, card_y + 6, card_w, card_h, 26)
        cr.set_source_rgba(0, 0, 0, 0.45)
        cr.fill()

        # Frosted Glass Capsule
        round_rect(cr, card_x, card_y, card_w, card_h, 26)
        cr.set_source_rgba(0.08, 0.09, 0.13, 0.84)
        cr.fill_preserve()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.24)
        cr.set_line_width(1.4)
        cr.stroke()

        # Inner Highlight Border
        round_rect(cr, card_x + 1.5, card_y + 1.5, card_w - 3, card_h - 3, 24.5)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.08)
        cr.set_line_width(1.0)
        cr.stroke()

        # Album Art Thumbnail (82x82)
        art_x = card_x + 16
        art_y = card_y + 16
        art_size = 82
        art_pix = fetch_art_pixbuf(meta.get("art_url"), size=art_size)

        cr.save()
        round_rect(cr, art_x, art_y, art_size, art_size, 16)
        cr.clip()
        if art_pix:
            Gdk.cairo_set_source_pixbuf(cr, art_pix, art_x, art_y)
            cr.paint()
        else:
            pat = cairo.LinearGradient(art_x, art_y, art_x + art_size, art_y + art_size)
            pat.add_color_stop_rgba(0, 0.22, 0.25, 0.35, 1.0)
            pat.add_color_stop_rgba(1, 0.12, 0.14, 0.20, 1.0)
            cr.set_source(pat)
            cr.paint()
            layout.set_font_description(Pango.font_description_from_string("Symbols Nerd Font, Sans 28"))
            layout.set_text("󰝚", -1)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.6)
            cr.move_to(art_x + 27, art_y + 22)
            PangoCairo.show_layout(cr, layout)
        cr.restore()

        # Art border
        round_rect(cr, art_x, art_y, art_size, art_size, 16)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.18)
        cr.set_line_width(1.0)
        cr.stroke()

        # Typography
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        layout.set_width(260 * Pango.SCALE)

        desc_t = Pango.font_description_from_string("Google Sans Flex, Cantarell, -apple-system, Sans Bold 13.5")
        layout.set_font_description(desc_t)
        layout.set_text(meta.get("title", "Unknown Track"), -1)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.96)
        cr.move_to(card_x + 112, card_y + 22)
        PangoCairo.show_layout(cr, layout)

        desc_s = Pango.font_description_from_string("Google Sans Flex, Cantarell, -apple-system, Sans 11")
        layout.set_font_description(desc_s)
        artist = meta.get("artist", "Unknown Artist")
        album = meta.get("album", "")
        sub = f"{artist} • {album}" if album else artist
        layout.set_text(sub, -1)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.70)
        cr.move_to(card_x + 112, card_y + 45)
        PangoCairo.show_layout(cr, layout)

        # Timeline Scrubber / Progress Bar
        round_rect(cr, card_x + 112, card_y + 72, 260, 4, 2)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.16)
        cr.fill()

        length = meta.get("length", 0)
        pos = meta.get("position", 0)
        pct = (pos / length) if length > 0 else 0.35
        pct = max(0.04, min(1.0, pct))
        round_rect(cr, card_x + 112, card_y + 72, int(260 * pct), 4, 2)
        cr.set_source_rgba(0.04, 0.52, 1.0, 0.95)  # Apple Vibrant Blue
        cr.fill()

        # Playback Glyph Controls
        layout.set_width(-1)
        is_playing = meta.get("status", "").lower() == "playing"
        play_icon = "󰏤" if is_playing else "󰐊"
        controls = [
            ("󰒮", card_x + 396, card_y + 44, 13),
            (play_icon, card_x + 430, card_y + 42, 16),
            ("󰒭", card_x + 468, card_y + 44, 13)
        ]
        for sym, cx, cy, fsz in controls:
            desc_c = Pango.font_description_from_string(f"Symbols Nerd Font, Sans {fsz}")
            layout.set_font_description(desc_c)
            layout.set_text(sym, -1)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.88)
            cr.move_to(cx, cy)
            PangoCairo.show_layout(cr, layout)

    surface.write_to_png(output_path)
    return True

# -----------------------------------------------------------------------------
# GTK Layer-Shell Interactive Companion Window
# -----------------------------------------------------------------------------
class LockMediaOverlayWindow(Gtk.Window):
    def __init__(self, monitor):
        super().__init__()
        self.monitor = monitor

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_namespace(self, "lock-media")
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_exclusive_zone(self, 0)
        GtkLayerShell.set_monitor(self, self.monitor)

        # Centered at bottom (aligned with card_y = 820 on 1080p, margin = 146)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, False)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, 146)

        self.current_art_url = None
        self.setup_ui()
        self.apply_css()
        self.update_state()

        GLib.timeout_add(1000, self.on_timer_tick)
        GLib.timeout_add(400, self.check_watchdog)

    def setup_ui(self):
        self.card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.card.set_name("lock-media-card")
        self.card.set_size_request(520, 114)
        self.add(self.card)

        self.art_img = Gtk.Image()
        self.art_img.set_name("lock-media-art")
        self.art_img.set_size_request(82, 82)
        self.card.pack_start(self.art_img, False, False, 0)

        self.info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.info_box.set_valign(Gtk.Align.CENTER)
        self.card.pack_start(self.info_box, True, True, 0)

        self.title_lbl = Gtk.Label()
        self.title_lbl.set_name("lock-media-title")
        self.title_lbl.set_xalign(0.0)
        self.title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_lbl.set_max_width_chars(26)
        self.info_box.pack_start(self.title_lbl, False, False, 0)

        self.artist_lbl = Gtk.Label()
        self.artist_lbl.set_name("lock-media-artist")
        self.artist_lbl.set_xalign(0.0)
        self.artist_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.artist_lbl.set_max_width_chars(30)
        self.info_box.pack_start(self.artist_lbl, False, False, 0)

        self.progress = Gtk.ProgressBar()
        self.progress.set_name("lock-media-progress")
        self.progress.set_fraction(0.0)
        self.info_box.pack_start(self.progress, False, False, 2)

        self.ctrl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.ctrl_box.set_valign(Gtk.Align.CENTER)
        self.card.pack_start(self.ctrl_box, False, False, 0)

        self.prev_btn = Gtk.Button(label="󰒮")
        self.prev_btn.get_style_context().add_class("media-btn")
        self.prev_btn.connect("clicked", lambda *_: subprocess.Popen(["playerctl", "previous"]))
        self.ctrl_box.pack_start(self.prev_btn, False, False, 0)

        self.play_btn = Gtk.Button(label="󰏤")
        self.play_btn.get_style_context().add_class("media-btn")
        self.play_btn.get_style_context().add_class("media-play-btn")
        self.play_btn.connect("clicked", lambda *_: subprocess.Popen(["playerctl", "play-pause"]))
        self.ctrl_box.pack_start(self.play_btn, False, False, 0)

        self.next_btn = Gtk.Button(label="󰒭")
        self.next_btn.get_style_context().add_class("media-btn")
        self.next_btn.connect("clicked", lambda *_: subprocess.Popen(["playerctl", "next"]))
        self.ctrl_box.pack_start(self.next_btn, False, False, 0)

    def apply_css(self):
        css_provider = Gtk.CssProvider()
        css = """
        * {
            font-family: Google Sans Flex, Cantarell, -apple-system, BlinkMacSystemFont, "SF Pro Display", "Symbols Nerd Font", sans-serif;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }

        window {
            background: transparent;
        }

        #lock-media-card {
            background-color: rgba(20, 22, 28, 0.84);
            border: 1.2px solid rgba(255, 255, 255, 0.24);
            border-radius: 26px;
            padding: 12px 18px;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.25), 0 18px 40px rgba(0, 0, 0, 0.55);
        }

        #lock-media-art {
            border-radius: 16px;
            border: 1px solid rgba(255, 255, 255, 0.18);
        }

        #lock-media-title {
            font-size: 13.5px;
            font-weight: bold;
            color: #ffffff;
        }

        #lock-media-artist {
            font-size: 11px;
            color: rgba(255, 255, 255, 0.72);
        }

        #lock-media-progress trough {
            min-height: 4px;
            border-radius: 2px;
            background-color: rgba(255, 255, 255, 0.18);
        }

        #lock-media-progress progress {
            min-height: 4px;
            border-radius: 2px;
            background-color: #0a84ff;
        }

        .media-btn {
            background-color: rgba(255, 255, 255, 0.12);
            border: 1px solid rgba(255, 255, 255, 0.22);
            border-radius: 9999px;
            color: #ffffff;
            font-size: 14px;
            min-width: 34px;
            min-height: 34px;
            padding: 0;
            box-shadow: none;
        }

        .media-btn:hover {
            background-color: rgba(255, 255, 255, 0.28);
            border-color: rgba(255, 255, 255, 0.45);
        }

        .media-play-btn {
            min-width: 40px;
            min-height: 40px;
            font-size: 16px;
            background-color: rgba(255, 255, 255, 0.22);
        }
        """
        css_provider.load_from_data(css.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def update_state(self):
        info = get_active_player_info()
        if not info:
            self.hide()
            return False

        self.title_lbl.set_text(info.get("title", "Unknown Track"))
        artist = info.get("artist", "Unknown Artist")
        album = info.get("album", "")
        self.artist_lbl.set_text(f"{artist} • {album}" if album else artist)

        is_playing = info.get("status", "").lower() == "playing"
        self.play_btn.set_label("󰏤" if is_playing else "󰐊")

        length = info.get("length", 0)
        pos = info.get("position", 0)
        pct = (pos / length) if length > 0 else 0.0
        self.progress.set_fraction(max(0.0, min(1.0, pct)))

        art_url = info.get("art_url")
        if art_url != self.current_art_url:
            self.current_art_url = art_url
            pix = fetch_art_pixbuf(art_url, size=82)
            if pix:
                self.art_img.set_from_pixbuf(pix)
            else:
                self.art_img.set_from_icon_name("audio-x-generic", Gtk.IconSize.DND)

        self.show_all()
        return True

    def on_timer_tick(self):
        self.update_state()
        return True

    def check_watchdog(self):
        if not is_swaylock_running():
            cleanup()
            return False
        return True

# -----------------------------------------------------------------------------
# Process & Lifecycle Management
# -----------------------------------------------------------------------------
def cleanup(*_):
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except OSError:
        pass
    Gtk.main_quit()

def render_media_background(output_path, base_wall=None):
    """
    Renders the blurred wallpaper combined with the floating music widget at y=820.
    Used as the background for gtklock.
    """
    if not base_wall:
        base_wall = os.path.expanduser("~/.cache/current_wallpaper_blurred.png")

    width, height = 1920, 1080
    pix = None
    if os.path.exists(base_wall):
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file(base_wall)
            width = pix.get_width()
            height = pix.get_height()
        except Exception:
            pix = None

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)

    if pix:
        Gdk.cairo_set_source_pixbuf(cr, pix, 0, 0)
        cr.paint()
    else:
        cr.set_source_rgba(0.08, 0.09, 0.13, 1.0)
        cr.paint()

    meta = get_active_player_info()
    if meta:
        card_w, card_h = 520, 114
        card_x = (width - card_w) / 2
        card_y = 820

        # Card Drop Shadow
        round_rect(cr, card_x, card_y + 6, card_w, card_h, 26)
        cr.set_source_rgba(0, 0, 0, 0.45)
        cr.fill()

        # Frosted Glass Capsule
        round_rect(cr, card_x, card_y, card_w, card_h, 26)
        cr.set_source_rgba(0.08, 0.09, 0.13, 0.84)
        cr.fill_preserve()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.24)
        cr.set_line_width(1.4)
        cr.stroke()

        # Inner Highlight Border
        round_rect(cr, card_x + 1.5, card_y + 1.5, card_w - 3, card_h - 3, 24.5)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.08)
        cr.set_line_width(1.0)
        cr.stroke()

        # Album Art Thumbnail (82x82)
        art_x = card_x + 16
        art_y = card_y + 16
        art_size = 82
        art_pix = fetch_art_pixbuf(meta.get("art_url"), size=art_size)

        cr.save()
        round_rect(cr, art_x, art_y, art_size, art_size, 16)
        cr.clip()
        layout = PangoCairo.create_layout(cr)
        if art_pix:
            Gdk.cairo_set_source_pixbuf(cr, art_pix, art_x, art_y)
            cr.paint()
        else:
            pat = cairo.LinearGradient(art_x, art_y, art_x + art_size, art_y + art_size)
            pat.add_color_stop_rgba(0, 0.22, 0.25, 0.35, 1.0)
            pat.add_color_stop_rgba(1, 0.12, 0.14, 0.20, 1.0)
            cr.set_source(pat)
            cr.paint()
            layout.set_font_description(Pango.font_description_from_string("Symbols Nerd Font, Sans 28"))
            layout.set_text("󰝚", -1)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.6)
            cr.move_to(art_x + 27, art_y + 22)
            PangoCairo.show_layout(cr, layout)
        cr.restore()

        # Art border
        round_rect(cr, art_x, art_y, art_size, art_size, 16)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.18)
        cr.set_line_width(1.0)
        cr.stroke()

        # Typography
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        layout.set_width(260 * Pango.SCALE)

        desc_t = Pango.font_description_from_string("Google Sans Flex, Cantarell, -apple-system, Sans Bold 13.5")
        layout.set_font_description(desc_t)
        layout.set_text(meta.get("title", "Unknown Track"), -1)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.96)
        cr.move_to(card_x + 112, card_y + 22)
        PangoCairo.show_layout(cr, layout)

        desc_s = Pango.font_description_from_string("Google Sans Flex, Cantarell, -apple-system, Sans 11")
        layout.set_font_description(desc_s)
        artist = meta.get("artist", "Unknown Artist")
        album = meta.get("album", "")
        sub = f"{artist} • {album}" if album else artist
        layout.set_text(sub, -1)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.70)
        cr.move_to(card_x + 112, card_y + 45)
        PangoCairo.show_layout(cr, layout)

        # Timeline Scrubber / Progress Bar
        round_rect(cr, card_x + 112, card_y + 72, 260, 4, 2)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.16)
        cr.fill()

        length = meta.get("length", 0)
        pos = meta.get("position", 0)
        pct = (pos / length) if length > 0 else 0.35
        pct = max(0.04, min(1.0, pct))
        round_rect(cr, card_x + 112, card_y + 72, int(260 * pct), 4, 2)
        cr.set_source_rgba(0.04, 0.52, 1.0, 0.95)
        cr.fill()

        # Playback Glyph Controls
        layout.set_width(-1)
        is_playing = meta.get("status", "").lower() == "playing"
        play_icon = "󰏤" if is_playing else "󰐊"
        controls = [
            ("󰒮", card_x + 396, card_y + 44, 13),
            (play_icon, card_x + 430, card_y + 42, 16),
            ("󰒭", card_x + 468, card_y + 44, 13)
        ]
        for sym, cx, cy, fsz in controls:
            desc_c = Pango.font_description_from_string(f"Symbols Nerd Font, Sans {fsz}")
            layout.set_font_description(desc_c)
            layout.set_text(sym, -1)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.88)
            cr.move_to(cx, cy)
            PangoCairo.show_layout(cr, layout)

    surface.write_to_png(output_path)
    return True

def main():
    parser = argparse.ArgumentParser(description="macOS Sonoma Lockscreen Media Hub")
    parser.add_argument("--generate-overlay", metavar="PATH", help="Render complete macOS Sonoma canvas overlay to PNG")
    parser.add_argument("--generate-media-bg", metavar="PATH", help="Render blurred wallpaper with media widget for gtklock")
    parser.add_argument("--daemon", action="store_true", help="Launch layer-shell companion daemon")
    args = parser.parse_args()

    if args.generate_overlay:
        ok = render_sonoma_overlay(args.generate_overlay)
        sys.exit(0 if ok else 1)

    if args.generate_media_bg:
        ok = render_media_background(args.generate_media_bg)
        sys.exit(0 if ok else 1)

    # Daemon mode
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            sys.exit(0)
        except (OSError, ValueError):
            try:
                os.remove(PID_FILE)
            except OSError:
                pass

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, cleanup)

    display = Gdk.Display.get_default()
    if not display:
        sys.exit(1)

    primary_mon = display.get_primary_monitor() or display.get_monitor(0)
    win = LockMediaOverlayWindow(primary_mon)

    try:
        Gtk.main()
    finally:
        cleanup()

if __name__ == "__main__":
    main()
