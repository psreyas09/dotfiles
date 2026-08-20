#!/bin/bash

# Fetch condition text + temp without OS emojis
WEATHER_RAW=$(curl -s --max-time 3 'wttr.in?format=%C+%t' | tr -d '\n' | xargs)

if [ -z "$WEATHER_RAW" ] || [[ "$WEATHER_RAW" == *"Unknown"* ]] || [[ "$WEATHER_RAW" == *"HTML"* ]]; then
    echo '{"text": "󰖐 N/A", "tooltip": "Weather info unavailable"}'
    exit 0
fi

# Extract temperature and condition
TEMP=$(echo "$WEATHER_RAW" | grep -oE '[+-]?[0-9]+°C' || echo "")
COND=$(echo "$WEATHER_RAW" | sed "s/$TEMP//g" | xargs | tr '[:upper:]' '[:lower:]')

# Clean monochrome Nerd Font weather icons
ICON="󰖙" # Default sun

case "$COND" in
    *sun*|*clear*)              ICON="󰖙" ;;
    *partly*cloud*)             ICON="󰖕" ;;
    *cloud*|*overcast*)         ICON="󰖐" ;;
    *rain*|*drizzle*|*shower*)  ICON="󰖖" ;;
    *thunder*)                  ICON="󰙾" ;;
    *snow*|*ice*)               ICON="󰼶" ;;
    *fog*|*mist*|*haze*)        ICON="󰖑" ;;
esac

TEXT="$ICON $TEMP"
if [ -z "$TEMP" ]; then
    TEXT="$ICON $WEATHER_RAW"
fi

echo "{\"text\": \"$TEXT\", \"tooltip\": \"Current Weather: $WEATHER_RAW\"}"
