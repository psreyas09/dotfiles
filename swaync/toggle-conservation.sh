#!/bin/bash
# Toggle Lenovo Battery Conservation Mode for SwayNC

VPC_PATH=""
for p in \
    /sys/bus/platform/drivers/ideapad_acpi/*/conservation_mode \
    /sys/bus/platform/devices/VPC2004:*/conservation_mode \
    /sys/devices/platform/ideapad_acpi/conservation_mode; do
    if [ -f "$p" ]; then
        VPC_PATH="$p"
        break
    fi
done

if [ -z "$VPC_PATH" ]; then
    if [ "$1" = "status" ]; then
        echo "false"
    fi
    exit 1
fi

get_status() {
    local val
    val=$(cat "$VPC_PATH" 2>/dev/null)
    if [ "$val" = "1" ]; then
        echo "true"
    else
        echo "false"
    fi
}

if [ "$1" = "status" ]; then
    get_status
    exit 0
fi

current_val=$(cat "$VPC_PATH" 2>/dev/null || echo "0")

# Determine target value
target=""
if [ "$1" = "on" ] || [ "$1" = "1" ]; then
    target="1"
elif [ "$1" = "off" ] || [ "$1" = "0" ]; then
    target="0"
elif [ "$SWAYNC_TOGGLE_STATE" = "true" ]; then
    target="1"
elif [ "$SWAYNC_TOGGLE_STATE" = "false" ]; then
    target="0"
else
    # Invert current state if not specified
    if [ "$current_val" = "1" ]; then
        target="0"
    else
        target="1"
    fi
fi

# Attempt 1: Direct write (if permissions allow)
if printf "%s" "$target" > "$VPC_PATH" 2>/dev/null; then
    written=true
else
    written=false
fi

# Attempt 2: sudo without password if available
if [ "$written" = "false" ]; then
    if sudo -n sh -c "echo $target > '$VPC_PATH' && chmod 666 '$VPC_PATH'" 2>/dev/null; then
        written=true
    fi
fi

# Attempt 3: PolicyKit authentication (prompts once via lxpolkit and sets mode 666)
if [ "$written" = "false" ]; then
    if pkexec sh -c "echo $target > '$VPC_PATH' && chmod 666 '$VPC_PATH'" 2>/dev/null; then
        written=true
    fi
fi

# Notify user of new state
new_val=$(cat "$VPC_PATH" 2>/dev/null || echo "$current_val")
if [ "$new_val" = "1" ]; then
    notify-send -a "Lenovo Vantage" -i "battery-good" -h string:x-canonical-private-synchronous:conservation-mode \
        "Conservation Mode Active" "Charging limited to 60-80% to protect battery health." 2>/dev/null
else
    notify-send -a "Lenovo Vantage" -i "battery-charging" -h string:x-canonical-private-synchronous:conservation-mode \
        "Conservation Mode Disabled" "Battery will charge to 100% full capacity." 2>/dev/null
fi
