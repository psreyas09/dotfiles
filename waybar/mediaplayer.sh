#!/bin/bash

# Animated Equalizer visualizer frames for Waybar
EQ_FRAMES=(" ▃▅▇" "▃▅▇▅" "▅▇▅▃" "▇▅▃ " "▅▃ ▃" "▃ ▃▅")
frame_idx=0
num_frames=${#EQ_FRAMES[@]}

while true; do
    if playerctl status > /dev/null 2>&1; then
        status=$(playerctl status 2>/dev/null)
        title=$(playerctl metadata title 2>/dev/null)
        artist=$(playerctl metadata artist 2>/dev/null)
        album=$(playerctl metadata album 2>/dev/null)
        player=$(playerctl metadata --format '{{playerName}}' 2>/dev/null)

        [ -z "$title" ] && title="Unknown Track"

        # Build tooltip with HTML escaping for Pango markup
        clean_title=$(echo "$title" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')
        clean_artist=$(echo "$artist" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')
        clean_album=$(echo "$album" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')

        tooltip="<b>$clean_title</b>"
        [ -n "$clean_artist" ] && tooltip="$tooltip\n $clean_artist"
        [ -n "$clean_album" ] && tooltip="$tooltip\n󰀥 $clean_album"
        tooltip="$tooltip\n󰐊 Status: $status"
        [ -n "$player" ] && tooltip="$tooltip ($player)"

        if [ "$status" = "Playing" ]; then
            eq="${EQ_FRAMES[$frame_idx]}"
            display_text="$eq $title"
            frame_idx=$(( (frame_idx + 1) % num_frames ))
            sleep_time=0.8
        elif [ "$status" = "Paused" ]; then
            display_text="$title"
            sleep_time=1.5
        else
            display_text="$title"
            sleep_time=2.0
        fi

        jq -n --arg text "$display_text" \
              --arg alt "$status" \
              --arg tooltip "$tooltip" \
              --arg class "$status" \
              '{$text, $alt, $tooltip, $class}' -c
    else
        echo '{"text": "No Media", "alt": "Stopped", "tooltip": "No media playing", "class": "stopped"}'
        sleep_time=2.0
    fi
    sleep "$sleep_time"
done
