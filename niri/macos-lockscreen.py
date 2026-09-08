#!/usr/bin/python3
"""
macOS Sonoma Native Lock Screen for Niri Wayland Compositor.
Features:
- ext-session-lock-v1 protocol via GtkSessionLock
- Apple Frosted Glass Clock & Typography (Cairo/PangoCairo multi-pass gradient & ambient drop shadows)
- Dynamic Live/Video Wallpaper support via GStreamer hardware-accelerated gtksink
- Pixel-perfect circular clipped profile picture with border and shadow
- macOS frosted password pill with GtkEntry, hidden dots, last-character peek, and submit arrow
- Interactive music card at bottom (Play/Pause, Next, Prev, album art, progress bar)
- Full mouse pointer and mouse click support
- PAM authentication (with Howdy face unlock & unix_chkpwd support)
"""

import os
import sys
import math
import time
import signal
import getpass
import hashlib
import subprocess
import urllib.parse
import urllib.request
import pwd
import argparse
import threading

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GtkSessionLock', '0.1')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gtk, Gdk, GtkSessionLock, GLib, GdkPixbuf, Pango, PangoCairo, Gst
import cairo
import numpy as np
import scipy.ndimage
import pam

PID_FILE = "/tmp/macos_lockscreen.pid"
ART_CACHE_DIR = "/tmp/swaylock_art_cache"
AVATAR_PATH = os.path.expanduser("~/.face.icon")
if not os.path.exists(AVATAR_PATH):
    AVATAR_PATH = os.path.expanduser("~/.face")

VIDEO_EXTENSIONS = ('.mp4', '.mov', '.webm', '.mkv', '.avi', '.gif')

os.makedirs(ART_CACHE_DIR, exist_ok=True)

# -----------------------------------------------------------------------------
# Wallpaper Source Resolver
# -----------------------------------------------------------------------------
def get_wallpaper_source(cli_override=None):
    if cli_override and cli_override != "auto":
        expanded = os.path.abspath(os.path.expanduser(cli_override))
        if os.path.isfile(expanded):
            return expanded

    if cli_override == "auto":
        live_dir = os.path.expanduser("~/wall/live")
        if os.path.isdir(live_dir):
            videos = [os.path.join(live_dir, f) for f in os.listdir(live_dir) if f.lower().endswith(VIDEO_EXTENSIONS)]
            if videos:
                videos.sort()
                return videos[0]

    # Check dedicated lockscreen wallpaper override
    lock_wall = os.path.expanduser("~/.cache/lockscreen_wallpaper")
    if os.path.isfile(lock_wall):
        try:
            with open(lock_wall, "r") as f:
                path = f.read().strip()
            if os.path.isfile(path):
                return path
        except Exception:
            pass

    # Check active desktop wallpaper
    curr_wall = os.path.expanduser("~/.cache/current_wallpaper")
    if os.path.isfile(curr_wall):
        try:
            with open(curr_wall, "r") as f:
                path = f.read().strip()
            if os.path.isfile(path):
                return path
        except Exception:
            pass

    # Fallback static wallpaper
    default_static = os.path.expanduser("~/wall/wall-05.png")
    if os.path.isfile(default_static):
        return default_static
    return None

