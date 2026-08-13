# Linux notes (Desktop Toolkit)

Desktop Toolkit is primarily developed for Windows. Linux support is **best-effort** (X11 preferred).

## What works
- Main UI (PyQt6)
- Region / fullscreen screenshot (`mss` + Qt fallback)
- Annotation tools (pen, text, emoji, etc.)
- Screen recording via ffmpeg/cv2 when packages are available
- Autostart via `~/.config/autostart/desktop-toolkit.desktop`

## Limitations
- **Global hotkeys**: Windows `RegisterHotKey` is not used on Linux. Use the tray/hub buttons, or bind a desktop shortcut that runs the app with a CLI flag if you add one.
- **Wayland**: Full-screen capture and overlay may require XWayland or portal-based capture; pure Wayland is incomplete.
- **System audio loopback**: Depends on PulseAudio/PipeWire setup; mic-only is more reliable.
- **Windows-only cleaners** (prefetch, Delivery Optimization) are skipped.

## Run from source
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Dependencies (distro packages)
```bash
# Debian/Ubuntu examples
sudo apt install python3-pyqt6 ffmpeg libportaudio2
# optional color emoji
sudo apt install fonts-noto-color-emoji
```
