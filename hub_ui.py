"""Main window: left nav + right content. Compact home + embedded tools."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QSize, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class _UpdateBridge(QObject):
    """Thread-safe UI callbacks for background update network I/O."""

    check_done = pyqtSignal(object, bool)  # result|Exception, silent_if_latest
    progress = pyqtSignal(str)
    download_done = pyqtSignal(object, object)  # path|None, err|None

from screenshot_ui import HotkeyCaptureEdit
from skin import bundle_root
from theme import apply_app_palette, main_window_qss


def ui_icon(name: str) -> Path | None:
    p = bundle_root() / "assets" / "ui" / f"{name}.png"
    return p if p.is_file() else None


class MainWindow(QMainWindow):
    # 无「效率」——效率入口只在首页
    NAV = [
        ("home", "首页"),
        ("shot", "截图"),
        ("record", "录屏"),
        ("music", "音乐播放器"),
        ("transfer", "传输"),
        ("clean", "清理"),
        ("prefs", "偏好设置"),
    ]

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.setWindowTitle("Desktop Toolkit")
        self.resize(1040, 700)
        self.setMinimumSize(900, 560)
        logo = bundle_root() / "logo.png"
        if logo.exists():
            self.setWindowIcon(QIcon(str(logo)))

        # Background-thread → main-thread (do NOT use QTimer from worker threads)
        self._update_bridge = _UpdateBridge(self)
        self._update_bridge.check_done.connect(self._on_update_check_done)
        self._update_bridge.progress.connect(self._on_update_progress)
        self._update_bridge.download_done.connect(self._on_update_download_done)

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        side = QFrame(objectName="sideNav")
        side.setFixedWidth(158)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(10, 14, 10, 12)
        sl.setSpacing(3)
        brand = QLabel("Desktop\nToolkit")
        brand.setObjectName("brand")
        brand.setWordWrap(True)
        sl.addWidget(brand)
        sl.addSpacing(8)

        self._nav_btns: dict[str, QPushButton] = {}
        for key, label in self.NAV:
            if key == "transfer":
                # 传输：固定二级菜单（局域网 / 跨网）
                self.btn_nav_transfer = QPushButton("传输")
                self.btn_nav_transfer.setObjectName("nav")
                self.btn_nav_transfer.setCheckable(True)
                self.btn_nav_transfer.clicked.connect(lambda: self.goto_transfer("lan"))
                sl.addWidget(self.btn_nav_transfer)
                self._nav_btns["transfer"] = self.btn_nav_transfer

                self.transfer_sub = QWidget()
                tsl = QVBoxLayout(self.transfer_sub)
                tsl.setContentsMargins(12, 0, 0, 4)
                tsl.setSpacing(2)
                self.btn_nav_lan = QPushButton("局域网共享")
                self.btn_nav_lan.setObjectName("nav")
                self.btn_nav_lan.setCheckable(True)
                self.btn_nav_lan.clicked.connect(lambda: self.goto_transfer("lan"))
                self.btn_nav_p2p = QPushButton("跨网传文件")
                self.btn_nav_p2p.setObjectName("nav")
                self.btn_nav_p2p.setCheckable(True)
                self.btn_nav_p2p.clicked.connect(lambda: self.goto_transfer("p2p"))
                tsl.addWidget(self.btn_nav_lan)
                tsl.addWidget(self.btn_nav_p2p)
                sl.addWidget(self.transfer_sub)
            else:
                b = QPushButton(label)
                b.setObjectName("nav")
                b.setCheckable(True)
                b.clicked.connect(lambda _=False, k=key: self.goto(k))
                sl.addWidget(b)
                self._nav_btns[key] = b
        sl.addStretch(1)
        try:
            from updater import APP_VERSION as _VER

            ver = QLabel(f"v{_VER}")
        except Exception:
            ver = QLabel("v1.1.6")
        ver.setObjectName("muted")
        sl.addWidget(ver)
        outer.addWidget(side)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)

        self._page_keys: list[str] = []
        for key, builder in (
            ("home", self._page_home),
            ("shot", self._page_shot),
            ("record", self._page_record),
            ("music", self._page_music),
            ("transfer", self._page_transfer),
            ("clean", self._page_clean),
            ("prefs", self._page_prefs),
        ):
            self._page_keys.append(key)
            self.stack.addWidget(builder())

        self.apply_theme()
        self.goto("home")

    def theme_mode(self) -> str:
        return str((self.host.store.state.get("prefs") or {}).get("theme") or "dark")

    def apply_theme(self) -> None:
        mode = self.theme_mode()
        apply_app_palette(self.host.app, mode)
        self.setStyleSheet(main_window_qss(mode))
        if hasattr(self, "lbl_theme_tip"):
            self.lbl_theme_tip.setText(f"当前：{'白天模式' if mode == 'light' else '暗黑模式'}")

    def goto(self, key: str) -> None:
        for k, b in self._nav_btns.items():
            b.setChecked(k == key)
        # clear transfer sub highlights unless navigating transfer
        if key != "transfer":
            if hasattr(self, "btn_nav_lan"):
                self.btn_nav_lan.setChecked(False)
            if hasattr(self, "btn_nav_p2p"):
                self.btn_nav_p2p.setChecked(False)
        if key in self._page_keys:
            self.stack.setCurrentIndex(self._page_keys.index(key))

    def _home_card(self, icon: str, text: str, cb) -> QPushButton:
        b = QPushButton(f"  {text}")
        b.setObjectName("homeCard")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        b.setMinimumHeight(58)
        b.setMaximumHeight(68)
        p = ui_icon(icon)
        if p:
            b.setIcon(QIcon(str(p)))
            b.setIconSize(QSize(24, 24))
        b.clicked.connect(cb)
        return b

    def _row(self, title: str, cards: list[tuple[str, str, object]]) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 2, 0, 4)
        lay.setSpacing(4)
        sec = QLabel(title)
        sec.setObjectName("section")
        lay.addWidget(sec)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for i, (icon, text, cb) in enumerate(cards):
            grid.addWidget(self._home_card(icon, text, cb), 0, i)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        lay.addLayout(grid)
        return wrap

    def _page_home(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(2)
        lay.addWidget(QLabel("首页", objectName="pageTitle"))
        tip = QLabel("第一排效率 · 第二排截图录屏 · 第三排传输 · 第四排媒体清理")
        tip.setObjectName("muted")
        lay.addWidget(tip)
        lay.addWidget(
            self._row(
                "效率办公",
                [
                    ("todos", "待办事项", self.host.show_todos),
                    ("notes", "便签", self.host.show_notes),
                    ("pomodoro", "番茄钟", self.host.show_pomodoro),
                    ("alarm", "闹钟", self.host.show_alarm_board),
                ],
            )
        )
        # 只有区域截图 + 录屏；截图点进设置页
        lay.addWidget(
            self._row(
                "截图与录屏",
                [
                    ("shot", "截图", lambda: self.goto("shot")),
                    ("recorder", "录屏", lambda: self.goto("record")),
                ],
            )
        )
        lay.addWidget(
            self._row(
                "文件传输",
                [
                    ("lan", "局域网共享", lambda: self.goto_transfer("lan")),
                    ("p2p", "跨网传文件", lambda: self.goto_transfer("p2p")),
                ],
            )
        )
        lay.addWidget(
            self._row(
                "媒体与系统",
                [
                    ("music", "音乐播放器", lambda: self.goto("music")),
                    ("clean", "清理电脑", lambda: self.goto("clean")),
                ],
            )
        )
        lay.addStretch(1)
        scroll.setWidget(body)
        return scroll

    def goto_transfer(self, which: str) -> None:
        self.goto("transfer")
        if which == "lan":
            if hasattr(self, "_show_transfer_lan"):
                self._show_transfer_lan()
            elif hasattr(self, "btn_sub_lan"):
                self.btn_sub_lan.click()
        elif which == "p2p":
            if hasattr(self, "_show_transfer_p2p"):
                self._show_transfer_p2p()
            elif hasattr(self, "btn_sub_p2p"):
                self.btn_sub_p2p.click()
        if hasattr(self, "btn_nav_lan"):
            self.btn_nav_lan.setChecked(which == "lan")
            self.btn_nav_p2p.setChecked(which == "p2p")
            self.btn_nav_transfer.setChecked(True)

    def _page_shot(self) -> QWidget:
        """Actions on top, settings below (no separate left column)."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(12)
        lay.addWidget(QLabel("截图", objectName="pageTitle"))

        act = QHBoxLayout()
        b1 = QPushButton("区域截图")
        b1.setObjectName("primary")
        b1.clicked.connect(self.host.start_screenshot_region)
        b2 = QPushButton("全屏截图")
        b2.setObjectName("soft")
        b2.clicked.connect(self.host.start_screenshot_full)
        act.addWidget(b1)
        act.addWidget(b2)
        act.addStretch(1)
        lay.addLayout(act)
        tip_shot = QLabel("标注时：鼠标滚轮可快速调节画笔粗细（1–40），工具条 +/- 同样可用。")
        tip_shot.setObjectName("muted")
        tip_shot.setWordWrap(True)
        lay.addWidget(tip_shot)

        panel = QFrame(objectName="panel")
        rl = QVBoxLayout(panel)
        rl.setContentsMargins(14, 12, 14, 12)
        rl.setSpacing(8)
        rl.addWidget(QLabel("截图设置", objectName="pageTitle"))
        cfg = self.host.store.state.setdefault("screenshot", {})
        rl.addWidget(QLabel("保存目录"))
        row = QHBoxLayout()
        self.txt_shot_dir = QLineEdit(
            str(cfg.get("save_dir") or str(Path.home() / "Pictures" / "ToolkitShots"))
        )
        bd = QPushButton("浏览", objectName="soft")
        bd.clicked.connect(self._pick_shot_dir)
        row.addWidget(self.txt_shot_dir, 1)
        row.addWidget(bd)
        rl.addLayout(row)
        rl.addWidget(QLabel("区域快捷键（点框后按键；录入时会暂时释放系统快捷键）"))
        self.hk_region = HotkeyCaptureEdit()
        self.hk_region.setText(str(cfg.get("hotkey_region") or "Ctrl+Alt+A"))
        self.hk_region.hotkey_captured.connect(lambda _c: self._save_shot_settings(True))
        self.hk_region.capture_started.connect(self._pause_shot_hotkeys)
        self.hk_region.capture_ended.connect(self._on_hk_capture_ended)
        rl.addWidget(self.hk_region)
        rl.addWidget(QLabel("全屏快捷键"))
        self.hk_full = HotkeyCaptureEdit()
        self.hk_full.setText(str(cfg.get("hotkey_full") or "Ctrl+Alt+Shift+A"))
        self.hk_full.hotkey_captured.connect(lambda _c: self._save_shot_settings(True))
        self.hk_full.capture_started.connect(self._pause_shot_hotkeys)
        self.hk_full.capture_ended.connect(self._on_hk_capture_ended)
        rl.addWidget(self.hk_full)
        self._hk_applying = False
        g = cfg.setdefault("gdrive", {})
        self.chk_gdrive = QCheckBox("启用 Google 云端上传")
        self.chk_gdrive.setChecked(bool(g.get("enabled")))
        rl.addWidget(self.chk_gdrive)
        self.chk_auto_up = QCheckBox("完成后自动上传并复制链接")
        self.chk_auto_up.setChecked(bool(cfg.get("auto_upload")))
        rl.addWidget(self.chk_auto_up)
        rl.addWidget(QLabel("OAuth JSON"))
        rowg = QHBoxLayout()
        self.txt_secrets = QLineEdit(str(g.get("client_secrets_path") or ""))
        bg = QPushButton("选择…", objectName="soft")
        bg.clicked.connect(self._pick_secrets)
        rowg.addWidget(self.txt_secrets, 1)
        rowg.addWidget(bg)
        rl.addLayout(rowg)
        self.txt_folder = QLineEdit(str(g.get("folder_id") or ""))
        self.txt_folder.setPlaceholderText("文件夹 ID 可选")
        rl.addWidget(self.txt_folder)
        save = QPushButton("保存设置", objectName="primary")
        save.clicked.connect(lambda: self._save_shot_settings(True))
        rl.addWidget(save)
        self.lbl_shot_status = QLabel("")
        self.lbl_shot_status.setObjectName("muted")
        rl.addWidget(self.lbl_shot_status)
        rl.addStretch(1)
        lay.addWidget(panel, 1)
        return page

    def _pick_shot_dir(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "截图目录", self.txt_shot_dir.text())
        if p:
            self.txt_shot_dir.setText(p)

    def _pick_secrets(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "OAuth JSON", "", "JSON (*.json)")
        if p:
            self.txt_secrets.setText(p)

    def _pause_shot_hotkeys(self) -> None:
        try:
            self.host.pause_screenshot_hotkeys()
        except Exception:
            pass

    def _on_hk_capture_ended(self) -> None:
        if getattr(self, "_hk_applying", False):
            return
        try:
            self.host.resume_screenshot_hotkeys()
        except Exception:
            pass

    def _save_shot_settings(self, apply_hk: bool = False) -> None:
        self._hk_applying = True
        try:
            cfg = self.host.store.state.setdefault("screenshot", {})
            g = cfg.setdefault("gdrive", {})
            cfg["save_dir"] = self.txt_shot_dir.text().strip()
            cfg["hotkey_region"] = self.hk_region.text().strip() or "Ctrl+Alt+A"
            cfg["hotkey_full"] = self.hk_full.text().strip() or "Ctrl+Alt+Shift+A"
            cfg["auto_upload"] = self.chk_auto_up.isChecked()
            g["enabled"] = self.chk_gdrive.isChecked()
            g["client_secrets_path"] = self.txt_secrets.text().strip()
            g["folder_id"] = self.txt_folder.text().strip()
            self.host.store.save_state()
            msg = "已保存"
            if apply_hk:
                try:
                    msg = self.host.rebind_screenshot_hotkeys() or msg
                except Exception as e:
                    msg = str(e)
            self.lbl_shot_status.setText(msg)
        finally:
            self._hk_applying = False

    def _page_record(self) -> QWidget:
        from recorder_ui import FloatingRecorderBoard

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.addWidget(QLabel("录屏", objectName="pageTitle"))
        if not getattr(self.host, "_embed_recorder", None):
            self.host._embed_recorder = FloatingRecorderBoard(
                self.host._cb(), self.host.store.state, embedded=True
            )
        lay.addWidget(self.host._embed_recorder, 1)
        return body

    def _page_music(self) -> QWidget:
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.addWidget(QLabel("音乐播放器", objectName="pageTitle"))
        # Embed music dashboard
        try:
            from lyrics_engine import LyricsEngine
            from lyrics_ui import FloatingLyricsWindow, LyricsDashboard

            if not getattr(self.host, "_embed_music", None):
                if self.host.lyrics_engine is None:
                    self.host.lyrics_engine = LyricsEngine(self.host)
                if self.host.lyrics_hud is None:
                    self.host.lyrics_hud = FloatingLyricsWindow()
                    self.host.lyrics_hud.hide()
                self.host._embed_music = LyricsDashboard(
                    self.host.lyrics_engine,
                    self.host.lyrics_hud,
                    state=self.host.store.state,
                    callbacks=self.host._cb(),
                    embedded=True,
                )
            lay.addWidget(self.host._embed_music, 1)
        except Exception as e:
            tip = QLabel(f"音乐模块加载失败：{e}")
            tip.setObjectName("muted")
            tip.setWordWrap(True)
            lay.addWidget(tip)
            b = QPushButton("重试打开", objectName="primary")
            b.clicked.connect(self.host.show_music_player)
            lay.addWidget(b)
            lay.addStretch(1)
        return body

    def _page_transfer(self) -> QWidget:
        """No middle sub-nav — left nav switches pages directly."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        self.transfer_stack = QStackedWidget()
        # page 0 lan
        lan_w = QWidget()
        lan_l = QVBoxLayout(lan_w)
        lan_l.setContentsMargins(0, 0, 0, 0)
        from lan_ui import FloatingLanBoard

        if not getattr(self.host, "_embed_lan", None):
            self.host._embed_lan = FloatingLanBoard(self.host, embedded=True)
        lan_l.addWidget(self.host._embed_lan)
        self.transfer_stack.addWidget(lan_w)

        # page 1 p2p
        p2p_w = QWidget()
        p2p_l = QVBoxLayout(p2p_w)
        p2p_l.setContentsMargins(0, 0, 0, 0)
        from p2p_ui import FloatingP2PBoard

        if not getattr(self.host, "_embed_p2p", None):
            self.host._embed_p2p = FloatingP2PBoard(
                self.host._cb(), self.host.store.state, embedded=True
            )
        p2p_l.addWidget(self.host._embed_p2p)
        self.transfer_stack.addWidget(p2p_w)

        outer.addWidget(self.transfer_stack, 1)

        # Compat stubs so goto_transfer can still "click" switches
        self.btn_sub_lan = QPushButton()
        self.btn_sub_lan.hide()
        self.btn_sub_p2p = QPushButton()
        self.btn_sub_p2p.hide()

        def show_lan() -> None:
            self.transfer_stack.setCurrentIndex(0)
            try:
                self.host._embed_lan._refresh_status()
            except Exception:
                pass

        def show_p2p() -> None:
            self.transfer_stack.setCurrentIndex(1)

        self.btn_sub_lan.clicked.connect(show_lan)
        self.btn_sub_p2p.clicked.connect(show_p2p)
        self._show_transfer_lan = show_lan
        self._show_transfer_p2p = show_p2p
        show_lan()
        return page

    def _page_clean(self) -> QWidget:
        from cleaner_ui import FloatingCleanerBoard

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.addWidget(QLabel("清理", objectName="pageTitle"))
        if not getattr(self.host, "_embed_cleaner", None):
            self.host._embed_cleaner = FloatingCleanerBoard(
                self.host.store.state,
                on_start_clean=self.host.start_deep_clean,
                on_save_state=self.host.store.save_state,
                embedded=True,
            )
        lay.addWidget(self.host._embed_cleaner, 1)
        return body

    def _page_prefs(self) -> QWidget:
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)
        lay.addWidget(QLabel("偏好设置", objectName="pageTitle"))

        lay.addWidget(QLabel("软件外观", objectName="section"))
        row = QHBoxLayout()
        b1 = QPushButton("暗黑模式", objectName="soft")
        b2 = QPushButton("白天模式", objectName="soft")
        b1.clicked.connect(lambda: self._set_theme("dark"))
        b2.clicked.connect(lambda: self._set_theme("light"))
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch(1)
        lay.addLayout(row)
        self.lbl_theme_tip = QLabel("")
        self.lbl_theme_tip.setObjectName("muted")
        lay.addWidget(self.lbl_theme_tip)

        lay.addWidget(QLabel("启动与桌面助手", objectName="section"))
        prefs = self.host.store.state.setdefault("prefs", {})
        self.chk_autostart = QCheckBox("开机自动启动")
        try:
            from autostart import is_autostart_enabled

            self.chk_autostart.setChecked(bool(is_autostart_enabled() or prefs.get("autostart")))
        except Exception:
            self.chk_autostart.setChecked(bool(prefs.get("autostart")))
        self.chk_autostart.toggled.connect(self._on_autostart)
        lay.addWidget(self.chk_autostart)

        self.chk_float_logo = QCheckBox("显示右下角悬浮机器人助手")
        self.chk_float_logo.setChecked(bool(prefs.get("float_assistant", True)))
        self.chk_float_logo.toggled.connect(self._on_float_logo)
        lay.addWidget(self.chk_float_logo)
        tip_a = QLabel("鼠标悬停在机器人上可快速打开：待办 / 便签 / 番茄钟 / 闹钟 / 截图 / 录屏 / 音乐 / 清理")
        tip_a.setObjectName("muted")
        tip_a.setWordWrap(True)
        lay.addWidget(tip_a)

        lay.addWidget(QLabel("提示与语音播报", objectName="section"))
        self.chk_tips = QCheckBox("显示字幕提示")
        self.chk_tips.setChecked(bool(prefs.get("tips_enabled", True)))
        self.chk_tips.toggled.connect(self._on_tips)
        lay.addWidget(self.chk_tips)
        self.chk_voice = QCheckBox("开启语音播报（Windows 系统语音）")
        self.chk_voice.setChecked(bool(prefs.get("voice_enabled", True)))
        self.chk_voice.toggled.connect(self._on_voice)
        lay.addWidget(self.chk_voice)
        test_row = QHBoxLayout()
        btn_test = QPushButton("试听语音", objectName="soft")
        btn_test.clicked.connect(self._test_voice)
        test_row.addWidget(btn_test)
        test_row.addStretch(1)
        lay.addLayout(test_row)
        self.lbl_prefs_status = QLabel("")
        self.lbl_prefs_status.setObjectName("muted")
        lay.addWidget(self.lbl_prefs_status)

        lay.addWidget(QLabel("快捷键", objectName="section"))
        lay.addWidget(
            QLabel("Ctrl+Alt+T 主窗口 · 截图快捷键在「截图」页设置", objectName="muted")
        )

        lay.addWidget(QLabel("版本与更新", objectName="section"))
        try:
            from updater import APP_VERSION

            ver_txt = APP_VERSION
        except Exception:
            ver_txt = "1.1.6"
        self.lbl_app_version = QLabel(f"当前版本：v{ver_txt}")
        self.lbl_app_version.setObjectName("muted")
        lay.addWidget(self.lbl_app_version)
        self.chk_auto_update = QCheckBox("启动时自动检查更新（有新版本会提示）")
        self.chk_auto_update.setChecked(bool(self._prefs().get("auto_check_update", True)))
        self.chk_auto_update.toggled.connect(self._on_auto_update)
        lay.addWidget(self.chk_auto_update)
        upd_row = QHBoxLayout()
        self.btn_check_update = QPushButton("检查更新", objectName="primary")
        self.btn_check_update.clicked.connect(self._check_update)
        self.btn_open_release = QPushButton("打开下载页", objectName="soft")
        self.btn_open_release.setEnabled(False)
        self.btn_open_release.clicked.connect(self._open_release_page)
        upd_row.addWidget(self.btn_check_update)
        upd_row.addWidget(self.btn_open_release)
        upd_row.addStretch(1)
        lay.addLayout(upd_row)
        self.lbl_update_status = QLabel("点「检查更新」：有新版本会询问是否下载安装，不会直接打开网页。")
        self.lbl_update_status.setObjectName("muted")
        self.lbl_update_status.setWordWrap(True)
        lay.addWidget(self.lbl_update_status)
        self._last_release_url = ""
        self._last_download_url = ""
        self._last_asset_name = ""
        self._update_checking = False

        lay.addStretch(1)
        self.apply_theme()
        return body

    def _prefs(self) -> dict:
        return self.host.store.state.setdefault("prefs", {})

    def _set_theme(self, mode: str) -> None:
        self._prefs()["theme"] = mode
        self.host.store.save_state()
        self.apply_theme()

    def _on_autostart(self, on: bool) -> None:
        self._prefs()["autostart"] = bool(on)
        self.host.store.save_state()
        try:
            from autostart import set_autostart

            msg = set_autostart(bool(on))
        except Exception as e:
            msg = str(e)
        self.lbl_prefs_status.setText(msg)
        try:
            self.host.announce(msg)
        except Exception:
            pass

    def _on_float_logo(self, on: bool) -> None:
        self._prefs()["float_assistant"] = bool(on)
        self.host.store.save_state()
        try:
            self.host.set_float_assistant_visible(bool(on))
        except Exception:
            pass
        self.lbl_prefs_status.setText("已显示悬浮助手" if on else "已隐藏悬浮助手")

    def _on_tips(self, on: bool) -> None:
        self._prefs()["tips_enabled"] = bool(on)
        self.host.store.save_state()

    def _on_voice(self, on: bool) -> None:
        self._prefs()["voice_enabled"] = bool(on)
        self.host.store.save_state()
        self.lbl_prefs_status.setText("语音播报已开启" if on else "语音播报已关闭")

    def _test_voice(self) -> None:
        try:
            self.host.announce("桌面工具箱语音播报正常", force_voice=True)
            self.lbl_prefs_status.setText("正在试听…")
        except Exception as e:
            self.lbl_prefs_status.setText(f"试听失败：{e}")

    def _on_auto_update(self, on: bool) -> None:
        self._prefs()["auto_check_update"] = bool(on)
        self.host.store.save_state()

    def _check_update(self, *, silent_if_latest: bool = False) -> None:
        """Query GitHub; if newer, offer download+install (not just open browser)."""
        if self._update_checking:
            return
        self._update_checking = True
        if hasattr(self, "btn_check_update"):
            self.btn_check_update.setEnabled(False)
        if hasattr(self, "lbl_update_status"):
            self.lbl_update_status.setText("正在检查更新…")
        import threading

        def work() -> None:
            try:
                from updater import check_for_update

                # Slightly longer timeout; always return via signal (never hang UI)
                result = check_for_update(timeout=12.0)
            except Exception as e:
                result = e
            self._update_bridge.check_done.emit(result, bool(silent_if_latest))

        threading.Thread(target=work, daemon=True).start()

    def _on_update_check_done(self, result, silent_if_latest: bool) -> None:
        self._update_checking = False
        if hasattr(self, "btn_check_update"):
            self.btn_check_update.setEnabled(True)
        if isinstance(result, Exception):
            if hasattr(self, "lbl_update_status"):
                self.lbl_update_status.setText(f"检查失败：{result}")
            if not silent_if_latest:
                QMessageBox.warning(self, "检查更新", f"检查失败：{result}")
            return
        self._apply_update_result(result, silent_if_latest=silent_if_latest)

    def _on_update_progress(self, text: str) -> None:
        if hasattr(self, "lbl_update_status"):
            self.lbl_update_status.setText(text)

    def _on_update_download_done(self, path, err) -> None:
        if hasattr(self, "btn_check_update"):
            self.btn_check_update.setEnabled(True)
        if err is not None:
            if hasattr(self, "lbl_update_status"):
                self.lbl_update_status.setText(f"下载/安装失败：{err}")
            QMessageBox.warning(self, "更新失败", str(err))
            return
        if hasattr(self, "lbl_update_status"):
            self.lbl_update_status.setText(f"已启动安装程序：{path}")
        box = QMessageBox(self)
        box.setWindowTitle("更新")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("安装程序已启动。\n为避免文件占用，建议现在退出 Desktop Toolkit。")
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.button(QMessageBox.StandardButton.Yes).setText("退出软件")
        box.button(QMessageBox.StandardButton.No).setText("稍后退出")
        if box.exec() == QMessageBox.StandardButton.Yes:
            try:
                self.host.quit()
            except Exception:
                pass

    def _apply_update_result(self, result, *, silent_if_latest: bool = False) -> None:
        self.lbl_update_status.setText(result.message)
        self._last_release_url = result.release_url or ""
        self._last_download_url = result.download_url or ""
        self._last_asset_name = getattr(result, "asset_name", "") or ""
        self.btn_open_release.setEnabled(bool(self._last_release_url or self._last_download_url))
        if not result.ok:
            if not silent_if_latest:
                QMessageBox.warning(self, "检查更新", result.message)
            return
        if not result.has_update:
            if not silent_if_latest:
                QMessageBox.information(self, "检查更新", result.message)
                try:
                    self.host.announce(result.message)
                except Exception:
                    pass
            else:
                self.lbl_update_status.setText(result.message)
            return

        # Has update → ask download & install
        box = QMessageBox(self)
        box.setWindowTitle("发现新版本")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(result.message)
        has_setup = bool(self._last_download_url) and (
            self._last_download_url.lower().endswith(".exe")
            or "setup" in (self._last_asset_name or "").lower()
        )
        if has_setup:
            box.setInformativeText(
                "是否下载安装包并启动安装程序？\n"
                "（安装前建议先保存工作；安装程序启动后可关闭本软件）"
            )
        else:
            box.setInformativeText(
                "未找到 setup 安装包链接，可打开下载页手动下载。"
            )
        btn_install = box.addButton("下载并安装", QMessageBox.ButtonRole.AcceptRole)
        btn_page = box.addButton("打开下载页", QMessageBox.ButtonRole.ActionRole)
        box.addButton("稍后", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_install if has_setup else btn_page)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_install and has_setup:
            self._download_and_install()
        elif clicked is btn_page:
            self._open_release_page()

    def _download_and_install(self) -> None:
        url = self._last_download_url
        if not url:
            self.lbl_update_status.setText("没有下载地址")
            return
        self.btn_check_update.setEnabled(False)
        self.lbl_update_status.setText("正在下载安装包…")
        import threading

        name = self._last_asset_name or None

        def work() -> None:
            err = None
            path = None
            try:
                from updater import download_update, launch_installer

                def prog(done: int, total: int) -> None:
                    pct = int(done * 100 / total) if total else 0
                    self._update_bridge.progress.emit(f"正在下载安装包… {pct}%")

                path = download_update(url, filename=name, progress_cb=prog)
                launch_installer(path)
            except Exception as e:
                err = e
            self._update_bridge.download_done.emit(path, err)

        threading.Thread(target=work, daemon=True).start()

    def _open_release_page(self) -> None:
        url = self._last_release_url
        if not url:
            try:
                from updater import RELEASES_PAGE

                url = RELEASES_PAGE
            except Exception:
                return
        QDesktopServices.openUrl(QUrl(url))