# -----------------------------------------------------------------------------
# System Status Query (Battery, Audio, Wi-Fi, DND)
# -----------------------------------------------------------------------------
def get_system_status():
    """
    Queries battery, volume, wifi, and DND status with low-latency fallbacks.
    """
    # 1. Battery & Power
    bat_info = {"percent": 100, "charging": False, "status": "Full"}
    try:
        if os.path.exists("/sys/class/power_supply"):
            bats = [d for d in os.listdir("/sys/class/power_supply") if d.startswith("BAT")]
            if bats:
                bat_dir = os.path.join("/sys/class/power_supply", bats[0])
                cap_file = os.path.join(bat_dir, "capacity")
                stat_file = os.path.join(bat_dir, "status")
                cap = int(open(cap_file).read().strip()) if os.path.exists(cap_file) else 100
                stat = open(stat_file).read().strip() if os.path.exists(stat_file) else "Full"
                charging = stat.lower() in ("charging", "pending-charge")
                if not charging:
                    for ac in os.listdir("/sys/class/power_supply"):
                        if ac.startswith("AC") or ac.startswith("ADP"):
                            f = os.path.join("/sys/class/power_supply", ac, "online")
                            if os.path.exists(f) and open(f).read().strip() == "1":
                                charging = True
                                break
                bat_info = {"percent": cap, "charging": charging, "status": stat}
    except Exception:
        pass

    # 2. Volume
    vol_info = {"volume": 0.5, "muted": False}
    try:
        res = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=0.3)
        if res.returncode == 0:
            out = res.stdout.strip()
            parts = out.split()
            vol = float(parts[1]) if len(parts) >= 2 else 0.5
            vol_info = {"volume": vol, "muted": "[MUTED]" in out}
    except Exception:
        pass

    # 3. Wi-Fi
    wifi_info = {"connected": False, "signal": 0}
    try:
        res = subprocess.run(["nmcli", "-t", "-f", "active,ssid,signal", "dev", "wifi"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=0.5)
        if res.returncode == 0:
            for line in res.stdout.strip().split("\n"):
                if line.startswith("yes:"):
                    p = line.split(":")
                    wifi_info = {"connected": True, "signal": int(p[2]) if len(p) > 2 and p[2].isdigit() else 80}
                    break
    except Exception:
        pass

    # 4. DND (Do Not Disturb)
    dnd = False
    try:
        res = subprocess.run(["swaync-client", "-D"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=0.3)
        if res.returncode == 0:
            dnd = res.stdout.strip().lower() == "true"
    except Exception:
        pass

    # 5. Bluetooth
    bt_info = {"connected": False, "name": ""}
    try:
        res = subprocess.run(["bluetoothctl", "devices", "Connected"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=0.3)
        if res.returncode == 0 and res.stdout.strip():
            lines = [l.strip() for l in res.stdout.strip().split("\n") if l.strip()]
            if lines:
                parts = lines[0].split(maxsplit=2)
                name = parts[2] if len(parts) >= 3 else "Headphones"
                bt_info = {"connected": True, "name": name}
    except Exception:
        pass

    return {"battery": bat_info, "audio": vol_info, "wifi": wifi_info, "dnd": dnd, "bluetooth": bt_info}

# -----------------------------------------------------------------------------
# Metadata & Playerctl Query
# -----------------------------------------------------------------------------
def get_active_player_info():
    try:
        cmd = [
            "playerctl", "-a", "metadata",
            "--format", "{{status}};;;{{artist}};;;{{title}};;;{{album}};;;{{mpris:artUrl}};;;{{position}};;;{{mpris:length}}"
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1.2)
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
                    return info
                if selected is None:
                    selected = info
        return selected
    except Exception:
        return None

def fetch_art_pixbuf(art_url, size=82):
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
                with urllib.request.urlopen(req, timeout=1.5) as resp, open(cached, "wb") as f:
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

def round_rect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()

def create_gaussian_shadow_surface(w, h, radius, blur_sigma=22, offset_y=12, opacity=0.32, pad=44):
    """
    Creates a perfectly smooth Gaussian blurred shadow surface.
    Zero stepped bands, zero harsh silhouettes.
    """
    sw = w + pad * 2
    sh = h + pad * 2
    surf = cairo.ImageSurface(cairo.FORMAT_A8, sw, sh)
    cr = cairo.Context(surf)
    rx, ry = pad, pad
    r = radius
    round_rect(cr, rx, ry, w, h, r)
    cr.set_source_rgba(1, 1, 1, 1)
    cr.fill()

    buf = surf.get_data()
    stride = surf.get_stride()
    arr = np.frombuffer(buf, dtype=np.uint8).reshape((sh, stride))[:, :sw].astype(float)
    blurred = scipy.ndimage.gaussian_filter(arr, sigma=blur_sigma)
    blurred_alpha = np.clip(blurred * opacity, 0, 255).astype(np.uint8)

    out_b = np.zeros_like(blurred_alpha)
    out_g = np.zeros_like(blurred_alpha)
    out_r = np.zeros_like(blurred_alpha)
    out_buf = np.ascontiguousarray(np.stack([out_b, out_g, out_r, blurred_alpha], axis=-1))
    out_surf = cairo.ImageSurface.create_for_data(out_buf, cairo.FORMAT_ARGB32, sw, sh, sw * 4)
    return out_surf, out_buf, pad

def create_macos_liquid_glass_card(bg_sub, w, h, radius=26):
    """
    Authentic macOS Liquid Glass material:
    - Optical displacement & chromatic dispersion from background wallpaper
    - Crisp translucent acrylic glass substrate
    - 1.35x vibrancy saturation boost
    """
    H, W = h, w
    r = radius
    y_coords, x_coords = np.mgrid[0:H, 0:W]
    dx = np.maximum(np.abs(x_coords - W / 2.0) - (W / 2.0 - r), 0.0)
    dy = np.maximum(np.abs(y_coords - H / 2.0) - (H / 2.0 - r), 0.0)
    dist = np.sqrt(dx**2 + dy**2) - r
    inside = dist <= 0.0

    # Gentle optical displacement (convex magnification)
    dir_x = (x_coords - W / 2.0) / (W / 2.0)
    dir_y = (y_coords - H / 2.0) / (H / 2.0)
    disp_mag = 0.04 * 18.0 * (1.0 - (dir_x**2 + dir_y**2) * 0.3)

    # 3-pass chromatic dispersion
    disp_r = 0.40
    sx_r = np.clip(x_coords + dir_x * disp_mag * (1.0 + disp_r * 0.4), 0, W - 1)
    sy_r = np.clip(y_coords + dir_y * disp_mag * (1.0 + disp_r * 0.4), 0, H - 1)
    sx_g = np.clip(x_coords + dir_x * disp_mag, 0, W - 1)
    sy_g = np.clip(y_coords + dir_y * disp_mag, 0, H - 1)
    sx_b = np.clip(x_coords + dir_x * disp_mag * (1.0 - disp_r * 0.4), 0, W - 1)
    sy_b = np.clip(y_coords + dir_y * disp_mag * (1.0 - disp_r * 0.4), 0, H - 1)

    def sample(img, sx, sy, ch):
        x0 = np.floor(sx).astype(int)
        x1 = np.clip(x0 + 1, 0, W - 1)
        y0 = np.floor(sy).astype(int)
        y1 = np.clip(y0 + 1, 0, H - 1)
        wa = (x1 - sx) * (y1 - sy)
        wb = (sx - x0) * (y1 - sy)
        wc = (x1 - sx) * (sy - y0)
        wd = (sx - x0) * (sy - y0)
        return img[y0, x0, ch] * wa + img[y0, x1, ch] * wb + img[y1, x0, ch] * wc + img[y1, x1, ch] * wd

    ref_r = sample(bg_sub, sx_r, sy_r, 0)
    ref_g = sample(bg_sub, sx_g, sy_g, 1)
    ref_b = sample(bg_sub, sx_b, sy_b, 2)

    # Saturation boost (1.35x vibrancy)
    luma = 0.299 * ref_r + 0.587 * ref_g + 0.114 * ref_b
    ref_r = np.clip(luma + (ref_r - luma) * 1.35, 0, 255)
    ref_g = np.clip(luma + (ref_g - luma) * 1.35, 0, 255)
    ref_b = np.clip(luma + (ref_b - luma) * 1.35, 0, 255)

    # Blend with Apple crystalline liquid glass tint (luminous frost + wallpaper vibrancy)
    y_norm = np.linspace(0.0, 1.0, H)[:, None]
    white_veil = (0.30 - 0.15 * y_norm) * 255.0

    glass_r = np.clip(ref_r * 0.72 + white_veil * 0.20 + 16.0 * 0.08, 0, 255)
    glass_g = np.clip(ref_g * 0.72 + white_veil * 0.20 + 20.0 * 0.08, 0, 255)
    glass_b = np.clip(ref_b * 0.72 + white_veil * 0.20 + 32.0 * 0.08, 0, 255)

    alpha_mask = np.where(inside, 255.0, 0.0)
    edge_aa = np.clip(-dist, 0.0, 1.0)
    alpha = (alpha_mask * edge_aa).astype(np.uint8)

    pm_b = (glass_b * (alpha / 255.0)).astype(np.uint8)
    pm_g = (glass_g * (alpha / 255.0)).astype(np.uint8)
    pm_r = (glass_r * (alpha / 255.0)).astype(np.uint8)

    cairo_buf = np.ascontiguousarray(np.stack([pm_b, pm_g, pm_r, alpha], axis=-1))
    surf = cairo.ImageSurface.create_for_data(cairo_buf, cairo.FORMAT_ARGB32, W, H, W * 4)
    return surf, cairo_buf

# -----------------------------------------------------------------------------
# CSS Styling (macOS Sonoma Glassmorphism)
# -----------------------------------------------------------------------------
CSS = """
* {
    font-family: "Google Sans Flex", -apple-system, BlinkMacSystemFont, "Cantarell", "SF Pro Display", sans-serif;
    font-feature-settings: "tnum";
}

window {
    background-color: transparent;
}

#dynamic-island {
    background-color: transparent;
    background-image: none;
    background: none;
    border: none;
    box-shadow: none;
}

#user-lbl {
    font-size: 17px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.98);
    text-shadow: 0 1px 6px rgba(0, 0, 0, 0.85), 0 0 3px rgba(0, 0, 0, 0.90);
    margin-top: 10px;
}

/* macOS Frosted Password Input Pill */
#pwd-pill {
    background-color: rgba(18, 22, 30, 0.60);
    border: 1.2px solid rgba(255, 255, 255, 0.28);
    border-radius: 20px;
    padding: 3px 6px 3px 14px;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.22), 0 8px 24px rgba(0, 0, 0, 0.50);
    min-width: 240px;
    transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

#pwd-pill:focus-within {
    border-color: rgba(10, 132, 255, 0.85);
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.30), 0 0 0 2px rgba(10, 132, 255, 0.40), 0 8px 24px rgba(0, 0, 0, 0.55);
}

#pwd-pill.error {
    border-color: rgba(255, 69, 58, 0.90);
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.15), 0 0 0 2px rgba(255, 69, 58, 0.50), 0 8px 24px rgba(0, 0, 0, 0.55);
}

#pwd-entry {
    background: transparent;
    border: none;
    outline: none;
    box-shadow: none;
    color: rgba(255, 255, 255, 0.96);
    font-size: 14px;
    caret-color: #0a84ff;
}

#pwd-entry placeholder {
    color: rgba(255, 255, 255, 0.45);
    font-size: 12.5px;
}

#submit-btn {
    background-color: rgba(255, 255, 255, 0.14);
    border: 1px solid rgba(255, 255, 255, 0.25);
    border-radius: 14px;
    min-width: 28px;
    min-height: 28px;
    padding: 0;
    color: rgba(255, 255, 255, 0.85);
    font-family: "Symbols Nerd Font", sans-serif;
    font-size: 13px;
    transition: all 0.15s ease;
}

#submit-btn:hover {
    background-color: #0a84ff;
    border-color: #0a84ff;
    color: white;
}

#submit-btn:active {
    background-color: #0071e3;
}

#error-lbl {
    color: #ff453a;
    font-size: 12.5px;
    font-weight: 500;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
    margin-top: 6px;
    min-height: 16px;
}

#caps-indicator {
    font-family: "Symbols Nerd Font", "Google Sans Flex", sans-serif;
    color: rgba(255, 255, 255, 0.95);
    background-color: rgba(255, 255, 255, 0.20);
    border: 1px solid rgba(255, 255, 255, 0.30);
    border-radius: 6px;
    font-size: 13px;
    font-weight: 700;
    padding: 1px 6px;
    margin-right: 4px;
    box-shadow: 0 0 8px rgba(255, 255, 255, 0.30);
}

#face-id-lbl {
    font-family: "Symbols Nerd Font", "Google Sans Flex", sans-serif;
    font-size: 13px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.75);
    margin-top: 6px;
    text-shadow: 0 1px 4px rgba(0, 0, 0, 0.60);
}

#face-id-lbl.face-success {
    color: #34C759;
    font-weight: 600;
    text-shadow: 0 0 10px rgba(52, 199, 89, 0.60);
}

/* Apple Liquid Glass Music Card (Foreground Box) */
#music-card {
    background: transparent;
    border: none;
    box-shadow: none;
    padding: 12px 18px;
}

#music-title {
    font-size: 14px;
    font-weight: 700;
    color: rgba(255, 255, 255, 0.98);
    text-shadow: 0 1px 4px rgba(0, 0, 0, 0.65);
}

#music-sub {
    font-size: 11.5px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.72);
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.45);
}

.media-btn {
    background-image: none;
    background-color: rgba(255, 255, 255, 0.12);
    border: 1px solid rgba(255, 255, 255, 0.28);
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
    color: rgba(255, 255, 255, 0.90);
    font-family: "Symbols Nerd Font", sans-serif;
    font-size: 14px;
    min-width: 32px;
    min-height: 32px;
    padding: 0;
    margin: 0;
    border-radius: 16px;
    outline: none;
    transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}

.media-btn:hover {
    color: #ffffff;
    background-image: none;
    background-color: rgba(255, 255, 255, 0.25);
    border-color: rgba(255, 255, 255, 0.45);
    box-shadow: 0 3px 10px rgba(0, 0, 0, 0.35);
}

.media-btn:active {
    background-image: none;
    background-color: rgba(255, 255, 255, 0.16);
}

.media-play-btn {
    min-width: 38px;
    min-height: 38px;
    border-radius: 19px;
    background-image: none;
    background-color: rgba(255, 255, 255, 0.22);
    border: 1px solid rgba(255, 255, 255, 0.40);
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.32), 0 3px 8px rgba(0, 0, 0, 0.30);
    font-size: 17px;
    color: #ffffff;
}

.media-play-btn:hover {
    background-image: none;
    background-color: rgba(255, 255, 255, 0.32);
    border-color: rgba(255, 255, 255, 0.55);
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.40), 0 4px 14px rgba(0, 0, 0, 0.35);
}

#progress-bar trough, #progress-bar progress {
    min-height: 4px;
    border-radius: 2px;
}

#progress-bar trough {
    background-color: rgba(255, 255, 255, 0.18);
    box-shadow: inset 0 0.5px 1px rgba(0, 0, 0, 0.30);
}

#progress-bar progress {
    background: linear-gradient(90deg, #0a84ff, #5ac8fa);
    box-shadow: 0 0 6px rgba(10, 132, 255, 0.50);
}
"""

# -----------------------------------------------------------------------------
# Apple Dynamic Island Face ID HUD (iOS Style Top-Center)
# -----------------------------------------------------------------------------
class AppleDynamicIslandWidget(Gtk.DrawingArea):
    """
    Apple Dynamic Island Face ID Biometric HUD — complete rewrite.

    Shape: Superellipse (squircle) |x/a|^n + |y/b|^n = 1
    Idle: Compact black pill (126×36, n=2.0) at top-center
    Expanded: Soft squircle (100×100, n=4.5) with padlock + scanning arc
    Expand: Critically-damped spring (280ms, zero bounce)
    Success: Padlock shackle opens → green checkmark morph (180ms)
    Contract: Under-damped spring with rubber-band bounce (350ms)
    Canvas: OPERATOR_CLEAR each frame to avoid compositor ghosting
    """

    # Geometry constants
    IDLE_W, IDLE_H = 126.0, 36.0
    SQ_SIZE = 100.0
    N_PILL = 2.0
    N_SQUARE = 4.5

    # Timing constants (seconds)
    T_EXPAND = 0.28
    T_SUCCESS = 0.18
    T_CONTRACT = 0.35
    T_FAILED = 0.35

    def __init__(self):
        super().__init__()
        self.set_size_request(200, 130)
        # Prevent GTK from painting the theme's default widget background
        self.set_app_paintable(True)
        # No own GdkWindow: draw directly on parent's surface.
        # This eliminates the opaque background rectangle entirely.
        self.set_has_window(False)
        self.set_name("dynamic-island")
        self.state = "idle"
        self.anim_t0 = 0.0       # global animation start (for scanning arc rotation)
        self.expand_t0 = 0.0
        self.success_t0 = 0.0
        self.contract_t0 = 0.0
        self.failed_t0 = 0.0
        self.success_cb = None
        self.tick_id = None
        self.connect("draw", self.on_draw)

    # --- Static geometry helper ---
    @staticmethod
    def draw_squircle_path(cr, cx, cy, w, h, n=4.5):
        """Draw a superellipse: |x/a|^n + |y/b|^n = 1"""
        a, b = w / 2.0, h / 2.0
        steps = 120
        cr.new_sub_path()
        for i in range(steps + 1):
            theta = 2.0 * math.pi * i / steps
            ct, st = math.cos(theta), math.sin(theta)
            sc = 1.0 if ct >= 0 else -1.0
            ss = 1.0 if st >= 0 else -1.0
            x = cx + a * sc * (abs(ct) ** (2.0 / n))
            y = cy + b * ss * (abs(st) ** (2.0 / n))
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.close_path()

    # --- Spring physics ---
    @staticmethod
    def _spring_expand(t, duration=0.28):
        """Critically-damped spring: fast expand, zero bounce/oscillation."""
        p = min(1.0, max(0.0, t / duration))
        omega = 14.0
        return min(1.0, max(0.0, 1.0 - (1.0 + omega * p) * math.exp(-omega * p)))

    @staticmethod
    def _spring_contract(t, duration=0.35):
        """Under-damped spring: rubber-band snap-back with overshoot."""
        p = min(1.0, max(0.0, t / duration))
        omega = 22.0
        zeta = 0.55
        wd = omega * math.sqrt(max(0.001, 1.0 - zeta * zeta))
        # Shape from 1 → 0 with slight overshoot past 0
        val = (1.0 - p) + math.exp(-zeta * omega * p) * (math.cos(wd * p) - 1.0) * 0.3
        return max(0.0, min(1.0, val))

    # --- State transitions ---
    def _ensure_ticking(self):
        if not self.tick_id:
            self.tick_id = self.add_tick_callback(self._on_tick)

    def start_scanning(self):
        """Begin the Face ID scanning animation (expand pill → squircle)."""
        self.state = "expanding"
        now = time.time()
        self.anim_t0 = now
        self.expand_t0 = now
        self.set_opacity(1.0)
        self._ensure_ticking()
        self.queue_draw()

    def set_success(self, callback=None):
        """Face recognized — morph padlock → checkmark, then contract."""
        if self.state in ("success", "contracting"):
            return
        self.state = "success"
        self.success_t0 = time.time()
        self.success_cb = callback
        self._ensure_ticking()
        self.queue_draw()

    def set_failed(self):
        """Face not recognized — shake and contract."""
        if self.state in ("failed", "contracting_failed"):
            return
        self.state = "failed"
        self.failed_t0 = time.time()
        self._ensure_ticking()
        self.queue_draw()

    def set_idle(self):
        """Return to idle state (completely invisible)."""
        self.state = "idle"
        self._stop_tick()
        self.queue_draw()

    def _stop_tick(self):
        if self.tick_id:
            try:
                self.remove_tick_callback(self.tick_id)
            except Exception:
                pass
            self.tick_id = None

    # --- Frame tick dispatcher ---
    def _on_tick(self, widget, frame_clock):
        now = time.time()

        if self.state == "expanding":
            if now - self.expand_t0 >= self.T_EXPAND:
                self.state = "scanning"
            self.queue_draw()
            return GLib.SOURCE_CONTINUE

        elif self.state == "scanning":
            self.queue_draw()
            return GLib.SOURCE_CONTINUE

        elif self.state == "success":
            elapsed = now - self.success_t0
            if elapsed >= self.T_SUCCESS:
                self.state = "contracting"
                self.contract_t0 = now
                cb = self.success_cb
                self.success_cb = None
                if cb:
                    cb()
            self.queue_draw()
            return GLib.SOURCE_CONTINUE

        elif self.state == "contracting":
            if now - self.contract_t0 >= self.T_CONTRACT:
                self.set_idle()
                return GLib.SOURCE_REMOVE
            self.queue_draw()
            return GLib.SOURCE_CONTINUE

        elif self.state == "failed":
            if now - self.failed_t0 >= self.T_FAILED:
                self.state = "contracting_failed"
                self.contract_t0 = now
            self.queue_draw()
            return GLib.SOURCE_CONTINUE

        elif self.state == "contracting_failed":
            if now - self.contract_t0 >= self.T_CONTRACT:
                self.set_idle()
                return GLib.SOURCE_REMOVE
            self.queue_draw()
            return GLib.SOURCE_CONTINUE

        self._stop_tick()
        return GLib.SOURCE_REMOVE

    # --- Rendering ---
    def on_draw(self, widget, cr):
        if self.state == "idle":
            return False

        alloc = self.get_allocation()
        CW, CH = alloc.width, alloc.height
        if CW <= 0 or CH <= 0:
            CW, CH = 200, 130

        now = time.time()
        cx = CW / 2.0
        top_y = 14.0
        IW, IH = self.IDLE_W, self.IDLE_H
        SQ = self.SQ_SIZE

        # ---- Compute per-frame interpolated parameters ----
        cur_w = IW
        cur_h = IH
        n_exp = self.N_PILL
        global_alpha = 1.0
        icon_alpha = 0.0
        icon_scale = 0.001
        morph_p = 0.0           # 0=padlock, 1=checkmark
        scan_angle = 0.0
        shake_x = 0.0
        rim_green = 0.0
        rim_red = 0.0

        if self.state == "expanding":
            s = self._spring_expand(now - self.expand_t0, self.T_EXPAND)
            cur_w = IW + (SQ - IW) * s
            cur_h = IH + (SQ - IH) * s
            n_exp = self.N_PILL + (self.N_SQUARE - self.N_PILL) * s
            global_alpha = min(1.0, (now - self.expand_t0) / 0.12)
            icon_alpha = min(1.0, s * 1.5)
            icon_scale = max(0.001, s)
            scan_angle = (now - self.anim_t0) * 5.0

        elif self.state == "scanning":
            cur_w, cur_h = SQ, SQ
            n_exp = self.N_SQUARE
            global_alpha = 1.0
            icon_alpha = 1.0
            icon_scale = 1.0
            scan_angle = (now - self.anim_t0) * 5.0

        elif self.state == "success":
            p = min(1.0, (now - self.success_t0) / self.T_SUCCESS)
            cur_w, cur_h = SQ, SQ
            n_exp = self.N_SQUARE
            global_alpha = 1.0
            icon_alpha = 1.0
            icon_scale = 1.0
            morph_p = p
            rim_green = min(1.0, p * 2.0)

        elif self.state == "contracting":
            t_elapsed = now - self.contract_t0
            s = self._spring_contract(t_elapsed, self.T_CONTRACT)
            cur_w = IW + (SQ - IW) * s
            cur_h = IH + (SQ - IH) * s
            n_exp = self.N_PILL + (self.N_SQUARE - self.N_PILL) * max(0.0, s)
            global_alpha = max(0.0, 1.0 - t_elapsed / self.T_CONTRACT)
            icon_alpha = max(0.0, 1.0 - t_elapsed / 0.15)
            icon_scale = max(0.001, s)
            morph_p = 1.0
            rim_green = max(0.0, 1.0 - t_elapsed / 0.15)

        elif self.state == "failed":
            t = now - self.failed_t0
            p = min(1.0, t / self.T_FAILED)
            decay = max(0.0, 1.0 - p)
            shake_x = 6.0 * math.sin(p * 30.0) * decay
            cur_w, cur_h = SQ, SQ
            n_exp = self.N_SQUARE
            global_alpha = 1.0
            icon_alpha = 1.0
            icon_scale = 1.0
            rim_red = decay

        elif self.state == "contracting_failed":
            t_elapsed = now - self.contract_t0
            s = self._spring_contract(t_elapsed, self.T_CONTRACT)
            cur_w = IW + (SQ - IW) * s
            cur_h = IH + (SQ - IH) * s
            n_exp = self.N_PILL + (self.N_SQUARE - self.N_PILL) * max(0.0, s)
            global_alpha = max(0.0, 1.0 - t_elapsed / self.T_CONTRACT)
            icon_alpha = max(0.0, 1.0 - t_elapsed / 0.15)
            icon_scale = max(0.001, s)

        if global_alpha <= 0.001:
            return False

        cy = top_y + cur_h / 2.0

        # ---- 1. Background squircle ----
        self.draw_squircle_path(cr, cx + shake_x, cy, cur_w, cur_h, n=n_exp)

        # Drop shadow
        cr.save()
        cr.set_source_rgba(0, 0, 0, 0.45 * global_alpha)
        cr.fill_preserve()
        cr.restore()

        # Deep obsidian fill
        cr.set_source_rgba(0.02, 0.02, 0.03, 0.98 * global_alpha)
        cr.fill_preserve()

        # Specular rim
        rim = cairo.LinearGradient(cx, top_y, cx, top_y + cur_h)
        if rim_green > 0:
            rim.add_color_stop_rgba(0.0, 0.204, 0.780, 0.349, 0.80 * rim_green * global_alpha)
            rim.add_color_stop_rgba(1.0, 0.204, 0.780, 0.349, 0.20 * rim_green * global_alpha)
        elif rim_red > 0:
            rim.add_color_stop_rgba(0.0, 1.0, 0.23, 0.19, 0.80 * rim_red * global_alpha)
            rim.add_color_stop_rgba(1.0, 0.8, 0.15, 0.15, 0.25 * rim_red * global_alpha)
        else:
            rim.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.25 * global_alpha)
            rim.add_color_stop_rgba(0.35, 1.0, 1.0, 1.0, 0.10 * global_alpha)
            rim.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.04 * global_alpha)
        cr.set_source(rim)
        cr.set_line_width(1.0)
        cr.stroke()

        # ---- 2. Icon content (padlock / scanning arc / checkmark) ----
        if icon_alpha > 0.01 and icon_scale > 0.01:
            cr.save()
            # Clip icon content to the squircle bounds (prevents arc/icon bleeding outside)
            self.draw_squircle_path(cr, cx + shake_x, cy, cur_w - 2.0, cur_h - 2.0, n=n_exp)
            cr.clip()
            cr.translate(cx + shake_x, cy)
            cr.scale(max(0.001, icon_scale), max(0.001, icon_scale))

            # Rotating scanning arc
            if morph_p < 0.7:
                arc_alpha = (1.0 - morph_p / 0.7) * icon_alpha
                cr.save()
                cr.rotate(scan_angle)
                r = 36.0
                pat = cairo.LinearGradient(-r, -r, r, r)
                pat.add_color_stop_rgba(0.0, 0.25, 0.75, 1.0, 0.0)
                pat.add_color_stop_rgba(0.45, 0.55, 0.9, 1.0, 0.9 * arc_alpha)
                pat.add_color_stop_rgba(1.0, 0.25, 0.75, 1.0, 0.0)
                cr.set_source(pat)
                cr.set_line_width(2.5)
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.arc(0, 0, r, 0, 0.65 * math.pi)
                cr.stroke()
                cr.restore()

            # Padlock (fades out as checkmark appears)
            if morph_p < 1.0:
                pad_a = (1.0 - morph_p) * icon_alpha
                cr.save()
                if rim_red > 0:
                    cr.set_source_rgba(1.0, 0.40, 0.40, pad_a)
                else:
                    cr.set_source_rgba(1.0, 1.0, 1.0, pad_a)

                # Shackle (pivots open during morph)
                shackle_open = morph_p * 0.5
                cr.save()
                cr.translate(6.0, -5.0)
                cr.rotate(-shackle_open)
                cr.translate(-6.0, 5.0)
                cr.set_line_width(3.0)
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.move_to(-6.0, -5.0)
                cr.line_to(-6.0, -11.0)
                cr.arc(0, -11.0, 6.0, math.pi, 2.0 * math.pi)
                cr.line_to(6.0, -5.0)
                cr.stroke()
                cr.restore()

                # Body — proper rounded rectangle
                bw, bh, br = 22.0, 16.0, 3.5
                bx0, by0 = -bw / 2.0, -5.0
                bx1, by1 = bw / 2.0, by0 + bh
                cr.move_to(bx0 + br, by0)
                cr.line_to(bx1 - br, by0)
                cr.arc(bx1 - br, by0 + br, br, -math.pi / 2, 0)
                cr.line_to(bx1, by1 - br)
                cr.arc(bx1 - br, by1 - br, br, 0, math.pi / 2)
                cr.line_to(bx0 + br, by1)
                cr.arc(bx0 + br, by1 - br, br, math.pi / 2, math.pi)
                cr.line_to(bx0, by0 + br)
                cr.arc(bx0 + br, by0 + br, br, math.pi, 3 * math.pi / 2)
                cr.close_path()
                cr.fill()

                # Keyhole
                cr.set_source_rgba(0.05, 0.05, 0.08, pad_a)
                cr.arc(0, by0 + 6.0, 2.0, 0, 2 * math.pi)
                cr.fill()
                cr.set_line_width(1.8)
                cr.move_to(0, by0 + 6.0)
                cr.line_to(0, by0 + 10.5)
                cr.stroke()

                cr.restore()

            # Green checkmark (fades in as padlock fades out)
            if morph_p > 0.0:
                chk_a = min(1.0, morph_p * 1.5) * icon_alpha
                chk_progress = min(1.0, morph_p * 1.3)

                cr.save()
                # Slight spring pop scale
                chk_s = 0.6 + 0.4 * morph_p + 0.15 * math.sin(morph_p * math.pi)
                cr.scale(chk_s, chk_s)

                # Expanding green halo ring
                if morph_p < 0.8:
                    halo_r = 18.0 + morph_p * 16.0
                    halo_a = (1.0 - morph_p / 0.8) * 0.55 * icon_alpha
                    cr.set_line_width(1.5)
                    cr.set_source_rgba(0.204, 0.780, 0.349, halo_a)
                    cr.arc(0, 0, halo_r, 0, 2 * math.pi)
                    cr.stroke()

                # Apple System Green checkmark (#34C759)
                cr.set_line_width(4.0)
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)
                cr.set_source_rgba(0.204, 0.780, 0.349, chk_a)

                p1 = (-9.0, 1.5)
                p2 = (-2.5, 8.0)
                p3 = (10.0, -7.0)
                l1 = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
                l2 = math.hypot(p3[0] - p2[0], p3[1] - p2[1])
                drawn = (l1 + l2) * chk_progress

                cr.move_to(*p1)
                if drawn <= l1:
                    f = drawn / l1
                    cr.line_to(p1[0] + (p2[0] - p1[0]) * f, p1[1] + (p2[1] - p1[1]) * f)
                else:
                    cr.line_to(*p2)
                    f = (drawn - l1) / l2
                    cr.line_to(p2[0] + (p3[0] - p2[0]) * f, p2[1] + (p3[1] - p2[1]) * f)
                cr.stroke()
                cr.restore()

            cr.restore()

        return False

