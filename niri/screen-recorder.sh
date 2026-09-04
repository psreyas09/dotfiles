#!/usr/bin/env bash

# Paths & Settings
SAVE_DIR="$HOME/Videos/Recordings"
PID_FILE="/tmp/wl-screenrec.pid"
INFO_FILE="/tmp/wl-screenrec.info"

mkdir -p "$SAVE_DIR"

is_recording() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        rm -f "$PID_FILE" "$INFO_FILE" 2>/dev/null
    fi
    return 1
}

stop_recording() {
    if ! is_recording; then
        notify-send "Screen Recorder" "No active recording found." -u low -i dialog-information -a "Screen Recorder"
        rm -f "$PID_FILE" "$INFO_FILE"
        pkill -RTMIN+8 waybar 2>/dev/null
        exit 0
    fi

    local pid
    pid=$(cat "$PID_FILE" 2>/dev/null)
    [ -z "$pid" ] && pid=$(pgrep -x wl-screenrec | head -n 1)

    local target_file=""
    if [ -f "$INFO_FILE" ]; then
        target_file=$(grep "^FILE=" "$INFO_FILE" 2>/dev/null | cut -d'=' -f2-)
    fi

    if [ -n "$pid" ]; then
        kill -INT "$pid" 2>/dev/null
        # Wait up to 3 seconds for file to be finalized
        for _ in {1..30}; do
            if ! kill -0 "$pid" 2>/dev/null; then
                break
            fi
            sleep 0.1
        done
    fi

    rm -f "$PID_FILE" "$INFO_FILE"
    pkill -RTMIN+8 waybar 2>/dev/null

    if [ -n "$target_file" ] && [ -f "$target_file" ]; then
        local filename
        filename=$(basename "$target_file")
        notify-send "Recording Saved" "Saved to ~/Videos/Recordings/$filename" \
            -u normal -i video-x-generic -a "Screen Recorder"
    else
        notify-send "Screen Recorder" "Recording stopped." -u low -i media-record -a "Screen Recorder"
    fi
}

start_recording() {
    local mode="$1"      # "screen" or "area"
    local with_audio="$2" # "audio" or "none"

    if is_recording; then
        stop_recording
        exit 0
    fi

    local geom=""
    if [ "$mode" == "area" ]; then
        geom=$(slurp -d -b "#00000066" -c "#89b4fa" -s "#89b4fa33" -w 2)
        if [ -z "$geom" ]; then
            exit 0 # User cancelled selection with Escape or right click
        fi
    fi

    local timestamp
    timestamp=$(date +%Y-%m-%d_%H-%M-%S)
    local out_file="$SAVE_DIR/Recording_${timestamp}.mp4"

    local cmd=(wl-screenrec --no-hw --ffmpeg-encoder-options "preset=ultrafast,crf=22" -f "$out_file")

    if [ "$mode" == "area" ] && [ -n "$geom" ]; then
        cmd+=(-g "$geom")
    fi

    if [ "$with_audio" == "audio" ]; then
        cmd+=(--audio)
    fi

    # Start recorder in background
    "${cmd[@]}" >/dev/null 2>&1 &
    local rec_pid=$!

    # Verify recorder started
    sleep 0.2
    if ! kill -0 "$rec_pid" 2>/dev/null; then
        notify-send "Screen Recorder" "Failed to start recording." -u critical -i dialog-error -a "Screen Recorder"
        exit 1
    fi

    echo "$rec_pid" > "$PID_FILE"
    {
        echo "PID=$rec_pid"
        echo "FILE=$out_file"
        echo "START=$(date +%s)"
        echo "MODE=$mode"
        echo "AUDIO=$with_audio"
    } > "$INFO_FILE"

    pkill -RTMIN+8 waybar 2>/dev/null

    local audio_msg=""
    [ "$with_audio" == "audio" ] && audio_msg=" (with Audio)"
    notify-send "Recording Started" "Mode: ${mode}${audio_msg}\nPress shortcut or click Waybar REC to stop." \
        -u normal -i media-record -a "Screen Recorder"
}

get_status() {
    if is_recording; then
        local start_time=0
        if [ -f "$INFO_FILE" ]; then
            start_time=$(grep "^START=" "$INFO_FILE" 2>/dev/null | cut -d'=' -f2-)
        fi

        local elapsed_str=""
        if [ -n "$start_time" ] && [ "$start_time" -gt 0 ] 2>/dev/null; then
            local now
            now=$(date +%s)
            local diff=$((now - start_time))
            local mins=$((diff / 60))
            local secs=$((diff % 60))
            printf -v elapsed_str "%02d:%02d" "$mins" "$secs"
        fi

        local text=" REC"
        [ -n "$elapsed_str" ] && text=" REC $elapsed_str"

        printf '{"text":"%s","tooltip":"Recording active (%s)\\nClick to stop","class":"recording"}\n' "$text" "$elapsed_str"
    else
        printf '{"text":"","class":"inactive"}\n'
    fi
}

show_menu() {
    if is_recording; then
        local choice
        choice=$(echo -e "⏹  Stop Recording\n❌ Cancel" | fuzzel --dmenu -p "Recording in Progress: ")
        if [ "$choice" == "⏹  Stop Recording" ]; then
            stop_recording
        fi
        exit 0
    fi

    local options="󰹑  Record Screen (Fullscreen)\n󰩭  Record Selection (Area)\n󰍬  Record Screen + Audio (Mic)\n󰍬  Record Selection + Audio (Mic)"
    local choice
    choice=$(echo -e "$options" | fuzzel --dmenu -p "Screen Recorder: ")

    case "$choice" in
        *"Record Screen (Fullscreen)"*)
            start_recording "screen" "none"
            ;;
        *"Record Selection (Area)"*)
            start_recording "area" "none"
            ;;
        *"Record Screen + Audio"*)
            start_recording "screen" "audio"
            ;;
        *"Record Selection + Audio"*)
            start_recording "area" "audio"
            ;;
    esac
}

# --- Argument Routing ---
case "$1" in
    --stop)
        stop_recording
        ;;
    --status)
        get_status
        ;;
    --toggle)
        if is_recording; then
            stop_recording
        else
            show_menu
        fi
        ;;
    --fullscreen|--screen)
        start_recording "screen" "none"
        ;;
    --area)
        start_recording "area" "none"
        ;;
    --fullscreen-audio)
        start_recording "screen" "audio"
        ;;
    --area-audio)
        start_recording "area" "audio"
        ;;
    *)
        if is_recording; then
            stop_recording
        else
            show_menu
        fi
        ;;
esac
