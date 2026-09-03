#!/bin/bash
WALL_DIR="$HOME/wall/live"
# Use fuzzel to select the file
SELECTED=$(ls "$WALL_DIR" | fuzzel --dmenu -p "Live Wall: ")

if [ -n "$SELECTED" ]; then
    bash "$HOME/.config/niri/wallpaper-picker.sh" "$WALL_DIR/$SELECTED"
fi