# -----------------------------------------------------------------------------
# Lockscreen Window Implementation
# -----------------------------------------------------------------------------
class AnimState:
    ENTRANCE = 1
    IDLE = 2
    EXIT = 3

class MacOSLockWindow(Gtk.Window):
    def __init__(self, monitor, is_primary=True, on_unlock_cb=None, cli_wall=None):
        super().__init__()
        self.monitor = monitor
        self.is_primary = is_primary
        self.on_unlock_cb = on_unlock_cb
        self.cli_wall = cli_wall
        self.current_art_url = None
        self.gst_pipeline = None

        self.bg_full = None
        self.music_lens_surface = None
        self._music_lens_buf = None
        self._cached_card_shadow = None
        self._cached_clock_shadow = None

        self.anim_state = AnimState.ENTRANCE
        self.anim_start_time = None
        self.anim_duration = 0.25
        self.exit_duration = 0.16

        now = time.localtime()
        self.date_str = time.strftime("%A, %B %e", now).replace("  ", " ")
        self.time_str = time.strftime("%-I:%M", now)
        self.ampm_str = time.strftime("%p", now)

        self.system_status = get_system_status()
        self._status_updating = False
        self.status_bar_da = None
        self.weather_str = ""
        self.last_media_info = None
        self.last_activity_time = time.time()
        self.monitors_off = False
        self.unlocked = False
        self.caps_indicator = None
        self.dynamic_island = None
        self.howdy_in_progress = False

        self.set_decorated(False)
        self.realize()

        # Set default cursor to standard pointer
        gdk_win = self.get_window()
        if gdk_win:
            cursor = Gdk.Cursor.new_from_name(Gdk.Display.get_default(), "default")
            if cursor:
                gdk_win.set_cursor(cursor)

        # Apply CSS styling if not already applied
        if not hasattr(MacOSLockWindow, '_css_applied'):
            css_provider = Gtk.CssProvider()
            css_provider.load_from_data(CSS.encode("utf-8"))
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            MacOSLockWindow._css_applied = True

        self.setup_ui()
        if self.is_primary:
            self.refresh_weather_async()
            self.update_media()

    def setup_ui(self):
        self.overlay = Gtk.Overlay()
        self.add(self.overlay)

        wall_source = get_wallpaper_source(self.cli_wall)
        is_video = False
        if wall_source:
            _, ext = os.path.splitext(wall_source.lower())
            if ext in VIDEO_EXTENSIONS:
                is_video = True

        # 1. Base Layer: Blurred static wallpaper (zero black frame during initialization)
        wall_blurred = os.path.expanduser("~/.cache/current_wallpaper_blurred.png")
        if not os.path.exists(wall_blurred) and wall_source and not is_video:
            wall_blurred = wall_source

        bg_img = None
        if os.path.exists(wall_blurred):
            try:
                bg_pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(wall_blurred, 1920, 1080, False)
                bg_img = Gtk.Image.new_from_pixbuf(bg_pix)

                # Prepare wallpaper pixel buffer for optical refraction
                n_ch = bg_pix.get_n_channels()
                stride = bg_pix.get_rowstride()
                pixels = bg_pix.get_pixels()
                arr = np.frombuffer(pixels, dtype=np.uint8).reshape((1080, stride))[:, :1920 * n_ch].reshape((1080, 1920, n_ch))
                if n_ch == 3:
                    arr = np.concatenate([arr, np.full((1080, 1920, 1), 255, dtype=np.uint8)], axis=-1)
                self.bg_full = arr
            except Exception as e:
                print(f"Warning: could not prepare wallpaper for refraction: {e}", file=sys.stderr)

        if self.bg_full is None:
            self.bg_full = np.full((1080, 1920, 4), 28, dtype=np.uint8)

        # 2. Live Video Wallpaper Layer (GStreamer hardware-accelerated playback)
        video_started = False
        if is_video:
            try:
                self.gst_pipeline = Gst.ElementFactory.make("playbin", None)
                self.gst_sink = Gst.ElementFactory.make("gtksink", None)
                if self.gst_pipeline and self.gst_sink:
                    self.gst_pipeline.set_property("video-sink", self.gst_sink)
                    # flags: 0x01 = GST_PLAY_FLAG_VIDEO only (mute wallpaper audio)
                    self.gst_pipeline.set_property("flags", 0x01)
                    self.gst_pipeline.set_property("uri", "file://" + os.path.abspath(wall_source))

                    v_widget = self.gst_sink.props.widget
                    v_widget.set_size_request(1920, 1080)
                    self.overlay.add(v_widget)
                    video_started = True

                    # Seamless video looping on EOS
                    bus = self.gst_pipeline.get_bus()
                    bus.add_signal_watch()
                    def on_bus_msg(bus, msg):
                        if msg.type == Gst.MessageType.EOS:
                            self.gst_pipeline.seek_simple(
                                Gst.Format.TIME,
                                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                                0
                            )
                    bus.connect("message", on_bus_msg)
                    self.gst_pipeline.set_state(Gst.State.PLAYING)

                    # Dark translucent glass scrim for optimal typography legibility
                    scrim_da = Gtk.DrawingArea()
                    def on_scrim_draw(w, cr):
                        cr.set_source_rgba(0.04, 0.05, 0.08, 0.25)
                        cr.paint()
                    scrim_da.connect("draw", on_scrim_draw)
                    self.overlay.add_overlay(scrim_da)
                    self.overlay.set_overlay_pass_through(scrim_da, True)
            except Exception as e:
                print(f"Warning: Could not start live wallpaper playback: {e}", file=sys.stderr)

        if not video_started:
            if bg_img:
                self.overlay.add(bg_img)
            else:
                fallback_box = Gtk.Box()
                fallback_box.set_size_request(1920, 1080)
                self.overlay.add(fallback_box)

        # 3. Main Vertical Layout Container (Smoothly animated via pure opacity)
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.main_box.set_opacity(0.0)
        self.overlay.add_overlay(self.main_box)
        self.main_box.add_tick_callback(self.on_animation_tick)
        self.connect("key-press-event", self.on_key_press)
        self.connect("key-release-event", self.on_key_release)
        self.connect("motion-notify-event", self.on_user_activity)
        self.connect("button-press-event", self.on_user_activity)
        self.connect("scroll-event", self.on_user_activity)
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.SCROLL_MASK)

        # Top-right macOS Status Bar (Battery + %, Sound, Wi-Fi, DND)
        self.status_bar_da = self.create_status_bar_widget()
        self.status_bar_da.set_opacity(0.0)
        self.overlay.add_overlay(self.status_bar_da)
        self.status_bar_da.show_all()

        # Apple Dynamic Island Face ID HUD (Top Center - Persistent Hardware Pill)
        self.dynamic_island = AppleDynamicIslandWidget()
        self.dynamic_island.set_halign(Gtk.Align.CENTER)
        self.dynamic_island.set_valign(Gtk.Align.START)
        self.dynamic_island.set_margin_top(12)
        self.dynamic_island.set_opacity(0.0)
        self.overlay.add_overlay(self.dynamic_island)
        self.dynamic_island.show()

        # Top Date & Giant Glass Clock
        self.top_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.top_box.set_valign(Gtk.Align.START)
        self.top_box.set_margin_top(112)
        self.main_box.pack_start(self.top_box, False, False, 0)

        self.clock_da = self.create_glass_clock_widget()
        self.top_box.pack_start(self.clock_da, False, False, 0)

        if not self.is_primary:
            return  # Secondary monitors only show Clock & Date

        # 5. Center Group: Avatar, Display Name, Password Box
        self.mid_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.mid_box.set_valign(Gtk.Align.CENTER)
        self.mid_box.set_margin_top(48)
        self.main_box.pack_start(self.mid_box, False, False, 0)

        # Circular Avatar DrawingArea
        self.avatar_da = self.create_avatar_widget(88)
        self.mid_box.pack_start(self.avatar_da, False, False, 0)

        user_name = getpass.getuser()
        real_name = user_name.capitalize()
        try:
            entry = pwd.getpwnam(user_name)
            gecos = entry.pw_gecos.split(",")[0].strip()
            if gecos:
                real_name = gecos
        except Exception:
            pass

        self.user_lbl = Gtk.Label(label=real_name)
        self.user_lbl.set_name("user-lbl")
        self.mid_box.pack_start(self.user_lbl, False, False, 0)

        # macOS Password Pill Capsule
        self.pill_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.pill_box.set_name("pwd-pill")
        self.pill_box.set_halign(Gtk.Align.CENTER)
        self.pill_box.set_margin_top(14)
        self.mid_box.pack_start(self.pill_box, False, False, 0)

        self.entry = Gtk.Entry()
        self.entry.set_name("pwd-entry")
        self.entry.set_placeholder_text("Enter Password")
        self.entry.set_visibility(False)
        self.entry.set_property("caps-lock-warning", False)
        self.entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.entry.connect("activate", self.on_submit)
        self.pill_box.pack_start(self.entry, False, False, 0)

        # macOS Caps Lock Warning Badge
        self.caps_indicator = Gtk.Label(label="⇪")
        self.caps_indicator.set_name("caps-indicator")
        self.caps_indicator.set_valign(Gtk.Align.CENTER)
        self.caps_indicator.set_no_show_all(True)
        self.caps_indicator.hide()
        self.pill_box.pack_start(self.caps_indicator, False, False, 0)

        self.submit_btn = Gtk.Button(label="󰁔")
        self.submit_btn.set_name("submit-btn")
        self.submit_btn.set_valign(Gtk.Align.CENTER)
        self.submit_btn.connect("clicked", self.on_submit)
        self.pill_box.pack_start(self.submit_btn, False, False, 0)

        self.error_lbl = Gtk.Label(label="")
        self.error_lbl.set_name("error-lbl")
        self.error_lbl.set_halign(Gtk.Align.CENTER)
        self.mid_box.pack_start(self.error_lbl, False, False, 0)

        km = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
        if km:
            km.connect("state-changed", lambda *_: self.check_caps_lock())
        self.check_caps_lock()

        # 5. Bottom Group: Music Player Card (Apple Liquid Glass)
        self.bot_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.bot_box.set_valign(Gtk.Align.END)
        self.bot_box.set_margin_bottom(70)
        self.main_box.pack_end(self.bot_box, False, False, 0)

        self.music_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.music_container.set_halign(Gtk.Align.CENTER)
        self.music_container.set_no_show_all(True)
        self.bot_box.pack_start(self.music_container, False, False, 0)

        self.music_overlay = Gtk.Overlay()
        self.music_overlay.set_size_request(580, 156)
        self.music_container.pack_start(self.music_overlay, False, False, 0)

        # A. Liquid Glass Background Canvas
        self.music_glass_da = Gtk.DrawingArea()
        self.music_glass_da.set_size_request(580, 156)
        self.music_glass_da.connect("draw", self.draw_liquid_glass_card)
        self.music_overlay.add(self.music_glass_da)

        # B. Interactive Foreground Container
        self.music_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.music_card.set_name("music-card")
        self.music_card.set_halign(Gtk.Align.CENTER)
        self.music_card.set_valign(Gtk.Align.CENTER)
        self.music_card.set_size_request(510, 108)
        self.music_card.set_margin_start(16)
        self.music_card.set_margin_end(18)
        self.music_card.set_margin_top(14)
        self.music_card.set_margin_bottom(14)
        self.music_card.add_events(Gdk.EventMask.SCROLL_MASK)
        self.music_card.connect("scroll-event", self.on_music_scroll)
        self.music_overlay.add_overlay(self.music_card)

        # Album Art DrawingArea (rounded 14px squircle with drop shadow & specular glass sheen)
        self.art_pixbuf = None
        self.art_da = Gtk.DrawingArea()
        self.art_da.set_size_request(76, 76)
        self.art_da.connect("draw", self.draw_art)
        self.music_card.pack_start(self.art_da, False, False, 0)

        # Info Box (Title, Artist/Album, Scrubber)
        self.info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.info_box.set_valign(Gtk.Align.CENTER)
        self.music_card.pack_start(self.info_box, True, True, 0)

        self.track_lbl = Gtk.Label()
        self.track_lbl.set_name("music-title")
        self.track_lbl.set_xalign(0.0)
        self.track_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.track_lbl.set_max_width_chars(26)
        self.info_box.pack_start(self.track_lbl, False, False, 0)

        self.artist_lbl = Gtk.Label()
        self.artist_lbl.set_name("music-sub")
        self.artist_lbl.set_xalign(0.0)
        self.artist_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.artist_lbl.set_max_width_chars(30)
        self.info_box.pack_start(self.artist_lbl, False, False, 0)

        # Interactive Media Scrubber
        self.progress_event_box = Gtk.EventBox()
        self.progress_event_box.set_visible_window(False)
        self.progress_event_box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.progress_event_box.connect("button-press-event", self.on_progress_click)
        def on_pb_realize(widget):
            gw = widget.get_window()
            if gw:
                c = Gdk.Cursor.new_from_name(Gdk.Display.get_default(), "pointer")
                if c:
                    gw.set_cursor(c)
        self.progress_event_box.connect("realize", on_pb_realize)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_name("progress-bar")
        self.progress_bar.set_fraction(0.0)
        self.progress_event_box.add(self.progress_bar)
        self.info_box.pack_start(self.progress_event_box, False, False, 2)

        # Control Buttons (Previous, Play/Pause, Next)
        self.ctrl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.ctrl_box.set_valign(Gtk.Align.CENTER)
        self.music_card.pack_start(self.ctrl_box, False, False, 0)

        self.prev_btn = Gtk.Button(label="󰒮")
        self.prev_btn.set_valign(Gtk.Align.CENTER)
        self.prev_btn.get_style_context().add_class("media-btn")
        self.prev_btn.connect("clicked", lambda *_: subprocess.Popen(["playerctl", "previous"]))
        self.ctrl_box.pack_start(self.prev_btn, False, False, 0)

        self.play_btn = Gtk.Button(label="󰏤")
        self.play_btn.set_valign(Gtk.Align.CENTER)
        self.play_btn.get_style_context().add_class("media-btn")
        self.play_btn.get_style_context().add_class("media-play-btn")
        self.play_btn.connect("clicked", lambda *_: subprocess.Popen(["playerctl", "play-pause"]))
        self.ctrl_box.pack_start(self.play_btn, False, False, 0)

        self.next_btn = Gtk.Button(label="󰒭")
        self.next_btn.set_valign(Gtk.Align.CENTER)
        self.next_btn.get_style_context().add_class("media-btn")
        self.next_btn.connect("clicked", lambda *_: subprocess.Popen(["playerctl", "next"]))
        self.ctrl_box.pack_start(self.next_btn, False, False, 0)

        # Auto-focus entry
        self.entry.grab_focus()

    def create_status_bar_widget(self):
        da = Gtk.DrawingArea()
        da.set_size_request(340, 36)
        da.set_halign(Gtk.Align.END)
        da.set_valign(Gtk.Align.START)
        da.set_margin_top(18)
        da.set_margin_end(26)

        def on_draw(widget, cr):
            w = widget.get_allocated_width()
            h = widget.get_allocated_height()
            st = getattr(self, 'system_status', None)
            if not st:
                st = {
                    "battery": {"percent": 100, "charging": False},
                    "audio": {"volume": 0.5, "muted": False},
                    "wifi": {"connected": True, "signal": 80},
                    "dnd": False
                }

            bat = st.get("battery", {})
            audio = st.get("audio", {})
            wifi = st.get("wifi", {})
            dnd = st.get("dnd", False)

            cur_x = w - 4
            cy = h / 2.0

            def draw_item_with_shadow(draw_fn):
                cr.save()
                # macOS subtle drop shadow
                cr.set_source_rgba(0.0, 0.0, 0.0, 0.35)
                cr.save()
                cr.translate(0, 1.2)
                draw_fn(shadow=True)
                cr.restore()
                # Crisp white foreground
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.92)
                draw_fn(shadow=False)
                cr.restore()

            # 1. Battery Percentage
            pct = bat.get("percent", 100)
            pct_str = f"{pct}%"
            pctx = PangoCairo.create_context(cr)
            layout = Pango.Layout(pctx)
            desc = Pango.FontDescription("Google Sans Flex SemiBold 13")
            layout.set_font_description(desc)
            layout.set_text(pct_str, -1)
            ink, log = layout.get_pixel_extents()
            tw, th = log.width, log.height

            cur_x -= tw
            tx = cur_x
            ty = cy - th / 2.0

            def draw_pct(shadow=False):
                cr.move_to(tx, ty)
                if not shadow:
                    cr.set_source_rgba(1.0, 1.0, 1.0, 0.92)
                PangoCairo.show_layout(cr, layout)
            draw_item_with_shadow(draw_pct)

            cur_x -= 8

            # 2. Battery Icon (macOS Pill with Terminal Nipple)
            bw, bh = 25.0, 12.5
            br = 3.5
            nip_w, nip_h = 2.0, 5.0
            cur_x -= (bw + nip_w)
            bx = cur_x
            by = cy - bh / 2.0

            charging = bat.get("charging", False)

            def draw_battery(shadow=False):
                # Outer rounded capsule
                r = br
                cr.new_sub_path()
                cr.arc(bx + bw - r, by + r, r, -math.pi / 2, 0)
                cr.arc(bx + bw - r, by + bh - r, r, 0, math.pi / 2)
                cr.arc(bx + r, by + bh - r, r, math.pi / 2, math.pi)
                cr.arc(bx + r, by + r, r, math.pi, 3 * math.pi / 2)
                cr.close_path()
                cr.set_line_width(1.3)
                cr.stroke()

                # Terminal nipple
                nx = bx + bw + 0.8
                ny = by + (bh - nip_h) / 2.0
                cr.new_sub_path()
                cr.arc(nx + nip_w - 0.8, ny + 0.8, 0.8, -math.pi / 2, 0)
                cr.arc(nx + nip_w - 0.8, ny + nip_h - 0.8, 0.8, 0, math.pi / 2)
                cr.arc(nx, ny + nip_h, 0, math.pi / 2, math.pi)
                cr.arc(nx, ny, 0, math.pi, 3 * math.pi / 2)
                cr.close_path()
                cr.fill()

                # Inner charge bar
                pad = 2.2
                avail_w = bw - pad * 2
                fill_w = max(2.0, avail_w * (pct / 100.0))
                fill_h = bh - pad * 2
                fx = bx + pad
                fy = by + pad
                fr = 1.8
                cr.new_sub_path()
                cr.arc(fx + fill_w - fr, fy + fr, fr, -math.pi / 2, 0)
                cr.arc(fx + fill_w - fr, fy + fill_h - fr, fr, 0, math.pi / 2)
                cr.arc(fx + fr, fy + fill_h - fr, fr, math.pi / 2, math.pi)
                cr.arc(fx + fr, fy + fr, fr, math.pi, 3 * math.pi / 2)
                cr.close_path()

                if not shadow:
                    if charging:
                        # macOS Apple System Green: #34C759
                        cr.set_source_rgba(52 / 255.0, 199 / 255.0, 89 / 255.0, 0.98)
                    elif pct <= 20:
                        # Apple Low Battery Red: #FF3B30
                        cr.set_source_rgba(255 / 255.0, 59 / 255.0, 48 / 255.0, 0.98)
                    else:
                        cr.set_source_rgba(1.0, 1.0, 1.0, 0.92)
                cr.fill()

                # Lightning bolt if charging
                if charging:
                    cx_bat = bx + bw / 2.0
                    cy_bat = by + bh / 2.0

                    def bolt_path():
                        cr.new_sub_path()
                        cr.move_to(cx_bat + 0.6, cy_bat - 4.5)
                        cr.line_to(cx_bat - 2.4, cy_bat + 0.5)
                        cr.line_to(cx_bat - 0.2, cy_bat + 0.5)
                        cr.line_to(cx_bat - 0.7, cy_bat + 4.5)
                        cr.line_to(cx_bat + 2.7, cy_bat - 0.5)
                        cr.line_to(cx_bat + 0.5, cy_bat - 0.5)
                        cr.close_path()

                    if not shadow:
                        # Subtle dark stroke for high contrast over green fill
                        cr.save()
                        bolt_path()
                        cr.set_source_rgba(0.04, 0.16, 0.08, 0.70)
                        cr.set_line_width(1.2)
                        cr.stroke()
                        cr.restore()

                        # Crisp White Bolt
                        cr.save()
                        bolt_path()
                        cr.set_source_rgba(1.0, 1.0, 1.0, 0.98)
                        cr.fill()
                        cr.restore()

            draw_item_with_shadow(draw_battery)

            cur_x -= 18

            # 3. Sound / Volume Icon
            vw = 18.0
            cur_x -= vw
            vx = cur_x
            vy = cy
            vol = audio.get("volume", 0.5)
            muted = audio.get("muted", False)

            def draw_sound(shadow=False):
                cr.save()
                cr.new_sub_path()
                cr.rectangle(vx, vy - 3.2, 3.2, 6.4)
                cr.move_to(vx + 3.2, vy - 3.2)
                cr.line_to(vx + 7.5, vy - 6.5)
                cr.line_to(vx + 7.5, vy + 6.5)
                cr.line_to(vx + 3.2, vy + 3.2)
                cr.close_path()
                cr.fill()

                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_width(1.4)
                if muted:
                    cr.move_to(vx + 9.5, vy - 5.0)
                    cr.line_to(vx + 16.5, vy + 5.0)
                    cr.stroke()
                else:
                    cr.new_sub_path()
                    cr.arc(vx + 6.5, vy, 4.5, -math.pi * 0.28, math.pi * 0.28)
                    cr.stroke()
                    if vol > 0.35:
                        cr.new_sub_path()
                        cr.arc(vx + 6.5, vy, 8.2, -math.pi * 0.28, math.pi * 0.28)
                        cr.stroke()
                cr.restore()

            draw_item_with_shadow(draw_sound)

            # 3.5 Bluetooth Headphone Icon (if connected)
            bt = st.get("bluetooth", {})
            if bt.get("connected", False):
                cur_x -= 16
                hw = 16.0
                cur_x -= hw
                hx = cur_x + hw / 2.0
                hy = cy

                def draw_headphone(shadow=False):
                    cr.save()
                    cr.set_line_cap(cairo.LINE_CAP_ROUND)
                    cr.set_line_width(1.4)
                    # Headband arc
                    cr.new_sub_path()
                    cr.arc(hx, hy - 0.8, 5.8, math.pi, 2 * math.pi)
                    cr.stroke()
                    # Left earcup pill
                    round_rect(cr, hx - 6.8, hy - 2.8, 2.6, 6.2, 1.3)
                    cr.fill()
                    # Right earcup pill
                    round_rect(cr, hx + 4.2, hy - 2.8, 2.6, 6.2, 1.3)
                    cr.fill()
                    cr.restore()

                draw_item_with_shadow(draw_headphone)

            cur_x -= 18

            # 4. Wi-Fi Icon (macOS 3-tier fan)
            ww = 18.0
            cur_x -= ww
            wx = cur_x + ww / 2.0
            wy = cy + 5.5

            def draw_wifi(shadow=False):
                cr.save()
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.arc(wx, wy, 1.4, 0, 2 * math.pi)
                cr.fill()

                cr.set_line_width(1.5)
                cr.new_sub_path()
                cr.arc(wx, wy, 5.0, -math.pi * 0.75, -math.pi * 0.25)
                cr.stroke()

                cr.new_sub_path()
                cr.arc(wx, wy, 9.0, -math.pi * 0.75, -math.pi * 0.25)
                cr.stroke()

                cr.new_sub_path()
                cr.arc(wx, wy, 13.0, -math.pi * 0.75, -math.pi * 0.25)
                cr.stroke()
                cr.restore()

            draw_item_with_shadow(draw_wifi)

            # 5. DND Icon (macOS Crescent Moon) - Only if DND active
            if dnd:
                cur_x -= 18
                mw = 14.0
                cur_x -= mw
                mx = cur_x + mw / 2.0
                my = cy

                def draw_moon(shadow=False):
                    cr.save()
                    cr.new_sub_path()
                    cr.arc(mx, my, 6.2, -math.pi * 0.45, math.pi * 0.55)
                    cr.arc_negative(mx - 2.8, my, 5.8, math.pi * 0.45, -math.pi * 0.40)
                    cr.close_path()
                    cr.fill()
                    cr.restore()

                draw_item_with_shadow(draw_moon)

        da.connect("draw", on_draw)
        return da

    def update_status(self):
        if getattr(self, '_status_updating', False):
            return
        self._status_updating = True

        def worker():
            st = get_system_status()
            def apply_status():
                self.system_status = st
                self._status_updating = False
                if hasattr(self, 'status_bar_da') and self.status_bar_da:
                    self.status_bar_da.queue_draw()
                return False
            GLib.idle_add(apply_status)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def refresh_weather_async(self):
        def worker():
            try:
                script = os.path.expanduser("~/.config/waybar/weather.sh")
                if os.path.exists(script):
                    res = subprocess.run(["bash", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3.0)
                    if res.returncode == 0 and res.stdout.strip():
                        import json
                        data = json.loads(res.stdout.strip())
                        text = data.get("text", "").strip()
                        if text and "N/A" not in text:
                            cleaned = text.replace("+", "")
                            def apply_weather():
                                self.weather_str = cleaned
                                if hasattr(self, 'clock_da') and self.clock_da:
                                    self.clock_da.queue_draw()
                                return False
                            GLib.idle_add(apply_weather)
            except Exception:
                pass

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def create_glass_clock_widget(self):
        da = Gtk.DrawingArea()
        da.set_size_request(800, 240)
        da.set_halign(Gtk.Align.CENTER)

        def on_draw(widget, cr):
            w = widget.get_allocated_width()
            h = widget.get_allocated_height()
            pctx = PangoCairo.create_context(cr)

            # 1. Date Layout (macOS Sonoma Frosted Typography with Weather Glance)
            date_layout = Pango.Layout(pctx)
            date_desc = Pango.FontDescription("Google Sans Flex SemiBold 24")
            date_layout.set_font_description(date_desc)
            date_text = self.date_str
            if getattr(self, 'weather_str', ''):
                date_text = f"{self.date_str}   •   {self.weather_str}"
            date_layout.set_text(date_text, -1)
            date_layout.set_alignment(Pango.Alignment.CENTER)
            date_layout.set_width(w * Pango.SCALE)

            date_y = 12
            cr.save()
            cr.move_to(0, date_y + 1.2)
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.25)
            PangoCairo.show_layout(cr, date_layout)
            cr.move_to(0, date_y)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.68)
            PangoCairo.show_layout(cr, date_layout)
            cr.restore()

            # 2. Giant macOS Liquid Glass Clock Numerals (126pt SemiBold)
            time_layout = Pango.Layout(pctx)
            time_layout.set_markup(f"<span font='Google Sans Flex SemiBold 126'>{self.time_str}</span>", -1)
            time_layout.set_alignment(Pango.Alignment.CENTER)
            time_layout.set_width(w * Pango.SCALE)

            time_y = 54

            # A. Ambient Soft Gaussian Drop Shadow for Numerals
            if not hasattr(self, '_cached_clock_shadow') or self._cached_clock_shadow is None or self._cached_clock_shadow[0] != self.time_str:
                clock_mask = cairo.ImageSurface(cairo.FORMAT_A8, w, h)
                cm_cr = cairo.Context(clock_mask)
                cm_pctx = PangoCairo.create_context(cm_cr)
                cm_layout = Pango.Layout(cm_pctx)
                cm_layout.set_markup(f"<span font='Google Sans Flex SemiBold 126'>{self.time_str}</span>", -1)
                cm_layout.set_alignment(Pango.Alignment.CENTER)
                cm_layout.set_width(w * Pango.SCALE)
                cm_cr.move_to(0, time_y)
                PangoCairo.show_layout(cm_cr, cm_layout)

                c_buf = clock_mask.get_data()
                c_stride = clock_mask.get_stride()
                c_arr = np.frombuffer(c_buf, dtype=np.uint8).reshape((h, c_stride))[:, :w].astype(float)
                c_blur = scipy.ndimage.gaussian_filter(c_arr, sigma=14.0)
                c_shadow_alpha = np.clip(c_blur * 0.22, 0, 255).astype(np.uint8)

                c_sh_surf = cairo.ImageSurface.create_for_data(
                    np.ascontiguousarray(np.stack([np.zeros_like(c_shadow_alpha), np.zeros_like(c_shadow_alpha), np.zeros_like(c_shadow_alpha), c_shadow_alpha], axis=-1)),
                    cairo.FORMAT_ARGB32, w, h, w * 4
                )
                self._cached_clock_shadow = (self.time_str, c_sh_surf, c_shadow_alpha)

            _, c_sh_surf, _ = self._cached_clock_shadow
            cr.save()
            cr.set_source_surface(c_sh_surf, 0, 5)
            cr.paint()
            cr.restore()

            # B. Liquid Glass Numerals Fill using native FreeType show_layout
            cr.save()
            cr.move_to(0, time_y)
            glass_grad = cairo.LinearGradient(0, time_y, 0, time_y + 140)
            glass_grad.add_color_stop_rgba(0.00, 1.0, 1.0, 1.0, 0.88)
            glass_grad.add_color_stop_rgba(0.45, 1.0, 1.0, 1.0, 0.72)
            glass_grad.add_color_stop_rgba(1.00, 1.0, 1.0, 1.0, 0.58)
            cr.set_source(glass_grad)
            PangoCairo.show_layout(cr, time_layout)

            # Subtle upper catch-light (0.5px offset up)
            cr.move_to(0, time_y - 0.7)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.20)
            PangoCairo.show_layout(cr, time_layout)
            cr.restore()

        da.connect("draw", on_draw)
        return da

    def create_avatar_widget(self, size=88):
        da = Gtk.DrawingArea()
        da.set_size_request(size, size)
        da.set_halign(Gtk.Align.CENTER)

        pix = None
        if os.path.exists(AVATAR_PATH):
            try:
                pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(AVATAR_PATH, size, size, False)
            except Exception:
                pass

        def on_draw(widget, cr):
            w = widget.get_allocated_width()
            h = widget.get_allocated_height()
            r = min(w, h) / 2 - 2
            cx, cy = w / 2, h / 2

            # Drop shadow
            cr.arc(cx, cy + 3, r, 0, 2 * math.pi)
            cr.set_source_rgba(0, 0, 0, 0.40)
            cr.fill()

            # Circular clip & paint image
            cr.save()
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.clip()
            if pix:
                Gdk.cairo_set_source_pixbuf(cr, pix, cx - r, cy - r)
                cr.paint()
            else:
                cr.set_source_rgba(0.18, 0.20, 0.26, 1.0)
                cr.paint()
            cr.restore()

            # Crisp white border
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.40)
            cr.set_line_width(2.0)
            cr.stroke()

        da.connect("draw", on_draw)
        return da

    def draw_liquid_glass_card(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        cw, ch = 510, 108
        pad_x = max(0, (width - cw) // 2)
        pad_y = max(0, (height - ch) // 2)
        r = 26

        # 1. Authentic macOS Liquid Glass Optical Refraction (Pure floating glass, zero dark under-shade)
        if self.bg_full is not None:
            if self.music_lens_surface is None or self.music_lens_surface.get_width() != cw or self.music_lens_surface.get_height() != ch:
                coords = widget.translate_coordinates(self, 0, 0)
                if coords:
                    card_x_screen = coords[0] + pad_x
                    card_y_screen = coords[1] + pad_y
                else:
                    win_w = self.get_allocated_width() if self.get_allocated_width() > 100 else 1920
                    win_h = self.get_allocated_height() if self.get_allocated_height() > 100 else 1080
                    card_x_screen = (win_w - cw) // 2
                    card_y_screen = win_h - 70 - 156 + pad_y

                bg_h, bg_w = self.bg_full.shape[:2]
                card_x_screen = max(0, min(card_x_screen, bg_w - cw))
                card_y_screen = max(0, min(card_y_screen, bg_h - ch))

                sub_bg = self.bg_full[card_y_screen:card_y_screen + ch, card_x_screen:card_x_screen + cw].copy()
                self.music_lens_surface, self._music_lens_buf = create_macos_liquid_glass_card(
                    sub_bg, cw, ch, radius=r
                )

        if self.music_lens_surface is not None:
            cr.save()
            cr.set_source_surface(self.music_lens_surface, pad_x, pad_y)
            cr.paint()
            cr.restore()
        else:
            cr.save()
            round_rect(cr, pad_x, pad_y, cw, ch, r)
            cr.set_source_rgba(0.08, 0.10, 0.16, 0.65)
            cr.fill()
            cr.restore()

        # 3. Top Specular Sheen & Meniscus Tension Arc
        cr.save()
        round_rect(cr, pad_x, pad_y, cw, ch, r)
        cr.clip()

        veil = cairo.LinearGradient(pad_x, pad_y, pad_x, pad_y + ch)
        veil.add_color_stop_rgba(0.00, 1.0, 1.0, 1.0, 0.24)
        veil.add_color_stop_rgba(0.35, 1.0, 1.0, 1.0, 0.08)
        veil.add_color_stop_rgba(1.00, 1.0, 1.0, 1.0, 0.02)
        cr.set_source(veil)
        cr.paint()

        men_h = ch * 0.40
        cr.new_sub_path()
        cr.move_to(pad_x, pad_y + r)
        cr.arc(pad_x + r, pad_y + r, r, math.pi, 3 * math.pi / 2)
        cr.line_to(pad_x + cw - r, pad_y)
        cr.arc(pad_x + cw - r, pad_y + r, r, -math.pi / 2, 0)
        cr.line_to(pad_x + cw, pad_y + men_h * 0.70)
        cr.curve_to(pad_x + cw * 0.65, pad_y + men_h * 1.05,
                    pad_x + cw * 0.35, pad_y + men_h * 1.05,
                    pad_x, pad_y + men_h * 0.70)
        cr.close_path()
        cr.clip()

        men_pat = cairo.LinearGradient(pad_x, pad_y, pad_x, pad_y + men_h)
        men_pat.add_color_stop_rgba(0.00, 1.0, 1.0, 1.0, 0.22)
        men_pat.add_color_stop_rgba(0.50, 1.0, 1.0, 1.0, 0.06)
        men_pat.add_color_stop_rgba(1.00, 1.0, 1.0, 1.0, 0.00)
        cr.set_source(men_pat)
        cr.paint()
        cr.restore()

        # 4. Inset 1px Specular Bevel
        cr.save()
        round_rect(cr, pad_x + 1.0, pad_y + 1.0, cw - 2.0, ch - 2.0, r - 1.0)
        in_pat = cairo.LinearGradient(pad_x, pad_y, pad_x, pad_y + ch)
        in_pat.add_color_stop_rgba(0.00, 1.0, 1.0, 1.0, 0.45)
        in_pat.add_color_stop_rgba(0.30, 1.0, 1.0, 1.0, 0.15)
        in_pat.add_color_stop_rgba(1.00, 1.0, 1.0, 1.0, 0.03)
        cr.set_source(in_pat)
        cr.set_line_width(1.0)
        cr.stroke()
        cr.restore()

        # 5. Hairline Outer Specular Rim
        cr.save()
        round_rect(cr, pad_x + 0.5, pad_y + 0.5, cw - 1.0, ch - 1.0, r - 0.5)
        out_pat = cairo.LinearGradient(pad_x, pad_y, pad_x, pad_y + ch)
        out_pat.add_color_stop_rgba(0.00, 1.0, 1.0, 1.0, 0.75)
        out_pat.add_color_stop_rgba(0.30, 1.0, 1.0, 1.0, 0.35)
        out_pat.add_color_stop_rgba(0.70, 1.0, 1.0, 1.0, 0.15)
        out_pat.add_color_stop_rgba(1.00, 1.0, 1.0, 1.0, 0.30)
        cr.set_source(out_pat)
        cr.set_line_width(1.0)
        cr.stroke()
        cr.restore()

    def draw_art(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        r = 15
        pad = 2
        aw, ah = w - pad * 2, h - pad * 2

        # Soft drop shadow
        round_rect(cr, pad, pad + 2, aw, ah, r)
        cr.set_source_rgba(0, 0, 0, 0.35)
        cr.fill()

        # Album art clipped
        round_rect(cr, pad, pad, aw, ah, r)
        cr.save()
        cr.clip()
        if self.art_pixbuf:
            Gdk.cairo_set_source_pixbuf(cr, self.art_pixbuf, pad, pad)
            cr.paint()
        else:
            pat = cairo.LinearGradient(pad, pad, pad + aw, pad + ah)
            pat.add_color_stop_rgba(0, 0.22, 0.26, 0.38, 1.0)
            pat.add_color_stop_rgba(1, 0.12, 0.14, 0.22, 1.0)
            cr.set_source(pat)
            cr.paint()

            # Note glyph placeholder
            pctx = PangoCairo.create_context(cr)
            layout = Pango.Layout(pctx)
            layout.set_font_description(Pango.font_description_from_string("Symbols Nerd Font, Sans 26"))
            layout.set_text("󰝚", -1)
            ext = layout.get_pixel_extents()[1]
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.50)
            cr.move_to(pad + (aw - ext.width) / 2, pad + (ah - ext.height) / 2)
            PangoCairo.show_layout(cr, layout)

        # Specular gloss across top-left corner
        asheen = cairo.LinearGradient(pad, pad, pad + aw, pad + ah * 0.6)
        asheen.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.30)
        asheen.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.0)
        cr.set_source(asheen)
        cr.paint()
        cr.restore()

        # Crisp 1px glass border
        round_rect(cr, pad + 0.5, pad + 0.5, aw - 1.0, ah - 1.0, r)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.35)
        cr.set_line_width(1.0)
        cr.stroke()

    def update_clock(self):
        now = time.localtime()
        new_date = time.strftime("%A, %B %e", now).replace("  ", " ")
        new_time = time.strftime("%-I:%M", now)
        new_ampm = time.strftime("%p", now)
        if new_date != self.date_str or new_time != self.time_str or new_ampm != self.ampm_str:
            self.date_str = new_date
            self.time_str = new_time
            self.ampm_str = new_ampm
            self._cached_clock_shadow = None
            if hasattr(self, 'clock_da') and self.clock_da:
                self.clock_da.queue_draw()
        return True

    def update_media(self):
        info = get_active_player_info()
        self.last_media_info = info
        if not info:
            if hasattr(self, 'music_container'):
                self.music_container.hide()
            elif hasattr(self, 'music_card'):
                self.music_card.hide()
            return True

        if hasattr(self, 'music_container'):
            self.music_overlay.show_all()
            self.music_container.show()
        elif hasattr(self, 'music_card'):
            self.music_card.show_all()

        self.track_lbl.set_text(info.get("title", "Unknown Track"))
        artist = info.get("artist", "Unknown Artist")
        album = info.get("album", "")
        self.artist_lbl.set_text(f"{artist} • {album}" if album else artist)

        is_playing = info.get("status", "").lower() == "playing"
        self.play_btn.set_label("󰏤" if is_playing else "󰐊")

        length = info.get("length", 0)
        pos = info.get("position", 0)
        pct = (pos / length) if length > 0 else 0.0
        self.progress_bar.set_fraction(max(0.0, min(1.0, pct)))

        art_url = info.get("art_url")
        if art_url != self.current_art_url:
            self.current_art_url = art_url
            self.art_pixbuf = fetch_art_pixbuf(art_url, size=80)
            self.art_da.queue_draw()

        if hasattr(self, 'music_glass_da') and self.music_glass_da:
            self.music_glass_da.queue_draw()

        return True

    def on_user_activity(self, *_):
        self.reset_inactivity()
        return False

    def reset_inactivity(self):
        self.last_activity_time = time.time()
        if self.monitors_off:
            self.monitors_off = False
            try:
                subprocess.Popen(["niri", "msg", "action", "power-on-monitors"])
            except Exception:
                pass

    def check_idle_sleep(self):
        if not self.is_primary or self.unlocked:
            return
        # After 60 seconds of inactivity, put displays into DPMS sleep
        if not self.monitors_off and (time.time() - self.last_activity_time > 60):
            self.monitors_off = True
            try:
                subprocess.Popen(["niri", "msg", "action", "power-off-monitors"])
            except Exception:
                pass

    def check_caps_lock(self):
        if not hasattr(self, 'caps_indicator') or not self.caps_indicator:
            return
        km = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
        if km:
            is_caps = km.get_caps_lock_state()
            if is_caps:
                self.caps_indicator.show()
            else:
                self.caps_indicator.hide()

    def on_key_release(self, widget, event):
        self.reset_inactivity()
        self.check_caps_lock()
        return False

    def on_key_press(self, widget, event):
        self.reset_inactivity()
        self.check_caps_lock()
        if event.keyval == Gdk.KEY_Escape:
            if hasattr(self, 'entry'):
                self.entry.set_text("")
                self.entry.grab_focus()
            if hasattr(self, 'dynamic_island') and self.dynamic_island:
                self.dynamic_island.set_idle()
            return True
        elif event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if hasattr(self, 'entry') and not self.entry.has_focus():
                self.on_submit()
                return True
        elif hasattr(self, 'entry') and not self.entry.has_focus():
            self.entry.grab_focus()
        return False

    def on_progress_click(self, widget, event):
        self.reset_inactivity()
        if not self.last_media_info:
            return False
        alloc = widget.get_allocation()
        if alloc.width <= 0:
            return False
        click_x = max(0, min(event.x, alloc.width))
        fraction = click_x / float(alloc.width)
        length_us = self.last_media_info.get("length", 0)
        if length_us > 0:
            target_pos_sec = fraction * (length_us / 1000000.0)
            subprocess.Popen(["playerctl", "position", str(target_pos_sec)])
            self.progress_bar.set_fraction(max(0.0, min(1.0, fraction)))
        return True

    def on_music_scroll(self, widget, event):
        self.reset_inactivity()
        dy = 0.0
        if event.direction == Gdk.ScrollDirection.UP:
            dy = -1.0
        elif event.direction == Gdk.ScrollDirection.DOWN:
            dy = 1.0
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            success, dx, sdy = event.get_scroll_deltas()
            if success:
                dy = sdy

        if dy < 0:
            subprocess.Popen(["wpctl", "set-volume", "-l", "1.5", "@DEFAULT_AUDIO_SINK@", "5%+"])
            GLib.timeout_add(150, self.update_status)
            return True
        elif dy > 0:
            subprocess.Popen(["wpctl", "set-volume", "-l", "1.5", "@DEFAULT_AUDIO_SINK@", "5%-"])
            GLib.timeout_add(150, self.update_status)
            return True
        return False

    def start_howdy_auth(self):
        if not self.is_primary or self.unlocked or self.howdy_in_progress:
            return
        if not (os.path.exists("/usr/local/bin/howdy") or os.path.exists("/usr/bin/howdy")):
            return

        # Check if Howdy is disabled in config
        howdy_conf = "/usr/local/etc/howdy/config.ini"
        if not os.path.exists(howdy_conf):
            howdy_conf = "/etc/howdy/config.ini"
        if os.path.exists(howdy_conf):
            try:
                import configparser
                cfg = configparser.ConfigParser()
                cfg.read(howdy_conf)
                if cfg.getboolean("core", "disabled", fallback=False):
                    return
            except Exception:
                pass

        self.howdy_in_progress = True
        if hasattr(self, 'dynamic_island') and self.dynamic_island:
            self.dynamic_island.start_scanning()

        def worker():
            if self.unlocked:
                self.howdy_in_progress = False
                return
            user = getpass.getuser()
            p = pam.PamAuthenticator()
            try:
                auth_res = p.authenticate(user, "", service="swaylock")
            except Exception:
                auth_res = False

            def on_res():
                self.howdy_in_progress = False
                if self.unlocked:
                    return False
                if auth_res:
                    if hasattr(self, 'dynamic_island') and self.dynamic_island:
                        self.dynamic_island.set_success(self.on_face_unlock_success)
                    else:
                        self.on_face_unlock_success()
                else:
                    if hasattr(self, 'dynamic_island') and self.dynamic_island:
                        self.dynamic_island.set_failed()
                return False

            GLib.idle_add(on_res)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def on_face_unlock_success(self):
        if self.unlocked:
            return
        self.unlocked = True
        if hasattr(self, 'submit_btn'):
            self.submit_btn.set_label("󰄬")
        if self.on_unlock_cb:
            self.on_unlock_cb()

    def on_animation_tick(self, widget, frame_clock):
        now = time.time()
        if self.anim_start_time is None:
            self.anim_start_time = now
            return True

        elapsed = now - self.anim_start_time

        if self.anim_state == AnimState.ENTRANCE:
            progress = min(1.0, elapsed / self.anim_duration)
            eased = 1.0 - math.pow(1.0 - progress, 2.5)
            self.main_box.set_opacity(eased)
            if hasattr(self, 'status_bar_da') and self.status_bar_da:
                self.status_bar_da.set_opacity(eased)
            if hasattr(self, 'dynamic_island') and self.dynamic_island:
                self.dynamic_island.set_opacity(eased)

            if progress >= 1.0:
                self.anim_state = AnimState.IDLE
                self.main_box.set_opacity(1.0)
                if hasattr(self, 'status_bar_da') and self.status_bar_da:
                    self.status_bar_da.set_opacity(1.0)
                if hasattr(self, 'dynamic_island') and self.dynamic_island:
                    self.dynamic_island.set_opacity(1.0)
                return True

        elif self.anim_state == AnimState.EXIT:
            progress = min(1.0, elapsed / self.exit_duration)
            eased = math.pow(progress, 2.0)
            alpha = max(0.0, 1.0 - eased)
            self.main_box.set_opacity(alpha)
            if hasattr(self, 'status_bar_da') and self.status_bar_da:
                self.status_bar_da.set_opacity(alpha)
            if hasattr(self, 'dynamic_island') and self.dynamic_island:
                self.dynamic_island.set_opacity(alpha)

            if progress >= 1.0:
                self.anim_state = AnimState.IDLE
                self.main_box.set_opacity(0.0)
                if hasattr(self, 'status_bar_da') and self.status_bar_da:
                    self.status_bar_da.set_opacity(0.0)
                if hasattr(self, 'dynamic_island') and self.dynamic_island:
                    self.dynamic_island.set_opacity(0.0)
                return False

        return True

    def start_exit_animation(self):
        if self.anim_state == AnimState.EXIT:
            return
        self.anim_state = AnimState.EXIT
        self.anim_start_time = time.time()
        self.main_box.queue_draw()

    def on_submit(self, *_):
        if self.unlocked:
            return

        pwd_text = self.entry.get_text()

        # If user pressed Enter with NO password entered: trigger Face Unlock!
        if not pwd_text:
            if not self.howdy_in_progress:
                self.start_howdy_auth()
            return

        # If user entered a password, dismiss any active Face ID HUD
        if hasattr(self, 'dynamic_island') and self.dynamic_island:
            self.dynamic_island.set_idle()

        self.entry.set_sensitive(False)
        self.submit_btn.set_sensitive(False)

        def auth_worker():
            user = getpass.getuser()
            p = pam.PamAuthenticator()
            # Authenticate via PAM login service (pure password auth, zero camera/Howdy delay)
            success = p.authenticate(user, pwd_text, service="login")
            if not success and p.code == 7:
                # Fallback to system-auth
                success = p.authenticate(user, pwd_text, service="system-auth")

            def on_res():
                if self.unlocked:
                    return False
                if success:
                    self.unlocked = True
                    self.submit_btn.set_label("󰄬")
                    if hasattr(self, 'dynamic_island') and self.dynamic_island:
                        self.dynamic_island.set_idle()
                    if self.on_unlock_cb:
                        self.on_unlock_cb()
                else:
                    self.entry.set_text("")
                    self.entry.set_sensitive(True)
                    self.submit_btn.set_sensitive(True)
                    self.entry.grab_focus()
                    self.pill_box.get_style_context().add_class("error")
                    self.error_lbl.set_text("Incorrect password")
                    GLib.timeout_add(1500, lambda: self.pill_box.get_style_context().remove_class("error"))
                return False

            GLib.idle_add(on_res)

        threading.Thread(target=auth_worker, daemon=True).start()

    def cleanup(self):
        self.unlocked = True
        if self.monitors_off:
            try:
                subprocess.Popen(["niri", "msg", "action", "power-on-monitors"])
            except Exception:
                pass
        if self.gst_pipeline:
            try:
                self.gst_pipeline.set_state(Gst.State.NULL)
            except Exception:
                pass
            self.gst_pipeline = None

