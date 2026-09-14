#!/bin/bash
# Switch Waybar layout between 'default' and 'macos'

LAYOUTS_DIR="$HOME/.config/waybar/layouts"
STATE_FILE="$HOME/.config/waybar/layout.json"
DOTFILE_STATE="$HOME/dotfile/waybar/layout.json"

TARGET_LAYOUT="${1:-default}"

if [ ! -d "$LAYOUTS_DIR/$TARGET_LAYOUT" ]; then
    echo "Unknown layout: $TARGET_LAYOUT"
    echo "Available: default, macos"
    exit 1
fi

# Copy layout configuration and stylesheet
cp -f "$LAYOUTS_DIR/$TARGET_LAYOUT/config.jsonc" "$HOME/.config/waybar/config.jsonc"
cp -f "$LAYOUTS_DIR/$TARGET_LAYOUT/style.css" "$HOME/.config/waybar/style.css"

# Save state
echo "{\"layout\": \"$TARGET_LAYOUT\"}" > "$STATE_FILE"

# Sync to dotfile if present
if [ -d "$HOME/dotfile/waybar" ]; then
    cp -f "$LAYOUTS_DIR/$TARGET_LAYOUT/config.jsonc" "$HOME/dotfile/waybar/config.jsonc"
    cp -f "$LAYOUTS_DIR/$TARGET_LAYOUT/style.css" "$HOME/dotfile/waybar/style.css"
    echo "{\"layout\": \"$TARGET_LAYOUT\"}" > "$DOTFILE_STATE" 2>/dev/null || true
fi

# Cleanly restart Waybar via Niri
killall waybar 2>/dev/null
sleep 0.25
niri msg action spawn -- waybar 2>/dev/null

if [ "$TARGET_LAYOUT" = "macos" ]; then
    notify-send -a "Waybar" -i preferences-desktop-theme "Waybar Layout" "Switched to macOS Menu Bar layout" 2>/dev/null
else
    notify-send -a "Waybar" -i preferences-desktop-theme "Waybar Layout" "Switched to Default Modern Bar layout" 2>/dev/null
fi
