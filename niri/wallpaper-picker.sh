#!/bin/bash

# Define paths
LIVE_DIR="$HOME/wall/live"
STATIC_DIR="$HOME/wall"
CACHE_DIR="$HOME/.cache"
STATE_FILE="$CACHE_DIR/current_wallpaper"
BLURRED_WALL="$CACHE_DIR/current_wallpaper_blurred.png"
DEFAULT_WALL="$STATIC_DIR/0anime4.jpg"

mkdir -p "$CACHE_DIR"

# Helper function to ensure swww daemon is running
ensure_swww() {
    if ! pgrep -x swww-daemon >/dev/null; then
        setsid swww-daemon >/dev/null 2>&1 &
        sleep 0.3
    fi
}

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

# Helper function to apply wallpaper with smooth animated transitions + overview backdrop
apply_wallpaper() {
    local img="$1"
    [ ! -f "$img" ] && return 1

    # Save selection for persistence across reboots/logouts
    echo "$img" > "$STATE_FILE"

    pkill -9 mpvpaper 2>/dev/null
    pkill -9 swaybg 2>/dev/null

    ensure_swww

    # Pick a random transition animation each time
    local transitions=("wipe" "wave" "grow" "outer" "fade" "any")
    local chosen_type="${transitions[$((RANDOM % ${#transitions[@]}))]}"

    case "$chosen_type" in
        wipe)
            local angles=(0 30 45 60 90 120 135 180 210 240 270 315)
            local angle="${angles[$((RANDOM % ${#angles[@]}))]}"
            swww img "$img" \
                --transition-type wipe \
                --transition-angle "$angle" \
                --transition-duration 1.3 \
                --transition-fps 60 \
                --transition-bezier .54,0,.34,.99 2>/dev/null
            ;;
        wave)
            local angles=(0 30 45 60 90 120 135 180 210 240 270 315)
            local angle="${angles[$((RANDOM % ${#angles[@]}))]}"
            swww img "$img" \
                --transition-type wave \
                --transition-angle "$angle" \
                --transition-duration 1.3 \
                --transition-fps 60 2>/dev/null
            ;;
        grow)
            local positions=("center" "top" "bottom" "left" "right" "top-left" "top-right" "bottom-left" "bottom-right")
            local pos="${positions[$((RANDOM % ${#positions[@]}))]}"
            swww img "$img" \
                --transition-type grow \
                --transition-pos "$pos" \
                --transition-duration 1.3 \
                --transition-fps 60 \
                --transition-bezier .54,0,.34,.99 2>/dev/null
            ;;
        outer)
            local positions=("center" "top-left" "top-right" "bottom-left" "bottom-right")
            local pos="${positions[$((RANDOM % ${#positions[@]}))]}"
            swww img "$img" \
                --transition-type outer \
                --transition-pos "$pos" \
                --transition-duration 1.3 \
                --transition-fps 60 \
                --transition-bezier .54,0,.34,.99 2>/dev/null
            ;;
        any)
            swww img "$img" \
                --transition-type any \
                --transition-duration 1.3 \
                --transition-fps 60 \
                --transition-bezier .54,0,.34,.99 2>/dev/null
            ;;
        fade|*)
            swww img "$img" \
                --transition-type fade \
                --transition-duration 1.3 \
                --transition-fps 60 \
                --transition-bezier .54,0,.34,.99 2>/dev/null
            ;;
    esac

    # 2. Update blurred backdrop for Overview in background
    (
        pkill -9 swaybg-backdrop 2>/dev/null
        magick "$img" -resize 1920x1080^ -gravity center -extent 1920x1080 -blur 0x25 "$BLURRED_WALL" 2>/dev/null || \
        ffmpeg -y -i "$img" -vf "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=25" "$BLURRED_WALL" 2>/dev/null
        nohup swaybg-backdrop -i "$BLURRED_WALL" -m fill > /dev/null 2>&1 &
    ) &

    # 3. Generate dynamic color palette
    apply_wallust_palette "$img"
}

# Helper function to apply live wallpaper
apply_live_wallpaper() {
    local video="$1"
    [ ! -f "$video" ] && return 1

    # Save selection for persistence across reboots/logouts
    echo "$video" > "$STATE_FILE"

    pkill -9 swww-daemon 2>/dev/null
    pkill -9 swaybg 2>/dev/null
    pkill -9 mpvpaper 2>/dev/null
    pkill -9 swaybg-backdrop 2>/dev/null

    # Generate blurred first frame for Overview backdrop
    ffmpeg -y -i "$video" -vframes 1 -vf "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=25" "$BLURRED_WALL" 2>/dev/null
    if [ -f "$BLURRED_WALL" ]; then
        nohup swaybg-backdrop -i "$BLURRED_WALL" -m fill > /dev/null 2>&1 &
    fi

    # Launch live wallpaper with mpvpaper
    nohup mpvpaper -o "no-audio --loop-playlist --hwdec=nvdec --vf=scale=1920:1080 --video-zoom=0.15 --video-pan-y=0" "eDP-1" "$video" > /dev/null 2>&1 &
}

# Helper function to restore wallpaper at startup
restore_wallpaper() {
    local wall=""
    if [ -f "$STATE_FILE" ]; then
        wall=$(cat "$STATE_FILE" 2>/dev/null)
    fi

    # Fallback if saved file does not exist
    if [ -z "$wall" ] || [ ! -f "$wall" ]; then
        wall="$DEFAULT_WALL"
    fi

    [ ! -f "$wall" ] && exit 0

    local ext="${wall##*.}"
    ext=$(echo "$ext" | tr '[:upper:]' '[:lower:]')

    case "$ext" in
        mp4|mkv|mov|webm|avi|gif)
            apply_live_wallpaper "$wall"
            ;;
        *)
            pkill -9 mpvpaper 2>/dev/null
            pkill -9 swaybg 2>/dev/null
            pkill -9 swaybg-backdrop 2>/dev/null

            ensure_swww
            swww img "$wall" --transition-type none 2>/dev/null || swww img "$wall" 2>/dev/null

            # If blurred cache does not exist, generate it
            if [ ! -f "$BLURRED_WALL" ]; then
                magick "$wall" -resize 1920x1080^ -gravity center -extent 1920x1080 -blur 0x25 "$BLURRED_WALL" 2>/dev/null || \
                ffmpeg -y -i "$wall" -vf "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=25" "$BLURRED_WALL" 2>/dev/null
            fi

            nohup swaybg-backdrop -i "$BLURRED_WALL" -m fill > /dev/null 2>&1 &
            ;;
    esac
}

# --- Argument Routing ---
if [ "$1" == "--restore" ] || [ "$1" == "-r" ] || [ "$1" == "--init" ]; then
    restore_wallpaper
    exit 0
elif [ -n "$1" ] && [ -f "$1" ]; then
    file_path="$1"
    ext="${file_path##*.}"
    ext=$(echo "$ext" | tr '[:upper:]' '[:lower:]')
    case "$ext" in
        mp4|mkv|mov|webm|avi|gif)
            apply_live_wallpaper "$file_path"
            ;;
        *)
            apply_wallpaper "$file_path"
            ;;
    esac
    exit 0
fi

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
        apply_live_wallpaper "$LIVE_DIR/$SELECTED"
    fi

elif [ "$TYPE" == "Static (sxiv)" ]; then
    # STATIC WALLPAPER VIA SXIV
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
