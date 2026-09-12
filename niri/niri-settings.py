#!/usr/bin/python3
import os
import sys
import glob
import json
import re
import shutil
import subprocess
import threading

import math
import cairo
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, Pango, PangoCairo

GLib.set_prgname("niri-settings")
GLib.set_application_name("Niri Settings")

APP_TITLE = "Niri Settings"
THEME_CSS_PATH = "/home/sreyas/.config/waybar/current-theme.css"
WALLPAPER_DIR = "/home/sreyas/wall"
CONFIG_KDL_PATH = "/home/sreyas/.config/niri/config.kdl"
DOTFILE_KDL_PATH = "/home/sreyas/dotfile/niri/config.kdl"
CURRENT_WALL_CACHE = "/home/sreyas/.cache/current_wallpaper"
NIGHT_LIGHT_SCRIPT = "/home/sreyas/.config/niri/night-light.sh"
NIGHT_LIGHT_CONFIG = "/home/sreyas/.config/niri/night-light.json"

def get_night_light_state():
    state = {"running": False, "enabled": False, "temperature": 4000, "brightness": 1.0}
    if os.path.exists(NIGHT_LIGHT_CONFIG):
        try:
            with open(NIGHT_LIGHT_CONFIG, "r") as f:
                data = json.load(f)
                state["enabled"] = bool(data.get("enabled", False))
                state["temperature"] = int(data.get("temperature", 4000))
                state["brightness"] = float(data.get("brightness", 1.0))
        except Exception:
            pass
    try:
        res = subprocess.run(["pgrep", "-x", "gammastep"], stdout=subprocess.PIPE)
        state["running"] = (res.returncode == 0)
    except Exception:
        pass
    return state

def set_night_light_enabled(enabled, temp=None, brightness=None):
    if enabled:
        cmd = [NIGHT_LIGHT_SCRIPT, "on"]
        if temp is not None:
            cmd.append(str(temp))
            if brightness is not None:
                cmd.append(str(brightness))
        subprocess.Popen(cmd)
    else:
        subprocess.Popen([NIGHT_LIGHT_SCRIPT, "off"])

def set_night_light_params(temp, brightness=1.0):
    subprocess.Popen([NIGHT_LIGHT_SCRIPT, "set", str(temp), str(brightness)])

def parse_theme_colors():
    colors = {
        "accent-purple": (0.44, 0.42, 0.63, 1.0),
        "fg-color": (0.93, 0.99, 1.0, 1.0),
        "bg-color": (0.05, 0.05, 0.07, 1.0),
        "comment-color": (0.61, 0.67, 0.67, 1.0),
        "accent-color": (0.44, 0.42, 0.63, 1.0),
    }
    if os.path.exists(THEME_CSS_PATH):
        try:
            with open(THEME_CSS_PATH, "r") as f:
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
            if "accent-purple" in colors:
                colors["accent-color"] = colors["accent-purple"]
        except Exception:
            pass
    return colors

def get_current_avatar_path():
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

def get_avatar_source_path():
    p = os.path.expanduser("~/.config/waybar/avatar_source.png")
    if os.path.exists(p) and os.path.isfile(p):
        return p
    return get_current_avatar_path()

def get_avatar_pixbuf(size):
    path = get_current_avatar_path()
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
    except Exception:
        return None

def set_profile_picture(filepath):
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file(filepath)
        if hasattr(pb, 'apply_embedded_orientation'):
            pb = pb.apply_embedded_orientation()
        pw, ph = pb.get_width(), pb.get_height()
        side = min(pw, ph)
        src_x = (pw - side) // 2
        src_y = (ph - side) // 2
        square = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, side, side)
        square.fill(0x00000000)
        pb.copy_area(src_x, src_y, side, side, square, 0, 0)

        final_pb = square.scale_simple(512, 512, GdkPixbuf.InterpType.BILINEAR)

        target_waybar = os.path.expanduser("~/.config/waybar/avatar.png")
        target_face = os.path.expanduser("~/.face")
        target_face_icon = os.path.expanduser("~/.face.icon")

        os.makedirs(os.path.dirname(target_waybar), exist_ok=True)
        final_pb.savev(target_waybar, "png", [], [])
        final_pb.savev(target_face, "png", [], [])
        try:
            final_pb.savev(target_face_icon, "png", [], [])
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"Error setting profile picture: {e}")
        return False

def remove_profile_picture():
    for p in [os.path.expanduser("~/.config/waybar/avatar.png"),
              os.path.expanduser("~/.config/waybar/avatar_source.png"),
              os.path.expanduser("~/.face"),
              os.path.expanduser("~/.face.icon")]:
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

def run_cmd(cmd):
    try:
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
        return res.stdout.strip()
    except Exception:
        return ""

def async_cmd(cmd):
    threading.Thread(target=lambda: subprocess.run(cmd, shell=True), daemon=True).start()

def sync_kdl_to_dotfile(content):
    if os.path.exists(DOTFILE_KDL_PATH):
        try:
            with open(DOTFILE_KDL_PATH, "w") as f:
                f.write(content)
        except Exception:
            pass

MIRROR_SCRIPT = "/home/sreyas/.config/niri/mirror.sh"

