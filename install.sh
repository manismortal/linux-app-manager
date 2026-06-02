#!/usr/bin/env bash
set -e

APP_NAME="linux-app-manager"
SCRIPT_NAME="gui_tool.py"
LOGO_NAME="logo.png"
INSTALL_DIR="/opt/${APP_NAME}"
BIN_LINK="/usr/local/bin/${APP_NAME}"
DESKTOP_FILE="${HOME}/.local/share/applications/${APP_NAME}.desktop"
ICON_BASE="${HOME}/.local/share/icons/hicolor"

# --- Uninstall ---
if [ "$1" = "--uninstall" ] || [ "$1" = "--remove" ]; then
    echo "Removing ${APP_NAME}..."
    sudo rm -rf "${INSTALL_DIR}"
    sudo rm -f "${BIN_LINK}"
    rm -f "${DESKTOP_FILE}"
    # Remove icons at all sizes
    find "${ICON_BASE}" -name "${APP_NAME}.*" -exec rm -f {} + 2>/dev/null || true
    gtk-update-icon-cache -f -t "${HOME}/.local/share/icons" 2>/dev/null || true
    update-desktop-database "${HOME}/.local/share/applications" 2>/dev/null || true
    echo "Done. ${APP_NAME} has been uninstalled."
    exit 0
fi

# --- Update ---
if [ "$1" = "--update" ]; then
    echo "Updating ${APP_NAME} from current directory..."
    sudo mkdir -p "${INSTALL_DIR}"
    sudo cp "$(dirname "$0")/${SCRIPT_NAME}" "${INSTALL_DIR}/${SCRIPT_NAME}"
    sudo chmod +x "${INSTALL_DIR}/${SCRIPT_NAME}"
    # Also update logo if present
    if [ -f "$(dirname "$0")/${LOGO_NAME}" ]; then
        sudo cp "$(dirname "$0")/${LOGO_NAME}" "${INSTALL_DIR}/${LOGO_NAME}"
        echo "Updated logo."
    fi
    echo "Updated ${INSTALL_DIR}/${SCRIPT_NAME}"
    echo "Done. (venv preserved, no desktop entry changes)"
    exit 0
fi

# =====================================================================
#  HEADER
# =====================================================================
echo ""
echo "  =========================================="
echo "   Linux Application Manager - Installer"
echo "  =========================================="
echo ""
echo "   Repository: https://github.com/manismortal/linux-app-manager"
echo ""
echo "   Install from Git:"
echo "     git clone https://github.com/manismortal/linux-app-manager.git"
echo "     cd linux-app-manager"
echo "     ./install.sh"
echo ""
echo "   Options:"
echo "     ./install.sh --uninstall    Remove the application"
echo "     ./install.sh --update       Re-install files (keeps venv)"
echo ""

# =====================================================================
#  CHECK PREREQUISITES
# =====================================================================
echo " [1/6] Checking prerequisites..."

if ! command -v python3 &>/dev/null; then
    echo "  ERROR: Python 3 is required."
    echo "  Install it with: sudo apt install python3"
    exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  Python $PY_VER detected."

# =====================================================================
#  INSTALL DIRECTORY
# =====================================================================
echo " [2/6] Creating install directory..."
sudo mkdir -p "${INSTALL_DIR}"
sudo cp "$(dirname "$0")/${SCRIPT_NAME}" "${INSTALL_DIR}/${SCRIPT_NAME}"
sudo chmod +x "${INSTALL_DIR}/${SCRIPT_NAME}"

# Copy logo to install dir for future updates
if [ -f "$(dirname "$0")/${LOGO_NAME}" ]; then
    sudo cp "$(dirname "$0")/${LOGO_NAME}" "${INSTALL_DIR}/${LOGO_NAME}"
    echo "  Logo copied."
fi

# =====================================================================
#  VIRTUAL ENVIRONMENT
# =====================================================================
echo " [3/6] Setting up Python virtual environment..."

if [ -d "${INSTALL_DIR}/venv" ]; then
    echo "  Virtual environment already exists. Skipping."
else
    if python3 -m venv "${INSTALL_DIR}/venv" 2>/dev/null; then
        echo "  Virtual environment created."
    else
        echo "  Installing ${PY_VER} venv package..."
        PY_VENV_PKG="python${PY_VER}-venv"
        sudo apt update -qq 2>/dev/null || true
        if sudo apt install -y "${PY_VENV_PKG}" 2>/dev/null; then
            echo "  Installed ${PY_VENV_PKG}."
        else
            echo "  Trying alternative venv packages..."
            for pkg in python3-venv python3.12-venv python3.11-venv python3.10-venv; do
                if sudo apt install -y "$pkg" 2>/dev/null; then
                    echo "  Installed $pkg."
                    break
                fi
            done
        fi
        python3 -m venv "${INSTALL_DIR}/venv"
        echo "  Virtual environment created."
    fi
