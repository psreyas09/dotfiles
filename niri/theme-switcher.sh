#!/bin/bash

THEMES_DIR="$HOME/.config/themes"

# 1. Select theme via fuzzel
CHOSEN_THEME=$(ls "$THEMES_DIR" | fuzzel --dmenu -p "Select Theme: ")

if [ -z "$CHOSEN_THEME" ]; then
    exit 0
fi

# Use readlink to resolve the absolute canonical path cleanly
TARGET_DIR=$(readlink -f "$THEMES_DIR/$CHOSEN_THEME")

# --- 2. Apply Theme Configurations Safely ---

# Force clean, absolute path symlinks
ln -sf "$TARGET_DIR/kitty.conf" "$HOME/.config/kitty/current-theme.conf"
ln -sf "$TARGET_DIR/waybar.css" "$HOME/.config/waybar/current-theme.css"
ln -sf "$TARGET_DIR/niri.kdl" "$HOME/.config/niri/current-theme.kdl"
ln -sf "$TARGET_DIR/fuzzel.ini" "$HOME/.config/fuzzel/fuzzel.ini"

# Starship (Reconstruct main config + target palette profile)
if [ -f "$HOME/.config/starship_base.toml" ]; then
    cat "$HOME/.config/starship_base.toml" "$TARGET_DIR/starship.toml" > "$HOME/.config/starship.toml"
fi

# --- 3. Live Hot-Reload Running Software ---

# Reload Kitty configurations live
pkill -USR1 kitty 2>/dev/null

# Cleanly restart Waybar dashboard via Niri IPC
killall waybar 2>/dev/null
niri msg action spawn -- waybar 2>/dev/null

# Force Niri to refresh window borders instantly
niri msg action load-config-file 2>/dev/null

# Hot-reload SwayNotificationCenter theme
swaync-client -R && swaync-client -rs 2>/dev/null

# Send desktop notification toast feedback
notify-send "Desktop Theme" "Applied '$CHOSEN_THEME' theme profile!" -u low -i preferences-desktop-theme 2>/dev/null

echo "Theme changed successfully to $CHOSEN_THEME!"
