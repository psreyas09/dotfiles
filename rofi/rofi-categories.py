#!/usr/bin/python3
import os
import sys
import json
import subprocess

CACHE_DIR = "/home/sreyas/.cache/rofi-app-icons"
DB_FILE = "/home/sreyas/.cache/rofi-apps.json"

CATS_MAP = {
    "Internet": ["network", "webbrowser", "email", "chat", "instantmessaging", "feed", "filetransfer", "p2p", "remoteaccess", "videoconference"],
    "Development": ["development", "ide", "debugger", "texteditor", "webdevelopment", "science"],
    "Media": ["audiovideo", "audio", "video", "graphics", "2dgraphics", "3dgraphics", "rastergraphics", "vectorgraphics", "photography", "recorder", "music", "player", "audiovideoediting", "viewer"],
    "Games": ["game", "emulator", "simulation", "logicgame", "amusement"],
    "Office": ["office", "calendar", "contactmanagement", "spreadsheet", "wordprocessor", "presentation"],
    "System": ["system", "settings", "desktopsettings", "hardwaresettings", "filemanager", "terminalemulator", "monitor", "packagemanager", "filesystem", "utility", "calculator", "clock", "scanning", "printing", "x-gnome-utilities", "accessories", "archiving"]
}

def update_cache():
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gio

    os.makedirs(CACHE_DIR, exist_ok=True)
    apps = Gio.AppInfo.get_all()
    theme = Gtk.IconTheme.get_default()

    apps_db = []
    seen = set()

    for app in apps:
        if not app.should_show():
            continue
        app_id = app.get_id() or app.get_name()
        if not app_id or app_id in seen:
            continue
        seen.add(app_id)

        name = app.get_display_name() or app.get_name()
        clean_id = app_id.replace('.desktop', '').replace('/', '_')
        icon_path = f"{CACHE_DIR}/{clean_id}.png"

        # Pre-render icon if missing
        if not os.path.exists(icon_path):
            gicon = app.get_icon()
            if gicon:
                info = theme.lookup_by_gicon(gicon, 64, Gtk.IconLookupFlags.FORCE_SIZE)
                if info:
                    try:
                        pix = info.load_icon()
                        pix.savev(icon_path, "png", [], [])
                    except Exception:
                        pass

        raw_cats = (app.get_categories() or "").lower()
        cats = [c.strip() for c in raw_cats.split(";") if c.strip()]
        desktop_file = app.get_filename() or app.get_id() or ""

        app_categories = ["All"]
        for cat_name, keys in CATS_MAP.items():
            if any(k in cats for k in keys):
                app_categories.append(cat_name)

        apps_db.append({
            "name": name,
            "app_id": app_id,
            "icon": icon_path if os.path.exists(icon_path) else (app.get_icon().to_string() if app.get_icon() else "application-x-executable"),
            "desktop": desktop_file,
            "categories": app_categories
        })

    apps_db.sort(key=lambda a: a["name"].lower())
    with open(DB_FILE, "w") as f:
        json.dump(apps_db, f)

    return apps_db

def main():
    # Handle item launch
    if os.environ.get("ROFI_RETV") == "1":
        info = os.environ.get("ROFI_INFO")
        if info:
            try:
                if info.endswith(".desktop"):
                    base = os.path.splitext(os.path.basename(info))[0]
                    subprocess.Popen(["gtk-launch", base])
                else:
                    subprocess.Popen(info, shell=True)
            except Exception as e:
                subprocess.Popen(["notify-send", "Error launching app", str(e)])
        sys.exit(0)

    category = sys.argv[1] if len(sys.argv) > 1 else "All"

    if not os.path.exists(DB_FILE):
        apps = update_cache()
    else:
        try:
            with open(DB_FILE, "r") as f:
                apps = json.load(f)
        except Exception:
            apps = update_cache()

    for app in apps:
        if category == "All" or category in app.get("categories", []):
            sys.stdout.write(f"{app['name']}\0icon\x1f{app['icon']}\x1finfo\x1f{app['desktop']}\n")

if __name__ == "__main__":
    main()