def is_mirror_running():
    try:
        res = subprocess.run(["pgrep", "-x", "wl-mirror"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return res.returncode == 0
    except Exception:
        return False

def get_niri_outputs_info():
    try:
        res = subprocess.run(["niri", "msg", "-j", "outputs"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=2)
        if res.returncode == 0 and res.stdout.strip():
            return json.loads(res.stdout)
    except Exception as e:
        print(f"Error reading niri outputs: {e}")
    return {}

def get_aspect_ratio_str(w, h):
    if not w or not h:
        return "16:9"
    g = math.gcd(w, h)
    rw, rh = w // g, h // g
    if (rw, rh) == (8, 5): return "16:10"
    if (rw, rh) == (16, 9): return "16:9"
    if (rw, rh) == (4, 3): return "4:3"
    if (rw, rh) == (5, 4): return "5:4"
    if (rw, rh) == (21, 9) or (w, h) in [(2560, 1080), (3440, 1440)]: return "21:9"
    if (rw, rh) == (32, 9) or (w, h) in [(5120, 1440), (3840, 1080)]: return "32:9"
    if (rw, rh) == (3, 2): return "3:2"
    return f"{rw}:{rh}"

def update_niri_output(output_name="eDP-1", mode=None, scale=None, vrr=None, transform=None, position=None, custom_60hz=False):
    # 1. Live dynamic update via niri msg output
    try:
        if mode is not None:
            if custom_60hz or (isinstance(mode, str) and ("@60" in mode or "59.96" in mode)):
                subprocess.run(["niri", "msg", "output", output_name, "custom-mode", "1920x1080@60.000"], capture_output=True)
            else:
                subprocess.run(["niri", "msg", "output", output_name, "mode", str(mode)], capture_output=True)
        if scale is not None:
            subprocess.run(["niri", "msg", "output", output_name, "scale", str(scale)], capture_output=True)
        if transform is not None:
            subprocess.run(["niri", "msg", "output", output_name, "transform", str(transform)], capture_output=True)
        if position is not None:
            if isinstance(position, (list, tuple)) and len(position) >= 2:
                subprocess.run(["niri", "msg", "output", output_name, "position", str(position[0]), str(position[1])], capture_output=True)
        if vrr is not None:
            subprocess.run(["niri", "msg", "output", output_name, "vrr", "on" if vrr else "off"], capture_output=True)
    except Exception as e:
        print(f"Live niri output error: {e}")

    # 2. Persist to config.kdl
    try:
        with open(CONFIG_KDL_PATH, "r") as f:
            content = f.read()

        pat = rf'output\s+\"{re.escape(output_name)}\"\s*\{{([^}}]*)\}}'
        match = re.search(pat, content)
        if match:
            body = match.group(1)
            lines = [l.strip() for l in body.splitlines() if l.strip()]

            # Always remove any off lines so display is never disabled
            lines = [l for l in lines if l != "off"]

            if mode is not None:
                lines = [l for l in lines if not l.startswith("mode ") and not l.startswith("modeline ")]
                if custom_60hz or (isinstance(mode, str) and ("@60" in mode or "59.96" in mode)):
                    lines.append('modeline 173.00 1920 2048 2248 2576 1080 1083 1088 1120 "-hsync" "+vsync"')
                else:
                    lines.append(f'mode "{mode}"')
            if scale is not None:
                lines = [l for l in lines if not l.startswith("scale ")]
                lines.append(f'scale {scale}')
            if transform is not None:
                lines = [l for l in lines if not l.startswith("transform ")]
                if transform != "normal":
                    lines.append(f'transform "{transform}"')
            if position is not None:
                lines = [l for l in lines if not l.startswith("position ")]
                if isinstance(position, (list, tuple)) and len(position) >= 2:
                    lines.append(f'position x={position[0]} y={position[1]}')
            if vrr is not None:
                lines = [l for l in lines if not l.startswith("variable-refresh-rate")]
                if vrr:
                    lines.append('variable-refresh-rate')

            new_body = "\n" + "\n".join(f"    {l}" for l in lines) + "\n"
            new_content = re.sub(pat, f'output "{output_name}" {{{new_body}}}', content)
        else:
            new_lines = []
            if mode is not None:
                if custom_60hz or (isinstance(mode, str) and ("@60" in mode or "59.96" in mode)):
                    new_lines.append('modeline 173.00 1920 2048 2248 2576 1080 1083 1088 1120 "-hsync" "+vsync"')
                else:
                    new_lines.append(f'mode "{mode}"')
            if scale is not None:
                new_lines.append(f'scale {scale}')
            if transform is not None and transform != "normal":
                new_lines.append(f'transform "{transform}"')
            if position is not None and isinstance(position, (list, tuple)) and len(position) >= 2:
                new_lines.append(f'position x={position[0]} y={position[1]}')
            if vrr:
                new_lines.append('variable-refresh-rate')

            new_body = "\n" + "\n".join(f"    {l}" for l in new_lines) + "\n"
            new_block = f'\noutput "{output_name}" {{{new_body}}}\n'
            new_content = content + new_block

        with open(CONFIG_KDL_PATH, "w") as f:
            f.write(new_content)
        sync_kdl_to_dotfile(new_content)
        subprocess.run(["niri", "msg", "action", "load-config-file"], capture_output=True)
    except Exception as e:
        print(f"Error updating niri output in config: {e}")


def update_niri_input(tap=None, natural_touchpad=None, dwt=None, accel_touchpad=None, scroll_factor=None, ffm=None):
    try:
        with open(CONFIG_KDL_PATH, "r") as f:
            text = f.read()

        if tap is not None:
            if tap and "tap" not in text:
                text = text.replace("touchpad {", "touchpad {\n        tap")
            elif not tap:
                text = re.sub(r'^\s*tap\s*\n?', '', text, flags=re.MULTILINE)

        if natural_touchpad is not None:
            if natural_touchpad and "natural-scroll" not in text:
                text = text.replace("touchpad {", "touchpad {\n        natural-scroll")
            elif not natural_touchpad:
                text = re.sub(r'^\s*natural-scroll\s*\n?', '', text, flags=re.MULTILINE)

        if dwt is not None:
            if dwt and "dwt" not in text:
                text = text.replace("touchpad {", "touchpad {\n        dwt")
            elif not dwt:
                text = re.sub(r'^\s*dwt\s*\n?', '', text, flags=re.MULTILINE)

        if accel_touchpad is not None:
            if re.search(r'accel-speed\s+[\d.-]+', text):
                text = re.sub(r'accel-speed\s+[\d.-]+', f'accel-speed {accel_touchpad:.1f}', text)
            else:
                text = text.replace("touchpad {", f"touchpad {{\n        accel-speed {accel_touchpad:.1f}")

        if scroll_factor is not None:
            if re.search(r'scroll-factor\s+[\d.-]+', text):
                text = re.sub(r'scroll-factor\s+[\d.-]+', f'scroll-factor {scroll_factor:.1f}', text)
            else:
                text = text.replace("touchpad {", f"touchpad {{\n        scroll-factor {scroll_factor:.1f}")

        if ffm is not None:
            if ffm and "focus-follows-mouse" not in text:
                text = text.replace("input {", "input {\n    focus-follows-mouse max-scroll-amount=\"0%\"")
            elif not ffm:
                text = re.sub(r'^\s*focus-follows-mouse[^\n]*\n?', '', text, flags=re.MULTILINE)

        with open(CONFIG_KDL_PATH, "w") as f:
            f.write(text)
        sync_kdl_to_dotfile(text)
        subprocess.run(["niri", "msg", "action", "load-config-file"])
    except Exception as e:
        print(f"Error updating input: {e}")

def update_niri_layout(gaps=None, border_width=None):
    try:
        if gaps is not None:
            with open(CONFIG_KDL_PATH, "r") as f:
                text = f.read()
            text = re.sub(r'gaps\s+\d+', f'gaps {int(gaps)}', text)
            with open(CONFIG_KDL_PATH, "w") as f:
                f.write(text)
            sync_kdl_to_dotfile(text)

        if border_width is not None:
            theme_kdl = "/home/sreyas/.config/niri/current-theme.kdl"
            if os.path.exists(theme_kdl):
                with open(theme_kdl, "r") as f:
                    t_text = f.read()
                t_text = re.sub(r'width\s+\d+', f'width {int(border_width)}', t_text)
                with open(theme_kdl, "w") as f:
                    f.write(t_text)

        subprocess.run(["niri", "msg", "action", "load-config-file"])
    except Exception as e:
        print(f"Error updating layout: {e}")

def get_niri_blur_state():
    state = {
        "enabled": True,
        "passes": 3,
        "offset": 3.0,
        "noise": 0.02,
        "saturation": 1.4
    }
    try:
        with open(CONFIG_KDL_PATH, "r") as f:
            content = f.read()
        m = re.search(r'blur\s*\{([^}]*)\}', content)
        if m:
            body = m.group(1)
            if re.search(r'^\s*off\b', body, re.MULTILINE):
                state["enabled"] = False
            else:
                state["enabled"] = True
                p = re.search(r'passes\s+(\d+)', body)
                if p: state["passes"] = int(p.group(1))
                o = re.search(r'offset\s+([\d.]+)', body)
                if o: state["offset"] = float(o.group(1))
                n = re.search(r'noise\s+([\d.]+)', body)
                if n: state["noise"] = float(n.group(1))
                s = re.search(r'saturation\s+([\d.]+)', body)
                if s: state["saturation"] = float(s.group(1))
        else:
            state["enabled"] = False
    except Exception:
        pass
    return state

def update_niri_blur(enabled=None, passes=None, offset=None, noise=None, saturation=None):
    try:
        with open(CONFIG_KDL_PATH, "r") as f:
            content = f.read()

        current = get_niri_blur_state()
        new_enabled = current["enabled"] if enabled is None else bool(enabled)
        new_passes = current["passes"] if passes is None else int(passes)
        new_offset = current["offset"] if offset is None else float(offset)
        new_noise = current["noise"] if noise is None else float(noise)
        new_saturation = current["saturation"] if saturation is None else float(saturation)

        if not new_enabled or new_passes == 0:
            new_block = "blur {\n    off\n}"
        else:
            new_block = f"""blur {{
    passes {new_passes}
    offset {new_offset:.1f}
    noise {new_noise:.2f}
    saturation {new_saturation:.2f}
}}"""

        if re.search(r'blur\s*\{[^}]*\}', content):
            content = re.sub(r'blur\s*\{[^}]*\}', new_block, content)
        else:
            content = content + "\n\n" + new_block + "\n"

        with open(CONFIG_KDL_PATH, "w") as f:
            f.write(content)
        sync_kdl_to_dotfile(content)
        subprocess.run(["niri", "msg", "action", "load-config-file"], capture_output=True)
    except Exception as e:
        print(f"Error updating blur: {e}")

def get_niri_input_state():
    state = {
        "tap": True,
        "natural_touchpad": True,
        "dwt": True,
        "accel_touchpad": 0.2,
        "scroll_factor": 1.0,
        "ffm": True,
        "gaps": 16,
        "border_width": 2
    }
    try:
        with open(CONFIG_KDL_PATH, "r") as f:
            content = f.read()
        state["tap"] = "tap" in content
        state["natural_touchpad"] = "natural-scroll" in content
        state["dwt"] = "dwt" in content
        m = re.search(r'accel-speed\s+([\d.-]+)', content)
        if m: state["accel_touchpad"] = float(m.group(1))
        m = re.search(r'scroll-factor\s+([\d.-]+)', content)
        if m: state["scroll_factor"] = float(m.group(1))
        state["ffm"] = "focus-follows-mouse" in content
        m = re.search(r'gaps\s+(\d+)', content)
        if m: state["gaps"] = int(m.group(1))

        theme_kdl = "/home/sreyas/.config/niri/current-theme.kdl"
        if os.path.exists(theme_kdl):
            with open(theme_kdl, "r") as f:
                t_content = f.read()
            m = re.search(r'width\s+(\d+)', t_content)
            if m: state["border_width"] = int(m.group(1))
    except Exception:
        pass
    return state

def get_audio_devices():
    try:
        res = subprocess.run(["wpctl", "status"], capture_output=True, text=True, timeout=2)
        lines = res.stdout.splitlines()
        sinks = []
        sources = []
        current_section = None
        for line in lines:
            if "Sinks:" in line:
                current_section = "sinks"
                continue
            elif "Sources:" in line:
                current_section = "sources"
                continue
            elif "Filters:" in line or "Streams:" in line or "Video" in line:
                current_section = None
                continue
            if current_section:
                m = re.search(r'([* ])\s*(\d+)\.\s+(.*?)(?:\s+\[vol:|\s*$)', line)
                if m:
                    is_def = m.group(1) == '*'
                    dev_id = m.group(2)
                    dev_name = m.group(3).strip()
                    if current_section == "sinks":
                        sinks.append({"id": dev_id, "name": dev_name, "default": is_def})
                    elif current_section == "sources":
                        sources.append({"id": dev_id, "name": dev_name, "default": is_def})
        return sinks, sources
    except Exception:
        return [], []

def get_power_profile():
    try:
        res = subprocess.run("busctl get-property net.hadess.PowerProfiles /net/hadess/PowerProfiles net.hadess.PowerProfiles ActiveProfile", shell=True, capture_output=True, text=True)
        m = re.search(r'\"([^\"]+)\"', res.stdout)
        return m.group(1) if m else "balanced"
    except Exception:
        return "balanced"

def set_power_profile(profile):
    async_cmd(f'busctl set-property net.hadess.PowerProfiles /net/hadess/PowerProfiles net.hadess.PowerProfiles ActiveProfile s "{profile}"')

ENVYCONTROL_BIN = "/home/sreyas/.local/bin/envycontrol"
GRAPHICS_SWITCH_LOCK = threading.Lock()
GRAPHICS_SWITCH_IN_PROGRESS = False
GRAPHICS_SWITCH_STATUS = ""

def get_configured_graphics_mode():
    if os.path.exists("/etc/modprobe.d/blacklist-nvidia.conf") and (os.path.exists("/etc/udev/rules.d/50-remove-nvidia.rules") or os.path.exists("/lib/udev/rules.d/50-remove-nvidia.rules")):
        return "integrated"
    if os.path.exists("/etc/X11/xorg.conf.d/10-nvidia.conf") and os.path.exists("/etc/modprobe.d/nvidia.conf"):
        return "nvidia"
    if os.path.exists("/etc/modprobe.d/blacklist-nvidia.conf"):
        return "integrated"
    try:
        res = subprocess.run([ENVYCONTROL_BIN, "-q"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=2)
        if res.returncode == 0:
            m = res.stdout.strip().lower()
            if m in ["hybrid", "integrated", "nvidia"]:
                return m
    except Exception:
        pass
    return "hybrid"

def get_running_session_mode():
    if os.path.exists("/sys/module/nvidia"):
        return "hybrid"
    return "integrated"

def get_graphics_mode():
    return get_configured_graphics_mode()

def get_gpu_status_info():
    configured_mode = get_configured_graphics_mode()
    session_mode = get_running_session_mode()
    pending = (configured_mode != session_mode)
    info = {
        "mode": configured_mode,
        "configured_mode": configured_mode,
        "session_mode": session_mode,
        "pending": pending,
        "igpu": "AMD Radeon Vega Series (Renoir)",
        "dgpu": "NVIDIA GeForce GTX 1650 Mobile",
        "dgpu_status": "Unknown",
        "dgpu_power": ""
    }
    pci_status_path = "/sys/bus/pci/devices/0000:01:00.0/power/runtime_status"
    if session_mode == "integrated":
        info["dgpu_status"] = "Powered Off / Disabled"
        info["dgpu_power"] = "0W (Maximum Battery Life)"
    elif os.path.exists(pci_status_path):
        try:
            with open(pci_status_path) as f:
                st = f.read().strip().lower()
            if st == "suspended":
                info["dgpu_status"] = "Suspended (RTD3 Sleep)"
                info["dgpu_power"] = "~0W (Activates on-demand for games)"
            elif st == "active":
                info["dgpu_status"] = "Active (In-Use)"
                info["dgpu_power"] = "Powering 3D / Compute workload"
            else:
                info["dgpu_status"] = st.title()
        except Exception:
            info["dgpu_status"] = "Ready"
    else:
        info["dgpu_status"] = "Offline"
    return info

def set_graphics_mode(target_mode, on_progress=None, callback=None):
    global GRAPHICS_SWITCH_IN_PROGRESS, GRAPHICS_SWITCH_STATUS
    if GRAPHICS_SWITCH_IN_PROGRESS:
        if callback:
            GLib.idle_add(callback, False, get_configured_graphics_mode(), "Another graphics switch is already running.")
        return

    def worker():
        global GRAPHICS_SWITCH_IN_PROGRESS, GRAPHICS_SWITCH_STATUS
        with GRAPHICS_SWITCH_LOCK:
            GRAPHICS_SWITCH_IN_PROGRESS = True
            GRAPHICS_SWITCH_STATUS = "Starting configuration..."
            success = False
            err_msg = ""
            args = [ENVYCONTROL_BIN, "-s", target_mode]
            if target_mode == "hybrid":
                args += ["--rtd3", "2"]

            def update_msg(msg):
                global GRAPHICS_SWITCH_STATUS
                GRAPHICS_SWITCH_STATUS = msg
                if on_progress:
                    GLib.idle_add(on_progress, msg)

            try:
                # Test passwordless sudo
                res = subprocess.run(["sudo", "-n"] + args,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90)
                if res.returncode == 0:
                    success = True
            except Exception:
                pass

            if not success:
                try:
                    update_msg("Authenticating with system permissions...")
                    proc = subprocess.Popen(
                        ["pkexec"] + args,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1
                    )

                    if proc.stdout:
                        for line in iter(proc.stdout.readline, ""):
                            line = line.strip()
                            if not line:
                                continue
                            if "Switching to" in line:
                                update_msg(f"Configuring kernel drivers for {target_mode.title()} mode...")
                            elif "initramfs" in line:
                                update_msg("Updating boot image with dracut (~15-20s)...")
                            elif "completed successfully" in line:
                                update_msg("Graphics configuration updated successfully!")

                    proc.wait(timeout=240)
                    if proc.returncode == 0:
                        success = True
                    else:
                        stderr_out = proc.stderr.read().strip() if proc.stderr else ""
                        if proc.returncode in (126, 127) or "cancelled" in stderr_out.lower():
                            err_msg = "Authorization was cancelled."
                        else:
                            err_msg = stderr_out or f"Operation exited with code {proc.returncode}"
                except subprocess.TimeoutExpired:
                    err_msg = "Operation timed out."
                except Exception as e:
                    err_msg = str(e)
            else:
                update_msg("Configuration completed successfully!")

            GRAPHICS_SWITCH_IN_PROGRESS = False
            GRAPHICS_SWITCH_STATUS = ""
            current = get_configured_graphics_mode()
            if callback:
                GLib.idle_add(callback, success, current, err_msg)

    threading.Thread(target=worker, daemon=True).start()

HOWDY_CONFIG_PATH = "/usr/local/etc/howdy/config.ini"
HOWDY_BIN_PATH = "/usr/local/bin/howdy"

def get_howdy_status():
    if not os.path.exists(HOWDY_CONFIG_PATH):
        return False
    try:
        import configparser
        cfg = configparser.ConfigParser()
        cfg.read(HOWDY_CONFIG_PATH)
        return not cfg.getboolean("core", "disabled", fallback=False)
    except Exception:
        return False

def get_howdy_models_info():
    models_dir = "/usr/local/etc/howdy/models"
    user_model = os.path.join(models_dir, "sreyas.dat")
    if os.path.exists(user_model):
        try:
            st = os.stat(user_model)
            import datetime
            mod_time = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%b %d, %Y")
            return {
                "enrolled": True,
                "user": "sreyas",
                "file": user_model,
                "modified": mod_time,
                "size_kb": round(st.st_size / 1024, 1)
            }
        except Exception:
            pass
    return {"enrolled": False, "user": "sreyas", "file": None, "modified": "", "size_kb": 0}

def get_howdy_pam_services():
    services = {}
    for svc in ["sudo", "swaylock", "gdm-password"]:
        path = f"/etc/pam.d/{svc}"
        configured = False
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    configured = "pam_howdy.so" in f.read()
            except Exception:
                pass
        services[svc] = configured
    return services

def set_howdy_status(enable: bool, callback=None):
    """Toggles Howdy face unlock asynchronously across multiple privilege escalation tiers."""
    def worker():
        val_str = "false" if enable else "true"
        arg_val = "0" if enable else "1"
        success = False

        # Tier 1: Direct file write if writable
        try:
            if os.path.exists(HOWDY_CONFIG_PATH) and os.access(HOWDY_CONFIG_PATH, os.W_OK):
                with open(HOWDY_CONFIG_PATH, "r") as f:
                    text = f.read()
                new_text, count = re.subn(r"^(\s*disabled\s*=\s*).*$", rf"\g<1>{val_str}", text, flags=re.MULTILINE)
                if count > 0:
                    with open(HOWDY_CONFIG_PATH, "w") as f:
                        f.write(new_text)
                    success = True
        except Exception as e:
            print(f"Direct howdy config write failed: {e}")

        # Tier 2: Non-interactive sudo (if NOPASSWD configured)
        if not success:
            try:
                res = subprocess.run(["sudo", "-n", HOWDY_BIN_PATH, "disable", arg_val],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
                if res.returncode == 0:
                    success = True
            except Exception:
                pass

        # Tier 3: PolicyKit graphical authentication (prompts via lxpolkit if needed, also sets wheel group write for future instant toggles)
        if not success:
            try:
                cmd = f"{HOWDY_BIN_PATH} disable {arg_val} && chgrp wheel {HOWDY_CONFIG_PATH} && chmod 664 {HOWDY_CONFIG_PATH}"
                res = subprocess.run(["pkexec", "sh", "-c", cmd],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
                if res.returncode == 0:
                    success = True
            except Exception as e:
                print(f"pkexec howdy disable failed: {e}")

        final_state = get_howdy_status()
        if callback:
            GLib.idle_add(callback, success, final_state)

    threading.Thread(target=worker, daemon=True).start()


AUTOLOCK_CONF_PATH = os.path.expanduser("~/.config/niri/autolock.json")
DOTFILE_AUTOLOCK_PATH = os.path.expanduser("~/dotfile/niri/autolock.json")

def get_autolock_config():
    if os.path.exists(AUTOLOCK_CONF_PATH):
        try:
            with open(AUTOLOCK_CONF_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    is_running = (subprocess.run(["pgrep", "-x", "swayidle"], stdout=subprocess.DEVNULL).returncode == 0)
    return {"enabled": is_running, "timeout": 300}

def set_autolock_config(enabled, timeout=300):
    data = {"enabled": bool(enabled), "timeout": int(timeout)}
    for p in [AUTOLOCK_CONF_PATH, DOTFILE_AUTOLOCK_PATH]:
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


class AvatarCropDialog(Gtk.Dialog):
    """Interactive Crop, Pan, Zoom, and Rotation Dialog for Profile Pictures"""
    def __init__(self, parent, image_path):
        super().__init__(
            title="Crop & Adjust Profile Picture",
            transient_for=parent,
            modal=True,
            destroy_with_parent=True
        )
        self.set_default_size(460, 620)
        self.set_size_request(460, 600)
        self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self.set_name("crop-dialog")

        self.image_path = image_path
        self.orig_pixbuf = None
        self.display_pixbuf = None
        try:
            if image_path and os.path.exists(image_path):
                pb = GdkPixbuf.Pixbuf.new_from_file(image_path)
                if hasattr(pb, 'apply_embedded_orientation'):
                    pb = pb.apply_embedded_orientation()
                self.orig_pixbuf = pb
                # Create optimized display pixbuf for smooth 120Hz canvas rendering
                pw = pb.get_width()
                ph = pb.get_height()
                max_dim = max(pw, ph)
                if max_dim > 1400:
                    sc = 1400.0 / max_dim
                    self.display_pixbuf = pb.scale_simple(
                        max(1, int(round(pw * sc))),
                        max(1, int(round(ph * sc))),
                        GdkPixbuf.InterpType.BILINEAR
                    )
                else:
                    self.display_pixbuf = pb
        except Exception as e:
            print(f"Error loading image for crop dialog: {e}", file=sys.stderr)

        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.rotation_deg = 0
        self.dragging = False
        self.drag_start_x = 0.0
        self.drag_start_y = 0.0
        self.start_offset_x = 0.0
        self.start_offset_y = 0.0
        self.canvas_size = 350
        self.crop_radius = 135.0

        self.setup_ui()
        self.show_all()

    def setup_ui(self):
        content = self.get_content_area()
        content.set_spacing(12)
        content.set_margin_start(18)
        content.set_margin_end(18)
        content.set_margin_top(16)
        content.set_margin_bottom(12)

        # Header
        head_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        t_lbl = Gtk.Label(label="Crop & Adjust Picture")
        t_lbl.set_name("row-title")
        t_lbl.set_xalign(0.5)
        head_box.pack_start(t_lbl, False, False, 0)

        sub_lbl = Gtk.Label(label="Drag to reposition • Scroll or slider to zoom • Rotate 90°")
        sub_lbl.set_name("row-subtitle")
        sub_lbl.set_xalign(0.5)
        head_box.pack_start(sub_lbl, False, False, 0)
        content.pack_start(head_box, False, False, 0)

        # Canvas Frame
        canvas_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        canvas_box.set_halign(Gtk.Align.CENTER)
        canvas_box.set_name("crop-canvas-box")

        self.canvas = Gtk.DrawingArea()
        self.canvas.set_size_request(self.canvas_size, self.canvas_size)
        self.canvas.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.SCROLL_MASK |
            Gdk.EventMask.ENTER_NOTIFY_MASK |
            Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        self.canvas.connect("draw", self.on_draw)
        self.canvas.connect("button-press-event", self.on_button_press)
        self.canvas.connect("button-release-event", self.on_button_release)
        self.canvas.connect("motion-notify-event", self.on_motion)
        self.canvas.connect("scroll-event", self.on_scroll)
        self.canvas.connect("enter-notify-event", self.on_enter)
        self.canvas.connect("leave-notify-event", self.on_leave)

        canvas_box.pack_start(self.canvas, False, False, 0)
        content.pack_start(canvas_box, False, False, 0)

        # Zoom Controls
        zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        zoom_box.set_margin_start(10)
        zoom_box.set_margin_end(10)

        btn_zoom_out = Gtk.Button.new_from_icon_name("zoom-out-symbolic", Gtk.IconSize.BUTTON)
        btn_zoom_out.set_tooltip_text("Zoom Out")
        btn_zoom_out.connect("clicked", lambda *_: self.zoom_scale.set_value(max(0.5, self.zoom - 0.1)))
        zoom_box.pack_start(btn_zoom_out, False, False, 0)

        self.zoom_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.5, 4.0, 0.05)
        self.zoom_scale.set_value(1.0)
        self.zoom_scale.set_hexpand(True)
        self.zoom_scale.set_draw_value(False)
        self.zoom_scale.connect("value-changed", self.on_zoom_changed)
        zoom_box.pack_start(self.zoom_scale, True, True, 0)

        btn_zoom_in = Gtk.Button.new_from_icon_name("zoom-in-symbolic", Gtk.IconSize.BUTTON)
        btn_zoom_in.set_tooltip_text("Zoom In")
        btn_zoom_in.connect("clicked", lambda *_: self.zoom_scale.set_value(min(4.0, self.zoom + 0.1)))
        zoom_box.pack_start(btn_zoom_in, False, False, 0)

        content.pack_start(zoom_box, False, False, 0)

        # Quick Actions Row
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        actions_box.set_halign(Gtk.Align.CENTER)

        btn_rotate = Gtk.Button(label="󰑐 Rotate 90°")
        btn_rotate.connect("clicked", self.on_rotate_clicked)
        actions_box.pack_start(btn_rotate, False, False, 0)

        btn_reset = Gtk.Button(label="󰦛 Reset")
        btn_reset.connect("clicked", self.on_reset_clicked)
        actions_box.pack_start(btn_reset, False, False, 0)

        content.pack_start(actions_box, False, False, 0)

        # Dialog buttons
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        save_btn = self.add_button("󰸞 Save Avatar", Gtk.ResponseType.ACCEPT)
        save_btn.get_style_context().add_class("suggested-action")
        save_btn.set_name("crop-btn-save")
        self.set_default_response(Gtk.ResponseType.ACCEPT)

    def on_enter(self, widget, event):
        window = widget.get_window()
        if window:
            window.set_cursor(Gdk.Cursor.new_from_name(widget.get_display(), "grab"))
        return False

    def on_leave(self, widget, event):
        window = widget.get_window()
        if window:
            window.set_cursor(None)
        return False

    def on_button_press(self, widget, event):
        if event.button == 1:
            self.dragging = True
            self.drag_start_x = event.x
            self.drag_start_y = event.y
            self.start_offset_x = self.offset_x
            self.start_offset_y = self.offset_y
            window = widget.get_window()
            if window:
                window.set_cursor(Gdk.Cursor.new_from_name(widget.get_display(), "grabbing"))
            return True
        return False

    def on_button_release(self, widget, event):
        if event.button == 1:
            self.dragging = False
            window = widget.get_window()
            if window:
                window.set_cursor(Gdk.Cursor.new_from_name(widget.get_display(), "grab"))
            return True
        return False

    def on_motion(self, widget, event):
        if self.dragging:
            dx = event.x - self.drag_start_x
            dy = event.y - self.drag_start_y
            self.offset_x = self.start_offset_x + dx
            self.offset_y = self.start_offset_y + dy
            widget.queue_draw()
            return True
        return False

    def on_scroll(self, widget, event):
        factor = 1.12
        if event.direction == Gdk.ScrollDirection.UP:
            new_zoom = min(4.0, self.zoom * factor)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            new_zoom = max(0.5, self.zoom / factor)
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            _, dx, dy = event.get_scroll_deltas()
            new_zoom = min(4.0, max(0.5, self.zoom * (1.0 - dy * 0.1)))
        else:
            return False
        self.zoom_scale.set_value(new_zoom)
        return True

    def on_zoom_changed(self, scale):
        self.zoom = scale.get_value()
        self.canvas.queue_draw()

    def on_rotate_clicked(self, *_):
        self.rotation_deg = (self.rotation_deg + 90) % 360
        self.canvas.queue_draw()

    def on_reset_clicked(self, *_):
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.rotation_deg = 0
        self.zoom_scale.set_value(1.0)
        self.canvas.queue_draw()

    def on_draw(self, widget, cr):
        cw = widget.get_allocated_width()
        ch = widget.get_allocated_height()
        if cw <= 0 or ch <= 0:
            return False
        cx = cw / 2.0
        cy = ch / 2.0
        r = self.crop_radius

        colors = parse_theme_colors()
        accent = colors.get("accent-purple", (0.44, 0.42, 0.63, 1.0))

        # 1. Dark canvas background
        cr.set_source_rgb(0.06, 0.06, 0.08)
        cr.rectangle(0, 0, cw, ch)
        cr.fill()

        # 2. Draw transformed image
        draw_pb = self.display_pixbuf or self.orig_pixbuf
        if draw_pb:
            ow = draw_pb.get_width()
            oh = draw_pb.get_height()
            eff_w, eff_h = (oh, ow) if self.rotation_deg in (90, 270) else (ow, oh)
            min_dim = max(1, min(eff_w, eff_h))
            base_scale = (2.0 * r) / min_dim
            scale = base_scale * self.zoom

            cr.save()
            cr.translate(cx + self.offset_x, cy + self.offset_y)
            cr.rotate(math.radians(self.rotation_deg))
            cr.scale(scale, scale)
            Gdk.cairo_set_source_pixbuf(cr, draw_pb, -ow / 2.0, -oh / 2.0)
            cr.paint()
            cr.restore()
        else:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.45)
            layout = widget.create_pango_layout("No Image Selected")
            desc = Pango.FontDescription("13")
            layout.set_font_description(desc)
            _, logical = layout.get_pixel_extents()
            cr.move_to(cx - logical.width / 2.0, cy - logical.height / 2.0)
            PangoCairo.show_layout(cr, layout)

        # 3. Dimmed mask outside circle
        cr.save()
        cr.rectangle(0, 0, cw, ch)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.set_source_rgba(0.04, 0.04, 0.06, 0.76)
        cr.fill()
        cr.restore()

        # 4. Subtle rule-of-thirds grid inside circle
        cr.save()
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.clip()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.14)
        cr.set_line_width(1.0)
        cr.move_to(cx - r / 3.0, cy - r)
        cr.line_to(cx - r / 3.0, cy + r)
        cr.move_to(cx + r / 3.0, cy - r)
        cr.line_to(cx + r / 3.0, cy + r)
        cr.move_to(cx - r, cy - r / 3.0)
        cr.line_to(cx + r, cy - r / 3.0)
        cr.move_to(cx - r, cy + r / 3.0)
        cr.line_to(cx + r, cy + r / 3.0)
        cr.stroke()
        cr.restore()

        # 5. Accent circle border
        cr.set_source_rgba(accent[0], accent[1], accent[2], 0.95)
        cr.set_line_width(2.5)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()

        # 6. Subtle outer border of canvas
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.12)
        cr.set_line_width(1.0)
        cr.rectangle(0.5, 0.5, cw - 1.0, ch - 1.0)
        cr.stroke()
        return False

    def save_avatar(self):
        if not self.orig_pixbuf:
            return False
        try:
            ow = self.orig_pixbuf.get_width()
            oh = self.orig_pixbuf.get_height()
            eff_w, eff_h = (oh, ow) if self.rotation_deg in (90, 270) else (ow, oh)
            min_dim = max(1, min(eff_w, eff_h))
            OUT_SIZE = 512.0
            r_screen = self.crop_radius
            factor = OUT_SIZE / (2.0 * r_screen)
            out_scale = (OUT_SIZE / min_dim) * self.zoom
            out_offset_x = self.offset_x * factor
            out_offset_y = self.offset_y * factor

            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 512, 512)
            cr = cairo.Context(surface)
            cr.translate(256.0 + out_offset_x, 256.0 + out_offset_y)
            cr.rotate(math.radians(self.rotation_deg))
            cr.scale(out_scale, out_scale)
            Gdk.cairo_set_source_pixbuf(cr, self.orig_pixbuf, -ow / 2.0, -oh / 2.0)
            cr.paint()

            target_waybar = os.path.expanduser("~/.config/waybar/avatar.png")
            target_source = os.path.expanduser("~/.config/waybar/avatar_source.png")
            target_face = os.path.expanduser("~/.face")
            target_face_icon = os.path.expanduser("~/.face.icon")

            os.makedirs(os.path.dirname(target_waybar), exist_ok=True)
            surface.write_to_png(target_waybar)
            surface.write_to_png(target_face)
            try:
                surface.write_to_png(target_face_icon)
            except Exception:
                pass

            try:
                if self.image_path and os.path.exists(self.image_path) and os.path.abspath(self.image_path) != os.path.abspath(target_source):
                    shutil.copy2(self.image_path, target_source)
            except Exception:
                pass

            return True
        except Exception as e:
            print(f"Error saving cropped avatar: {e}", file=sys.stderr)
            return False


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
        sub_lbl.set_max_width_chars(46)
        text_box.pack_start(sub_lbl, False, False, 0)

    row.pack_start(text_box, True, True, 0)

    if control_widget:
        control_widget.set_valign(Gtk.Align.CENTER)
        row.pack_end(control_widget, False, False, 0)

    return row


class NiriSettingsApp(Gtk.Window):
    def __init__(self):
        super().__init__(title=APP_TITLE)
        self.set_default_size(980, 680)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.apply_css()
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
        sidebar_scroll.set_size_request(240, -1)
        sidebar_scroll.add(self.sidebar_list)
        main_box.pack_start(sidebar_scroll, False, False, 0)

        # Subtle vertical separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep.set_name("sidebar-divider")
        main_box.pack_start(sep, False, False, 0)

        # Right Content Pages Stack
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(140)
        main_box.pack_start(self.stack, True, True, 0)

        # Lazy Loading Page Factories
        self.pages_built = {}
        self.page_factories = {
            "display": self.page_display,
            "appearance": self.page_appearance,
            "users": self.page_users,
            "dock": self.page_dock,
            "mouse": self.page_mouse,
            "keyboard": self.page_keyboard,
            "sound": self.page_sound,
            "network": self.page_network,
            "notifications": self.page_notifications,
            "defaults": self.page_defaults,
            "power": self.page_power,
            "security": self.page_security,
            "storage": self.page_storage,
            "shortcuts": self.page_shortcuts,
            "about": self.page_about,
        }

        self.current_display_tab = None
        self.build_sidebar()
        self.load_page("display")
        first_row = self.sidebar_list.get_row_at_index(0)
        if first_row:
            self.sidebar_list.select_row(first_row)

    def setup_headerbar(self):
        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.set_title(APP_TITLE)
        hb.set_subtitle("Desktop Control Center")
        self.set_titlebar(hb)

        refresh_btn = Gtk.Button()
        refresh_btn.set_tooltip_text("Reload Live Settings")
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
        self.add_nav_item("users", "User & Profile", "avatar-default")
        self.add_nav_item("dock", "Dock & Top Bar", "user-desktop")
        self.add_nav_item("mouse", "Mouse & Touchpad", "input-mouse")
        self.add_nav_item("keyboard", "Keyboard & Brightness", "input-keyboard")
        self.add_nav_item("sound", "Sound & Audio", "audio-volume-high")
        self.add_nav_item("network", "Wi-Fi & Bluetooth", "network-wireless")
        self.add_nav_item("notifications", "Notifications & DND", "preferences-system-notifications")
        self.add_nav_item("defaults", "Default Applications", "preferences-desktop-default-applications")
        self.add_nav_item("power", "Power & Performance", "system-lock-screen")
        self.add_nav_item("security", "Security & Face Unlock", "dialog-password")
        self.add_nav_item("storage", "Storage & Maintenance", "drive-harddisk")
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

    def reload_display_page(self):
        if "display" in self.pages_built:
            w = self.pages_built.pop("display")
            self.stack.remove(w)
        self.load_page("display")
        self.stack.set_visible_child_name("display")

    def switch_to_page(self, page_id):
        self.load_page(page_id)
        self.stack.set_visible_child_name(page_id)
        for row in self.sidebar_list.get_children():
            if getattr(row, "page_id", None) == page_id:
                self.sidebar_list.select_row(row)
                break

    def show_graphics_switch_dialog(self, target_mode, on_complete=None):
        mode_titles = {
            "hybrid": "Hybrid Mode (AMD iGPU + On-Demand NVIDIA)",
            "integrated": "Integrated Mode (iGPU Only • Maximum Battery)",
            "nvidia": "NVIDIA Dedicated Mode (Maximum Performance)"
        }
        mode_descriptions = {
            "hybrid": "AMD Radeon Vega drives the desktop & Wayland. NVIDIA GTX 1650 enters low-power sleep (~0W) and activates automatically on-demand for games or 3D workloads.",
            "integrated": "Completely disables and powers off the NVIDIA GeForce GPU. Maximizes laptop battery life by running exclusively on AMD Radeon Vega graphics.",
            "nvidia": "Sets the NVIDIA GeForce GPU as primary for all applications. Recommended for heavy gaming, video editing, and external displays on AC power."
        }

        dlg = Gtk.Dialog(
            title="Switch Graphics Mode",
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT
        )
        dlg.set_default_size(540, 260)
        box = dlg.get_content_area()
        box.set_spacing(16)
        box.set_margin_top(22)
        box.set_margin_bottom(20)
        box.set_margin_start(24)
        box.set_margin_end(24)

        # Header with icon
        h_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        icon = Gtk.Image.new_from_icon_name("applications-games", Gtk.IconSize.DIALOG)
        h_box.pack_start(icon, False, False, 0)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        lbl_title = Gtk.Label(label=f"Switch to {mode_titles.get(target_mode, target_mode)}?")
        lbl_title.set_name("row-title")
        lbl_title.set_xalign(0)
        title_box.pack_start(lbl_title, False, False, 0)

        lbl_desc = Gtk.Label(
            label=f"{mode_descriptions.get(target_mode, '')}\n\n"
                  f"Changing graphics mode updates kernel drivers and bootloader initramfs. "
                  f"A system restart is required for the new hardware configuration to take effect."
        )
        lbl_desc.set_name("row-subtitle")
        lbl_desc.set_xalign(0)
        lbl_desc.set_line_wrap(True)
        lbl_desc.set_max_width_chars(52)
        title_box.pack_start(lbl_desc, False, False, 0)
        h_box.pack_start(title_box, True, True, 0)
        box.pack_start(h_box, True, True, 0)

        # Progress / status box
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        spinner = Gtk.Spinner()
        status_lbl = Gtk.Label(label="Configuring graphics drivers... Please wait.")
        status_lbl.set_name("row-subtitle")
        status_lbl.set_line_wrap(True)
        status_box.pack_start(spinner, False, False, 0)
        status_box.pack_start(status_lbl, True, True, 0)
        status_box.set_no_show_all(True)
        box.pack_start(status_box, False, False, 0)

        # Buttons
        btn_cancel = dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        btn_apply_later = dlg.add_button("Apply & Reboot Later", Gtk.ResponseType.APPLY)
        btn_apply_now = dlg.add_button("Apply & Reboot Now", Gtk.ResponseType.OK)
        btn_apply_now.get_style_context().add_class("suggested-action")

        dlg.show_all()

        is_running = [False]

        def on_response(dialog, response_id):
            if response_id in [Gtk.ResponseType.OK, Gtk.ResponseType.APPLY]:
                is_running[0] = True
                status_box.show()
                spinner.start()

                reboot_immediately = (response_id == Gtk.ResponseType.OK)

                if reboot_immediately:
                    btn_cancel.set_sensitive(False)
                    btn_apply_later.hide()
                    btn_apply_now.set_sensitive(False)
                    status_lbl.set_text("Authenticating with system permissions...")
                else:
                    # Apply & Reboot Later: allow user to dismiss to background at any time!
                    btn_cancel.set_label("Run in Background")
                    btn_cancel.set_sensitive(True)
                    btn_apply_later.hide()
                    btn_apply_now.hide()
                    status_lbl.set_text("Authenticating with system permissions...")

                def update_progress_ui(msg):
                    try:
                        status_lbl.set_text(msg)
                    except Exception:
                        pass

                def on_done_ui(success, final_mode, err_msg):
                    try:
                        spinner.stop()
                    except Exception:
                        pass
                    if success:
                        try:
                            subprocess.Popen([
                                "notify-send", "-u", "normal", "-i", "video-display",
                                "Graphics Mode Updated",
                                f"Switched to {target_mode.title()} mode. Please restart your computer to apply hardware changes."
                            ])
                        except Exception:
                            pass

                        if reboot_immediately:
                            try:
                                status_lbl.set_text("Graphics mode configured successfully! Rebooting system...")
                            except Exception:
                                pass
                            GLib.timeout_add(1500, lambda: subprocess.Popen(["systemctl", "reboot"]))
                        else:
                            try:
                                status_lbl.set_text(f"Successfully configured {target_mode.title()} mode! Closing...")
                                GLib.timeout_add(1200, lambda: dialog.destroy())
                            except Exception:
                                pass
                            if on_complete:
                                on_complete(True, final_mode)
                    else:
                        try:
                            status_lbl.set_text(f"Operation failed or cancelled: {err_msg}")
                            btn_cancel.set_label("Close")
                            btn_cancel.set_sensitive(True)
                            btn_apply_later.show()
                            btn_apply_later.set_sensitive(True)
                            btn_apply_now.show()
                            btn_apply_now.set_sensitive(True)
                        except Exception:
                            pass
                        if on_complete:
                            on_complete(False, final_mode)

                set_graphics_mode(target_mode, on_progress=update_progress_ui, callback=on_done_ui)
                return True
            else:
                dialog.destroy()
                if is_running[0] and on_complete:
                    on_complete(None, None)
                return False

        dlg.connect("response", on_response)

    def make_page_container(self, title, description=""):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        vbox.set_margin_top(22)
        vbox.set_margin_bottom(28)
        vbox.set_margin_start(30)
        vbox.set_margin_end(30)

        header_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title_lbl = Gtk.Label(label=title)
        title_lbl.set_name("page-title")
        title_lbl.set_xalign(0)
        header_vbox.pack_start(title_lbl, False, False, 0)

        if description:
            desc_lbl = Gtk.Label(label=description)
            desc_lbl.set_name("page-description")
            desc_lbl.set_xalign(0)
            header_vbox.pack_start(desc_lbl, False, False, 0)

        vbox.pack_start(header_vbox, False, False, 0)
        scroll.add(vbox)
        return scroll, vbox

    # ==========================================
    # PAGE 1: DISPLAY & MONITOR
    # ==========================================
    def page_display(self):
        scroll, vbox = self.make_page_container("Display & Monitor", "Panel resolution, refresh rate, screen mirroring for projectors, and multi-display layout")

        outputs_info = get_niri_outputs_info()
        if not outputs_info:
            outputs_info = {
                "eDP-1": {
                    "name": "eDP-1",
                    "make": "AU Optronics",
                    "model": "0xD1ED",
                    "physical_size": [340, 190],
                    "modes": [{"width": 1920, "height": 1080, "refresh_rate": 120213, "is_preferred": True}],
                    "current_mode": 0,
                    "logical": {"x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1.0, "transform": "Normal"}
                }
            }

        display_names = list(outputs_info.keys())
        if not hasattr(self, "current_display_tab") or self.current_display_tab not in display_names:
            self.current_display_tab = "eDP-1" if "eDP-1" in display_names else display_names[0]

        active_disp = self.current_display_tab
        disp_data = outputs_info.get(active_disp, {})

        # -------------------------------------------------------------
        # 1. DISPLAY SELECTOR / TOP BAR
        # -------------------------------------------------------------
        selector_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        selector_box.set_margin_bottom(6)

        tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for d_name in display_names:
            d_info = outputs_info[d_name]
            d_make = d_info.get("make", "") or "Display"
            is_primary = (d_name == "eDP-1")
            
            btn_label = f"{d_name}"
            if d_make and d_make != "Unknown":
                btn_label += f" ({d_make})"
            if is_primary:
                btn_label += " ★ Primary"

            btn = Gtk.Button(label=btn_label)
            btn.set_name("display-pill-btn")
            if d_name == active_disp:
                btn.get_style_context().add_class("suggested-action")
            
            def make_tab_cb(target_name):
                def _cb(_):
                    self.current_display_tab = target_name
                    self.reload_display_page()
                return _cb
            btn.connect("clicked", make_tab_cb(d_name))
            tab_box.pack_start(btn, False, False, 0)

        selector_box.pack_start(tab_box, True, True, 0)

        # Rescan Displays Button
        rescan_btn = Gtk.Button(label="Rescan 🔄")
        rescan_btn.set_tooltip_text("Detect newly connected monitors, projectors, or HDMI cables")
        rescan_btn.connect("clicked", lambda _: self.reload_display_page())
        selector_box.pack_end(rescan_btn, False, False, 0)

        # Identify Displays Button
        def on_identify_clicked(_):
            for name, info in outputs_info.items():
                m_str = "Active"
                if info.get("logical"):
                    l = info["logical"]
                    m_str = f"{l.get('width', '')}x{l.get('height', '')} @ {l.get('scale', 1.0)}x"
                subprocess.Popen([
                    "notify-send", "-u", "normal", "-i", "video-display", "-t", "4000",
                    f"Display: {name}", f"Model: {info.get('make', '')} {info.get('model', '')}\nMode: {m_str}"
                ])
        identify_btn = Gtk.Button(label="Identify")
        identify_btn.set_tooltip_text("Flash display identifiers on all connected monitors")
        identify_btn.connect("clicked", on_identify_clicked)
        selector_box.pack_end(identify_btn, False, False, 4)

        vbox.pack_start(selector_box, False, False, 0)

        # -------------------------------------------------------------
        # 2. DISPLAY HARDWARE & STATUS CARD
        # -------------------------------------------------------------
        info_card = SettingsCard()
        vbox.pack_start(info_card, False, False, 0)

        phys = disp_data.get("physical_size") or [340, 190]
        if phys and len(phys) >= 2 and phys[0] and phys[1]:
            diag = round(((phys[0]**2 + phys[1]**2)**0.5) / 25.4, 1)
            size_str = f"{diag}\""
        else:
            size_str = "External"

        logical = disp_data.get("logical")
        is_display_on = logical is not None
        if logical:
            log_desc = f"Active • {logical.get('width')}x{logical.get('height')} @ {logical.get('scale', 1.0)}x • Pos: ({logical.get('x', 0)}, {logical.get('y', 0)})"
        else:
            log_desc = "Connected"

        make_model = f"{disp_data.get('make', 'Generic')} {disp_data.get('model', '')}".strip()
        info_card.add_row(create_setting_row(
            "video-display",
            f"{make_model} ({active_disp})",
            f"{size_str} Panel • {log_desc}",
            Gtk.Label(label="Primary" if active_disp == "eDP-1" else "Secondary")
        ))

        # GPU Status info
        gpu_info = get_gpu_status_info()
        gpu_btn = Gtk.Button(label="Manage in Power Settings →")
        gpu_btn.connect("clicked", lambda *_: self.switch_to_page("power"))
        info_card.add_row(create_setting_row(
            "applications-games",
            "Graphics Processors (GPU)",
            f"Mode: {gpu_info['mode'].title()} • {gpu_info['igpu']} + {gpu_info['dgpu']} ({gpu_info['dgpu_status']})",
            gpu_btn
        ))

        # -------------------------------------------------------------
        # 3. DISPLAY RESOLUTION & MODE SETTINGS CARD
        # -------------------------------------------------------------
        mode_card = SettingsCard()
        vbox.pack_start(mode_card, False, False, 0)

        modes = disp_data.get("modes", [])
        res_dict = {}
        for m in modes:
            key = (m.get("width", 1920), m.get("height", 1080))
            res_dict.setdefault(key, []).append(m)

        # Inject 60 Hz Battery Saver option if a display only reports >= 100 Hz modes in hardware EDID
        for key in list(res_dict.keys()):
            rates = [m.get("refresh_rate", 0) for m in res_dict[key]]
            if any(r >= 100000 for r in rates) and not any(55000 <= r <= 65000 for r in rates):
                res_dict[key].append({
                    "width": key[0],
                    "height": key[1],
                    "refresh_rate": 60000,
                    "is_preferred": False,
                    "is_custom": True
                })

        sorted_res = sorted(list(res_dict.keys()), key=lambda k: k[0] * k[1], reverse=True)
        if not sorted_res:
            sorted_res = [(1920, 1080)]
            res_dict[(1920, 1080)] = [{"width": 1920, "height": 1080, "refresh_rate": 120213, "is_preferred": True}]

        cur_mode_idx = disp_data.get("current_mode")
        if cur_mode_idx is not None and 0 <= cur_mode_idx < len(modes):
            cur_m = modes[cur_mode_idx]
            cur_w, cur_h = cur_m.get("width", 1920), cur_m.get("height", 1080)
            cur_rate_mhz = cur_m.get("refresh_rate", 120213)
        else:
            cur_w, cur_h = sorted_res[0]
            cur_rate_mhz = res_dict[(cur_w, cur_h)][0].get("refresh_rate", 120213)

        # If output is configured with custom modeline in config.kdl, reflect 60 Hz active
        try:
            with open(CONFIG_KDL_PATH, "r") as _f:
                _cfg_text = _f.read()
            _pat = rf'output\s+\"{re.escape(active_disp)}\"\s*\{{([^}}]*)\}}'
            _m = re.search(_pat, _cfg_text)
            if _m and "modeline" in _m.group(1):
                cur_rate_mhz = 60000
        except Exception:
            pass

        cur_res_id = f"{cur_w}x{cur_h}"
        updating_mode = [False]

        # Resolution Dropdown
        res_combo = Gtk.ComboBoxText()
        for (w, h) in sorted_res:
            aspect = get_aspect_ratio_str(w, h)
            is_pref = any(m.get("is_preferred", False) for m in res_dict[(w, h)])
            label = f"{w}x{h} ({aspect})" + (" — Native" if is_pref else "")
            res_combo.append(f"{w}x{h}", label)
        res_combo.set_active_id(cur_res_id if cur_res_id in [f"{w}x{h}" for w, h in sorted_res] else f"{sorted_res[0][0]}x{sorted_res[0][1]}")

        # Refresh Rate Dropdown
        rate_combo = Gtk.ComboBoxText()
        def populate_rate_combo(res_str, select_mhz=None):
            rate_combo.remove_all()
            try:
                w_str, h_str = res_str.split("x")
                w, h = int(w_str), int(h_str)
                m_list = res_dict.get((w, h), [])
                m_list_sorted = sorted(m_list, key=lambda m: m.get("refresh_rate", 0), reverse=True)
                for m in m_list_sorted:
                    mhz = m.get("refresh_rate", 60000)
                    hz_num = round(mhz / 1000.0, 2)
                    if m.get("is_preferred"):
                        hz_label = f"{hz_num} Hz (Native - Smooth)"
                    elif 58.0 <= hz_num <= 62.0:
                        hz_label = f"{hz_num} Hz (Battery Saver)"
                    else:
                        hz_label = f"{hz_num} Hz"
                    rate_combo.append(str(mhz), hz_label)

                if select_mhz is not None:
                    sel_int = int(select_mhz)
                    matched_id = None
                    for m in m_list_sorted:
                        if abs(m.get("refresh_rate", 0) - sel_int) < 2500:
                            matched_id = str(m.get("refresh_rate"))
                            break
                    if matched_id:
                        rate_combo.set_active_id(matched_id)
                    elif m_list_sorted:
                        rate_combo.set_active_id(str(m_list_sorted[0].get("refresh_rate")))
                elif m_list_sorted:
                    rate_combo.set_active_id(str(m_list_sorted[0].get("refresh_rate")))
            except Exception as e:
                print(f"Error populating rate combo: {e}")

        populate_rate_combo(cur_res_id, cur_rate_mhz)

        def apply_selected_mode():
            if updating_mode[0]:
                return
            res_id = res_combo.get_active_id()
            rate_id = rate_combo.get_active_id()
            if not res_id:
                return
            is_custom = False
            if rate_id:
                try:
                    mhz_val = int(rate_id)
                    hz_float = mhz_val / 1000.0
                    mode_str = f"{res_id}@{hz_float:.3f}"
                    if 58000 <= mhz_val <= 62000 and res_id == "1920x1080":
                        orig_rates = [m.get("refresh_rate", 0) for m in disp_data.get("modes", []) if (m.get("width"), m.get("height")) == (1920, 1080) and not m.get("is_custom", False)]
                        if not any(58000 <= r <= 62000 for r in orig_rates):
                            is_custom = True
                except ValueError:
                    mode_str = res_id
            else:
                mode_str = res_id
            update_niri_output(active_disp, mode=mode_str, custom_60hz=is_custom)

        def on_res_changed(combo):
            if updating_mode[0]:
                return
            res_id = combo.get_active_id()
            if not res_id:
                return
            updating_mode[0] = True
            populate_rate_combo(res_id)
            updating_mode[0] = False
            apply_selected_mode()

        def on_rate_changed(combo):
            if updating_mode[0]:
                return
            apply_selected_mode()

        res_combo.connect("changed", on_res_changed)
        rate_combo.connect("changed", on_rate_changed)

        mode_card.add_row(create_setting_row(
            "preferences-desktop-display",
            "Screen Resolution",
            "Change display resolution. Native aspect ratio offers crisp text and ideal geometry.",
            res_combo
        ))

        mode_card.add_row(create_setting_row(
            "video-display",
            "Display Refresh Rate",
            "Vertical refresh frequency. Higher rates deliver ultra-smooth window scrolling.",
            rate_combo
        ))

        # Desktop Scaling Dropdown
        cur_scale = str(disp_data.get("logical", {}).get("scale", 1.0)) if disp_data.get("logical") else "1.0"
        scale_combo = Gtk.ComboBoxText()
        scale_combo.append("1.0", "100% (Native 1.0x)")
        scale_combo.append("1.25", "125% (Comfortable 1.25x)")
        scale_combo.append("1.5", "150% (High DPI 1.5x)")
        scale_combo.append("1.75", "175% (1.75x)")
        scale_combo.append("2.0", "200% (Retina 2.0x)")
        scale_combo.set_active_id(cur_scale if cur_scale in ["1.0", "1.25", "1.5", "1.75", "2.0"] else "1.0")
        scale_combo.connect("changed", lambda c: update_niri_output(active_disp, scale=c.get_active_id()))

        mode_card.add_row(create_setting_row(
            "zoom-fit-best",
            "Desktop Scaling",
            "Scale UI elements proportionally for high resolution visibility and comfort",
            scale_combo
        ))

        # Display Orientation / Rotation Dropdown
        cur_trans = str(disp_data.get("logical", {}).get("transform", "Normal")).lower() if disp_data.get("logical") else "normal"
        trans_combo = Gtk.ComboBoxText()
        trans_combo.append("normal", "Standard (Landscape - 0°)")
        trans_combo.append("90", "Rotated 90° (Portrait - Clockwise)")
        trans_combo.append("180", "Inverted 180° (Upside Down)")
        trans_combo.append("270", "Rotated 270° (Portrait - Counter-Clockwise)")
        trans_combo.set_active_id(cur_trans if cur_trans in ["normal", "90", "180", "270"] else "normal")
        trans_combo.connect("changed", lambda c: update_niri_output(active_disp, transform=c.get_active_id()))

        mode_card.add_row(create_setting_row(
            "object-rotate-right",
            "Display Orientation",
            "Rotate screen orientation for vertical monitor stands or presentations",
            trans_combo
        ))

        # Display Arrangement / Position (when multiple monitors exist)
        if len(display_names) > 1 and active_disp != "eDP-1":
            pos_combo = Gtk.ComboBoxText()
            pos_combo.append("auto", "Auto (Niri Managed Placement)")
            pos_combo.append("right", "Right of Primary (eDP-1)")
            pos_combo.append("left", "Left of Primary (eDP-1)")
            pos_combo.append("above", "Above Primary (eDP-1)")
            pos_combo.append("below", "Below Primary (eDP-1)")

            cur_pos = disp_data.get("logical")
            if cur_pos:
                cx, cy = cur_pos.get("x", 0), cur_pos.get("y", 0)
                if cx > 0 and cy == 0:
                    pos_combo.set_active_id("right")
                elif cx < 0 and cy == 0:
                    pos_combo.set_active_id("left")
                elif cy < 0 and cx == 0:
                    pos_combo.set_active_id("above")
                elif cy > 0 and cx == 0:
                    pos_combo.set_active_id("below")
                else:
                    pos_combo.set_active_id("auto")
            else:
                pos_combo.set_active_id("auto")

            def on_pos_changed(c):
                pid = c.get_active_id()
                pri_log = outputs_info.get("eDP-1", {}).get("logical", {"width": 1920, "height": 1080})
                pri_w = pri_log.get("width", 1920)
                pri_h = pri_log.get("height", 1080)
                sec_log = disp_data.get("logical", {"width": 1920, "height": 1080})
                sec_w = sec_log.get("width", 1920)
                sec_h = sec_log.get("height", 1080)

                if pid == "right":
                    update_niri_output(active_disp, position=(pri_w, 0))
                elif pid == "left":
                    update_niri_output(active_disp, position=(-sec_w, 0))
                elif pid == "above":
                    update_niri_output(active_disp, position=(0, -sec_h))
                elif pid == "below":
                    update_niri_output(active_disp, position=(0, pri_h))
                else:
                    update_niri_output(active_disp, position="auto")

            pos_combo.connect("changed", on_pos_changed)
            mode_card.add_row(create_setting_row(
                "video-display",
                "Display Arrangement",
                "Position this secondary monitor relative to primary laptop display",
                pos_combo
            ))

        # VRR Switch
        vrr_switch = Gtk.Switch()
        vrr_switch.set_active(disp_data.get("vrr_enabled", False))
        vrr_switch.set_sensitive(disp_data.get("vrr_supported", True))
        vrr_switch.connect("state-set", lambda _, state: (update_niri_output(active_disp, vrr=state), False)[1])

        mode_card.add_row(create_setting_row(
            "applications-games",
            "Variable Refresh Rate (VRR / FreeSync)",
            "Dynamically scales refresh rate between 60 Hz and 120 Hz to eliminate tearing and save battery",
            vrr_switch
        ))

        # -------------------------------------------------------------
        # 4. PROJECTOR & SCREEN MIRRORING CARD
        # -------------------------------------------------------------
        mirror_card = SettingsCard()
        vbox.pack_start(mirror_card, False, False, 0)

        # Mirror Status & Master Toggle
        mirror_active = is_mirror_running()
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        status_badge = Gtk.Label(label="● Mirroring Active" if mirror_active else "● Mirroring Inactive")
        status_badge.set_name("badge-label-active" if mirror_active else "badge-label-muted")

        mirror_btn = Gtk.Button(label="⏹ Stop Mirroring" if mirror_active else "▶ Start Projector Mirror")
        if not mirror_active:
            mirror_btn.get_style_context().add_class("suggested-action")
        else:
            mirror_btn.get_style_context().add_class("destructive-action")

        status_box.pack_start(status_badge, False, False, 0)
        status_box.pack_start(mirror_btn, False, False, 0)

        mirror_card.add_row(create_setting_row(
            "preferences-desktop-display",
            "Projector & Screen Mirroring",
            "Duplicate your screen to an external projector or monitor for presentations and slideshows",
            status_box
        ))

        # Source & Target Output Selectors
        src_target_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        src_combo = Gtk.ComboBoxText()
        for n in display_names:
            src_combo.append(n, f"Source: {n}" + (" (Laptop)" if n == "eDP-1" else ""))
        src_combo.set_active_id("eDP-1" if "eDP-1" in display_names else display_names[0])

        arrow_lbl = Gtk.Label(label="→")
        arrow_lbl.set_name("row-title")

        target_combo = Gtk.ComboBoxText()
        other_outputs = [n for n in display_names if n != src_combo.get_active_id()]
        for n in other_outputs:
            target_combo.append(n, f"Projector: {n}")
        target_combo.append("window", "Preview (Floating Window)")
        if other_outputs:
            target_combo.set_active_id(other_outputs[0])
        else:
            target_combo.set_active_id("window")

        src_target_box.pack_start(src_combo, False, False, 0)
        src_target_box.pack_start(arrow_lbl, False, False, 0)
        src_target_box.pack_start(target_combo, False, False, 0)

        mirror_card.add_row(create_setting_row(
            "video-display",
            "Mirror Source & Target",
            "Select display to broadcast and the connected projector or external screen",
            src_target_box
        ))

        # Scaling Mode Dropdown
        scaling_combo = Gtk.ComboBoxText()
        scaling_combo.append("fit", "Fit Screen (Preserve Aspect Ratio - Best for Projectors)")
        scaling_combo.append("cover", "Cover Screen (Fill completely, crop borders)")
        scaling_combo.append("exact", "Exact (1:1 Multiples)")
        scaling_combo.set_active_id("fit")

        mirror_card.add_row(create_setting_row(
            "zoom-fit-best",
            "Projector Aspect Ratio & Scaling",
            "Fit preserves original proportions on 4:3 and 16:9 projectors without image stretching",
            scaling_combo
        ))

        # Show Mouse Cursor Switch
        cursor_switch = Gtk.Switch()
        cursor_switch.set_active(True)

        mirror_card.add_row(create_setting_row(
            "input-mouse",
            "Show Cursor on Projector",
            "Display the mouse pointer clearly on the mirrored presentation screen",
            cursor_switch
        ))

        # Master Button Callback
        def on_mirror_btn_clicked(_):
            if is_mirror_running():
                subprocess.run([MIRROR_SCRIPT, "stop"])
            else:
                src = src_combo.get_active_id() or "eDP-1"
                tgt = target_combo.get_active_id() or ""
                s_mode = scaling_combo.get_active_id() or "fit"
                s_cur = "yes" if cursor_switch.get_active() else "no"
                subprocess.Popen([MIRROR_SCRIPT, "start", src, tgt, s_mode, s_cur])
            
            GLib.timeout_add(350, update_mirror_ui_state)

        mirror_btn.connect("clicked", on_mirror_btn_clicked)

        def update_mirror_ui_state():
            active = is_mirror_running()
            if active:
                status_badge.set_text("● Mirroring Active")
                status_badge.set_name("badge-label-active")
                mirror_btn.set_label("⏹ Stop Mirroring")
                mirror_btn.get_style_context().remove_class("suggested-action")
                mirror_btn.get_style_context().add_class("destructive-action")
            else:
                status_badge.set_text("● Mirroring Inactive")
                status_badge.set_name("badge-label-muted")
                mirror_btn.set_label("▶ Start Projector Mirror")
                mirror_btn.get_style_context().remove_class("destructive-action")
                mirror_btn.get_style_context().add_class("suggested-action")
            return True

        # Keep state updated via timeout while viewing this page
        timer_id = GLib.timeout_add(1500, update_mirror_ui_state)
        scroll.connect("destroy", lambda _: GLib.source_remove(timer_id))

        # Shortcut Quick Tip Box
        tip_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        tip_box.set_name("info-banner")
        tip_icon = Gtk.Image.new_from_icon_name("dialog-information", Gtk.IconSize.DND)
        tip_lbl = Gtk.Label(label="Quick Shortcut: Press Mod + P or your laptop's Display key (Fn + F7/F8) anytime to instantly toggle projector mirroring on and off.")
        tip_lbl.set_line_wrap(True)
        tip_lbl.set_xalign(0)
        tip_box.pack_start(tip_icon, False, False, 0)
        tip_box.pack_start(tip_lbl, True, True, 0)
        vbox.pack_start(tip_box, False, False, 0)

        # -------------------------------------------------------------
        # NIGHT LIGHT / EYE COMFORT CARD
        # -------------------------------------------------------------
        nl_card = SettingsCard()
        vbox.pack_start(nl_card, False, False, 0)

        nl_state = get_night_light_state()
        cur_k = max(2000, min(6500, nl_state["temperature"]))
        cur_warmth = int(round((6500 - cur_k) / (6500 - 2000) * 100))
        cur_bright = int(round(nl_state["brightness"] * 100))

        nl_controls = []

        # Master Toggle Switch
        nl_switch = Gtk.Switch()
        nl_is_active = nl_state["enabled"] or nl_state["running"]
        nl_switch.set_active(nl_is_active)

        nl_card.add_row(create_setting_row(
            "night-light-symbolic",
            "Night Light (Eye Comfort)",
            "Warm up display colors to reduce eye fatigue and blue light exposure",
            nl_switch
        ))

        # Warmth / Color Temperature Slider
        temp_row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        temp_val_lbl = Gtk.Label(label=f"{cur_k} K")
        temp_val_lbl.set_name("row-subtitle")
        temp_val_lbl.set_width_chars(7)

        temp_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        temp_scale.set_value(cur_warmth)
        temp_scale.set_size_request(200, -1)
        temp_scale.set_tooltip_text("Slide right for warmer amber light")
        temp_scale.set_sensitive(nl_is_active)
        nl_controls.append(temp_scale)

        temp_row_box.pack_start(temp_scale, True, True, 0)
        temp_row_box.pack_start(temp_val_lbl, False, False, 0)

        # Brightness / Soft Dimming Slider
        bright_row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bright_val_lbl = Gtk.Label(label=f"{cur_bright}%")
        bright_val_lbl.set_name("row-subtitle")
        bright_val_lbl.set_width_chars(5)

        bright_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 50, 100, 5)
        bright_scale.set_value(cur_bright)
        bright_scale.set_size_request(200, -1)
        bright_scale.set_tooltip_text("Screen gamma brightness attenuation")
        bright_scale.set_sensitive(nl_is_active)
        nl_controls.append(bright_scale)

        bright_row_box.pack_start(bright_scale, True, True, 0)
        bright_row_box.pack_start(bright_val_lbl, False, False, 0)

        # Debounced applier
        apply_timer = [None]
        def queue_apply_night_light():
            if apply_timer[0] is not None:
                GLib.source_remove(apply_timer[0])
            def do_apply():
                apply_timer[0] = None
                w_val = temp_scale.get_value()
                k = int(round(6500 - (w_val / 100.0) * (6500 - 2000)))
                b = round(bright_scale.get_value() / 100.0, 2)
                if nl_switch.get_active():
                    set_night_light_params(k, b)
                return False
            apply_timer[0] = GLib.timeout_add(70, do_apply)

        def on_temp_changed(scale):
            w_val = scale.get_value()
            k = int(round(6500 - (w_val / 100.0) * (6500 - 2000)))
            temp_val_lbl.set_text(f"{k} K")
            queue_apply_night_light()

        def on_bright_changed(scale):
            b_val = int(scale.get_value())
            bright_val_lbl.set_text(f"{b_val}%")
            queue_apply_night_light()

        temp_scale.connect("value-changed", on_temp_changed)
        bright_scale.connect("value-changed", on_bright_changed)

        def on_switch_toggled(sw, state):
            for c in nl_controls:
                c.set_sensitive(state)
            w_val = temp_scale.get_value()
            k = int(round(6500 - (w_val / 100.0) * (6500 - 2000)))
            b = round(bright_scale.get_value() / 100.0, 2)
            set_night_light_enabled(state, k, b)
            return False

        nl_switch.connect("state-set", on_switch_toggled)

        nl_card.add_row(create_setting_row(
            "preferences-desktop-display",
            "Warmth Intensity",
            "Color temperature (higher intensity gives a warmer amber tint)",
            temp_row_box
        ))

        nl_card.add_row(create_setting_row(
            "display-brightness",
            "Night Light Dimming",
            "Softer contrast and brightness level for low-light environments",
            bright_row_box
        ))

        # Preset Chips Row
        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        preset_box.set_sensitive(nl_is_active)
        nl_controls.append(preset_box)

        presets = [
            ("Mild", 5500),
            ("Comfort", 4200),
            ("Deep Warm", 3000),
            ("Candlelight", 2000),
        ]
        for name, k_target in presets:
            pct = int(round((6500 - k_target) / (6500 - 2000) * 100))
            btn = Gtk.Button(label=f"{name} ({k_target}K)")
            def make_cb(target_pct, target_k):
                def _cb(_):
                    temp_scale.set_value(target_pct)
                    b = round(bright_scale.get_value() / 100.0, 2)
                    if not nl_switch.get_active():
                        nl_switch.set_active(True)
                    set_night_light_params(target_k, b)
                return _cb
            btn.connect("clicked", make_cb(pct, k_target))
            preset_box.pack_start(btn, True, True, 0)

        nl_card.add_row(create_setting_row(
            "starred-symbolic",
            "Warmth Presets",
            "Instant color temperature profiles for common lighting conditions",
            preset_box
        ))

        return scroll

    # ==========================================
    # PAGE 2: APPEARANCE & THEMES
    # ==========================================
    def page_appearance(self):
        scroll, vbox = self.make_page_container("Appearance & Themes", "Personalize desktop wallpapers, dynamic Wallust palette, GTK themes, and window layout")

        # Current Wallpaper Card with Thumbnail
        wall_card = SettingsCard()
        vbox.pack_start(wall_card, False, False, 0)

        cur_wall = "/home/sreyas/wall/0anime4.jpg"
        if os.path.exists(CURRENT_WALL_CACHE):
            try:
                with open(CURRENT_WALL_CACHE, "r") as f:
                    c = f.read().strip()
                    if os.path.exists(c):
                        cur_wall = c
            except Exception:
                pass

        thumb_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        thumb_box.set_margin_start(16)
        thumb_box.set_margin_end(16)
        thumb_box.set_margin_top(12)
        thumb_box.set_margin_bottom(12)

        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(cur_wall, 160, 90, False)
            wall_img = Gtk.Image.new_from_pixbuf(pixbuf)
            wall_img.set_name("wall-preview-img")
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

        # Quick Wallpaper Gallery
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

        # Desktop Theme Profiles
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
                "Full palette sync: Waybar, Kitty, Fuzzel & SwayNC",
                t_btn
            ))

        # System GTK & UI Styling Card
        vbox.pack_start(Gtk.Label(label="SYSTEM GTK & WINDOW STYLING", xalign=0, name="section-caption"), False, False, 0)
        style_card = SettingsCard()
        vbox.pack_start(style_card, False, False, 0)

        # Dark Mode Preference
        cur_color_scheme = run_cmd("gsettings get org.gnome.desktop.interface color-scheme")
        dark_switch = Gtk.Switch()
        dark_switch.set_active("prefer-dark" in cur_color_scheme)
        def on_dark_toggled(sw, state):
            val = "prefer-dark" if state else "prefer-light"
            async_cmd(f"gsettings set org.gnome.desktop.interface color-scheme '{val}'")
            return False
        dark_switch.connect("state-set", on_dark_toggled)

        style_card.add_row(create_setting_row(
            "weather-clear-night",
            "Dark Mode Preference",
            "Request modern dark interface styling in all GTK and web applications",
            dark_switch
        ))

        # GTK Theme Dropdown
        cur_gtk_theme = run_cmd("gsettings get org.gnome.desktop.interface gtk-theme").strip("'\"")
        gtk_combo = Gtk.ComboBoxText()
        for gt in ["Adwaita-dark", "Adwaita", "Breeze-Dark", "Breeze"]:
            gtk_combo.append(gt, gt)
        gtk_combo.set_active_id(cur_gtk_theme if cur_gtk_theme in ["Adwaita-dark", "Adwaita", "Breeze-Dark", "Breeze"] else "Adwaita-dark")
        gtk_combo.connect("changed", lambda c: async_cmd(f"gsettings set org.gnome.desktop.interface gtk-theme '{c.get_active_id()}'"))

        style_card.add_row(create_setting_row(
            "preferences-desktop-theme",
            "GTK Widget Theme",
            "System visual styling for native GTK applications and dialogs",
            gtk_combo
        ))

        # Icon Theme Dropdown
        cur_icon_theme = run_cmd("gsettings get org.gnome.desktop.interface icon-theme").strip("'\"")
        icon_combo = Gtk.ComboBoxText()
        for it in ["Adwaita", "breeze-dark", "breeze", "elementary", "gnome"]:
            icon_combo.append(it, it.title())
        icon_combo.set_active_id(cur_icon_theme if cur_icon_theme in ["Adwaita", "breeze-dark", "breeze", "elementary", "gnome"] else "Adwaita")
        icon_combo.connect("changed", lambda c: async_cmd(f"gsettings set org.gnome.desktop.interface icon-theme '{c.get_active_id()}'"))

        style_card.add_row(create_setting_row(
            "preferences-desktop-icons",
            "System Icon Theme",
            "Application and file icon set used throughout the desktop",
            icon_combo
        ))

        # Cursor Size Dropdown
        cur_cursor_size = run_cmd("gsettings get org.gnome.desktop.interface cursor-size").strip() or "24"
        cursor_combo = Gtk.ComboBoxText()
        cursor_combo.append("24", "24 px (Standard)")
        cursor_combo.append("32", "32 px (Medium)")
        cursor_combo.append("48", "48 px (Large / High DPI)")
        cursor_combo.set_active_id(cur_cursor_size if cur_cursor_size in ["24", "32", "48"] else "24")
        cursor_combo.connect("changed", lambda c: async_cmd(f"gsettings set org.gnome.desktop.interface cursor-size {c.get_active_id()}"))

        style_card.add_row(create_setting_row(
            "input-mouse",
            "Mouse Cursor Size",
            "Adjust cursor arrow and pointer dimensions",
            cursor_combo
        ))

        # Niri Window Gaps & Borders
        kdl_state = get_niri_input_state()
        gaps_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 32, 2)
        gaps_scale.set_value(kdl_state["gaps"])
        gaps_scale.set_size_request(180, -1)
        gaps_scale.connect("value-changed", lambda s: update_niri_layout(gaps=s.get_value()))

        style_card.add_row(create_setting_row(
            "view-fullscreen",
            "Window Gaps (Spacing)",
            "Margin separation spacing between tiled columns and screen edges",
            gaps_scale
        ))

        border_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 6, 1)
        border_scale.set_value(kdl_state["border_width"])
        border_scale.set_size_request(180, -1)
        border_scale.connect("value-changed", lambda s: update_niri_layout(border_width=s.get_value()))

        style_card.add_row(create_setting_row(
            "preferences-desktop-display",
            "Active Window Border Width",
            "Glow outline thickness around currently focused window",
            border_scale
        ))

        # Frosted Glass & Background Blur Card
        vbox.pack_start(Gtk.Label(label="FROSTED GLASS & BLUR EFFECTS", xalign=0, name="section-caption"), False, False, 0)
        blur_card = SettingsCard()
        vbox.pack_start(blur_card, False, False, 0)

        blur_state = get_niri_blur_state()

        # 1. Master Blur Switch
        blur_switch = Gtk.Switch()
        blur_switch.set_active(blur_state["enabled"])

        blur_card.add_row(create_setting_row(
            "weather-fog",
            "Dual-Kawase Background Blur",
            "Hardware-accelerated frosted glass effect on translucent windows, terminals, and menus",
            blur_switch
        ))

        # 2. Blur Quality (Passes)
        passes_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 4, 1)
        passes_scale.set_digits(0)
        passes_scale.set_value(blur_state["passes"])
        passes_scale.set_size_request(180, -1)
        passes_scale.set_sensitive(blur_state["enabled"])

        # 3. Blur Spread / Offset
        offset_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1.0, 6.0, 0.5)
        offset_scale.set_digits(1)
        offset_scale.set_value(blur_state["offset"])
        offset_scale.set_size_request(180, -1)
        offset_scale.set_sensitive(blur_state["enabled"])

        # 4. Color Saturation Boost
        sat_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1.0, 1.8, 0.1)
        sat_scale.set_digits(1)
        sat_scale.set_value(blur_state["saturation"])
        sat_scale.set_size_request(180, -1)
        sat_scale.set_sensitive(blur_state["enabled"])

        # 5. Film Grain / Noise
        noise_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 0.08, 0.01)
        noise_scale.set_digits(2)
        noise_scale.set_value(blur_state["noise"])
        noise_scale.set_size_request(180, -1)
        noise_scale.set_sensitive(blur_state["enabled"])

        blur_timer = [None]
        def schedule_blur_update():
            if blur_timer[0]:
                GLib.source_remove(blur_timer[0])
            def _apply():
                update_niri_blur(
                    enabled=blur_switch.get_active(),
                    passes=int(passes_scale.get_value()),
                    offset=offset_scale.get_value(),
                    saturation=sat_scale.get_value(),
                    noise=noise_scale.get_value()
                )
                blur_timer[0] = None
                return False
            blur_timer[0] = GLib.timeout_add(120, _apply)

        def on_blur_toggled(sw, state):
            passes_scale.set_sensitive(state)
            offset_scale.set_sensitive(state)
            sat_scale.set_sensitive(state)
            noise_scale.set_sensitive(state)
            update_niri_blur(enabled=state)
            return False

        blur_switch.connect("state-set", on_blur_toggled)
        passes_scale.connect("value-changed", lambda _: schedule_blur_update())
        offset_scale.connect("value-changed", lambda _: schedule_blur_update())
        sat_scale.connect("value-changed", lambda _: schedule_blur_update())
        noise_scale.connect("value-changed", lambda _: schedule_blur_update())

        blur_card.add_row(create_setting_row(
            "applications-graphics",
            "Blur Intensity (Shader Passes)",
            "1 = Light / Fast, 2 = Balanced (Best Battery), 3 = Deep Glass, 4 = Ultra Smooth",
            passes_scale
        ))

        blur_card.add_row(create_setting_row(
            "zoom-fit-best",
            "Blur Radius & Spread (Offset)",
            "Diffusion distance. Higher values create a softer, more dispersed background",
            offset_scale
        ))

        blur_card.add_row(create_setting_row(
            "color-management",
            "Vibrancy & Saturation",
            "Color intensity of wallpaper hues shining through frosted glass windows",
            sat_scale
        ))

        blur_card.add_row(create_setting_row(
            "emblem-default",
            "Micro-Noise & Grain",
            "Fine-textured grain to prevent banding on dark gradients and shadows",
            noise_scale
        ))

        return scroll

    # ==========================================
    # PAGE: USER & PROFILE
    # ==========================================
    def page_users(self):
        scroll, vbox = self.make_page_container("User & Profile", "Manage user profile picture, identity details, and system avatar")

        # 1. Profile Picture Hero Card
        vbox.pack_start(Gtk.Label(label="USER AVATAR & IDENTITY", xalign=0, name="section-caption"), False, False, 0)
        avatar_card = SettingsCard()
        vbox.pack_start(avatar_card, False, False, 0)

        hero_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        hero_box.set_margin_start(16)
        hero_box.set_margin_end(16)
        hero_box.set_margin_top(16)
        hero_box.set_margin_bottom(16)

        # Avatar Drawing Area (96x96 px circular) inside clickable EventBox
        avatar_event_box = Gtk.EventBox()
        avatar_event_box.set_tooltip_text("Click to adjust & crop profile picture")
        avatar_event_box.connect("enter-notify-event", lambda w, e: w.get_window().set_cursor(Gdk.Cursor.new_from_name(w.get_display(), "pointer")) if w.get_window() else None)
        avatar_event_box.connect("leave-notify-event", lambda w, e: w.get_window().set_cursor(None) if w.get_window() else None)

        avatar_draw = Gtk.DrawingArea()
        avatar_draw.set_size_request(96, 96)

        def draw_avatar(w, cr):
            pw = w.get_allocated_width()
            ph = w.get_allocated_height()
            if pw <= 0 or ph <= 0:
                return False
            cx, cy = pw / 2.0, ph / 2.0
            r = min(pw, ph) / 2.0 - 2.0

            colors = parse_theme_colors()
            accent = colors.get("accent-purple", (0.44, 0.42, 0.63, 1.0))

            cr.save()
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.clip()

            pixbuf = get_avatar_pixbuf(96)
            if pixbuf:
                bw = pixbuf.get_width()
                bh = pixbuf.get_height()
                Gdk.cairo_set_source_pixbuf(cr, pixbuf, cx - bw / 2.0, cy - bh / 2.0)
                cr.paint()
            else:
                cr.set_source_rgba(accent[0] * 0.35, accent[1] * 0.35, accent[2] * 0.35, 0.85)
                cr.paint()
                layout = w.create_pango_layout("")
                desc = Pango.FontDescription("Symbols Nerd Font 40")
                layout.set_font_description(desc)
                _, logical = layout.get_pixel_extents()
                cr.set_source_rgba(accent[0], accent[1], accent[2], 0.95)
                cr.move_to(cx - logical.width / 2.0, cy - logical.height / 2.0)
                PangoCairo.show_layout(cr, layout)

            cr.restore()

            # Outer ring
            cr.set_source_rgba(accent[0], accent[1], accent[2], 0.9)
            cr.set_line_width(2.5)
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.stroke()
            return False

        avatar_draw.connect("draw", draw_avatar)
        avatar_event_box.add(avatar_draw)
        hero_box.pack_start(avatar_event_box, False, False, 0)

        # Info Box
        info_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_vbox.set_valign(Gtk.Align.CENTER)

        user_name = os.getenv("USER", "user")
        hostname = os.uname().nodename
        u_lbl = Gtk.Label(label=f"@{user_name} • {hostname}")
        u_lbl.set_name("row-title")
        u_lbl.set_xalign(0)
        info_vbox.pack_start(u_lbl, False, False, 0)

        cur_path = get_current_avatar_path()
        disp_p = cur_path.replace(os.path.expanduser("~"), "~") if cur_path else "Default system icon"
        path_lbl = Gtk.Label(label=f"Active: {disp_p}")
        path_lbl.set_name("row-subtitle")
        path_lbl.set_xalign(0)
        info_vbox.pack_start(path_lbl, False, False, 0)

        tip_lbl = Gtk.Label(label="PNG, JPG, WEBP, or SVG • Drag, zoom & rotate to fit perfectly")
        tip_lbl.set_name("badge-label-muted")
        tip_lbl.set_xalign(0)
        info_vbox.pack_start(tip_lbl, False, False, 2)

        hero_box.pack_start(info_vbox, True, True, 0)

        # Buttons Box
        btn_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        btn_vbox.set_valign(Gtk.Align.CENTER)

        def open_crop_dialog(image_path):
            if not image_path or not os.path.exists(image_path):
                return False
            crop_dlg = AvatarCropDialog(self, image_path)
            crop_dlg.show_all()
            res = crop_dlg.run()
            saved = False
            if res == Gtk.ResponseType.ACCEPT:
                if crop_dlg.save_avatar():
                    saved = True
                    avatar_draw.queue_draw()
                    cur = get_current_avatar_path()
                    if cur:
                        path_lbl.set_text(f"Active: {cur.replace(os.path.expanduser('~'), '~')}")
                    async_cmd("pkill -SIGUSR2 -f 'dashboard.py' 2>/dev/null || true")
            crop_dlg.destroy()
            return saved

        btn_change = Gtk.Button(label="Change Picture...")

        def on_change_clicked(*_):
            selected_file = None
            dialog_shown = False
            try:
                dialog = Gtk.FileChooserDialog(
                    title="Select Profile Picture",
                    parent=self,
                    action=Gtk.FileChooserAction.OPEN
                )
                dialog.add_button("_Cancel", Gtk.ResponseType.CANCEL)
                dialog.add_button("_Select", Gtk.ResponseType.ACCEPT)
                dialog.set_default_response(Gtk.ResponseType.ACCEPT)
                dialog.set_modal(True)
                dialog.set_default_size(840, 560)

                filter_img = Gtk.FileFilter()
                filter_img.set_name("Image Files (*.png, *.jpg, *.jpeg, *.webp, *.svg)")
                filter_img.add_mime_type("image/png")
                filter_img.add_mime_type("image/jpeg")
                filter_img.add_mime_type("image/webp")
                filter_img.add_mime_type("image/svg+xml")
                filter_img.add_pattern("*.png")
                filter_img.add_pattern("*.jpg")
                filter_img.add_pattern("*.jpeg")
                filter_img.add_pattern("*.webp")
                filter_img.add_pattern("*.svg")
                filter_img.add_pattern("*.PNG")
                filter_img.add_pattern("*.JPG")
                filter_img.add_pattern("*.JPEG")
                filter_img.add_pattern("*.WEBP")
                filter_img.add_pattern("*.SVG")
                dialog.add_filter(filter_img)

                filter_all = Gtk.FileFilter()
                filter_all.set_name("All Files (*.*)")
                filter_all.add_pattern("*")
                dialog.add_filter(filter_all)

                pics_dir = os.path.expanduser("~/Pictures")
                if os.path.isdir(pics_dir):
                    dialog.set_current_folder(pics_dir)
                else:
                    dialog.set_current_folder(os.path.expanduser("~"))

                # Live preview widget
                preview = Gtk.Image()
                dialog.set_preview_widget(preview)
                def update_preview_cb(fc):
                    fn = fc.get_preview_filename()
                    try:
                        if fn and os.path.isfile(fn):
                            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(fn, 180, 180, True)
                            preview.set_from_pixbuf(pb)
                            fc.set_preview_widget_active(True)
                        else:
                            fc.set_preview_widget_active(False)
                    except Exception:
                        fc.set_preview_widget_active(False)

                dialog.connect("update-preview", update_preview_cb)

                dialog_shown = True
                resp = dialog.run()
                if resp == Gtk.ResponseType.ACCEPT:
                    selected_file = dialog.get_filename()
                dialog.destroy()
            except Exception as e:
                print(f"FileChooserDialog error: {e}", file=sys.stderr)
                selected_file = None

            # Fallback to Zenity if GTK dialog failed to open and zenity is installed
            if not selected_file and not dialog_shown and shutil.which("zenity"):
                try:
                    cmd = [
                        "zenity",
                        "--file-selection",
                        "--title=Select Profile Picture",
                        "--file-filter=Image Files (*.png, *.jpg, *.webp, *.svg) | *.png *.jpg *.jpeg *.webp *.svg *.PNG *.JPG *.JPEG *.WEBP *.SVG",
                        "--file-filter=All Files | *"
                    ]
                    pics = os.path.expanduser("~/Pictures")
                    if os.path.isdir(pics):
                        cmd.append(f"--filename={pics}/")
                    z_res = subprocess.run(cmd, capture_output=True, text=True)
                    if z_res.returncode == 0 and z_res.stdout.strip():
                        selected_file = z_res.stdout.strip()
                except Exception:
                    pass

            if selected_file and os.path.exists(selected_file):
                open_crop_dialog(selected_file)

        btn_change.connect("clicked", on_change_clicked)
        btn_vbox.pack_start(btn_change, False, False, 0)

        def on_adjust_clicked(*_):
            src_path = get_avatar_source_path()
            if src_path and os.path.exists(src_path):
                open_crop_dialog(src_path)
            else:
                on_change_clicked()

        avatar_event_box.connect("button-press-event", on_adjust_clicked)

        btn_adjust = Gtk.Button(label="Adjust & Crop...")
        btn_adjust.connect("clicked", on_adjust_clicked)
        btn_vbox.pack_start(btn_adjust, False, False, 0)

        btn_remove = Gtk.Button(label="Remove Picture")
        def on_remove_clicked(*_):
            remove_profile_picture()
            avatar_draw.queue_draw()
            cur = get_current_avatar_path()
            if cur:
                path_lbl.set_text(f"Active: {cur.replace(os.path.expanduser('~'), '~')}")
            else:
                path_lbl.set_text("Active: Default system icon")
            async_cmd("pkill -SIGUSR2 -f 'dashboard.py' 2>/dev/null || true")

        btn_remove.connect("clicked", on_remove_clicked)
        btn_vbox.pack_start(btn_remove, False, False, 0)

        hero_box.pack_end(btn_vbox, False, False, 0)
        avatar_card.pack_start(hero_box, False, False, 0)

        # 2. Account Details Card
        vbox.pack_start(Gtk.Label(label="ACCOUNT DETAILS", xalign=0, name="section-caption"), False, False, 0)
        account_card = SettingsCard()
        vbox.pack_start(account_card, False, False, 0)

        real_name = user_name.capitalize()
        try:
            import pwd
            entry = pwd.getpwnam(user_name)
            gecos = entry.pw_gecos.split(",")[0].strip()
            if gecos:
                real_name = gecos
        except Exception:
            pass

        account_card.add_row(create_setting_row("avatar-default", "User Account", f"Username: {user_name}", Gtk.Label(label=user_name)))
        account_card.add_row(create_setting_row("user-info", "Full Name", real_name, Gtk.Label(label=real_name)))
        account_card.add_row(create_setting_row("dialog-password", "Account Privileges", "Administrative (wheel group member)", Gtk.Label(label="Admin")))
        account_card.add_row(create_setting_row("folder-home", "Home Directory", os.path.expanduser("~"), Gtk.Label(label=os.path.expanduser("~"))))
        account_card.add_row(create_setting_row("utilities-terminal", "Login Shell", os.getenv("SHELL", "/bin/bash"), Gtk.Label(label=os.path.basename(os.getenv("SHELL", "bash")))))

        # 3. Synchronization & Display Card
        vbox.pack_start(Gtk.Label(label="DESKTOP & WAYBAR INTEGRATION", xalign=0, name="section-caption"), False, False, 0)
        sync_card = SettingsCard()
        vbox.pack_start(sync_card, False, False, 0)

        sync_card.add_row(create_setting_row("preferences-desktop-theme", "Caelestia Dashboard Header", "Profile avatar renders in the clock dropdown dashboard", Gtk.Label(label="Connected")))
        sync_card.add_row(create_setting_row("system-lock-screen", "Lock Screen & Display Manager", "Synchronized to ~/.face and ~/.face.icon for Swaylock and SDDM/GDM", Gtk.Label(label="Synchronized")))

        return scroll

    # ==========================================
    # PAGE 3: DOCK & BARS
    # ==========================================
    def page_dock(self):
        scroll, vbox = self.make_page_container("Dock & Top Bar", "Manage bottom macOS dock, top Waybar, and Super+Tab App Switcher HUD")

        dock_card = SettingsCard()
        vbox.pack_start(dock_card, False, False, 0)

        # Dock restart / status
        restart_btn = Gtk.Button(label="Restart Dock")
        restart_btn.connect("clicked", lambda *_: async_cmd("pkill -9 -f macos-dock.py; rm -f /tmp/macos_dock.pid; sleep 0.2; niri msg action spawn -- /usr/bin/python3 /home/sreyas/.config/niri/macos-dock.py"))
        dock_card.add_row(create_setting_row(
            "user-desktop",
            "Bottom macOS Dock",
            "Floating frosted glass dock with 120Hz smooth physics and dynamic active apps",
            restart_btn
        ))

        # Manage Pinned Apps
        manage_pin_btn = Gtk.Button(label="Manage Pinned Apps...")
        manage_pin_btn.connect("clicked", lambda *_: async_cmd("/usr/bin/python3 /home/sreyas/.config/niri/macos-dock.py --pin-dialog"))
        dock_card.add_row(create_setting_row(
            "view-pin-symbolic",
            "Pinned Applications",
            "Add, remove, and manage applications permanently pinned to the bottom dock",
            manage_pin_btn
        ))

        dock_card.add_row(create_setting_row(
            "go-bottom",
            "Intelligent Auto-Hide",
            "Glides down when windows are open; stays visible on empty desktop",
            Gtk.Label(label="Active")
        ))

        dock_card.add_row(create_setting_row(
            "view-grid",
            "Overview Integration",
            "Smoothly slides up and stays visible whenever Overview (Mod+D) is active",
            Gtk.Label(label="Enabled")
        ))

        # Top Bar & Daemons Card
        vbox.pack_start(Gtk.Label(label="DESKTOP SHELL SERVICES", xalign=0, name="section-caption"), False, False, 0)
        bar_card = SettingsCard()
        vbox.pack_start(bar_card, False, False, 0)

        waybar_btn = Gtk.Button(label="Restart Waybar")
        waybar_btn.connect("clicked", lambda *_: async_cmd("killall waybar; sleep 0.2; waybar &"))
        bar_card.add_row(create_setting_row(
            "preferences-system-windows",
            "Top Status Bar (Waybar)",
            "System clock, battery monitor, audio status, workspaces & tray",
            waybar_btn
        ))

        swaync_btn = Gtk.Button(label="Restart SwayNC")
        swaync_btn.connect("clicked", lambda *_: async_cmd("pkill swaync; sleep 0.2; swaync &"))
        bar_card.add_row(create_setting_row(
            "preferences-system-notifications",
            "Notification Center (SwayNC)",
            "Right slide-out notification drawer, media control, and quick toggles",
            swaync_btn
        ))

        # Switcher HUD
        vbox.pack_start(Gtk.Label(label="APP SWITCHER HUD", xalign=0, name="section-caption"), False, False, 0)
        hud_card = SettingsCard()
        vbox.pack_start(hud_card, False, False, 0)

        hud_card.add_row(create_setting_row(
            "preferences-system-windows",
            "Super+Tab / Alt+Tab Switcher",
            "macOS-authentic floating pill with 64px icons and instant switch on key release",
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
    # PAGE 4: MOUSE & TOUCHPAD (NEW)
    # ==========================================
    def page_mouse(self):
        scroll, vbox = self.make_page_container("Mouse & Touchpad", "Touchpad gestures, tap to click, natural scrolling, and tracking speed")

        kdl_state = get_niri_input_state()

        # Touchpad Settings Card
        vbox.pack_start(Gtk.Label(label="TOUCHPAD GESTURES & BEHAVIOR", xalign=0, name="section-caption"), False, False, 0)
        pad_card = SettingsCard()
        vbox.pack_start(pad_card, False, False, 0)

        # Tap to Click
        tap_sw = Gtk.Switch()
        tap_sw.set_active(kdl_state["tap"])
        tap_sw.connect("state-set", lambda _, state: (update_niri_input(tap=state), False)[1])
        pad_card.add_row(create_setting_row(
            "input-touchpad",
            "Tap to Click",
            "Tap surface with one finger for left click, two fingers for right click",
            tap_sw
        ))

        # Natural Scrolling (Touchpad)
        nat_sw = Gtk.Switch()
        nat_sw.set_active(kdl_state["natural_touchpad"])
        nat_sw.connect("state-set", lambda _, state: (update_niri_input(natural_touchpad=state), False)[1])
        pad_card.add_row(create_setting_row(
            "view-refresh-symbolic",
            "Natural Scrolling",
            "Content moves smoothly in the same direction as your two-finger gesture (macOS style)",
            nat_sw
        ))

        # Disable While Typing
        dwt_sw = Gtk.Switch()
        dwt_sw.set_active(kdl_state["dwt"])
        dwt_sw.connect("state-set", lambda _, state: (update_niri_input(dwt=state), False)[1])
        pad_card.add_row(create_setting_row(
            "input-keyboard",
            "Disable While Typing (DWT)",
            "Prevent accidental cursor jumping and palms tapping while using keyboard",
            dwt_sw
        ))

        # ── Sensitivity helper ─────────────────────────────────────────────
        def make_sensitivity_widget(lo, hi, step, default_val, current_val,
                                    lo_label, hi_label, fmt_fn, on_change):
            """Compact compound control: endpoint labels + slider + live chip + Reset."""
            wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            wrapper.set_size_request(260, -1)

            slider_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

            lbl_lo = Gtk.Label(label=lo_label)
            lbl_lo.set_name("row-subtitle")
            slider_row.pack_start(lbl_lo, False, False, 0)

            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
            scale.set_value(current_val)
            scale.set_draw_value(False)
            scale.set_hexpand(True)
            scale.add_mark(lo,                Gtk.PositionType.BOTTOM, None)
            scale.add_mark((lo + hi) / 2,    Gtk.PositionType.BOTTOM, None)
            scale.add_mark(hi,                Gtk.PositionType.BOTTOM, None)
            scale.add_mark(default_val,       Gtk.PositionType.BOTTOM, None)
            slider_row.pack_start(scale, True, True, 0)

            lbl_hi = Gtk.Label(label=hi_label)
            lbl_hi.set_name("row-subtitle")
            slider_row.pack_start(lbl_hi, False, False, 0)

            wrapper.pack_start(slider_row, False, False, 0)

            chip_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            chip_row.set_halign(Gtk.Align.END)

            val_lbl = Gtk.Label(label=fmt_fn(current_val))
            val_lbl.set_name("sens-value-chip")
            chip_row.pack_start(val_lbl, False, False, 0)

            btn_reset = Gtk.Button(label="Reset")
            btn_reset.set_name("sens-reset-btn")
            btn_reset.set_tooltip_text(f"Reset to default ({fmt_fn(default_val)})")
            chip_row.pack_start(btn_reset, False, False, 0)

            wrapper.pack_start(chip_row, False, False, 0)

            def _on_change(s):
                val_lbl.set_text(fmt_fn(s.get_value()))
                on_change(s.get_value())
            scale.connect("value-changed", _on_change)
            btn_reset.connect("clicked", lambda _: scale.set_value(default_val))

            return wrapper

        # Touchpad Pointer Speed
        speed_widget = make_sensitivity_widget(
            lo=-1.0, hi=1.0, step=0.05,
            default_val=0.2,
            current_val=kdl_state["accel_touchpad"],
            lo_label="Slow", hi_label="Fast",
            fmt_fn=lambda v: f"{v:+.2f}",
            on_change=lambda v: update_niri_input(accel_touchpad=round(v, 2)),
        )
        pad_card.add_row(create_setting_row(
            "input-mouse",
            "Touchpad Sensitivity",
            "Drag to adjust pointer speed • negative = slower, positive = faster",
            speed_widget
        ))

        # Scroll Sensitivity
        scroll_widget = make_sensitivity_widget(
            lo=0.4, hi=3.0, step=0.1,
            default_val=1.0,
            current_val=kdl_state["scroll_factor"],
            lo_label="Slow", hi_label="Fast",
            fmt_fn=lambda v: f"{v:.1f}\u00d7",
            on_change=lambda v: update_niri_input(scroll_factor=round(v, 1)),
        )
        pad_card.add_row(create_setting_row(
            "edit-select-all",
            "Scroll Sensitivity",
            "Distance scrolled per two-finger swipe unit (1.0\u00d7 = default)",
            scroll_widget
        ))

        # Mouse & Focus Card
        vbox.pack_start(Gtk.Label(label="WINDOW FOCUS & POINTER BEHAVIOR", xalign=0, name="section-caption"), False, False, 0)
        focus_card = SettingsCard()
        vbox.pack_start(focus_card, False, False, 0)

        ffm_sw = Gtk.Switch()
        ffm_sw.set_active(kdl_state["ffm"])
        ffm_sw.connect("state-set", lambda _, state: (update_niri_input(ffm=state), False)[1])
        focus_card.add_row(create_setting_row(
            "preferences-system-windows",
            "Focus Follows Mouse",
            "Automatically activate window focus under cursor without requiring a click",
            ffm_sw
        ))

        return scroll

    # ==========================================
    # PAGE 5: KEYBOARD & BRIGHTNESS
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
            "Screen Backlight Intensity",
            "Adjust internal laptop display brightness",
            b_scale
        ))

        # Keyboard Backlight
        kbd_on = run_cmd("brightnessctl --device='platform::kbd_backlight' get") == "1"
        kbd_switch = Gtk.Switch()
        kbd_switch.set_active(kbd_on)
        kbd_switch.connect("state-set", lambda _, state: async_cmd(f"brightnessctl --device='platform::kbd_backlight' set {'1' if state else '0'}"))

        bright_card.add_row(create_setting_row(
            "input-keyboard",
            "Keyboard Key Illumination",
            "Toggle laptop keyboard backlight keys",
            kbd_switch
        ))

        # Key Repeat & Input Card
        info_card = SettingsCard()
        vbox.pack_start(info_card, False, False, 0)

        info_card.add_row(create_setting_row(
            "preferences-desktop-keyboard",
            "Layout & Character Repeat",
            "Layout: English (US) • Repeat Delay: 600ms • Repeat Rate: 25 keys/sec",
            Gtk.Label(label="Configured in Niri")
        ))

        return scroll

    # ==========================================
    # PAGE 6: SOUND & AUDIO
    # ==========================================
    def page_sound(self):
        scroll, vbox = self.make_page_container("Sound & Audio", "Manage audio outputs, live device routing, volume levels, and microphone inputs")

        sinks, sources = get_audio_devices()

        # Output Card
        vbox.pack_start(Gtk.Label(label="OUTPUT PLAYBACK", xalign=0, name="section-caption"), False, False, 0)
        audio_card = SettingsCard()
        vbox.pack_start(audio_card, False, False, 0)

        # Current volume via wpctl
        cur_vol = 70
        is_muted = False
        try:
            out = run_cmd("wpctl get-volume @DEFAULT_AUDIO_SINK@")
            if "Volume:" in out:
                cur_vol = int(float(out.split()[1]) * 100)
            is_muted = "[MUTED]" in out
        except Exception:
            pass

        vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        vol_scale.set_value(cur_vol)
        vol_scale.set_size_request(200, -1)
        vol_scale.connect("value-changed", lambda s: async_cmd(f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {s.get_value()/100:.2f}"))

        audio_card.add_row(create_setting_row(
            "audio-volume-high",
            "Master Output Volume",
            "Adjust playback sound level across all applications",
            vol_scale
        ))

        # Output Sink Selector
        sink_combo = Gtk.ComboBoxText()
        active_sink_id = None
        for s in sinks:
            sink_combo.append(s["id"], s["name"])
            if s["default"]:
                active_sink_id = s["id"]
        if active_sink_id:
            sink_combo.set_active_id(active_sink_id)
        sink_combo.connect("changed", lambda c: async_cmd(f"wpctl set-default {c.get_active_id()}"))

        audio_card.add_row(create_setting_row(
            "audio-speakers",
            "Active Output Device",
            "Select hardware speaker, Bluetooth headset, or HDMI monitor",
            sink_combo
        ))

        # Output Mute Toggle
        out_mute_sw = Gtk.Switch()
        out_mute_sw.set_active(not is_muted)
        out_mute_sw.connect("state-set", lambda _, state: async_cmd(f"wpctl set-mute @DEFAULT_AUDIO_SINK@ {'0' if state else '1'}"))
        audio_card.add_row(create_setting_row(
            "audio-volume-muted",
            "Audio Playback Enabled",
            "Mute or un-mute master sound output",
            out_mute_sw
        ))

        # Test audio button
        test_btn = Gtk.Button(label="Play Test Chime")
        test_btn.connect("clicked", lambda *_: async_cmd("paplay /usr/share/sounds/freedesktop/stereo/audio-channel-front-center.oga 2>/dev/null || wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.7"))
        audio_card.add_row(create_setting_row(
            "audio-headphones",
            "Speaker & Channel Test",
            "Emit stereo tone to verify output routing and balance",
            test_btn
        ))

        # Microphone Input Card
        vbox.pack_start(Gtk.Label(label="INPUT MICROPHONE", xalign=0, name="section-caption"), False, False, 0)
        mic_card = SettingsCard()
        vbox.pack_start(mic_card, False, False, 0)

        cur_mic_vol = 80
        try:
            m_out = run_cmd("wpctl get-volume @DEFAULT_AUDIO_SOURCE@")
            if "Volume:" in m_out:
                cur_mic_vol = int(float(m_out.split()[1]) * 100)
        except Exception:
            pass

        mic_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        mic_scale.set_value(cur_mic_vol)
        mic_scale.set_size_request(200, -1)
        mic_scale.connect("value-changed", lambda s: async_cmd(f"wpctl set-volume @DEFAULT_AUDIO_SOURCE@ {s.get_value()/100:.2f}"))

        mic_card.add_row(create_setting_row(
            "audio-input-microphone",
            "Microphone Input Level",
            "Adjust microphone gain and recording sensitivity",
            mic_scale
        ))

        # Input Source Selector
        source_combo = Gtk.ComboBoxText()
        active_source_id = None
        for sc in sources:
            source_combo.append(sc["id"], sc["name"])
            if sc["default"]:
                active_source_id = sc["id"]
        if active_source_id:
            source_combo.set_active_id(active_source_id)
        source_combo.connect("changed", lambda c: async_cmd(f"wpctl set-default {c.get_active_id()}"))

        mic_card.add_row(create_setting_row(
            "audio-card",
            "Active Recording Device",
            "Select internal analog microphone or external USB/Bluetooth headset",
            source_combo
        ))

        return scroll

    # ==========================================
    # PAGE 7: NETWORK & BLUETOOTH
    # ==========================================
    def page_network(self):
        scroll, vbox = self.make_page_container("Wi-Fi & Bluetooth", "Control network interfaces, wireless connectivity and Bluetooth accessories")

        net_card = SettingsCard()
        vbox.pack_start(net_card, False, False, 0)

        # Wi-Fi toggle
        wifi_on = run_cmd("nmcli radio wifi") == "enabled"
        wifi_switch = Gtk.Switch()
        wifi_switch.set_active(wifi_on)
        wifi_switch.connect("state-set", lambda _, state: async_cmd(f"nmcli radio wifi {'on' if state else 'off'}"))

        net_card.add_row(create_setting_row(
            "network-wireless",
            "Wi-Fi Wireless Radio",
            "Enable or disable 802.11 Wi-Fi networking radio",
            wifi_switch
        ))

        wifi_btn = Gtk.Button(label="Network Menu...")
        wifi_btn.connect("clicked", lambda *_: async_cmd("/usr/bin/python3 ~/.config/waybar/scripts/wifi-popup.py"))

        net_card.add_row(create_setting_row(
            "network-workgroup",
            "Available Networks & Hotspots",
            "Scan nearby access points, join networks, or configure static IP",
            wifi_btn
        ))

        # Bluetooth Card
        bt_card = SettingsCard()
        vbox.pack_start(bt_card, False, False, 0)

        bt_state = run_cmd("bluetoothctl show | grep 'Powered:'")
        bt_on = "yes" in bt_state
        bt_switch = Gtk.Switch()
        bt_switch.set_active(bt_on)
        bt_switch.connect("state-set", lambda _, state: async_cmd(f"bluetoothctl power {'on' if state else 'off'}"))

        bt_card.add_row(create_setting_row(
            "bluetooth-active",
            "Bluetooth Radio",
            "Connect wireless accessories, mice, keyboards, and headphones",
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
    # PAGE 8: NOTIFICATIONS & DND (NEW)
    # ==========================================
    def page_notifications(self):
        scroll, vbox = self.make_page_container("Notifications & DND", "Manage desktop alerts, Do Not Disturb, and notification history")

        notif_card = SettingsCard()
        vbox.pack_start(notif_card, False, False, 0)

        # Do Not Disturb Toggle
        dnd_active = run_cmd("swaync-client -D") == "true"
        dnd_sw = Gtk.Switch()
        dnd_sw.set_active(dnd_active)
        dnd_sw.connect("state-set", lambda _, state: async_cmd("swaync-client -d"))

        notif_card.add_row(create_setting_row(
            "notifications-disabled",
            "Do Not Disturb (DND)",
            "Silence popups and banners during presentations and focused work",
            dnd_sw
        ))

        # Notification Center Drawer
        drawer_btn = Gtk.Button(label="Open Notification Center")
        drawer_btn.connect("clicked", lambda *_: async_cmd("swaync-client -t"))

        notif_card.add_row(create_setting_row(
            "preferences-system-notifications",
            "Notification Center Drawer",
            "Toggle right-hand sidebar showing missed alerts, calendar, and media widgets",
            drawer_btn
        ))

        # Clear All Notifications
        clear_btn = Gtk.Button(label="Clear All Alerts")
        clear_btn.connect("clicked", lambda *_: async_cmd("swaync-client -C"))

        notif_card.add_row(create_setting_row(
            "edit-clear-all",
            "Dismiss All Notifications",
            "Clear and wipe active notifications history from drawer",
            clear_btn
        ))

        return scroll

    # ==========================================
    # PAGE 9: DEFAULT APPLICATIONS (NEW)
    # ==========================================
    def page_defaults(self):
        scroll, vbox = self.make_page_container("Default Applications", "Configure preferred web browser, file manager, text editor, and terminal")

        app_card = SettingsCard()
        vbox.pack_start(app_card, False, False, 0)

        # Default Web Browser
        cur_browser = run_cmd("xdg-settings get default-web-browser")
        browser_combo = Gtk.ComboBoxText()
        browser_combo.append("app.zen_browser.zen.desktop", "Zen Browser")
        browser_combo.append("google-chrome.desktop", "Google Chrome")
        browser_combo.set_active_id(cur_browser if "zen" in cur_browser or "chrome" in cur_browser else "app.zen_browser.zen.desktop")
        browser_combo.connect("changed", lambda c: async_cmd(f"xdg-settings set default-web-browser {c.get_active_id()}"))

        app_card.add_row(create_setting_row(
            "web-browser",
            "Default Web Browser",
            "Application used to open web links, HTTP URLs, and HTML documents",
            browser_combo
        ))

        # Default File Manager
        cur_fm = run_cmd("xdg-mime query default inode/directory")
        fm_combo = Gtk.ComboBoxText()
        fm_combo.append("org.gnome.Nautilus.desktop", "GNOME Files (Nautilus)")
        fm_combo.set_active_id("org.gnome.Nautilus.desktop")
        fm_combo.connect("changed", lambda c: async_cmd(f"xdg-mime default {c.get_active_id()} inode/directory"))

        app_card.add_row(create_setting_row(
            "system-file-manager",
            "Default File Manager",
            "Application used to browse directories, folders, and storage devices",
            fm_combo
        ))

        # Default Text / Code Editor
        cur_editor = run_cmd("xdg-mime query default text/plain")
        editor_combo = Gtk.ComboBoxText()
        editor_combo.append("code.desktop", "Visual Studio Code")
        editor_combo.append("org.gnome.gedit.desktop", "GNOME Text Editor (Gedit)")
        editor_combo.set_active_id(cur_editor if "code" in cur_editor or "gedit" in cur_editor else "code.desktop")
        editor_combo.connect("changed", lambda c: async_cmd(f"xdg-mime default {c.get_active_id()} text/plain"))

        app_card.add_row(create_setting_row(
            "accessories-text-editor",
            "Default Code / Text Editor",
            "Application used to open source code, markdown, and plain text files",
            editor_combo
        ))

        # Default Terminal
        app_card.add_row(create_setting_row(
            "utilities-terminal",
            "Default Terminal Emulator",
            "GPU-accelerated Kitty terminal configured for Niri hotkeys",
            Gtk.Label(label="Kitty Terminal")
        ))

        return scroll

    # ==========================================
    # PAGE 10: POWER & PERFORMANCE
    # ==========================================
    def page_power(self):
        scroll, vbox = self.make_page_container("Power & Performance", "Hardware power profiles, battery optimization, and screen locking")

        # Hardware Power Profile Card
        vbox.pack_start(Gtk.Label(label="SYSTEM POWER PROFILE", xalign=0, name="section-caption"), False, False, 0)
        perf_card = SettingsCard()
        vbox.pack_start(perf_card, False, False, 0)

        cur_profile = get_power_profile()
        profile_combo = Gtk.ComboBoxText()
        profile_combo.append("performance", "High Performance (Unthrottled Clock Speeds)")
        profile_combo.append("balanced", "Balanced (Standard Dynamic Power / Performance)")
        profile_combo.append("power-saver", "Power Saver (Maximum Battery Conservation)")
        profile_combo.set_active_id(cur_profile if cur_profile in ["performance", "balanced", "power-saver"] else "balanced")
        profile_combo.connect("changed", lambda c: set_power_profile(c.get_active_id()))

        perf_card.add_row(create_setting_row(
            "power-profile-balanced",
            "Hardware Energy Profile",
            "Tune CPU clock states, GPU power gating, and cooling fan curves",
            profile_combo
        ))

        # Graphics & GPU Power Mode Card
        vbox.pack_start(Gtk.Label(label="GRAPHICS & HYBRID GPU MODE", xalign=0, name="section-caption"), False, False, 0)

        gpu_info = get_gpu_status_info()
        configured_mode = gpu_info["configured_mode"]
        session_mode = gpu_info["session_mode"]
        is_pending = gpu_info.get("pending", False)

        # In-Progress Banner
        if GRAPHICS_SWITCH_IN_PROGRESS:
            in_prog_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            in_prog_box.set_name("info-banner")
            in_prog_box.set_margin_bottom(6)
            spin = Gtk.Spinner()
            spin.start()
            in_prog_box.pack_start(spin, False, False, 0)
            status_text = GRAPHICS_SWITCH_STATUS or "Updating drivers in background..."
            lbl = Gtk.Label(label=f"Configuring graphics drivers: {status_text}", xalign=0)
            lbl.set_name("row-subtitle")
            in_prog_box.pack_start(lbl, True, True, 0)
            vbox.pack_start(in_prog_box, False, False, 0)

        # Pending Reboot Banner
        elif is_pending:
            target_title = configured_mode.title()
            banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            banner.set_name("warning-banner")
            banner.set_margin_bottom(6)

            b_icon = Gtk.Image.new_from_icon_name("software-update-available", Gtk.IconSize.LARGE_TOOLBAR)
            banner.pack_start(b_icon, False, False, 0)

            b_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            b_title = Gtk.Label(label=f"System Restart Required for {target_title} Mode", xalign=0)
            b_title.set_name("row-title")
            b_desc = Gtk.Label(
                label=f"Graphics mode is configured to {target_title}. This active session continues running on {session_mode.title()} graphics until you reboot.",
                xalign=0
            )
            b_desc.set_name("row-subtitle")
            b_desc.set_line_wrap(True)
            b_vbox.pack_start(b_title, False, False, 0)
            b_vbox.pack_start(b_desc, False, False, 0)
            banner.pack_start(b_vbox, True, True, 0)

            reboot_btn = Gtk.Button(label="Restart Now")
            reboot_btn.get_style_context().add_class("suggested-action")
            reboot_btn.connect("clicked", lambda *_: subprocess.Popen(["systemctl", "reboot"]))
            banner.pack_end(reboot_btn, False, False, 0)

            vbox.pack_start(banner, False, False, 0)

        gpu_card = SettingsCard()
        vbox.pack_start(gpu_card, False, False, 0)

        # Row 1: Hardware & Live State
        status_badge = Gtk.Label()
        if is_pending:
            status_badge.set_name("badge-label-warning")
            status_badge.set_text(f"{configured_mode.title()} (Restart Pending)")
            desc_text = (
                f"Configured: {configured_mode.title()} Mode (Restart Required to Apply)\n"
                f"Current Session: {session_mode.title()} Mode • iGPU: {gpu_info['igpu']} • Discrete: {gpu_info['dgpu']}"
            )
        elif configured_mode == "integrated":
            status_badge.set_name("badge-label-muted")
            status_badge.set_text("iGPU Only (NVIDIA Off)")
            desc_text = f"Active: Integrated Mode • iGPU: {gpu_info['igpu']}\nDiscrete: {gpu_info['dgpu']} ({gpu_info['dgpu_status']} • {gpu_info['dgpu_power']})"
        elif configured_mode == "hybrid":
            status_badge.set_name("badge-label-active")
            status_badge.set_text("Hybrid Active")
            desc_text = f"Active: Hybrid Mode • iGPU: {gpu_info['igpu']}\nDiscrete: {gpu_info['dgpu']} ({gpu_info['dgpu_status']} • {gpu_info['dgpu_power']})"
        else:
            status_badge.set_name("badge-label-info")
            status_badge.set_text("NVIDIA Dedicated")
            desc_text = f"Active: Dedicated Mode • iGPU: {gpu_info['igpu']}\nDiscrete: {gpu_info['dgpu']} ({gpu_info['dgpu_status']} • {gpu_info['dgpu_power']})"

        gpu_card.add_row(create_setting_row(
            "video-display",
            "Installed Graphics Processors",
            desc_text,
            status_badge
        ))

        # Row 2: Mode Selector & Action
        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        mode_box.set_valign(Gtk.Align.CENTER)

        mode_combo = Gtk.ComboBoxText()
        mode_combo.append("hybrid", "Hybrid (On-Demand NVIDIA PRIME)")
        mode_combo.append("integrated", "Integrated (iGPU Only • Maximum Battery)")
        mode_combo.set_active_id(configured_mode if configured_mode in ["hybrid", "integrated"] else "hybrid")

        apply_btn = Gtk.Button(label="Apply Mode...")
        apply_btn.set_sensitive(False)
        apply_btn.get_style_context().add_class("suggested-action")

        if GRAPHICS_SWITCH_IN_PROGRESS:
            mode_combo.set_sensitive(False)
            apply_btn.set_sensitive(False)

        mode_box.pack_start(mode_combo, False, False, 0)
        mode_box.pack_start(apply_btn, False, False, 0)

        def on_gpu_mode_changed(combo):
            selected = combo.get_active_id()
            active = get_configured_graphics_mode()
            apply_btn.set_sensitive(selected != active and not GRAPHICS_SWITCH_IN_PROGRESS)

        mode_combo.connect("changed", on_gpu_mode_changed)

        def on_apply_gpu_clicked(_):
            selected = mode_combo.get_active_id()
            if selected and selected != get_configured_graphics_mode():
                self.show_graphics_switch_dialog(selected, on_complete=lambda *_: self.reload_all_state())

        apply_btn.connect("clicked", on_apply_gpu_clicked)

        gpu_card.add_row(create_setting_row(
            "applications-games",
            "Switch Operating Graphics Mode",
            "Switch between Hybrid (PRIME on-demand) or Integrated (NVIDIA disabled to maximize battery life)",
            mode_box
        ))

        # Battery Health Card
        vbox.pack_start(Gtk.Label(label="BATTERY STATE", xalign=0, name="section-caption"), False, False, 0)
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
            f"Battery Charge: {perc}",
            f"Status: {state} • Health Conservation Active",
            Gtk.Label(label=perc)
        ))

        # Auto-lock toggle
        lock_card = SettingsCard()
        vbox.pack_start(lock_card, False, False, 0)

        autolock_cfg = get_autolock_config()
        auto_lock_switch = Gtk.Switch()
        auto_lock_switch.set_active(autolock_cfg.get("enabled", True))
        def on_autolock_toggled(sw, state):
            set_autolock_config(state)
            target = "on" if state else "off"
            async_cmd(f"bash ~/.config/niri/toggle-autolock.sh {target}")
            return False

        auto_lock_switch.connect("state-set", on_autolock_toggled)

        lock_card.add_row(create_setting_row(
            "system-lock-screen",
            "Automatic Screen Lock (Swaylock)",
            "Automatically lock session with blurred screenshot after 5 minutes of inactivity",
            auto_lock_switch
        ))

        # Howdy Face Recognition Quick Toggle
        power_face_switch = Gtk.Switch()
        power_face_switch.set_active(get_howdy_status())
        power_face_updating = False
        def on_power_face_toggled(sw, st):
            nonlocal power_face_updating
            if power_face_updating:
                return False
            power_face_updating = True
            sw.set_sensitive(False)
            def on_done(ok, final):
                nonlocal power_face_updating
                sw.set_active(final)
                sw.set_state(final)
                sw.set_sensitive(True)
                power_face_updating = False
            set_howdy_status(st, on_done)
            return True
        power_face_switch.connect("state-set", on_power_face_toggled)
        lock_card.add_row(create_setting_row(
            "dialog-password",
            "Howdy Face Recognition Unlock",
            "Unlock Swaylock and authenticate sudo with your face using the IR camera",
            power_face_switch
        ))

        # Power Action Buttons
        vbox.pack_start(Gtk.Label(label="SYSTEM ACTIONS", xalign=0, name="section-caption"), False, False, 0)
        action_card = SettingsCard()
        vbox.pack_start(action_card, False, False, 0)

        lock_btn = Gtk.Button(label="Lock Screen Now")
        lock_btn.connect("clicked", lambda *_: async_cmd("/home/sreyas/.config/niri/lock-screen.sh"))
        action_card.add_row(create_setting_row("system-lock-screen", "Lock Session", "Immediately lock session and turn off screen illumination", lock_btn))

        suspend_btn = Gtk.Button(label="Suspend PC")
        suspend_btn.connect("clicked", lambda *_: async_cmd("systemctl suspend"))
        action_card.add_row(create_setting_row("system-suspend", "Sleep / Suspend", "Enter low power sleep mode", suspend_btn))

        power_btn = Gtk.Button(label="Power Menu...")
        power_btn.connect("clicked", lambda *_: async_cmd("wlogout"))
        action_card.add_row(create_setting_row("system-shutdown", "Shut Down / Reboot", "Open interactive macOS-styled power menu", power_btn))

        return scroll

    # ==========================================
    # PAGE: SECURITY & FACE UNLOCK
    # ==========================================
    def page_security(self):
        scroll, vbox = self.make_page_container("Security & Face Unlock", "Facial recognition authentication via Howdy for sudo commands, lock screen, and login")

        # 1. Master Face Unlock Card
        vbox.pack_start(Gtk.Label(label="BIOMETRIC AUTHENTICATION", xalign=0, name="section-caption"), False, False, 0)
        face_card = SettingsCard()
        vbox.pack_start(face_card, False, False, 0)

        is_howdy_on = get_howdy_status()
        face_switch = Gtk.Switch()
        face_switch.set_active(is_howdy_on)

        status_lbl = Gtk.Label(label="Active in PAM" if is_howdy_on else "Disabled (Password Only)")
        status_lbl.set_name("badge-label-active" if is_howdy_on else "badge-label-muted")

        is_toggling_howdy = False
        def on_howdy_toggled(switch, state):
            nonlocal is_toggling_howdy
            if is_toggling_howdy:
                return False
            is_toggling_howdy = True
            switch.set_sensitive(False)
            status_lbl.set_text("Updating...")
            def on_done(success, final_state):
                nonlocal is_toggling_howdy
                switch.set_active(final_state)
                switch.set_state(final_state)
                switch.set_sensitive(True)
                is_toggling_howdy = False
                if final_state:
                    status_lbl.set_text("Active in PAM")
                    status_lbl.set_name("badge-label-active")
                else:
                    status_lbl.set_text("Disabled (Password Only)")
                    status_lbl.set_name("badge-label-muted")
            set_howdy_status(state, on_done)
            return True

        face_switch.connect("state-set", on_howdy_toggled)

        face_card.add_row(create_setting_row(
            "dialog-password",
            "Howdy Face Unlock",
            "Authenticate with your face for sudo commands, Swaylock lock screen, and system login",
            face_switch
        ))

        face_card.add_row(create_setting_row(
            "security-high",
            "PAM Authentication Status",
            "When enabled, pam_howdy.so triggers your infrared sensor before requesting a password",
            status_lbl
        ))

        # 2. Target Services
        vbox.pack_start(Gtk.Label(label="PROTECTED PAM SERVICES", xalign=0, name="section-caption"), False, False, 0)
        pam_card = SettingsCard()
        vbox.pack_start(pam_card, False, False, 0)

        pam_services = get_howdy_pam_services()
        pam_card.add_row(create_setting_row(
            "preferences-system",
            "Terminal & Sudo Elevation",
            "Running 'sudo' commands in terminal and elevation prompts uses facial recognition",
            Gtk.Label(label="Active (/etc/pam.d/sudo)" if pam_services.get("sudo") else "Not Configured")
        ))

        pam_card.add_row(create_setting_row(
            "system-lock-screen",
            "Lock Screen (Swaylock)",
            "Screen locks after idle or Super+Escape; looking at camera unlocks screen automatically",
            Gtk.Label(label="Active (/etc/pam.d/swaylock)" if pam_services.get("swaylock") else "Not Configured")
        ))

        pam_card.add_row(create_setting_row(
            "avatar-default",
            "Login Manager (GDM)",
            "Log in to Niri desktop session at system boot with face identification",
            Gtk.Label(label="Active (/etc/pam.d/gdm-password)" if pam_services.get("gdm-password") else "Not Configured")
        ))

        # 3. Biometric Profiles & Diagnostics
        vbox.pack_start(Gtk.Label(label="ENROLLED BIOMETRIC PROFILES", xalign=0, name="section-caption"), False, False, 0)
        profile_card = SettingsCard()
        vbox.pack_start(profile_card, False, False, 0)

        model_info = get_howdy_models_info()
        profile_desc = f"Model: {model_info['file']} • Updated {model_info['modified']} ({model_info['size_kb']} KB)" if model_info["enrolled"] else "No enrolled face models found"
        profile_card.add_row(create_setting_row(
            "user-available",
            f"User Profile: {model_info['user']}",
            profile_desc,
            Gtk.Label(label="Enrolled & Ready" if model_info["enrolled"] else "Not Enrolled")
        ))

        profile_card.add_row(create_setting_row(
            "camera-web",
            "IR Sensor Hardware",
            "Infrared camera /dev/video0 • Certainty: 3.5 • Timeout: 4s • Clamshell protection active",
            Gtk.Label(label="/dev/video0")
        ))

        # 4. Actions & Testing Card
        vbox.pack_start(Gtk.Label(label="FACE RECOGNITION ACTIONS", xalign=0, name="section-caption"), False, False, 0)
        action_card = SettingsCard()
        vbox.pack_start(action_card, False, False, 0)

        test_btn = Gtk.Button(label="Test Camera Feed")
        test_btn.connect("clicked", lambda *_: async_cmd("kitty --title 'Howdy Camera Test' bash -c 'echo Testing Howdy camera feed...; sudo howdy test; read -p \"Press Enter to exit...\"'"))
        action_card.add_row(create_setting_row(
            "camera-web",
            "Live Camera & Landmark Test",
            "Open real-time OpenCV window to verify camera feed and facial feature detection",
            test_btn
        ))

        add_btn = Gtk.Button(label="Add Face Model...")
        add_btn.connect("clicked", lambda *_: async_cmd("kitty --title 'Howdy Add Model' bash -c 'sudo howdy add; read -p \"Press Enter to exit...\"'"))
        action_card.add_row(create_setting_row(
            "face-smile",
            "Train Additional Face Angle",
            "Add another facial model (e.g. different lighting, glasses on/off) to increase accuracy",
            add_btn
        ))

        list_btn = Gtk.Button(label="List Models...")
        list_btn.connect("clicked", lambda *_: async_cmd("kitty --title 'Howdy Face Models' bash -c 'sudo howdy list; echo \"\"; read -p \"Press Enter to exit...\"'"))
        action_card.add_row(create_setting_row(
            "preferences-desktop-remote-desktop",
            "Manage Enrolled Models",
            "List or delete enrolled facial recognition models",
            list_btn
        ))

        return scroll

    # ==========================================
    # PAGE: STORAGE & MAINTENANCE
    # ==========================================
    def page_storage(self):
        scroll, vbox = self.make_page_container("Storage & Maintenance", "Local disk utilization, system storage overview, and temporary cache cleaning")

        disk_card = SettingsCard()
        vbox.pack_start(disk_card, False, False, 0)

        try:
            total, used, free = shutil.disk_usage("/home/sreyas")
            t_gb = round(total / (1024**3), 1)
            u_gb = round(used / (1024**3), 1)
            f_gb = round(free / (1024**3), 1)
            perc = round((used / total) * 100, 1)
        except Exception:
            t_gb, u_gb, f_gb, perc = 500, 400, 100, 80

        # Progress bar
        pbar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        pbar_box.set_margin_start(16)
        pbar_box.set_margin_end(16)
        pbar_box.set_margin_top(14)
        pbar_box.set_margin_bottom(14)

        p_lbl = Gtk.Label(label=f"NVMe SSD Storage (Home Directory): {u_gb} GB of {t_gb} GB used ({f_gb} GB free)")
        p_lbl.set_name("row-title")
        p_lbl.set_xalign(0)
        pbar_box.pack_start(p_lbl, False, False, 0)

        pbar = Gtk.ProgressBar()
        pbar.set_fraction(perc / 100.0)
        pbar.set_text(f"{perc}% Used")
        pbar.set_show_text(True)
        pbar_box.pack_start(pbar, False, False, 0)

        disk_card.pack_start(pbar_box, False, False, 0)

        # Maintenance Card
        vbox.pack_start(Gtk.Label(label="STORAGE CLEANUP & OPTIMIZATION", xalign=0, name="section-caption"), False, False, 0)
        maint_card = SettingsCard()
        vbox.pack_start(maint_card, False, False, 0)

        clean_cache_btn = Gtk.Button(label="Clean Thumbnail Cache")
        clean_cache_btn.connect("clicked", lambda *_: async_cmd("rm -rf ~/.cache/thumbnails/* && notify-send 'Storage' 'Thumbnail cache wiped!'"))
        maint_card.add_row(create_setting_row(
            "edit-clear",
            "Clear Thumbnail Cache",
            "Remove generated image previews and thumbnail cache in ~/.cache/thumbnails",
            clean_cache_btn
        ))

        flatpak_clean_btn = Gtk.Button(label="Clean Unused Flatpaks")
        flatpak_clean_btn.connect("clicked", lambda *_: async_cmd("flatpak uninstall --unused -y && notify-send 'Storage' 'Unused Flatpak runtimes cleaned!'"))
        maint_card.add_row(create_setting_row(
            "package-x-generic",
            "Remove Unused Flatpak Runtimes",
            "Uninstall orphan GNOME/KDE Flatpak runtime libraries no longer required",
            flatpak_clean_btn
        ))

        return scroll

    # ==========================================
    # PAGE 12: SHORTCUTS REFERENCE
    # ==========================================
    def page_shortcuts(self):
        scroll, vbox = self.make_page_container("Shortcuts Reference", "Interactive cheatsheet for all Niri window management and desktop shortcuts")

        search_entry = Gtk.SearchEntry()
        search_entry.set_placeholder_text("Search keybindings by action or key name...")
        search_entry.set_size_request(-1, 38)
        vbox.pack_start(search_entry, False, False, 0)

        shortcuts_card = SettingsCard()
        vbox.pack_start(shortcuts_card, False, False, 0)

        shortcuts = [
            ("Mod + Return", "Spawn Kitty GPU Terminal"),
            ("Mod + D", "Open Application Launcher (Fuzzel)"),
            ("Mod + Comma", "Open Niri Settings Control Center"),
            ("Mod + Tab / Alt + Tab", "Switch Windows (macOS Style Switcher HUD)"),
            ("Mod + Shift + T", "Switch Desktop Themes (Waybar, Kitty, Fuzzel)"),
            ("Mod + Shift + W", "Interactive Wallpaper Picker"),
            ("Mod + Shift + D", "Toggle Bottom macOS Dock Auto-Hide"),
            ("Mod + Shift + Slash", "Niri Keybindings Hotkey Cheat Sheet"),
            ("Mod + L", "Lock Screen (Swaylock Blurred Image)"),
            ("Mod + Shift + L", "Toggle Automatic Screen Lock (Swayidle)"),
            ("Mod + Escape", "Open Power / Logout Menu (Wlogout)"),
            ("Mod + Q", "Close Focused Window"),
            ("Mod + Left / Right", "Navigate Columns Left / Right"),
            ("Mod + Up / Down", "Navigate Windows in Column Up / Down"),
            ("Mod + Shift + Left / Right", "Move Window Column Left / Right"),
            ("Mod + F", "Maximize Column Width"),
            ("Mod + Shift + F", "Fullscreen Active Window"),
            ("Mod + Space", "Toggle Window Floating Mode"),
            ("Mod + 1 .. 9", "Switch to Workspace 1 to 9"),
            ("Mod + Shift + 1 .. 9", "Move Window to Workspace 1 to 9"),
            ("Print", "Capture Region Screenshot"),
            ("Shift + Print", "Capture Full Screen to Clipboard"),
            ("Ctrl + Print", "Record Screen Video (GPU NVENC)"),
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
    # PAGE 13: ABOUT SYSTEM
    # ==========================================
    def page_about(self):
        scroll, vbox = self.make_page_container("About System", "Hardware, kernel and compositor environment details")

        about_card = SettingsCard()
        vbox.pack_start(about_card, False, False, 0)

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
        for pid in list(self.pages_built.keys()):
            w = self.pages_built.pop(pid)
            self.stack.remove(w)
        cur = self.sidebar_list.get_selected_row()
        if cur and hasattr(cur, "page_id"):
            self.load_page(cur.page_id)
            self.stack.set_visible_child_name(cur.page_id)

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

        #nav-row:selected {{
            background-color: alpha(@accent-color, 0.22);
        }}

        #nav-row:selected #nav-label {{
            font-weight: 700;
            color: @accent-color;
        }}

        #nav-label {{
            font-size: 13px;
            font-weight: 500;
        }}

        #sidebar-divider {{
            background-color: alpha(@border-color, 0.25);
            min-width: 1px;
        }}

        /* Content Area */
        #page-title {{
            font-size: 22px;
            font-weight: 800;
            color: @fg-color;
            margin-bottom: 2px;
        }}

        #page-description {{
            font-size: 13px;
            color: rgba(255, 255, 255, 0.60);
            margin-bottom: 8px;
        }}

        #section-caption {{
            font-size: 11px;
            font-weight: 700;
            color: alpha(@accent-color, 0.85);
            letter-spacing: 0.8px;
            margin-top: 6px;
            margin-bottom: -4px;
        }}

        /* Settings Card (iOS / macOS Style) */
        #settings-card {{
            background-color: alpha(@bg-color, 0.70);
            border: 1px solid alpha(@border-color, 0.35);
            border-radius: 14px;
            padding: 2px 0px;
        }}

        #settings-row {{
            padding: 10px 16px;
            min-height: 48px;
        }}

        #card-separator {{
            background-color: alpha(@border-color, 0.18);
            min-height: 1px;
            margin-left: 54px;
            margin-right: 16px;
        }}

        #icon-badge {{
            background-color: alpha(@accent-color, 0.14);
            border-radius: 9px;
            padding: 8px;
            min-width: 32px;
            min-height: 32px;
        }}

        #row-title {{
            font-size: 13.5px;
            font-weight: 600;
            color: @fg-color;
        }}

        #row-subtitle {{
            font-size: 12px;
            color: rgba(255, 255, 255, 0.55);
        }}

        #key-badge {{
            background-color: alpha(@accent-color, 0.18);
            border: 1px solid alpha(@accent-color, 0.40);
            border-radius: 6px;
            padding: 4px 8px;
            font-family: "JetBrains Mono", monospace;
            font-size: 11px;
            font-weight: 700;
            color: @accent-color;
        }}

        #badge-label-active {{
            background-color: rgba(46, 204, 113, 0.20);
            border: 1px solid rgba(46, 204, 113, 0.45);
            border-radius: 6px;
            padding: 3px 8px;
            font-size: 11px;
            font-weight: 700;
            color: #2ecc71;
        }}

        #badge-label-muted {{
            background-color: rgba(231, 76, 60, 0.20);
            border: 1px solid rgba(231, 76, 60, 0.40);
            border-radius: 6px;
            padding: 3px 8px;
            font-size: 11px;
            font-weight: 700;
            color: #e74c3c;
        }}

        #badge-label-info {{
            background-color: rgba(52, 152, 219, 0.20);
            border: 1px solid rgba(52, 152, 219, 0.45);
            border-radius: 6px;
            padding: 3px 8px;
            font-size: 11px;
            font-weight: 700;
            color: #3498db;
        }}

        #badge-label-warning {{
            background-color: rgba(243, 156, 18, 0.20);
            border: 1px solid rgba(243, 156, 18, 0.45);
            border-radius: 6px;
            padding: 3px 8px;
            font-size: 11px;
            font-weight: 700;
            color: #f39c12;
        }}

        #warning-banner {{
            background-color: rgba(243, 156, 18, 0.12);
            border: 1px solid rgba(243, 156, 18, 0.35);
            border-radius: 12px;
            padding: 12px 16px;
        }}

        #info-banner {{
            background-color: rgba(52, 152, 219, 0.12);
            border: 1px solid rgba(52, 152, 219, 0.35);
            border-radius: 12px;
            padding: 12px 16px;
        }}

        #wall-preview-img {{
            border-radius: 10px;
            border: 1px solid alpha(@border-color, 0.4);
        }}

        #gallery-btn {{
            border-radius: 8px;
            padding: 0;
            margin: 4px;
            border: 2px solid transparent;
            background: transparent;
        }}

        #gallery-btn:hover {{
            border-color: @accent-color;
        }}

        /* Switches & Controls */
        switch:checked {{
            background-color: @accent-color;
        }}

        scale highlight {{
            background-color: @accent-color;
            border-radius: 4px;
        }}

        scale slider {{
            background-color: @fg-color;
            border-radius: 50%;
            min-width: 16px;
            min-height: 16px;
        }}

        button {{
            border-radius: 8px;
            padding: 6px 14px;
            background-color: alpha(@accent-color, 0.14);
            border: 1px solid alpha(@accent-color, 0.35);
            font-size: 12.5px;
            font-weight: 600;
            transition: all 0.12s ease;
        }}

        button:hover {{
            background-color: alpha(@accent-color, 0.28);
            border-color: @accent-color;
        }}

        button.suggested-action {{
            background-color: @accent-color;
            color: @bg-color;
            border-color: @accent-color;
        }}

        button.suggested-action:hover {{
            background-color: alpha(@accent-color, 0.85);
            border-color: @accent-color;
        }}

        button.destructive-action {{
            background-color: rgba(231, 76, 60, 0.85);
            color: #ffffff;
            border-color: #e74c3c;
        }}

        button.destructive-action:hover {{
            background-color: rgba(231, 76, 60, 1.0);
            border-color: #e74c3c;
        }}

        #display-pill-btn {{
            border-radius: 18px;
            padding: 5px 12px;
            font-size: 12px;
        }}

        combobox button.combo {{
            padding: 4px 10px;
            border-radius: 8px;
        }}

        progressbar trough {{
            border-radius: 8px;
            background-color: alpha(@border-color, 0.3);
            min-height: 14px;
        }}

        progressbar progress {{
            border-radius: 8px;
            background-color: @accent-color;
            min-height: 14px;
        }}

        /* Crop & Adjust Dialog */
        window#crop-dialog {{
            background-color: alpha(@bg-color, 0.98);
        }}

        #crop-canvas-box {{
            background-color: #0b0b0e;
            border-radius: 12px;
            padding: 2px;
            border: 1px solid alpha(@border-color, 0.35);
        }}

        #crop-btn-save {{
            background-color: @accent-color;
            color: #ffffff;
            font-weight: 700;
            border-radius: 8px;
            padding: 8px 18px;
            border: 1px solid alpha(@accent-color, 0.8);
        }}

        #crop-btn-save:hover {{
            background-color: alpha(@accent-color, 0.85);
        }}

        /* Sensitivity slider chip & reset */
        #sens-value-chip {{
            font-family: "JetBrains Mono", monospace;
            font-size: 11.5px;
            font-weight: 700;
            color: @accent-color;
            background-color: alpha(@accent-color, 0.12);
            border: 1px solid alpha(@accent-color, 0.30);
            border-radius: 6px;
            padding: 2px 8px;
            min-width: 52px;
        }}

        #sens-reset-btn {{
            font-size: 11px;
            font-weight: 600;
            padding: 2px 10px;
            border-radius: 6px;
            background-color: alpha(@fg-color, 0.07);
            border: 1px solid alpha(@border-color, 0.30);
            color: rgba(255,255,255,0.60);
        }}

        #sens-reset-btn:hover {{
            background-color: alpha(@accent-color, 0.18);
            border-color: @accent-color;
            color: @accent-color;
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
    app = NiriSettingsApp()
    app.connect("destroy", Gtk.main_quit)
    if "--page" in sys.argv:
        try:
            pid = sys.argv[sys.argv.index("--page") + 1]
            app.switch_to_page(pid)
        except Exception:
            pass
    app.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
