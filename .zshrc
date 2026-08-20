export PATH="$HOME/.cargo/bin:$PATH"

# Added by Antigravity CLI installer
export PATH="/home/sreyas/.local/bin:$PATH"

# --- Custom Desktop Ricing Aliases & Sync Functions ---
alias theme='bash ~/.config/niri/theme-switcher.sh'
alias wall='bash ~/.config/niri/wallpaper-picker.sh'
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
