"""Subtitle tips + optional Windows SAPI voice broadcast."""

from __future__ import annotations

import threading
from typing import Callable

from PyQt6.QtCore import Qt, QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget


class VoiceService(QObject):
    """Speak text via Windows SAPI when enabled."""

    spoke = pyqtSignal(str)

    def __init__(self, get_prefs: Callable[[], dict], parent=None):
        super().__init__(parent)
        self.get_prefs = get_prefs
        self._busy = False

    def enabled(self) -> bool:
        p = self.get_prefs() or {}
        return bool(p.get("voice_enabled", True))

    def tips_enabled(self) -> bool:
        p = self.get_prefs() or {}
        return bool(p.get("tips_enabled", True))

    def announce(self, text: str, *, force_voice: bool | None = None) -> None:
        text = (text or "").strip()
        if not text:
            return
        self.spoke.emit(text)
        use_voice = self.enabled() if force_voice is None else force_voice
        if not use_voice:
            return
        if self._busy:
            return
        self._busy = True

        def _run() -> None:
            try:
                import win32com.client  # type: ignore

                voice = win32com.client.Dispatch("SAPI.SpVoice")
                voice.Speak(text)
            except Exception:
                try:
                    import pyttsx3  # type: ignore

                    eng = pyttsx3.init()
                    eng.say(text)
                    eng.runAndWait()
                except Exception:
                    pass
            finally:
                self._busy = False

        threading.Thread(target=_run, daemon=True).start()


class SubtitleToast(QWidget):
    """Bottom-center floating subtitle for tips."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.lbl = QLabel("")
        self.lbl.setStyleSheet(
            "QLabel {"
            " background: rgba(15,23,42,0.92); color: #e2e8f0;"
            " border: 1px solid #6366f1; border-radius: 12px;"
            " padding: 10px 18px; font-size: 13px; font-weight: 700;"
            "}"
        )
        self.lbl.setWordWrap(True)
        self.lbl.setMaximumWidth(520)
        lay.addWidget(self.lbl)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self.hide()

    def show_tip(self, text: str, ms: int = 3200) -> None:
        text = (text or "").strip()
        if not text:
            return
        self.lbl.setText(text)
        self.adjustSize()
        scr = QGuiApplication.primaryScreen()
        if scr:
            g = scr.availableGeometry()
            self.move(
                g.center().x() - self.width() // 2,
                g.bottom() - self.height() - 80,
            )
        self.show()
        self.raise_()
        self._hide_timer.start(ms)
