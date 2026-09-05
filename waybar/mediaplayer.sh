#!/bin/bash

trap ":" USR2

# Animated Equalizer visualizer frames for Waybar
EQ_FRAMES=(" ▃▅▇" "▃▅▇▅" "▅▇▅▃" "▇▅▃ " "▅▃ ▃" "▃ ▃▅")
frame_idx=0
num_frames=${#EQ_FRAMES[@]}

while true; do
    ACTIVE_PLAYER=""
    if [ -f /tmp/waybar_active_player ]; then
        SAVED=$(cat /tmp/waybar_active_player 2>/dev/null)
        if [ -n "$SAVED" ] && playerctl -l 2>/dev/null | grep -qx "$SAVED"; then
            ACTIVE_PLAYER="$SAVED"
        fi
    fi

    PLAYER_ARG=""
    [ -n "$ACTIVE_PLAYER" ] && PLAYER_ARG="-p $ACTIVE_PLAYER"

    if playerctl $PLAYER_ARG status > /dev/null 2>&1; then
        status=$(playerctl $PLAYER_ARG status 2>/dev/null)
        title=$(playerctl $PLAYER_ARG metadata title 2>/dev/null)
        artist=$(playerctl $PLAYER_ARG metadata artist 2>/dev/null)
        album=$(playerctl $PLAYER_ARG metadata album 2>/dev/null)
        player=$(playerctl $PLAYER_ARG metadata --format '{{playerName}}' 2>/dev/null)

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
            display_text="$eq <span font_features='liga=0,clig=0,dlig=0,calt=0'>$clean_title</span>"
            frame_idx=$(( (frame_idx + 1) % num_frames ))
            sleep_time=0.8
        elif [ "$status" = "Paused" ]; then
            display_text="<span font_features='liga=0,clig=0,dlig=0,calt=0'>$clean_title</span>"
            sleep_time=1.5
        else
            display_text="<span font_features='liga=0,clig=0,dlig=0,calt=0'>$clean_title</span>"
            sleep_time=2.0
        fi

        jq -n --arg text "$display_text" \
              --arg alt "$status" \
              --arg tooltip "" \
              --arg class "$status" \
              '{$text, $alt, $tooltip, $class}' -c
    else
        echo '{"text": "<span font_features=\"liga=0,clig=0,dlig=0,calt=0\">No Media</span>", "alt": "Stopped", "tooltip": "", "class": "stopped"}'
        sleep_time=2.0
    fi
    sleep "$sleep_time"
done
