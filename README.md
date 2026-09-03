# 🌌 Niri Wayland Desktop Dotfiles

Personal high-performance, dynamic-themed dotfiles built around the **[Niri](https://github.com/YaLTeR/niri)** scrollable-tiling Wayland compositor on Fedora. Features an authentic macOS-style bottom dock with 120Hz auto-hide, a frosted-glass macOS App Switcher HUD, and desktop-environment quick settings popups.

---

## 🖥️ Overview

| Component | Tool / Engine | Description |
|---|---|---|
| **Compositor** | [Niri](https://github.com/YaLTeR/niri) | Scrollable Tiling Wayland Compositor |
| **Desktop Settings App** | Custom GTK3 (`niri-settings.py`) | Comprehensive control center with macOS UI/UX for display, wallpaper, dock, audio, network & shortcuts |
| **macOS Bottom Dock** | Custom GTK Layer Shell (`macos-dock.py`) | Centered floating glass dock with 120 FPS slide auto-hide, active app tracking, glowing running indicators, overview integration & Trash |
| **App Switcher HUD** | Custom GTK Layer Shell (`window-switcher.py`) | macOS-authentic `Super+Tab` / `Alt+Tab` switcher with 64px icons, frosted squircle plate, release-to-switch & `Q` to quit |
| **Quick Settings Popups** | Custom GTK Layer Shell | Interactive desktop menus for Wi-Fi (`wifi-popup.py`), Bluetooth (`bluetooth-popup.py`), and Media Player with Material You wavy seekbar (`media-popup.py`) |
| **Theme Engine** | [Wallust v3.5.1](https://codeberg.org/eon/wallust) | Auto-generates GTK, Kitty, Fuzzel & Waybar palettes dynamically from wallpaper |
| **Status Bar** | [Waybar](https://github.com/Alexays/Waybar) | Dynamic glass bar, tactile media pill, expandable audio volume slider drawer, quick settings integration |
| **Notification Center** | [SwayNC](https://github.com/ErikReider/SwayNotificationCenter) | Dynamic glass theme with 6-button quick action grid |
| **App Launcher** | [Fuzzel](https://codeberg.org/dnkl/fuzzel) | Glass geometry, 14px rounded borders, Adwaita icon theme |
| **Terminal** | [Kitty](https://sw.kovidgoyal.net/kitty/) | Powerline tabs, beam cursor, Kitty graphics protocol Survey Corps logo |
| **System Fetch** | [Fastfetch](https://github.com/fastfetch-cli/fastfetch) | Attack on Titan Survey Corps logo, CPU/GPU thermal badges, RAM/Disk progress bars |
| **Audio Visualizer** | [CAVA](https://github.com/karlstav/cava) | 60fps Monstercat smoothing, PipeWire/PulseAudio integration |
| **Shell Prompt** | [Starship](https://starship.rs/) | Powerline Git branch/status, execution timer, directory substitutions |
| **Screen Locker** | [swaylock-effects](https://github.com/mortie/swaylock-effects) | Screenshot blur, vignette frame, clock ring |
| **Power Menu** | [Wlogout](https://github.com/ArtsyMacaw/wlogout) | 3x2 symbol-only glass matrix grid |
| **Idle Manager** | [swayidle](https://github.com/swaywm/swayidle) | Auto-locks after 5 minutes of inactivity (toggleable) |

---

## ⌨️ Keybindings

> **Mod** = Super Key (`⌘` / `Windows`)

### 🚀 Applications & System HUD
| Keybind | Action |
|---|---|
| `Mod + Tab` / `Alt + Tab` | Cycle forward through **macOS App Switcher** |
| `Mod + Shift + Tab` / `Alt + Shift + Tab` | Cycle backward through **macOS App Switcher** |
| `Mod + ` ` (grave / tilde) | Cycle backward through **macOS App Switcher** (macOS native shortcut) |
| `Mod + Return` | Open terminal ([Kitty](file:///home/sreyas/.config/kitty/kitty.conf)) |
| `Mod + Space` | Open application launcher ([Fuzzel](file:///home/sreyas/.config/fuzzel/fuzzel.ini)) |
| `Mod + , (comma)` | Open **Niri Settings Control Center** |
| `Mod + D` | Toggle desktop overview (auto-reveals dock) |
| `Mod + W` | Open dynamic wallpaper picker script |
| `Mod + Shift + T` | Open desktop theme switcher toast menu |
| `Mod + Shift + N` | Open SwayNC notification control center |
| `Mod + Shift + E` | Open Wlogout 3x2 glass power matrix |
| `Mod + L` | Lock screen immediately ([Swaylock](file:///home/sreyas/.config/swaylock/config)) |
| `Mod + Shift + L` | Toggle automatic screen lock on / off |
| `Print` | Interactive region screenshot ([Niri native screenshot engine](file:///home/sreyas/.config/niri/config.kdl)) |
| `Mod + Q` | Close focused window |

### 🪟 Window Management
| Keybind | Action |
|---|---|
| `Mod + F` | Maximize column |
| `Mod + R` | Cycle preset column widths (33% / 50% / 67%) |
| `Mod + V` | Toggle window floating |
| `Mod + Shift + V` | Switch focus between floating and tiling windows |
| `Mod + ← / →` | Focus column left / right |
| `Mod + ↑ / ↓` | Focus workspace up / down |
| `Mod + 1–9` | Switch directly to workspace 1–9 |
| `Mod + Shift + 1–9` | Move focused window to workspace 1–9 |

---

## ✨ Features Spotlight

### ⚙️ Niri Desktop Settings Control Center
* **Comprehensive Modern GUI**: Built with GTK3 and styled with Apple/GNOME card groups and Wallust dynamic palette integration.
* **9 Dedicated Panels**: Display & Monitor (refresh rate, resolution, VRR), Appearance & Wallpapers (live gallery, Wallust themes), macOS Dock & HUD controls, Master Audio & Microphone gain, Wi-Fi & Bluetooth toggles, Screen & Keyboard Brightness, Battery health & Auto-lock, searchable Shortcuts Cheat Sheet, and System specs.
* **Universal Shortcut**: Launch anytime with <kbd>Mod</kbd>+<kbd>,</kbd> (comma) or by typing `settings` in the terminal.

### 🍎 macOS-Style Bottom Dock
* **Intelligent Auto-Hide**: Slides down out of the way when windows are active on the workspace; stays visible on empty desktop workspaces.
* **Hover to Reveal**: Hovering at the bottom edge smoothly glides the dock into view with 120 FPS physics.
* **Overview Aware**: Automatically appears during Niri Overview (<kbd>Mod</kbd>+<kbd>D</kbd>).
* **Running Indicators & Dynamic Apps**: Displays glowing macOS dots underneath open apps; unpinned open windows appear dynamically on the dock and disappear when closed.
* **0.0% Idle CPU**: Animation callbacks unhook completely when stationary to eliminate background CPU wakeups.

### 🪟 macOS App Switcher HUD
* Centered frosted-glass capsule displaying prominent 64px application icons in MRU order.
* Translucent selection squircle with centered bold app titles and document subtitles.
* Instant release-to-switch upon letting go of <kbd>Super</kbd> or <kbd>Alt</kbd>.
* Press <kbd>Q</kbd> while an app is highlighted to quit it directly from the switcher.

### 📶 Waybar Desktop Quick Settings
* **Wi-Fi Popup**: Left-click Wi-Fi module to open an interactive connection manager showing signal strengths, active network card, and available SSIDs.
* **Bluetooth Popup**: Left-click Bluetooth module for power toggling, paired device list, battery percentages, and live background discovery scan.
* **Media Popup**: Click song title to open a mini-player with live album art, track details, tactile controls, and a Cairo-rendered **Material You squiggly wave seekbar**.
* **Expandable Audio Drawer**: Hover over the volume icon to expand an integrated horizontal volume slider.

---

## ⚡ Custom Shell Shortcuts

| Command | Action |
|---|---|
| `theme` | Open interactive desktop theme preset selector |
| `wall` | Open wallpaper selector (Static Fuzzel / sxiv) |
| `settings` | Open **Niri Settings Control Center** |
| `fetch` / `sys` | Run Fastfetch Survey Corps system overview |
| `viz` | Launch CAVA 60fps audio visualizer |
| `lock` | Lock screen with blurred screenshot |
| `power` | Open Wlogout 3x2 glass power menu |
| `rice-update` | One-command dotfiles backup & auto-sync to GitHub (`psreyas09/dotfiles`) |

---

## 📦 Installation & Usage

1. **Clone repository**:
   ```bash
   git clone https://github.com/psreyas09/dotfiles.git ~/dotfile
   ```

2. **Sync dotfiles to `~/.config`**:
   ```bash
   cp -ra ~/dotfile/niri ~/dotfile/waybar ~/dotfile/kitty ~/dotfile/fuzzel ~/dotfile/swaync ~/dotfile/fastfetch ~/dotfile/swaylock ~/dotfile/cava ~/dotfile/wlogout ~/.config/
   cp ~/dotfile/.bashrc ~/dotfile/.zshrc ~/
   ```

3. **Reload Niri & Waybar**:
   ```bash
   niri msg action load-config-file
   killall waybar && waybar &
   ```

---

## 🤝 Acknowledgements & Credits

* Crafted with pair-programming assistance from **[Antigravity](https://github.com/google-deepmind)** (Google DeepMind) — architected the macOS-style GTK Layer Shell dock, window switcher HUD, Material You wavy media popup, Wi-Fi & Bluetooth quick settings menus, and 120 FPS compositor physics.
