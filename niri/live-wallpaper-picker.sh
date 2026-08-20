#!/bin/bash
WALL_DIR="$HOME/Downloads/backup-20250614T092941Z-1-001/backup/live/"
# Use fuzzel to select the file
SELECTED=$(ls "$WALL_DIR" | fuzzel --dmenu -p "Live Wall: ")

if [ -n "$SELECTED" ]; then
    # Kill any existing wallpaper processes
    pkill mpvpaper
    pkill swaybg
    
    # Use mpvpaper with your proven 'smooth' flags
    # '*' targets all monitors, or use 'eDP-1' for just your laptop screen
    mpvpaper -o "no-audio --loop-playlist --hwdec=nvdec --vo=gpu --vf=scale=1920:1080" "*" "$WALL_DIR/$SELECTED" &
fi

