#!/usr/bin/env bash
# popup-manager.sh — Mutual exclusion for Waybar popups
#
# Usage: popup-manager.sh <popup-name> [extra args passed to the popup script]
#
# Before opening the requested popup, all OTHER popups are closed via SIGUSR1.
# Supported popup names: wifi | bluetooth | media | power | dashboard

POPUP="$1"
shift

WAYBAR_SCRIPTS="$HOME/.config/waybar/scripts"

declare -A PID_FILES=(
    [wifi]="/tmp/waybar_wifi_popup.pid"
    [bluetooth]="/tmp/waybar_bluetooth_popup.pid"
    [media]="/tmp/waybar_media_popup.pid"
    [power]="/tmp/waybar_power_menu.pid"
    [dashboard]="/tmp/waybar_dashboard.pid"
)

declare -A SCRIPTS=(
    [wifi]="/usr/bin/python3 $WAYBAR_SCRIPTS/wifi-popup.py"
    [bluetooth]="/usr/bin/python3 $WAYBAR_SCRIPTS/bluetooth-popup.py"
    [media]="/usr/bin/python3 $WAYBAR_SCRIPTS/media-popup.py"
    [power]="/usr/bin/python3 $WAYBAR_SCRIPTS/power-menu.py"
    [dashboard]="/usr/bin/python3 $WAYBAR_SCRIPTS/dashboard.py"
)

close_others() {
    local target="$1"
    for name in "${!PID_FILES[@]}"; do
        [[ "$name" == "$target" ]] && continue
        local pid_file="${PID_FILES[$name]}"
        [[ -f "$pid_file" ]] || continue
        local pid
        pid=$(cat "$pid_file" 2>/dev/null) || continue
        if kill -0 "$pid" 2>/dev/null; then
            kill -SIGUSR1 "$pid" 2>/dev/null
        fi
    done
}

if [[ -z "${SCRIPTS[$POPUP]}" ]]; then
    echo "popup-manager: unknown popup '$POPUP'" >&2
    exit 1
fi

close_others "$POPUP"
sleep 0.05

exec ${SCRIPTS[$POPUP]} "$@"
