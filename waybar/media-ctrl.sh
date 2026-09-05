#!/bin/bash
ACTION="${1:-play-pause}"
ACTIVE_PLAYER=""

if [ -f /tmp/waybar_active_player ]; then
    SAVED=$(cat /tmp/waybar_active_player 2>/dev/null)
    if [ -n "$SAVED" ] && playerctl -l 2>/dev/null | grep -qx "$SAVED"; then
        ACTIVE_PLAYER="$SAVED"
    fi
fi

PLAYER_ARG=""
[ -n "$ACTIVE_PLAYER" ] && PLAYER_ARG="-p $ACTIVE_PLAYER"

playerctl $PLAYER_ARG "$ACTION"
pkill -USR2 -f "mediaplayer.sh" 2>/dev/null &
