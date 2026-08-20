#!/bin/bash

# Define paths
LIVE_DIR="$HOME/wall/live"
STATIC_DIR="$HOME/wall"

# Helper function to generate wallust palette & hot-reload apps
apply_wallust_palette() {
    local img="$1"
    if command -v wallust &>/dev/null || [ -x "$HOME/.cargo/bin/wallust" ]; then
        WALLUST_CMD=$(command -v wallust || echo "$HOME/.cargo/bin/wallust")
        "$WALLUST_CMD" run "$img" >/dev/null 2>&1
        pkill -USR1 kitty 2>/dev/null
        killall waybar 2>/dev/null; niri msg action spawn -- waybar 2>/dev/null
        swaync-client -R && swaync-client -rs 2>/dev/null
        notify-send "Wallust Palette" "Generated dynamic color palette from wallpaper!" -u low -i preferences-desktop-theme 2>/dev/null
    fi
}

# 1. Ask user for wallpaper type
TYPE=$(echo -e "Static (fuzzel)\nStatic (sxiv)\nLive (fuzzel)" | fuzzel --dmenu -p "Wallpaper Type: ")

if [ "$TYPE" == "Static (fuzzel)" ]; then
    # STATIC WALLPAPER VIA FUZZEL LOGIC
    SELECTED=$(ls "$STATIC_DIR" | grep -E '\.(jpg|jpeg|png|webp)$' | fuzzel --dmenu -p "Select Wall: ")
    if [ -n "$SELECTED" ]; then
        pkill mpvpaper
        pkill swaybg
        FULL_PATH="$STATIC_DIR/$SELECTED"
        swaybg -i "$FULL_PATH" -m fill > /dev/null 2>&1 &
        disown
        apply_wallust_palette "$FULL_PATH"
    fi

elif [ "$TYPE" == "Live (fuzzel)" ]; then
    # LIVE WALLPAPER LOGIC
    SELECTED=$(ls "$LIVE_DIR" | fuzzel --dmenu -p "Select Live Wall: ")
    if [ -n "$SELECTED" ]; then
        pkill mpvpaper
        pkill swaybg
        
        # Push black bars off-screen
        mpvpaper -o "no-audio --loop-playlist --hwdec=nvdec --vf=scale=1920:1080 --video-zoom=0.15 --video-pan-y=0" "eDP-1" "$LIVE_DIR/$SELECTED" > /dev/null 2>&1 &
        disown
    fi

elif [ "$TYPE" == "Static (sxiv)" ]; then
    # STATIC WALLPAPER LOGIC
    SELECTED=$(sxiv -t -o "$STATIC_DIR" | head -n 1)
    if [ -n "$SELECTED" ]; then
        pkill mpvpaper
        pkill swaybg
        swaybg -i "$SELECTED" -m fill > /dev/null 2>&1 &
        disown
        apply_wallust_palette "$SELECTED"
    fi
fi
