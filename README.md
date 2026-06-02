# Linux Application Manager

[![GitHub](https://img.shields.io/badge/GitHub-manismortal/linux--app--manager-blue?logo=github)](https://github.com/manismortal/linux-app-manager)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Platform](https://img.shields.io/badge/platform-Linux-lightgrey)

A GUI tool for Ubuntu/Debian Linux to **scan**, **install**, and **remove** applications from APT, Snap, Flatpak, AppImage, and manual installs — with full cleanup, leftover detection, and update status tracking.

---

## Features

| Feature | Description |
|---------|-------------|
| ** Scan** | Detect installed apps from APT, Snap, Flatpak, desktop entries, AppImages, `/opt` |
| ** Install** | Search & install from APT, Snap, Flatpak repos, or local `.deb` files |
| ** Remove** | Complete uninstall with config purge, orphan cleanup, and leftover file removal |
| ** Check Updates** | See which packages have updates available (status column per package) |
| ** Update All** | One-click `apt update + upgrade + autoremove` |
| ** Categories** | System vs User tagging with search & filter |
| ** Export List** | Save scanned package list to a `.txt` or `.csv` file |
| ** Multi-select** | Select multiple packages for bulk removal |
| ** Leftover Scan** | Checks `~/.config`, `~/.cache`, `/etc`, `/var` after removal and offers cleanup |

---

## Quick Install from GitHub

```bash
git clone https://github.com/manismortal/linux-app-manager.git
cd linux-app-manager
./install.sh
```

The installer will:
- Copy the app to `/opt/linux-app-manager/`
- Create a Python virtual environment with PySide6
- Create a `.desktop` entry in your app menu
- Create a symlink at `/usr/local/bin/linux-app-manager`

## Launch

- **Terminal:** `linux-app-manager`
- **App Menu:** Search for **"Linux Application Manager"**

Or run from source:
```bash
cd linux-app-manager
python3 -m venv venv
source venv/bin/activate
pip install PySide6
python3 gui_tool.py
```

---

## Usage Guide

### Scanning

Click any scan button to detect installed applications from that source. Use **Scan All** to scan everything at once.

| Button | Scans | Category |
|--------|-------|----------|
| APT | `dpkg --get-selections` | System |
| Snap | `snap list` | User |
| Flatpak | `flatpak list` | User |
| Desktop | `.desktop` files in `/usr/share/applications`, `~/.local/share/applications` | System/User |
| AppImage | `.AppImage` files in `~/Applications`, `/opt`, etc. | User |
| /opt | Directories under `/opt` | System |
| **Scan All** | All of the above | Mixed |

### Installing

1. Click **Install** (green button)
2. Choose tab: **Search Repositories** or **Install Local Package**
3. For repositories: select source (APT/Snap/Flatpak), search, pick a result, click **Install Selected Package**
4. For `.deb` files: click Browse, select file, click **Install .deb Package**
5. A live terminal output window shows real-time installation progress

### Removing

1. Select one or more packages in the list (Ctrl+Click for multi-select)
2. Click **Remove Selected** (red button)
3. Confirm removal
4. If leftovers are detected, choose whether to delete them

### Checking Updates

1. Click **Check Updates** (light blue button)
2. The **Status** column updates to show "Up-to-date" or "Update available"
3. Click **Update All** (orange button) to upgrade all APT packages

### Filtering

- Use the **Category** dropdown to show System / User / All
- Type in the **Search** box to filter by package name
- The count label shows `filtered/total`

---

## Screenshots

*(Add screenshots here by placing image files in a `screenshots/` directory)*

---

## Uninstall

```bash
# Using the install script:
./install.sh --uninstall

# Or manually:
sudo rm -rf /opt/linux-app-manager
sudo rm -f /usr/local/bin/linux-app-manager
rm -f ~/.local/share/applications/linux-app-manager.desktop
rm -f ~/.local/share/icons/hicolor/scalable/apps/linux-app-manager.svg
```

---

## Requirements

| Dependency | Note |
|------------|------|
| Python 3.8+ | Installed automatically via `install.sh` |
| PySide6 | Installed into a virtual environment by `install.sh` |
| `dpkg` | Required for APT scanning (all Debian/Ubuntu systems) |
| `snap` | Optional — for Snap scanning |
| `flatpak` | Optional — for Flatpak scanning |
| `pkexec` | Optional — for GUI privilege elevation (falls back to password dialog) |

---

## Repository

**GitHub:** https://github.com/manismortal/linux-app-manager

**Clone URL:**
```bash
git clone https://github.com/manismortal/linux-app-manager.git
```

**Report issues:** https://github.com/manismortal/linux-app-manager/issues

---

## Author

**Tanvir Mahdi**  
tanirmahdi1998@gmail.com

---

## License

This project is open source. See the [LICENSE](LICENSE) file for details.