# -----------------------------------------------------------------------------
# Main Application Entry Point
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="macOS Sonoma Native Lock Screen for Niri")
    parser.add_argument("--live", nargs="?", const="auto", default=None, help="Force live wallpaper or specify video path")
    args, _ = parser.parse_known_args()

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

    Gst.init(None)

    # Apply CSS
    css_provider = Gtk.CssProvider()
    css_provider.load_from_data(CSS.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        css_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    display = Gdk.Display.get_default()
    if not display or not GtkSessionLock.is_supported():
        sys.exit(1)

    lock = GtkSessionLock.prepare_lock()
    lock.lock_lock()

    windows = []
    unlocked = False

    def request_unlock():
        nonlocal unlocked
        if unlocked:
            return
        for w in windows:
            w.start_exit_animation()
        GLib.timeout_add(170, unlock_session)

    def unlock_session():
        nonlocal unlocked
        if unlocked:
            return
        unlocked = True
        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        except OSError:
            pass
        for w in windows:
            w.cleanup()
        lock.unlock_and_destroy()
        display.sync()
        Gtk.main_quit()

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGUSR1):
        signal.signal(sig, lambda *_: request_unlock())

    n_mon = display.get_n_monitors()
    for i in range(n_mon):
        mon = display.get_monitor(i)
        is_prim = (i == 0)
        win = MacOSLockWindow(mon, is_primary=is_prim, on_unlock_cb=request_unlock, cli_wall=args.live)
        lock.new_surface(win, mon)
        win.show_all()
        windows.append(win)

    # Periodic timers for Clock (1s), Media (1s), Idle Sleep (1s), and Status/Weather
    status_counter = [0]
    def on_tick():
        status_counter[0] += 1
        for w in windows:
            w.update_clock()
            if w.is_primary:
                w.update_media()
                w.check_idle_sleep()
                if status_counter[0] % 2 == 0:
                    w.update_status()
                if status_counter[0] % 60 == 0:
                    w.refresh_weather_async()
        return True

    GLib.timeout_add(1000, on_tick)

    try:
        Gtk.main()
    finally:
        if not unlocked:
            unlock_session()

if __name__ == "__main__":
    main()
