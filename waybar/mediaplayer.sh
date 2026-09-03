#!/bin/bash
while true; do
    # Check if any player is active and actually has metadata
    if playerctl status > /dev/null 2>&1; then
        title=$(playerctl metadata title 2>/dev/null)
        status=$(playerctl status 2>/dev/null)

        # Build JSON without tooltip
        jq -n --arg text "$title" \
              --arg alt "$status" \
              --arg class "$status" \
              '{$text, $alt, $class}' -c
    else
        # When no player is found, output a blank state quietly
        echo '{"text": "No Media", "alt": "Stopped", "class": "stopped"}'
    fi
    sleep 2
done
