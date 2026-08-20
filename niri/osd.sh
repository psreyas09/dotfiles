#!/usr/bin/env bash

# OSD (On-Screen Display) notification handler for Volume, Display Brightness, and Keyboard Backlight
# Integrates with wpctl, brightnessctl, and SwayNC / notify-send

show_volume() {
    local vol_raw
    vol_raw=$(wpctl get-volume @DEFAULT_AUDIO_SINK@)
    local vol
    vol=$(echo "$vol_raw" | awk '{print int($2 * 100)}')
    
    if [[ "$vol_raw" == *"[MUTED]"* ]]; then
        notify-send -h string:x-canonical-private-synchronous:osd \
                    -h int:value:"$vol" \
                    -u low \
                    -t 1200 \
                    -a "osd" \
                    -i "audio-volume-muted" \
                    "Volume: Muted" "${vol}%"
    else
        local icon="audio-volume-high"
        if [ "$vol" -eq 0 ]; then
            icon="audio-volume-muted"
        elif [ "$vol" -lt 33 ]; then
            icon="audio-volume-low"
        elif [ "$vol" -lt 66 ]; then
            icon="audio-volume-medium"
        fi
        notify-send -h string:x-canonical-private-synchronous:osd \
                    -h int:value:"$vol" \
                    -u low \
                    -t 1200 \
                    -a "osd" \
                    -i "$icon" \
                    "Volume" "${vol}%"
    fi
}

show_mic() {
    local mic_raw
    mic_raw=$(wpctl get-volume @DEFAULT_AUDIO_SOURCE@)
    if [[ "$mic_raw" == *"[MUTED]"* ]]; then
        notify-send -h string:x-canonical-private-synchronous:osd \
                    -u low \
                    -t 1200 \
                    -a "osd" \
                    -i "microphone-sensitivity-muted" \
                    "Microphone" "Muted"
    else
        notify-send -h string:x-canonical-private-synchronous:osd \
                    -u low \
                    -t 1200 \
                    -a "osd" \
                    -i "audio-input-microphone" \
                    "Microphone" "Active"
    fi
}

show_brightness() {
    local bright
    bright=$(brightnessctl -m | cut -d, -f4 | tr -d '%')
    notify-send -h string:x-canonical-private-synchronous:osd \
                -h int:value:"$bright" \
                -u low \
                -t 1200 \
                -a "osd" \
                -i "display-brightness-symbolic" \
                "Brightness" "${bright}%"
}

show_kbd_backlight() {
    local kbd_val
    kbd_val=$(brightnessctl -d '*::kbd_backlight*' -m 2>/dev/null | cut -d, -f4 | tr -d '%')
    if [ -z "$kbd_val" ]; then
        kbd_val=0
    fi
    notify-send -h string:x-canonical-private-synchronous:osd \
                -h int:value:"$kbd_val" \
                -u low \
                -t 1200 \
                -a "osd" \
                -i "keyboard-brightness-symbolic" \
                "Keyboard Backlight" "${kbd_val}%"
}

case "$1" in
    volume-up)
        wpctl set-volume -l 1.5 @DEFAULT_AUDIO_SINK@ 5%+ > /dev/null 2>&1
        show_volume
        ;;
    volume-down)
        wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%- > /dev/null 2>&1
        show_volume
        ;;
    volume-mute)
        wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle > /dev/null 2>&1
        show_volume
        ;;
    mic-mute)
        wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle > /dev/null 2>&1
        show_mic
        ;;
    brightness-up)
        brightnessctl -q set 5%+ > /dev/null 2>&1
        show_brightness
        ;;
    brightness-down)
        brightnessctl -q set 5%- > /dev/null 2>&1
        show_brightness
        ;;
    kbd-up)
        brightnessctl -q -d '*::kbd_backlight*' set 1+ > /dev/null 2>&1 || brightnessctl -q -d '*::kbd_backlight*' set 10%+ > /dev/null 2>&1
        show_kbd_backlight
        ;;
    kbd-down)
        brightnessctl -q -d '*::kbd_backlight*' set 1- > /dev/null 2>&1 || brightnessctl -q -d '*::kbd_backlight*' set 10%- > /dev/null 2>&1
        show_kbd_backlight
        ;;
    kbd-toggle)
        cur=$(brightnessctl -d '*::kbd_backlight*' get 2>/dev/null || echo 0)
        if [ "$cur" -eq 0 ]; then
            brightnessctl -q -d '*::kbd_backlight*' set 100% > /dev/null 2>&1 || brightnessctl -q -d '*::kbd_backlight*' set 1 > /dev/null 2>&1
        else
            brightnessctl -q -d '*::kbd_backlight*' set 0 > /dev/null 2>&1
        fi
        show_kbd_backlight
        ;;
    *)
        echo "Usage: $0 {volume-up|volume-down|volume-mute|mic-mute|brightness-up|brightness-down|kbd-up|kbd-down|kbd-toggle}"
        exit 1
        ;;
esac
