"""Desktop Toolkit — efficiency tools only (no desktop pet)."""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from cleaner import CleanReport, DEFAULT_SCOPES, run_deep_clean_async
from float_assistant import FloatingAssistant
from hotkeys import ToolkitHotkeys
from hub_ui import MainWindow
from lan_share import LanShareClient, LanShareServer
from skin import bundle_root
from storage import JsonStore
from theme import apply_app_palette
from voice import SubtitleToast, VoiceService


def _install_exception_hooks() -> Path:
    log_path = Path(__file__).resolve().parent / "DesktopToolkit-error.log"
    if getattr(sys, "frozen", False):
        log_path = Path(sys.executable).resolve().parent / "DesktopToolkit-error.log"

    def _write(msg: str) -> None:
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(msg if msg.endswith("\n") else msg + "\n")
        except OSError:
            pass

    def _hook(et, ev, tb) -> None:
        _write(
            f"\n[{datetime.now().isoformat(timespec='seconds')}]\n"
            + "".join(traceback.format_exception(et, ev, tb))
        )

    sys.excepthook = _hook
    return log_path


class ToolkitApp(QObject):
    clean_finished = pyqtSignal(object)

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.app = app
        self.store = JsonStore()
        self.lan_server = LanShareServer()
        self.lan_client = LanShareClient()
        self._cleaning = False
        self.main_win: MainWindow | None = None
        self.recorder_board = None
        self.p2p_board = None
        self.lan_board = None
        self.clean_board = None
        self.alarm_board = None
        self.todo_board = None
        self.notes_ctl = None
        self.pomo_board = None
        self.lyrics_dashboard = None
        self.lyrics_engine = None
        self.lyrics_hud = None

        mode = str((self.store.state.get("prefs") or {}).get("theme") or "dark")
        apply_app_palette(app, mode)

        self.voice = VoiceService(lambda: self.store.state.get("prefs") or {})
        self.subtitle = SubtitleToast()
        self.voice.spoke.connect(self._on_voice_spoke)
        self.assistant: FloatingAssistant | None = None

        self.tray = self._make_tray()
        sc = self.store.state.get("screenshot") or {}
        self.hotkeys = ToolkitHotkeys(
            open_hub=self.show_hub,
            shot_region=self.start_screenshot_region,
            shot_full=self.start_screenshot_full,
            hub_combo="Ctrl+Alt+T",
            region_combo=str(sc.get("hotkey_region") or "Ctrl+Alt+A"),
            full_combo=str(sc.get("hotkey_full") or "Ctrl+Alt+Shift+A"),
        )
        self.clean_finished.connect(self._on_clean_finished)
        self.alarm_timer = QTimer(self)
        self.alarm_timer.timeout.connect(self._alarm_tick)
        self.alarm_timer.start(1000)
        self.store.append_log("login", "Desktop Toolkit started")
        QTimer.singleShot(200, self.show_hub)
        QTimer.singleShot(400, self._init_assistant)
        QTimer.singleShot(800, lambda: self.announce("桌面工具箱已就绪"))
        # Quiet update check shortly after startup (prefs.auto_check_update)
        QTimer.singleShot(3500, self._startup_check_update)

    def _cb(self) -> SimpleNamespace:
        return SimpleNamespace(
            save_state=self.store.save_state,
            rebind_screenshot_hotkeys=self.rebind_screenshot_hotkeys,
            pause_screenshot_hotkeys=self.pause_screenshot_hotkeys,
            resume_screenshot_hotkeys=self.resume_screenshot_hotkeys,
        )

    def _prefs(self) -> dict:
        return self.store.state.setdefault("prefs", {})

    def announce(self, text: str, *, force_voice: bool | None = None) -> None:
        """Show subtitle tip and optional voice broadcast."""
        prefs = self._prefs()
        if prefs.get("tips_enabled", True) or force_voice:
            try:
                if prefs.get("tips_enabled", True):
                    self.subtitle.show_tip(text)
            except Exception:
                pass
        try:
            self.voice.announce(text, force_voice=force_voice)
        except Exception:
            pass

    def _on_voice_spoke(self, text: str) -> None:
        # Subtitle is shown in announce(); avoid extra tray spam here
        return

    def _init_assistant(self) -> None:
        if not self._prefs().get("float_assistant", True):
            return
        try:
            self.assistant = FloatingAssistant(self)
        except Exception:
            traceback.print_exc()

    def set_float_assistant_visible(self, visible: bool) -> None:
        if visible:
            if self.assistant is None:
                self.assistant = FloatingAssistant(self)
            else:
                self.assistant.show()
                self.assistant.raise_()
        elif self.assistant is not None:
            self.assistant.menu.hide()
            self.assistant.hide()

    def _make_tray(self) -> QSystemTrayIcon:
        logo = bundle_root() / "logo.png"
        icon = QIcon(str(logo)) if logo.exists() else QIcon()
        tray = QSystemTrayIcon(icon, self.app)
        menu = QMenu()
        for text, fn in (
            ("打开主界面 (Ctrl+Alt+T)", self.show_hub),
            ("区域截图", self.start_screenshot_region),
            ("录屏", self.show_recorder_board),
            ("跨网传文件", self.show_p2p_board),
            ("局域网共享", self.show_lan_share),
            ("待办", self.show_todos),
            ("便签", self.show_notes),
            ("清理电脑", self.start_deep_clean),
            ("音乐", self.show_music_player),
        ):
            a = QAction(text, menu)
            a.triggered.connect(fn)
            menu.addAction(a)
        menu.addSeparator()
        q = QAction("退出", menu)
        q.triggered.connect(self.quit)
        menu.addAction(q)
        tray.setContextMenu(menu)
        tray.setToolTip("Desktop Toolkit")
        tray.activated.connect(self._tray_activated)
        tray.show()
        return tray

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_hub()

    def show_hub(self) -> None:
        if self.main_win is None:
            self.main_win = MainWindow(self)
        self.main_win.show()
        self.main_win.raise_()
        self.main_win.activateWindow()

    def start_screenshot_region(self) -> None:
        from screenshot_app import start_screenshot

        start_screenshot(mode="region", state=self.store.state)

    def start_screenshot_full(self) -> None:
        from screenshot_app import start_screenshot

        start_screenshot(mode="full", state=self.store.state)

    def rebind_screenshot_hotkeys(self) -> str:
        sc = self.store.state.setdefault("screenshot", {})
        msg = self.hotkeys.rebind(
            region=str(sc.get("hotkey_region") or "Ctrl+Alt+A"),
            full=str(sc.get("hotkey_full") or "Ctrl+Alt+Shift+A"),
        )
        self.store.save_state()
        return msg

    def _startup_check_update(self) -> None:
        prefs = self.store.state.get("prefs") or {}
        if not prefs.get("auto_check_update", True):
            return
        try:
            if self.main_win is not None and hasattr(self.main_win, "_check_update"):
                self.main_win._check_update(silent_if_latest=True)
        except Exception:
            pass

    def pause_screenshot_hotkeys(self) -> None:
        try:
            self.hotkeys.pause_screenshot_hotkeys()
        except Exception:
            pass

    def resume_screenshot_hotkeys(self) -> None:
        try:
            self.hotkeys.resume_screenshot_hotkeys()
        except Exception:
            pass

    def show_recorder_board(self) -> None:
        from recorder_ui import FloatingRecorderBoard

        if self.recorder_board is None:
            self.recorder_board = FloatingRecorderBoard(self._cb(), self.store.state)
        self.recorder_board.show()
        self.recorder_board.raise_()

    def show_p2p_board(self) -> None:
        from p2p_ui import FloatingP2PBoard

        if self.p2p_board is None:
            self.p2p_board = FloatingP2PBoard(self._cb(), self.store.state)
        self.p2p_board.show()
        self.p2p_board.raise_()

    def show_lan_share(self) -> None:
        from lan_ui import FloatingLanBoard

        if self.lan_board is None:
            self.lan_board = FloatingLanBoard(self)
        self.lan_board.show()
        self.lan_board.raise_()
        self.lan_board._refresh_status()

    def start_deep_clean(self, scopes: list[str] | None = None) -> None:
        if self._cleaning:
            self.announce("正在清理中，请稍候")
            self.tray.showMessage("清理", "正在清理中…", QSystemTrayIcon.MessageIcon.Warning, 3000)
            return
        self._cleaning = True
        use = list(scopes) if scopes else list(
            (self.store.state.get("cleaner") or {}).get("scopes") or DEFAULT_SCOPES
        )
        self.announce("开始清理电脑")
        self.tray.showMessage("清理", "开始清理电脑…", QSystemTrayIcon.MessageIcon.Information, 3000)

        def done(report: CleanReport) -> None:
            self.clean_finished.emit(report)

        run_deep_clean_async(done, scopes=use)

    def show_cleaner_board(self) -> None:
        """Open main window clean page (embedded settings)."""
        self.show_hub()
        if self.main_win:
            self.main_win.goto("clean")

    def _on_clean_finished(self, report: object) -> None:
        self._cleaning = False
        if isinstance(report, CleanReport):
            summary = report.summary()
            self.announce(f"清理完成。{summary}")
            self.tray.showMessage("清理完成", summary, QSystemTrayIcon.MessageIcon.Information, 6000)
            self.store.append_log("clean_done", summary)
            try:
                emb = getattr(self, "_embed_cleaner", None)
                if emb:
                    emb.on_clean_result(summary)
            except Exception:
                pass

    def show_music_player(self) -> None:
        try:
            from lyrics_engine import LyricsEngine
            from lyrics_ui import FloatingLyricsWindow, LyricsDashboard

            if self.lyrics_dashboard is None:
                self.lyrics_engine = LyricsEngine(self)
                self.lyrics_hud = FloatingLyricsWindow()
                self.lyrics_dashboard = LyricsDashboard(
                    self.lyrics_engine,
                    self.lyrics_hud,
                    state=self.store.state,
                    callbacks=self._cb(),
                )
            self.lyrics_dashboard.show()
            self.lyrics_dashboard.raise_()
        except Exception as e:
            traceback.print_exc()
            QMessageBox.warning(None, "音乐", f"打开失败：{e}")

    def show_pomodoro(self) -> None:
        from simple_boards import PomodoroBoard, _clamp_widget_to_screens

        if self.pomo_board is None:
            self.pomo_board = PomodoroBoard(self.store.state, self.store.save_state)
            ui = (self.store.state.get("pomodoro_ui") or {})
            if ui.get("x") is not None and ui.get("y") is not None:
                try:
                    self.pomo_board.move(int(ui["x"]), int(ui["y"]))
                except (TypeError, ValueError):
                    pass
        _clamp_widget_to_screens(self.pomo_board, min_w=300, min_h=300)
        self.pomo_board.show()
        self.pomo_board.raise_()

    def show_todos(self) -> None:
        from simple_boards import TodosController

        if self.todo_board is None:
            # todo_board holds TodosController (multi-window)
            self.todo_board = TodosController(self.store.state, self.store.save_state)
        self.todo_board.show_all()

    def show_notes(self) -> None:
        from simple_boards import NotesController

        if self.notes_ctl is None:
            self.notes_ctl = NotesController(self.store.state, self.store.save_state)
        self.notes_ctl.show_all()

    def add_note(self) -> None:
        from simple_boards import NotesController

        if self.notes_ctl is None:
            self.notes_ctl = NotesController(self.store.state, self.store.save_state)
        self.notes_ctl.add_note()

    def show_alarm_board(self) -> None:
        from alarm_ui import FloatingAlarmBoard

        if self.alarm_board is None:
            self.alarm_board = FloatingAlarmBoard(self._cb(), self.store.state)
        self.alarm_board.show()
        self.alarm_board.raise_()

    def _alarm_tick(self) -> None:
        import datetime as dt

        now = dt.datetime.now()
        t_cfg = self.store.state.setdefault("timer", {})
        if t_cfg.get("active") and int(t_cfg.get("remaining") or 0) > 0 and not t_cfg.get("paused"):
            t_cfg["remaining"] = int(t_cfg.get("remaining") or 0) - 1
            if t_cfg["remaining"] <= 0:
                t_cfg["active"] = False
                try:
                    from alarm_sounds import play_ringtone

                    play_ringtone(str(t_cfg.get("ringtone") or "beep"))
                except Exception:
                    pass
                name = t_cfg.get("name") or "时间到"
                self.announce(f"倒计时结束。{name}")
                self.tray.showMessage(
                    "倒计时",
                    name,
                    QSystemTrayIcon.MessageIcon.Information,
                    6000,
                )
                self.store.save_state()

        cur = now.strftime("%H:%M")
        day = now.strftime("%Y-%m-%d")
        for alarm in self.store.state.get("alarms") or []:
            if not alarm.get("enabled"):
                continue
            if alarm.get("time") == cur and alarm.get("last_triggered_date") != day:
                alarm["last_triggered_date"] = day
                if alarm.get("repeat") == "once":
                    alarm["enabled"] = False
                try:
                    from alarm_sounds import play_ringtone

                    play_ringtone(str(alarm.get("ringtone") or "beep"))
                except Exception:
                    pass
                aname = str(alarm.get("name") or "闹钟")
                self.announce(f"闹钟提醒。{aname}")
                self.tray.showMessage(
                    "闹钟",
                    aname,
                    QSystemTrayIcon.MessageIcon.Information,
                    8000,
                )
                self.store.save_state()

    def quit(self) -> None:
        try:
            self.hotkeys.close()
        except Exception:
            pass
        try:
            self.lan_server.stop()
        except Exception:
            pass
        try:
            if self.assistant:
                self.assistant.menu.hide()
                self.assistant.hide()
        except Exception:
            pass
        self.store.save_state()
        self.app.quit()


def main() -> int:
    _install_exception_hooks()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setApplicationName("Desktop Toolkit")
    logo = bundle_root() / "logo.png"
    if logo.exists():
        app.setWindowIcon(QIcon(str(logo)))
    try:
        ToolkitApp(app)
    except Exception as exc:
        traceback.print_exc()
        QMessageBox.critical(None, "Desktop Toolkit", f"启动失败：{exc}")
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
