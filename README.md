#  Niri Wayland Desktop Dotfiles

Personal high-performance, dynamic-themed dotfiles built around the **[Niri](https://github.com/YaLTeR/niri)** scrollable-tiling Wayland compositor on Fedora.

---

##  Overview

| Component | Tool / Engine |
|---|---|
| **Compositor** | [Niri](https://github.com/YaLTeR/niri) (Scrollable Tiling Wayland Compositor) |
| **Theme Engine** | [Wallust v3.5.1](https://codeberg.org/eon/wallust) (Auto-generates GTK, Kitty, Fuzzel & Waybar palettes on wallpaper change) |
| **Status Bar** | [Waybar](https://github.com/Alexays/Waybar) (Flat glass design, right-click audio sink switcher, `btop` launchers, circle workspaces) |
| **Notification Center** | [SwayNC](https://github.com/ErikReider/SwayNotificationCenter) (Dynamic glass theme with 6-button quick action grid) |
| **App Launcher** | [Fuzzel](https://codeberg.org/dnkl/fuzzel) (Glass geometry, 14px rounded borders, Adwaita icon theme) |
| **Terminal** | [Kitty](https://sw.kovidgoyal.net/kitty/) (Powerline tabs, beam cursor, Kitty graphics protocol survey_corps logo) |
| **System Fetch** | [Fastfetch](https://github.com/fastfetch-cli/fastfetch) (Attack on Titan Survey Corps logo, CPU/GPU thermal badges, RAM/Disk progress bars) |
| **Audio Visualizer** | [CAVA](https://github.com/karlstav/cava) (60fps Monstercat smoothing, PipeWire/PulseAudio integration) |
| **Shell Prompt** | [Starship](https://starship.rs/) (Powerline Git branch/status, execution timer, directory substitutions) |
| **Screen Locker** | [swaylock-effects](https://github.com/mortie/swaylock-effects) (Screenshot blur, vignette frame, clock ring) |
| **Power Menu** | [Wlogout](https://github.com/ArtsyMacaw/wlogout) (3x2 symbol-only glass matrix grid) |
| **Idle Manager** | [swayidle](https://github.com/swaywm/swayidle) (Auto-locks after 5 minutes of inactivity) |

---

## ⌨ Keybindings

> **Mod** = Super Key (`⌘` / `Windows`)

###  Applications & Ricing Controls
| Keybind | Action |
|---|---|
| `Mod + Return` | Open terminal ([Kitty](file:///home/sreyas/.config/kitty/kitty.conf)) |
| `Mod + Space` | Open application launcher ([Fuzzel](file:///home/sreyas/.config/fuzzel/fuzzel.ini)) |
| `Mod + W` | Open dynamic wallpaper picker script |
| `Mod + Shift + T` | Open desktop theme switcher toast menu |
| `Mod + Shift + N` | Open SwayNC notification control center |
| `Mod + Shift + E` | Open Wlogout 3x2 glass power matrix |
| `Mod + L` | Lock screen immediately ([Swaylock](file:///home/sreyas/.config/swaylock/config)) |
| `Print` | Interactive region screenshot ([Niri native screenshot engine](file:///home/sreyas/.config/niri/config.kdl)) |
| `Mod + Q` | Close focused window |

### 🪟 Window Management
| Keybind | Action |
|---|---|
| `Mod + F` | Maximize column |
| `Mod + R` | Cycle preset column widths (33% / 50% / 67%) |
| `Mod + V` | Toggle window floating |
| `Mod + Shift + V` | Switch focus between floating and tiling windows |
| `Mod + D` | Toggle desktop overview |
| `Mod + ← / →` | Focus column left / right |
| `Mod + ↑ / ↓` | Focus workspace up / down |
| `Mod + 1–9` | Switch directly to workspace 1–9 |
| `Mod + Shift + 1–9` | Move focused window to workspace 1–9 |

---

## ⚡ Custom Shell Shortcuts & GitHub Sync

| Command | Action |
|---|---|
| `theme` | Open interactive desktop theme preset selector |
| `wall` | Open wallpaper selector (Static Fuzzel / sxiv) |
| `fetch` / `sys` | Run Fastfetch Survey Corps system overview |
| `viz` | Launch CAVA 60fps audio visualizer |
| `lock` | Lock screen with blurred screenshot |
| `power` | Open Wlogout 3x2 glass power menu |
| `rice-update` | One-command dotfiles backup & auto-sync to GitHub (`psreyas09/dotfiles`) |

---

##  Installation & Usage

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
