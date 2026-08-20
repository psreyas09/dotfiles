# dotfiles

My personal dotfiles for a Wayland desktop built around the **[niri](https://github.com/YaLTeR/niri)** scrollable-tiling compositor.

## Overview

| Component | Tool |
|---|---|
| Compositor | [niri](https://github.com/YaLTeR/niri) |
| Status bar | [Waybar](https://github.com/Alexays/Waybar) |
| App launcher | [Fuzzel](https://codeberg.org/dnkl/fuzzel) |
| Terminal | [Kitty](https://sw.kovidgoyal.net/kitty/) |
| Shell prompt | [Starship](https://starship.rs/) (Tokyo Night theme) |
| Screen locker | [swaylock-effects](https://github.com/mortie/swaylock-effects) |
| Idle manager | [swayidle](https://github.com/swaywm/swayidle) |
| Live wallpaper | [mpvpaper](https://github.com/GhostNaN/mpvpaper) |
| Logout menu | [wlogout](https://github.com/ArtsyMacaw/wlogout) |
| File manager | [Nautilus](https://apps.gnome.org/Nautilus/) |
| Browser | Firefox |

## Structure

```
dotfiles/
├── niri/
│   ├── config.kdl            # Main niri config (input, layout, window rules, autostart)
│   ├── keybinds.kdl          # Keybind overrides
│   ├── wallpaper-picker.sh   # Static wallpaper picker script
│   └── live-wallpaper-picker.sh  # Live wallpaper picker script
├── waybar/
│   ├── config.jsonc          # Waybar modules and layout
│   ├── style.css             # Waybar stylesheet
│   ├── mediaplayer.sh        # MPRIS media player script
│   ├── ram_usage.sh          # RAM usage helper
│   └── scripts/
│       └── ram.sh            # RAM stats script
├── wlogout/
│   ├── layout                # wlogout button layout (lock, logout, shutdown, reboot)
│   └── styles.css            # wlogout stylesheet
├── starship.toml             # Starship prompt configuration
└── starship.bash             # Starship Bash integration script
```

## Keybindings

> **Mod** = Super key

### Applications

| Keybind | Action |
|---|---|
| `Mod + Return` | Open terminal (Kitty) |
| `Mod + Space` | Open app launcher (Fuzzel) |
| `Mod + B` | Open browser (Firefox) |
| `Mod + N` | Open file manager (Nautilus) |
| `Mod + Q` | Close focused window |

### Window Management

| Keybind | Action |
|---|---|
| `Mod + F` | Maximize column |
| `Mod + R` | Cycle preset column widths (33% / 50% / 67%) |
| `Mod + V` | Toggle floating |
| `Mod + Shift+V` | Switch focus between floating and tiling |
| `Mod + D` | Toggle overview |
| `Mod + ←/→` | Focus column left/right |
| `Mod + ↑/↓` | Focus workspace up/down |
| `Mod + Shift + ←/→` | Move column left/right |
| `Mod + Shift + ↑/↓` | Move column to workspace up/down |
| `Mod + 1–9` | Switch to workspace 1–9 |
| `Mod + Shift + 1–9` | Move column to workspace 1–9 |

### System

| Keybind | Action |
|---|---|
| `Mod + L` | Lock screen |
| `Mod + Escape` | Power menu (Lock / Suspend / Logout / Reboot / Shutdown) |
| `Mod + Shift+B` | Restart Waybar |
| `Mod + W` | Wallpaper picker |
| `Print` | Screenshot |

### Media & Hardware

| Keybind | Action |
|---|---|
| `XF86AudioPlay/Stop/Prev/Next` | Media control (playerctl) |
| `XF86AudioRaiseVolume/LowerVolume/Mute` | Volume control (WirePlumber) |
| `XF86AudioMicMute` | Toggle microphone mute |
| `XF86MonBrightnessUp/Down` | Screen brightness (brightnessctl) |

## Waybar Modules

The bar sits at the top of the screen and shows:

- **Left:** niri workspaces, active window title
- **Center:** Clock (12-hour, toggles to date on click)
- **Right:** Media player controls, CPU, RAM, Bluetooth, Wi-Fi, audio volume, battery, power button

## Starship Prompt

Uses the **Tokyo Night** color palette with a powerline-style layout:

```
 os username  directory  branch status   time 
```

Right side shows command duration and exit status.

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/psreyas09/dotfiles.git
   ```

2. Copy (or symlink) each config to its target location:

   | File/Directory | Target |
   |---|---|
   | `niri/` | `~/.config/niri/` |
   | `waybar/` | `~/.config/waybar/` |
   | `wlogout/` | `~/.config/wlogout/` |
   | `starship.toml` | `~/.config/starship.toml` |
   | `starship.bash` | sourced from `~/.bashrc` |

3. Make scripts executable:
   ```bash
   chmod +x niri/wallpaper-picker.sh niri/live-wallpaper-picker.sh
   chmod +x waybar/mediaplayer.sh waybar/ram_usage.sh waybar/scripts/ram.sh
   ```

4. Ensure all required tools are installed (see [Overview](#overview)).
