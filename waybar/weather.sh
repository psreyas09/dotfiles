#!/bin/bash

# Fetch current weather with a 3-second timeout
WEATHER=$(curl -s --max-time 3 'wttr.in?format=%c+%t' | tr -d '\n' | xargs)

if [ -z "$WEATHER" ] || [[ "$WEATHER" == *"Unknown"* ]] || [[ "$WEATHER" == *"HTML"* ]]; then
    echo '{"text": "󰖐 N/A", "tooltip": "Weather info unavailable"}'
else
    echo "{\"text\": \"$WEATHER\", \"tooltip\": \"Current Weather: $WEATHER\"}"
fi
