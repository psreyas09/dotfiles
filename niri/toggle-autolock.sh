#!/usr/bin/env bash

# Toggle auto-lock (swayidle) on and off
LOCK_CMD="swaylock -f --screenshots --clock --indicator --effect-blur 7x5"
TIMEOUT=300

if pgrep -x "swayidle" > /dev/null; then
    killall swayidle
    notify-send -h string:x-canonical-private-synchronous:autolock \
                -h boolean:SWAYNC_BYPASS_DND:true \
                -u normal \
                -t 2500 \
                -a "autolock" \
                -i "changes-prevent" \
                "Auto-Lock Disabled" "Screen will stay awake"
else
    swayidle -w \
        timeout "$TIMEOUT" "$LOCK_CMD" \
        before-sleep "$LOCK_CMD" > /dev/null 2>&1 &
    notify-send -h string:x-canonical-private-synchronous:autolock \
                -h boolean:SWAYNC_BYPASS_DND:true \
                -u normal \
                -t 2500 \
                -a "autolock" \
                -i "system-lock-screen" \
                "Auto-Lock Enabled" "Screen will lock after 5 minutes of inactivity"
fi
