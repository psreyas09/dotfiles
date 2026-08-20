#!/bin/bash

# Fetch human-readable sink descriptions and internal names
SINKS_FILE="/tmp/waybar_audio_sinks.tmp"
pactl list sinks | awk '/Name:/ {name=$2} /Description:/ {sub(/Description: /, ""); print $0 " | " name}' > "$SINKS_FILE"

if [ ! -s "$SINKS_FILE" ]; then
    notify-send "Audio Switcher" "No audio output sinks found!" -u low
    exit 1
fi

CHOSEN=$(cut -d'|' -f1 "$SINKS_FILE" | fuzzel --dmenu -p "Select Audio Output: ")

if [ -n "$CHOSEN" ]; then
    SINK_NAME=$(grep "^$CHOSEN" "$SINKS_FILE" | cut -d'|' -f2 | xargs)
    if [ -n "$SINK_NAME" ]; then
        pactl set-default-sink "$SINK_NAME"
        
        # Move all currently playing audio streams to the new sink
        pactl list sink-inputs | awk '/Sink Input #/ {print $3}' | while read -r input; do
            pactl move-sink-input "$input" "$SINK_NAME" 2>/dev/null
        done
        
        notify-send "Audio Output" "Switched default sink to: $CHOSEN" -u low -i audio-speakers
    fi
fi

rm -f "$SINKS_FILE"