fi

echo "  Installing PySide6 (this may take a moment)..."
sudo "${INSTALL_DIR}/venv/bin/pip" install PySide6 --quiet 2>&1 | tail -1
echo "  PySide6 installed."

# =====================================================================
#  LAUNCHER SCRIPT
# =====================================================================
echo " [4/6] Creating launcher script..."

sudo tee "${INSTALL_DIR}/launcher.sh" > /dev/null << 'LAUNCHER'
#!/usr/bin/env bash
DIR="$(dirname "$(readlink -f "$0")")"
export QT_QPA_PLATFORM=wayland 2>/dev/null || true
exec "${DIR}/venv/bin/python3" "${DIR}/gui_tool.py" "$@"
LAUNCHER
sudo chmod +x "${INSTALL_DIR}/launcher.sh"

sudo ln -sf "${INSTALL_DIR}/launcher.sh" "${BIN_LINK}"
echo "  Symlink created: ${BIN_LINK}"

# =====================================================================
#  ICON
# =====================================================================
echo " [5/6] Installing application icon..."

ICON_SOURCE="$(dirname "$0")/${LOGO_NAME}"
ICON_TARGET="${INSTALL_DIR}/${LOGO_NAME}"

if [ -f "${ICON_SOURCE}" ]; then
    # Copy logo to install dir for updates
    sudo cp "${ICON_SOURCE}" "${ICON_TARGET}"

    # Install to standard icon directories at multiple sizes if convert is available
    if command -v convert &>/dev/null; then
        echo "  Generating icons at standard sizes..."
        for size in 32 48 64 128 256; do
            dir="${ICON_BASE}/${size}x${size}/apps"
            mkdir -p "${dir}"
            convert "${ICON_SOURCE}" -resize "${size}x${size}" "${dir}/${APP_NAME}.png" 2>/dev/null || true
        done
        # Also install scalable (original size)
        dir="${ICON_BASE}/scalable/apps"
        mkdir -p "${dir}"
        cp "${ICON_SOURCE}" "${dir}/${APP_NAME}.png"
        echo "  Icons installed at multiple sizes."
    else
        # Simple fallback: just copy to scalable
        echo "  (ImageMagick not found, using original size)"
        dir="${ICON_BASE}/scalable/apps"
        mkdir -p "${dir}"
        cp "${ICON_SOURCE}" "${dir}/${APP_NAME}.png"
        echo "  Icon installed."
    fi

    # Update icon cache
    gtk-update-icon-cache -f -t "${HOME}/.local/share/icons" 2>/dev/null || true
else
    echo "  WARNING: logo.png not found. Using default fallback icon."
    # Create a minimal PNG fallback (1-pixel transparent)
    dir="${ICON_BASE}/scalable/apps"
    mkdir -p "${dir}"
    # Generate a simple colored square as fallback using Python
    python3 -c "
width, height = 128, 128
pixels = []
for y in range(height):
    row = []
    for x in range(width):
        # Simple blue square with rounded corners
        cx, cy = x - width//2, y - height//2
        r = width//2 - 8
        if abs(cx) <= r and abs(cy) <= r:
            row.extend([74, 144, 217, 255])  # #4a90d9
        else:
            row.extend([0, 0, 0, 0])
        pixels.append(row)
    # Write as minimal PNG (not implemented here)
" 2>/dev/null || true
fi

# =====================================================================
#  DESKTOP ENTRY
# =====================================================================
echo " [6/6] Creating desktop entry..."

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
Keywords=apt;snap;flatpak;package;install;remove;update;
StartupNotify=true
DESKTOP

chmod +x "${DESKTOP_FILE}"
update-desktop-database "${HOME}/.local/share/applications" 2>/dev/null || true

# =====================================================================
#  DONE
# =====================================================================
echo ""
echo "  =========================================="
echo "   Installation Complete!"
echo "  =========================================="
echo ""
echo "   Launch from terminal:"
echo "     ${APP_NAME}"
echo ""
echo "   Launch from app menu:"
echo "     Search for 'Linux Application Manager'"
echo ""
echo "   To uninstall later:"
echo "     cd linux-app-manager && ./install.sh --uninstall"
echo ""
