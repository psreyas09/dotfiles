#!/usr/bin/env bash
# ==============================================================================
# macOS Sonoma Native Lock Screen Launcher for Niri
# Launches macos-lockscreen.py (native GtkSessionLock with dots, circular avatar,
# interactive media controls, and mouse support)
# ==============================================================================

set -euo pipefail

# Check if an actual (non-zombie) locker process is already running
is_locker_active() {
    for pid in $(pgrep -f "macos-lockscreen.py" 2>/dev/null); do
        state=$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null || true)
        if [ "$state" != "Z" ] && [ -n "$state" ]; then
            return 0
        fi
    done
    for pid in $(pgrep -x "gtklock|swaylock" 2>/dev/null); do
        state=$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null || true)
        if [ "$state" != "Z" ] && [ -n "$state" ]; then
            return 0
        fi
    done
    return 1
}

if is_locker_active; then
    exit 0
fi

# Ensure blurred wallpaper is available for background
BLURRED_WALL="$HOME/.cache/current_wallpaper_blurred.png"
if [ ! -s "$BLURRED_WALL" ]; then
    CURRENT_WALL=$(cat "$HOME/.cache/current_wallpaper" 2>/dev/null || echo "$HOME/wall/0anime4.jpg")
    if [ -f "$CURRENT_WALL" ]; then
        magick "$CURRENT_WALL" -filter Gaussian -resize 25% -define filter:sigma=2.5 -resize 400% "$BLURRED_WALL" 2>/dev/null || cp "$CURRENT_WALL" "$BLURRED_WALL"
    fi
fi

MACOS_LOCKER="/home/sreyas/.config/niri/macos-lockscreen.py"

# 1. Primary: Native macOS Sonoma Lockscreen (PyGObject + GtkSessionLock)
if [ -f "$MACOS_LOCKER" ]; then
    exec /usr/bin/python3 "$MACOS_LOCKER" "$@"
fi

# 2. Fallback: gtklock
if command -v gtklock >/dev/null 2>&1; then
    exec gtklock -c "$HOME/.config/gtklock/config.ini"
fi

# 3. Fallback: swaylock
exec swaylock -C "$HOME/.config/swaylock/config"
