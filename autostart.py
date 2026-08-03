"""Login autostart for Desktop Toolkit (Windows Run key / macOS LaunchAgent)."""

from __future__ import annotations

import sys
from pathlib import Path


APP_NAME = "DesktopToolkit"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    main_py = Path(__file__).resolve().parent / "main.py"
    py = Path(sys.executable).resolve()
    return f'"{py}" "{main_py}"'


def _mac_plist_path() -> Path:
    return Path.home() / "Library/LaunchAgents/com.desktoptoolkit.autostart.plist"


def is_autostart_enabled() -> bool:
    if sys.platform == "darwin":
        return _mac_plist_path().is_file()
    if sys.platform != "win32":
        return False
    try:
        import winreg  # type: ignore

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            try:
                winreg.QueryValueEx(key, APP_NAME)
                return True
            except FileNotFoundError:
                return False
    except Exception:
        return False


def set_autostart(enabled: bool) -> str:
    """Enable/disable run-at-login. Returns status message."""
    if sys.platform == "darwin":
        return _set_autostart_mac(enabled)
    if sys.platform != "win32":
        return "当前系统不支持开机自启设置"
    try:
        import winreg  # type: ignore

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
        ) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _launch_command())
                return "已开启开机自动启动"
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
            return "已关闭开机自动启动"
    except Exception as e:
        return f"设置失败：{e}"


def _set_autostart_mac(enabled: bool) -> str:
    plist = _mac_plist_path()
    try:
        if not enabled:
            if plist.is_file():
                plist.unlink()
            return "已关闭开机自动启动"
        plist.parent.mkdir(parents=True, exist_ok=True)
        if getattr(sys, "frozen", False):
            prog = str(Path(sys.executable).resolve())
            args = f"    <string>{prog}</string>\n"
        else:
            py = str(Path(sys.executable).resolve())
            main_py = str((Path(__file__).resolve().parent / "main.py"))
            args = f"    <string>{py}</string>\n    <string>{main_py}</string>\n"
        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.desktoptoolkit.autostart</string>
  <key>ProgramArguments</key>
  <array>
{args}  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
"""
        plist.write_text(body, encoding="utf-8")
        return "已开启开机自动启动（macOS LaunchAgent）"
    except Exception as e:
        return f"设置失败：{e}"
