"""Global hotkeys for Desktop Toolkit (screenshot + open hub)."""

from __future__ import annotations

import sys
from ctypes import wintypes
from typing import Callable

from PyQt6.QtCore import QAbstractNativeEventFilter, QTimer
from PyQt6.QtWidgets import QApplication

WM_HOTKEY = 0x0312
HOTKEY_HUB = 0xD001
HOTKEY_SHOT_REGION = 0xD002
HOTKEY_SHOT_FULL = 0xD003
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004


def _user32():
    if sys.platform != "win32":
        return None
    import ctypes

    return ctypes.windll.user32


def parse_hotkey_combo(combo: str) -> tuple[int, int] | None:
    if not combo or not str(combo).strip():
        return None
    parts = [p.strip().upper() for p in str(combo).replace(" ", "").split("+") if p.strip()]
    mods = 0
    vk: int | None = None
    for p in parts:
        if p in ("CTRL", "CONTROL"):
            mods |= MOD_CONTROL
        elif p == "ALT":
            mods |= MOD_ALT
        elif p == "SHIFT":
            mods |= MOD_SHIFT
        elif p in ("WIN", "META"):
            mods |= 0x0008
        elif len(p) == 1 and ("A" <= p <= "Z" or "0" <= p <= "9"):
            vk = ord(p)
        elif p.startswith("F") and p[1:].isdigit():
            n = int(p[1:])
            if 1 <= n <= 24:
                vk = 0x70 + n - 1
        elif p in ("PRINTSCREEN", "PRTSC"):
            vk = 0x2C
        elif p == "SPACE":
            vk = 0x20
    if vk is None:
        return None
    return mods, vk


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, handlers: dict[int, Callable[[], None]]) -> None:
        super().__init__()
        self.handlers = handlers

    def nativeEventFilter(self, event_type, message):
        if event_type != b"windows_generic_MSG":
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))
        except Exception:
            return False, 0
        if msg.message == WM_HOTKEY:
            cb = self.handlers.get(int(msg.wParam))
            if cb:
                QTimer.singleShot(0, cb)
                return True, 0
        return False, 0


class ToolkitHotkeys:
    def __init__(
        self,
        *,
        open_hub: Callable[[], None],
        shot_region: Callable[[], None],
        shot_full: Callable[[], None],
        hub_combo: str = "Ctrl+Alt+T",
        region_combo: str = "Ctrl+Alt+A",
        full_combo: str = "Ctrl+Alt+Shift+A",
    ) -> None:
        self.open_hub = open_hub
        self.shot_region = shot_region
        self.shot_full = shot_full
        self.hub_combo = hub_combo
        self.region_combo = region_combo
        self.full_combo = full_combo
        self._ids: list[int] = []
        self._handlers = {
            HOTKEY_HUB: open_hub,
            HOTKEY_SHOT_REGION: shot_region,
            HOTKEY_SHOT_FULL: shot_full,
        }
        self._filter = _Filter(self._handlers)
        app = QApplication.instance()
        if app:
            app.installNativeEventFilter(self._filter)
        self._register_all()

    def _unregister(self) -> None:
        u = _user32()
        if not u:
            return
        for hid in list(self._ids):
            try:
                u.UnregisterHotKey(None, hid)
            except Exception:
                pass
        self._ids.clear()

    def _unregister_shots(self) -> None:
        u = _user32()
        if not u:
            return
        for hid in (HOTKEY_SHOT_REGION, HOTKEY_SHOT_FULL):
            try:
                u.UnregisterHotKey(None, hid)
            except Exception:
                pass
            if hid in self._ids:
                self._ids.remove(hid)

    def _register_all(self) -> None:
        u = _user32()
        if not u:
            return
        self._unregister()
        import ctypes

        try:
            u.RegisterHotKey.argtypes = [
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.c_uint,
            ]
            u.RegisterHotKey.restype = wintypes.BOOL
        except Exception:
            pass
        for hid, combo, default in (
            (HOTKEY_HUB, self.hub_combo, (MOD_CONTROL | MOD_ALT, ord("T"))),
            (HOTKEY_SHOT_REGION, self.region_combo, (MOD_CONTROL | MOD_ALT, ord("A"))),
            (HOTKEY_SHOT_FULL, self.full_combo, (MOD_CONTROL | MOD_ALT | MOD_SHIFT, ord("A"))),
        ):
            parsed = parse_hotkey_combo(combo) or default
            mods, vk = parsed
            if u.RegisterHotKey(None, hid, int(mods), int(vk)):
                self._ids.append(hid)

    def pause_screenshot_hotkeys(self) -> None:
        """Free shot combos so capture widgets can receive those keys."""
        self._unregister_shots()

    def resume_screenshot_hotkeys(self) -> None:
        u = _user32()
        if not u:
            return
        self._unregister_shots()
        import ctypes

        try:
            u.RegisterHotKey.argtypes = [
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.c_uint,
            ]
            u.RegisterHotKey.restype = wintypes.BOOL
        except Exception:
            pass
        for hid, combo, default in (
            (HOTKEY_SHOT_REGION, self.region_combo, (MOD_CONTROL | MOD_ALT, ord("A"))),
            (HOTKEY_SHOT_FULL, self.full_combo, (MOD_CONTROL | MOD_ALT | MOD_SHIFT, ord("A"))),
        ):
            parsed = parse_hotkey_combo(combo) or default
            mods, vk = parsed
            if u.RegisterHotKey(None, hid, int(mods), int(vk)):
                self._ids.append(hid)

    def rebind(self, hub: str | None = None, region: str | None = None, full: str | None = None) -> str:
        if hub is not None:
            self.hub_combo = hub
        if region is not None:
            self.region_combo = region
        if full is not None:
            self.full_combo = full
        self._register_all()
        r_ok = HOTKEY_SHOT_REGION in self._ids
        f_ok = HOTKEY_SHOT_FULL in self._ids
        return (
            f"面板 {self.hub_combo} · 区域 {self.region_combo}:{'OK' if r_ok else '失败'} · "
            f"全屏 {self.full_combo}:{'OK' if f_ok else '失败'}"
        )

    def close(self) -> None:
        self._unregister()
