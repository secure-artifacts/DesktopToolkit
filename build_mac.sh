#!/usr/bin/env bash
# Build Desktop Toolkit .app on macOS (Apple Silicon or Intel).
# Usage (from repo root on a Mac):
#   chmod +x build_mac.sh
#   ./build_mac.sh
set -euo pipefail
cd "$(dirname "$0")"
VER="$(tr -d ' \r\n' < VERSION)"
echo "Building DesktopToolkit ${VER} for macOS…"

python3 -m pip install -r requirements.txt pyinstaller --quiet
rm -rf build/mac dist/DesktopToolkit.app dist/DesktopToolkit

python3 -m PyInstaller --noconfirm --windowed --name DesktopToolkit \
  --icon logo.ico \
  --add-data "assets:assets" \
  --add-data "logo.png:." \
  --add-data "logo.ico:." \
  --add-data "cloudflare:cloudflare" \
  --add-data "VERSION:." \
  --hidden-import mss \
  --hidden-import imageio_ffmpeg \
  --hidden-import cv2 \
  --hidden-import numpy \
  --hidden-import sounddevice \
  --hidden-import websockets \
  --hidden-import PyQt6.QtMultimedia \
  --hidden-import weather \
  --hidden-import notebook_store \
  --hidden-import notebook_ui \
  --hidden-import notebook_sync \
  --hidden-import file_organizer \
  --hidden-import file_organizer_ui \
  --hidden-import remote_ui \
  --hidden-import rustdesk_bridge \
  --hidden-import win_topmost \
  --hidden-import p2p_transfer \
  --hidden-import p2p_ui \
  --hidden-import PIL \
  --exclude-module torch \
  --exclude-module tensorflow \
  --exclude-module matplotlib \
  main.py

OUT="dist/release"
mkdir -p "$OUT"
APP="dist/DesktopToolkit.app"
if [[ ! -d "$APP" ]]; then
  if [[ -d dist/DesktopToolkit/DesktopToolkit.app ]]; then
    APP="dist/DesktopToolkit/DesktopToolkit.app"
  fi
fi
ZIP="$OUT/DesktopToolkit-${VER}-macos.zip"
rm -f "$ZIP"
if [[ -d "$APP" ]]; then
  ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
  shasum -a 256 "$ZIP" | awk '{print $1}' > "${ZIP}.sha256"
  echo "OK: $ZIP"
else
  echo "WARNING: .app not found — check dist/ and run PyInstaller output"
  ls -la dist || true
  exit 1
fi

echo ""
echo "macOS notes:"
echo "  - Screen/window capture permissions: System Settings → Privacy → Screen Recording"
echo "  - Window-specific capture is limited vs Windows; full/region screen works via mss"
echo "  - Autostart: in-app toggle writes LaunchAgent com.desktoptoolkit.autostart"
echo "  - Cleaner scopes are macOS-specific (Safari/Chrome caches, trash, logs, Xcode)"
echo "  - Remote control: install RustDesk from https://rustdesk.com if not already present"
