# .bashrc

# 1. Source global definitions
if [ -f /etc/bashrc ]; then
    . /etc/bashrc
fi

# 2. User specific environment & PATH
if ! [[ "$PATH" =~ "$HOME/.local/bin:$HOME/bin:" ]]; then
    PATH="$HOME/.local/bin:$HOME/bin:$PATH"
fi
export PATH

# 3. User specific aliases and functions
if [ -d ~/.bashrc.d ]; then
    for rc in ~/.bashrc.d/*; do
        if [ -f "$rc" ]; then
            . "$rc"
        fi
    done
fi
unset rc

# 4. Tool Initializations (Only ONCE each)

# Homebrew
if [ -f /home/linuxbrew/.linuxbrew/bin/brew ]; then
    eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
fi

# NVM (Node Version Manager)
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"

# Path for Global NPM
export PATH=~/.npm-global/bin:$PATH

# TheFuck alias
if command -v thefuck &> /dev/null; then
    eval "$(thefuck --alias)"
fi

# 5. Shell Enhancements
if [[ -f ~/.local/share/blesh/ble.sh ]]; then
    source ~/.local/share/blesh/ble.sh
fi

# 6. Initialize Starship (Updated for blesh compatibility)
if [[ ${BLE_VERSION-} ]]; then
    eval "$(starship init bash --print-full-init)"
else
    eval "$(starship init bash)"
fi

# 7. Post Initializations & Environment Paths
if [[ $- == *i* ]] && command -v fastfetch &>/dev/null; then
    fastfetch
fi
export PATH="$HOME/.cargo/bin:$PATH"
export PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:$PKG_CONFIG_PATH
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH

# 8. Custom User Aliases
alias anifetch='anifetch Downloads/bad_apple.mp4 -ff --sound'
alias clear='clear && printf "\033[3J"'
alias update='sudo dnf upgrade -y '

# --- Custom Desktop Ricing Aliases & Sync Functions ---
alias theme='bash ~/.config/niri/theme-switcher.sh'
alias wall='bash ~/.config/niri/wallpaper-picker.sh'
alias settings='/usr/bin/python3 ~/.config/niri/niri-settings.py'
alias fetch='fastfetch'
alias sys='fastfetch'
alias viz='cava'
alias lock='swaylock'
alias power='wlogout -b 3'
alias dotfiles='cd ~/dotfile'

# One-command Dotfiles Backup & GitHub Sync
rice-update() {
    local msg="${1:-update: sync latest desktop ricing configuration changes}"
    echo "Syncing ~/.config to ~/dotfile..."
    mkdir -p ~/dotfile
    cp -ra ~/.config/niri ~/.config/waybar ~/.config/kitty ~/.config/fuzzel ~/.config/swaync ~/.config/themes ~/.config/fastfetch ~/.config/swaylock ~/.config/cava ~/.config/wlogout ~/.config/starship*.toml ~/dotfile/ 2>/dev/null
    cd ~/dotfile || return
    git add .
    git commit -m "$msg"
    git push origin main
    echo "Desktop dotfiles synced & pushed to GitHub (psreyas09/dotfiles)!"
    cd - >/dev/null
}


# Added by Antigravity CLI installer
export PATH="/home/sreyas/.local/bin:$PATH"

# Qwen Code PATH block begin
export PATH='/home/sreyas/.local/bin':$PATH
# Qwen Code PATH block end
