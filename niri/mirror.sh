#!/usr/bin/env bash
# Screen mirroring / projector script for Niri using wl-mirror
# Created for Niri desktop environment

ACTION="${1:-toggle}"
SOURCE="${2:-}"
TARGET="${3:-}"
SCALING="${4:-fit}"
SHOW_CURSOR="${5:-yes}"

is_running() {
    pgrep -x wl-mirror >/dev/null 2>&1
}

stop_mirror() {
    if is_running; then
        pkill -x wl-mirror
        notify-send -u low -i video-display "Projector / Mirror" "Screen mirroring stopped"
    fi
}

start_mirror() {
    # Stop existing instance if any
    pkill -x wl-mirror 2>/dev/null
    sleep 0.15

    OUTPUTS_JSON=$(niri msg -j outputs 2>/dev/null)
    if [ -z "$OUTPUTS_JSON" ]; then
        notify-send -u critical -i dialog-error "Projector / Mirror" "Could not connect to Niri compositor"
        exit 1
    fi

    # Auto-detect outputs if not specified
    if [ -z "$SOURCE" ] || [ -z "$TARGET" ]; then
        DETECTED=$(/usr/bin/python3 -c "
import json, sys
try:
    data = json.loads('''$OUTPUTS_JSON''')
    names = list(data.keys())
    primary = 'eDP-1' if 'eDP-1' in names else (names[0] if names else '')
    others = [n for n in names if n != primary]
    secondary = others[0] if others else ''
    print(f'{primary}|{secondary}')
except Exception:
    print('|')
")
        AUTO_SOURCE=$(echo "$DETECTED" | cut -d'|' -f1)
        AUTO_TARGET=$(echo "$DETECTED" | cut -d'|' -f2)

        [ -z "$SOURCE" ] && SOURCE="$AUTO_SOURCE"
        [ -z "$TARGET" ] && TARGET="$AUTO_TARGET"
    fi

    if [ -z "$SOURCE" ]; then
        notify-send -u critical -i dialog-error "Projector / Mirror" "No display output detected"
        exit 1
    fi

    ARGS=("--backend" "screencopy-dmabuf" "--scaling" "$SCALING")

    if [ "$SHOW_CURSOR" = "no" ] || [ "$SHOW_CURSOR" = "false" ]; then
        ARGS+=("--no-show-cursor")
    else
        ARGS+=("--show-cursor")
    fi

    if [ -n "$TARGET" ] && [ "$TARGET" != "window" ] && [ "$TARGET" != "none" ]; then
        ARGS+=("--fullscreen-output" "$TARGET")
        notify-send -u normal -i video-display "Projector / Mirror" "Mirroring ${SOURCE} to ${TARGET} (${SCALING})"
    else
        notify-send -u normal -i video-display "Projector / Mirror" "Mirroring ${SOURCE} (Window mode)"
    fi

    ARGS+=("$SOURCE")

    # Launch wl-mirror in background detached
    nohup wl-mirror "${ARGS[@]}" >/dev/null 2>&1 &
}

case "$ACTION" in
    status)
        if is_running; then
            echo "active"
            exit 0
        else
            echo "inactive"
            exit 1
        fi
        ;;
    start)
        start_mirror
        ;;
    stop)
        stop_mirror
        ;;
    toggle)
        if is_running; then
            stop_mirror
        else
            start_mirror
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|toggle|status} [source] [target] [scaling] [show_cursor]"
        exit 1
        ;;
esac
