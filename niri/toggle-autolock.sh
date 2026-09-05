#!/usr/bin/env bash

# Auto-lock (swayidle) management script with persistent state saving
LOCK_CMD="swaylock -f --screenshots --clock --indicator --effect-blur 7x5"
TIMEOUT=300

CONF_FILE="$HOME/.config/niri/autolock.json"
DOTFILE_CONF="$HOME/dotfile/niri/autolock.json"

save_state() {
    local enabled="$1"
    mkdir -p "$HOME/.config/niri"
    cat <<EOF > "$CONF_FILE"
{
  "enabled": $enabled,
  "timeout": $TIMEOUT
}
EOF
    if [ -d "$HOME/dotfile/niri" ]; then
        cp "$CONF_FILE" "$DOTFILE_CONF" 2>/dev/null || true
    fi
}

is_saved_enabled() {
    if [ -f "$CONF_FILE" ]; then
        if grep -q '"enabled"[[:space:]]*:[[:space:]]*false' "$CONF_FILE"; then
            return 1
        elif grep -q '"enabled"[[:space:]]*:[[:space:]]*true' "$CONF_FILE"; then
            return 0
        fi
    fi
    # Default to running process check or enabled
    if pgrep -x "swayidle" > /dev/null; then
        return 0
    fi
    return 0
}

# Read custom timeout from JSON if present
if [ -f "$CONF_FILE" ]; then
    t_val=$(grep -o '"timeout"[[:space:]]*:[[:space:]]*[0-9]\+' "$CONF_FILE" | grep -o '[0-9]\+')
    if [ -n "$t_val" ] && [ "$t_val" -gt 0 ]; then
        TIMEOUT="$t_val"
    fi
fi

start_autolock() {
    local quiet="$1"
    killall swayidle 2>/dev/null || true
    sleep 0.1
    swayidle -w \
        timeout "$TIMEOUT" "$LOCK_CMD" \
        before-sleep "$LOCK_CMD" > /dev/null 2>&1 &
    save_state true
    if [ "$quiet" != "--quiet" ]; then
        notify-send -h string:x-canonical-private-synchronous:autolock \
                    -h boolean:SWAYNC_BYPASS_DND:true \
                    -u normal \
                    -t 2500 \
                    -a "autolock" \
                    -i "system-lock-screen" \
                    "Auto-Lock Enabled" "Screen will lock after 5 minutes of inactivity" 2>/dev/null || true
    fi
}

stop_autolock() {
    local quiet="$1"
    killall swayidle 2>/dev/null || true
    save_state false
    if [ "$quiet" != "--quiet" ]; then
        notify-send -h string:x-canonical-private-synchronous:autolock \
                    -h boolean:SWAYNC_BYPASS_DND:true \
                    -u normal \
                    -t 2500 \
                    -a "autolock" \
                    -i "changes-prevent" \
                    "Auto-Lock Disabled" "Screen will stay awake" 2>/dev/null || true
    fi
}

case "$1" in
    --startup|--restore|start-daemon)
        if is_saved_enabled; then
            start_autolock --quiet
        else
            killall swayidle 2>/dev/null || true
        fi
        ;;
    on|enable)
        start_autolock "$2"
        ;;
    off|disable)
        stop_autolock "$2"
        ;;
    status)
        if pgrep -x "swayidle" > /dev/null; then
            echo "enabled (running)"
            exit 0
        else
            echo "disabled"
            exit 1
        fi
        ;;
    toggle|"")
        if pgrep -x "swayidle" > /dev/null; then
            stop_autolock "$2"
        else
            start_autolock "$2"
        fi
        ;;
    *)
        echo "Usage: $0 [--startup | on | off | toggle | status] [--quiet]"
        exit 1
        ;;
esac
