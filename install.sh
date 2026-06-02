#!/usr/bin/env bash
set -e

APP_NAME="linux-app-manager"
SCRIPT_NAME="gui_tool.py"
INSTALL_DIR="/opt/${APP_NAME}"
BIN_LINK="/usr/local/bin/${APP_NAME}"
DESKTOP_FILE="${HOME}/.local/share/applications/${APP_NAME}.desktop"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
ICON_PATH="${ICON_DIR}/${APP_NAME}.svg"

# --- Handle flags ---
if [ "$1" = "--uninstall" ] || [ "$1" = "--remove" ]; then
    echo "Removing ${APP_NAME}..."
    sudo rm -rf "${INSTALL_DIR}"
    sudo rm -f "${BIN_LINK}"
    rm -f "${DESKTOP_FILE}"
    rm -f "${ICON_PATH}"
    gtk-update-icon-cache -f -t "${HOME}/.local/share/icons" 2>/dev/null || true
    echo "Done. ${APP_NAME} has been uninstalled."
    exit 0
fi

if [ "$1" = "--update" ]; then
    echo "Updating ${APP_NAME} from current directory..."
    sudo mkdir -p "${INSTALL_DIR}"
    sudo cp "$(dirname "$0")/${SCRIPT_NAME}" "${INSTALL_DIR}/${SCRIPT_NAME}"
    sudo chmod +x "${INSTALL_DIR}/${SCRIPT_NAME}"
    echo "Updated ${INSTALL_DIR}/${SCRIPT_NAME}"
    echo "Done. (venv preserved, no desktop entry changes)"
    exit 0
fi

echo "========================================"
echo " Linux Application Manager - Installer"
echo "========================================"
echo ""
echo " Install from Git:"
echo "   git clone <repo-url>"
echo "   cd linux-app-manager"
echo "   ./install.sh"
echo ""
echo " Other options:"
echo "   ./install.sh --uninstall    Remove the application"
echo "   ./install.sh --update       Re-install script (keeps venv)"
echo ""

# --- Check Python ---
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3 is required. Install it with: sudo apt install python3"
    exit 1
fi

# Detect Python version for venv package
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_VENV_PKG="python${PY_VER}-venv"

# --- Create install directory ---
echo "[1/5] Creating install directory..."
sudo mkdir -p "${INSTALL_DIR}"
sudo cp "$(dirname "$0")/${SCRIPT_NAME}" "${INSTALL_DIR}/${SCRIPT_NAME}"
sudo chmod +x "${INSTALL_DIR}/${SCRIPT_NAME}"

# --- Set up virtual environment ---
echo "[2/5] Setting up Python virtual environment..."
if ! python3 -m venv "${INSTALL_DIR}/venv" 2>/dev/null; then
    # Fallback: try to install the correct python3-venv package
    echo "     Installing ${PY_VENV_PKG}..."
    sudo apt update -qq 2>/dev/null
    sudo apt install -y "${PY_VENV_PKG}" 2>/dev/null || {
        # Last resort: try common alternatives
        for pkg in python3-venv python3.11-venv python3.10-venv python3.12-venv; do
            sudo apt install -y "$pkg" 2>/dev/null && break
        done
    }
    python3 -m venv "${INSTALL_DIR}/venv"
fi
sudo "${INSTALL_DIR}/venv/bin/pip" install PySide6 --quiet

# --- Create wrapper launcher ---
echo "[3/5] Creating launcher script..."
sudo tee "${INSTALL_DIR}/launcher.sh" > /dev/null << 'LAUNCHER'
#!/usr/bin/env bash
DIR="$(dirname "$(readlink -f "$0")")"
export QT_QPA_PLATFORM=wayland 2>/dev/null || true
exec "${DIR}/venv/bin/python3" "${DIR}/gui_tool.py" "$@"
LAUNCHER
sudo chmod +x "${INSTALL_DIR}/launcher.sh"

# --- Create symlink ---
echo "[4/5] Creating symlink..."
sudo ln -sf "${INSTALL_DIR}/launcher.sh" "${BIN_LINK}"

# --- Create icon (SVG) ---
echo "[5/5] Creating desktop entry and icon..."
mkdir -p "${ICON_DIR}"
cat > "${ICON_PATH}" << 'ICON'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">
  <rect width="128" height="128" rx="16" fill="#4a90d9"/>
  <g transform="translate(64,64)" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">
    <rect x="-36" y="-36" width="72" height="72" rx="8"/>
    <circle cx="0" cy="-18" r="8"/>
    <path d="M-24 30 L-12 6 L12 6 L24 30"/>
    <line x1="-18" y1="-6" x2="18" y2="-6"/>
  </g>
</svg>
ICON

# Update icon cache
gtk-update-icon-cache -f -t "${HOME}/.local/share/icons" 2>/dev/null || true

# --- Create .desktop entry ---
mkdir -p "$(dirname "${DESKTOP_FILE}")"
cat > "${DESKTOP_FILE}" << DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=Linux Application Manager
Comment=Manage installed applications: scan, install, and remove packages
Exec=${INSTALL_DIR}/launcher.sh
Icon=${APP_NAME}
Terminal=false
Categories=System;PackageManager;Utility;
Keywords=apt;snap;flatpak;package;install;remove;
StartupNotify=true
DESKTOP

chmod +x "${DESKTOP_FILE}"

echo ""
echo "========================================"
echo " Installation complete!"
echo "========================================"
echo ""
echo " Launch from terminal:   ${APP_NAME}"
echo " Launch from app menu:   Search for 'Linux Application Manager'"
echo ""
echo " To uninstall, run:"
echo "   sudo rm -rf ${INSTALL_DIR}"
echo "   sudo rm -f ${BIN_LINK}"
echo "   rm -f ${DESKTOP_FILE}"
echo "   rm -f ${ICON_PATH}"
echo ""
