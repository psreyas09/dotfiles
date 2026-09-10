#!/usr/bin/env bash
# ==============================================================================
# Night Light / Blue Light Filter Controller for Niri
# Controls display color temperature & brightness via gammastep (Wayland protocol)
# ==============================================================================

CONFIG_FILE="$HOME/.config/niri/night-light.json"
BIN="/home/sreyas/.local/bin/gammastep"

DEFAULT_ENABLED=false
DEFAULT_TEMP=4000
DEFAULT_BRIGHTNESS=1.0

read_config() {
    if [ -f "$CONFIG_FILE" ]; then
        ENABLED=$(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(str(d.get('enabled', False)).lower())" 2>/dev/null || echo "false")
        TEMP=$(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(d.get('temperature', $DEFAULT_TEMP))" 2>/dev/null || echo "$DEFAULT_TEMP")
        BRIGHTNESS=$(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(d.get('brightness', $DEFAULT_BRIGHTNESS))" 2>/dev/null || echo "$DEFAULT_BRIGHTNESS")
    else
        ENABLED="false"
        TEMP="$DEFAULT_TEMP"
        BRIGHTNESS="$DEFAULT_BRIGHTNESS"
    fi
}

write_config() {
    local enabled="$1"
    local temp="$2"
    local brightness="$3"
    python3 -c "
import json
data = {'enabled': bool($enabled), 'temperature': int($temp), 'brightness': float($brightness)}
with open('$CONFIG_FILE', 'w') as f:
    json.dump(data, f, indent=2)
" 2>/dev/null
}

apply_state() {
    local temp="$1"
    local brightness="${2:-1.0}"
    pkill -x gammastep 2>/dev/null || true
    local count=0
    while pgrep -x gammastep >/dev/null && [ $count -lt 15 ]; do
        sleep 0.02
        count=$((count + 1))
    done
    if pgrep -x gammastep >/dev/null; then
        pkill -9 -x gammastep 2>/dev/null || true
        sleep 0.02
    fi
    nohup "$BIN" -m wayland -O "$temp" -b "$brightness:$brightness" >/dev/null 2>&1 &
}

stop_night_light() {
    pkill -x gammastep 2>/dev/null || true
}

case "${1:-status}" in
    on)
        read_config
        TEMP="${2:-$TEMP}"
        BRIGHTNESS="${3:-$BRIGHTNESS}"
        write_config "True" "$TEMP" "$BRIGHTNESS"
        apply_state "$TEMP" "$BRIGHTNESS"
        ;;
    off)
        read_config
        write_config "False" "$TEMP" "$BRIGHTNESS"
        stop_night_light
        ;;
    set)
        read_config
        TEMP="${2:-$TEMP}"
        BRIGHTNESS="${3:-$BRIGHTNESS}"
        write_config "$([ "$ENABLED" = "true" ] && echo 'True' || echo 'False')" "$TEMP" "$BRIGHTNESS"
        if [ "$ENABLED" = "true" ] || pgrep -x gammastep >/dev/null; then
            apply_state "$TEMP" "$BRIGHTNESS"
        fi
        ;;
    toggle)
        read_config
        if pgrep -x gammastep >/dev/null || [ "$ENABLED" = "true" ]; then
            write_config "False" "$TEMP" "$BRIGHTNESS"
            stop_night_light
        else
            write_config "True" "$TEMP" "$BRIGHTNESS"
            apply_state "$TEMP" "$BRIGHTNESS"
        fi
        ;;
    restore)
        read_config
        if [ "$ENABLED" = "true" ]; then
            apply_state "$TEMP" "$BRIGHTNESS"
        else
            stop_night_light
        fi
        ;;
    status)
        read_config
        RUNNING=$(pgrep -x gammastep >/dev/null && echo "True" || echo "False")
        python3 -c "
import json
print(json.dumps({'running': $RUNNING, 'enabled': '$ENABLED' == 'true', 'temperature': int('$TEMP'), 'brightness': float('$BRIGHTNESS')}))
"
        ;;
    *)
        echo "Usage: $0 {on [temp] [brightness]|off|set <temp> [brightness]|toggle|restore|status}"
        exit 1
        ;;
esac
