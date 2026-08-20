#!/bin/bash

# Define paths
LIVE_DIR="$HOME/wall/live"
STATIC_DIR="$HOME/wall"

# 1. Ask user for type
TYPE=$(echo -e "Static (fuzzel)\nStatic (sxiv)\nLive (fuzzel)" | fuzzel --dmenu -p "Wallpaper Type: ")

if [ "$TYPE" == "Static (fuzzel)" ]; then
    # STATIC WALLPAPER VIA FUZZEL LOGIC
    SELECTED=$(ls "$STATIC_DIR" | grep -E '\.(jpg|jpeg|png|webp)$' | fuzzel --dmenu -p "Select Wall: ")
    if [ -n "$SELECTED" ]; then
        pkill mpvpaper
        pkill swaybg
        swaybg -i "$STATIC_DIR/$SELECTED" -m fill > /dev/null 2>&1 &
        disown
    fi

elif [ "$TYPE" == "Live (fuzzel)" ]; then
    # LIVE WALLPAPER LOGIC
    SELECTED=$(ls "$LIVE_DIR" | fuzzel --dmenu -p "Select Live Wall: ")
    if [ -n "$SELECTED" ]; then
        pkill mpvpaper
        pkill swaybg
        
        # ADDED: --video-zoom=0.15 and --video-pan-y=0 to push black bars off-screen
        mpvpaper -o "no-audio --loop-playlist --hwdec=nvdec --vf=scale=1920:1080 --video-zoom=0.15 --video-pan-y=0" "eDP-1" "$LIVE_DIR/$SELECTED" > /dev/null 2>&1 &
        disown
    fi

elif [ "$TYPE" == "Static (sxiv)" ]; then
    # STATIC WALLPAPER LOGIC
    SELECTED=$(sxiv -t -o "$STATIC_DIR" | head -n 1)
    if [ -n "$SELECTED" ]; then
        pkill mpvpaper
        pkill swaybg
        swaybg -i "$SELECTED" -m fill > /dev/null 2>&1 &
        disown
    fi
fi


