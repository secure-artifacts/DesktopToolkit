"""Force a Qt widget to stay above other windows (Windows HWND_TOPMOST)."""

from __future__ import annotations

import sys
from typing import Any


def force_topmost(widget: Any) -> bool:
    """Re-assert topmost z-order. Safe no-op if widget is missing/hidden."""
    if widget is None:
        return False
    try:
        if hasattr(widget, "isVisible") and not widget.isVisible():
            return False
    except Exception:
        return False

    try:
        widget.raise_()
    except Exception:
        pass

    if sys.platform != "win32":
        return True

    try:
        import win32con  # type: ignore
        import win32gui  # type: ignore

        hwnd = int(widget.winId())
        if not hwnd:
            return False
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_TOPMOST,
            0,
            0,
            0,
            0,
            win32con.SWP_NOMOVE
            | win32con.SWP_NOSIZE
            | win32con.SWP_SHOWWINDOW
            | win32con.SWP_NOACTIVATE,
        )
        return True
    except Exception:
        return False
