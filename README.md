# Linux Application Manager

A GUI tool for Ubuntu/Linux to scan, install, and remove applications from APT, Snap, Flatpak, AppImage, and manual installs — with full cleanup and leftover detection.

## Features

- **Scan** — Detect installed apps from APT, Snap, Flatpak, desktop entries, AppImages, `/opt`
- **Install** — Search and install packages from APT, Snap, Flatpak repos, or local `.deb` files
- **Remove** — Completely uninstall with configuration purge, dependency cleanup, and leftover file removal
- **Categorize** — System vs User tagging with search/filter
- **Leftover Scan** — After removal, checks `~/.config`, `~/.cache`, `/etc`, `/var` etc. and offers to delete leftovers

## Quick Install from Git

```bash
git clone <repo-url>
cd linux-app-manager
./install.sh
```

This installs the app to `/opt/linux-app-manager`, creates a desktop entry, and a symlink at `/usr/local/bin/linux-app-manager`.

## Launch

- **Terminal:** `linux-app-manager`
- **App Menu:** Search for "Linux Application Manager"

## Usage

| Button | Action |
|--------|--------|
| Scan APT / Snap / Flatpak / Desktop / AppImage / /opt | Scan a specific source |
| Scan All | Scan every source at once |
| Install Packages | Open the install dialog (search repos or install local `.deb`) |
| Remove Selected | Completely uninstall the selected package with full cleanup |

## Uninstall

```bash
sudo rm -rf /opt/linux-app-manager
sudo rm -f /usr/local/bin/linux-app-manager
rm -f ~/.local/share/applications/linux-app-manager.desktop
rm -f ~/.local/share/icons/hicolor/scalable/apps/linux-app-manager.svg
```

## Requirements

- Python 3.8+
- PySide6 (installed automatically by `install.sh` into a virtual environment)
- `dpkg`, `snap`, `flatpak` (depending on which sources you use)
- `pkexec` (PolicyKit) for GUI privilege elevation (falls back to password dialog)
