#!/bin/bash

# Define paths
LIVE_DIR="$HOME/wall/live"
STATIC_DIR="$HOME/wall"

# Helper function to generate wallust palette & hot-reload apps
apply_wallust_palette() {
    local img="$1"
    if command -v wallust &>/dev/null || [ -x "$HOME/.cargo/bin/wallust" ]; then
        WALLUST_CMD=$(command -v wallust || echo "$HOME/.cargo/bin/wallust")
        "$WALLUST_CMD" run -b fastresize -k "$img" >/dev/null 2>&1
        pkill -USR1 kitty 2>/dev/null
        killall waybar 2>/dev/null; niri msg action spawn -- waybar 2>/dev/null
        swaync-client -R && swaync-client -rs 2>/dev/null
        notify-send "Wallust Palette" "Generated dynamic high-contrast color palette from wallpaper!" -u low -i preferences-desktop-theme 2>/dev/null
    fi
}

# Helper function to apply wallpaper + blurred overview backdrop
apply_wallpaper() {
    local img="$1"
    pkill mpvpaper
    pkill swaybg
    pkill swaybg-backdrop

    # 1. Generate high-quality blurred backdrop for Overview
    mkdir -p "$HOME/.cache"
    magick "$img" -resize 1920x1080^ -gravity center -extent 1920x1080 -blur 0x25 "$HOME/.cache/current_wallpaper_blurred.png" 2>/dev/null || \
    ffmpeg -y -i "$img" -vf "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=25" "$HOME/.cache/current_wallpaper_blurred.png" 2>/dev/null

    # 2. Launch blurred backdrop for Overview
    swaybg-backdrop -i "$HOME/.cache/current_wallpaper_blurred.png" -m fill > /dev/null 2>&1 &
    disown

    # 3. Launch normal wallpaper for workspaces
    swaybg -i "$img" -m fill > /dev/null 2>&1 &
    disown

    # 4. Generate dynamic color palette
    apply_wallust_palette "$img"
}

# 1. Ask user for wallpaper type
TYPE=$(echo -e "Static (fuzzel)\nStatic (sxiv)\nLive (fuzzel)" | fuzzel --dmenu -p "Wallpaper Type: ")

if [ "$TYPE" == "Static (fuzzel)" ]; then
    # STATIC WALLPAPER VIA FUZZEL LOGIC
    SELECTED=$(ls "$STATIC_DIR" | grep -E '\.(jpg|jpeg|png|webp)$' | fuzzel --dmenu -p "Select Wall: ")
    if [ -n "$SELECTED" ]; then
        FULL_PATH="$STATIC_DIR/$SELECTED"
        apply_wallpaper "$FULL_PATH"
    fi

elif [ "$TYPE" == "Live (fuzzel)" ]; then
    # LIVE WALLPAPER LOGIC
    SELECTED=$(ls "$LIVE_DIR" | fuzzel --dmenu -p "Select Live Wall: ")
    if [ -n "$SELECTED" ]; then
        pkill mpvpaper
        pkill swaybg
        pkill swaybg-backdrop
        
        # Push black bars off-screen
        mpvpaper -o "no-audio --loop-playlist --hwdec=nvdec --vf=scale=1920:1080 --video-zoom=0.15 --video-pan-y=0" "eDP-1" "$LIVE_DIR/$SELECTED" > /dev/null 2>&1 &
        disown
    fi

elif [ "$TYPE" == "Static (sxiv)" ]; then
    # STATIC WALLPAPER LOGIC
    SELECTED=$(sxiv -t -o "$STATIC_DIR" | head -n 1)
    if [ -n "$SELECTED" ]; then
        if [[ "$SELECTED" != /* ]]; then
            FULL_PATH="$STATIC_DIR/$SELECTED"
        else
            FULL_PATH="$SELECTED"
        fi
        apply_wallpaper "$FULL_PATH"
    fi
fi
