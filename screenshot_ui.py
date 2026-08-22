"""Screenshot settings board + launch entry (Flameshot-style + Google Drive)."""

from __future__ import annotations

import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QObject
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class _Bridge(QObject):
    status = pyqtSignal(str)
    folder_id = pyqtSignal(str)


def key_event_to_hotkey(event: QKeyEvent) -> str | None:
    """Convert a QKeyEvent into 'Ctrl+Alt+A' style string. None if incomplete."""
    key = event.key()
    # Ignore pure modifiers
    if key in (
        Qt.Key.Key_Control,
        Qt.Key.Key_Shift,
        Qt.Key.Key_Alt,
        Qt.Key.Key_Meta,
        Qt.Key.Key_AltGr,
        Qt.Key.Key_unknown,
    ):
        return None

    mods = event.modifiers()
    parts: list[str] = []
    if mods & Qt.KeyboardModifier.ControlModifier:
        parts.append("Ctrl")
    if mods & Qt.KeyboardModifier.AltModifier:
        parts.append("Alt")
    if mods & Qt.KeyboardModifier.ShiftModifier:
        parts.append("Shift")
    if mods & Qt.KeyboardModifier.MetaModifier:
        parts.append("Win")

    # Main key name
    name = ""
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        name = f"F{key - Qt.Key.Key_F1 + 1}"
    elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        name = chr(ord("A") + (key - Qt.Key.Key_A))
    elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        name = chr(ord("0") + (key - Qt.Key.Key_0))
    elif key == Qt.Key.Key_Space:
        name = "Space"
    elif key == Qt.Key.Key_Print:
        name = "PrintScreen"
    elif key == Qt.Key.Key_Insert:
        name = "Insert"
    elif key == Qt.Key.Key_Delete:
        name = "Delete"
    elif key == Qt.Key.Key_Home:
        name = "Home"
    elif key == Qt.Key.Key_End:
        name = "End"
    elif key == Qt.Key.Key_PageUp:
        name = "PageUp"
    elif key == Qt.Key.Key_PageDown:
        name = "PageDown"
    elif key == Qt.Key.Key_Left:
        name = "Left"
    elif key == Qt.Key.Key_Right:
        name = "Right"
    elif key == Qt.Key.Key_Up:
        name = "Up"
    elif key == Qt.Key.Key_Down:
        name = "Down"
    elif key == Qt.Key.Key_Tab:
        name = "Tab"
    elif key == Qt.Key.Key_Backspace:
        name = "Backspace"
    else:
        # Fallback: text if printable single char
        t = (event.text() or "").strip()
        if len(t) == 1 and t.isprintable():
            name = t.upper()
        else:
            return None

    # Require at least one modifier for global hotkeys (safer)
    if not parts:
        return None

    parts.append(name)
    return "+".join(parts)


class HotkeyCaptureEdit(QLineEdit):
    """Click / focus, then press a combo — auto-fills e.g. Ctrl+Alt+A."""

    hotkey_captured = pyqtSignal(str)
    capture_started = pyqtSignal()
    capture_ended = pyqtSignal()

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText(placeholder or "点击后按下快捷键…")
        self.setToolTip("点击此框，然后直接按下想要的组合键（如 Ctrl+Alt+A）")
        self._listening = False
        self._saved = ""
        self._grabbed = False

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self._saved = self.text()
        self._listening = True
        self.setStyleSheet(
            "QLineEdit { background:#0c4a6e; color:#e0f2fe; border:2px solid #38bdf8; "
            "border-radius:10px; padding:8px 10px; min-height:28px; font-weight:700; }"
        )
        self.setPlaceholderText("请按下快捷键…（Esc 取消）")
        self.capture_started.emit()
        try:
            self.grabKeyboard()
            self._grabbed = True
        except Exception:
            self._grabbed = False

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._listening = False
        self.setStyleSheet("")
        self.setPlaceholderText("点击后按下快捷键…")
        if self._grabbed:
            try:
                self.releaseKeyboard()
            except Exception:
                pass
            self._grabbed = False
        self.capture_ended.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.setText(self._saved)
            self.clearFocus()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and not (
            event.modifiers()
            & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.AltModifier
                | Qt.KeyboardModifier.ShiftModifier
                | Qt.KeyboardModifier.MetaModifier
            )
        ):
            # Clear hotkey
            self.setText("")
            self.hotkey_captured.emit("")
            event.accept()
            return

        combo = key_event_to_hotkey(event)
        if combo:
            self.setText(combo)
            self.hotkey_captured.emit(combo)
            self.clearFocus()
            event.accept()
            return
        # Still holding only modifiers — wait for main key
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        super().mousePressEvent(event)
        self.setFocus(Qt.FocusReason.MouseFocusReason)


class FloatingScreenshotBoard(QWidget):
    def __init__(self, callbacks=None, state=None, parent=None):
        super().__init__(parent)
        self.callbacks = callbacks
        self.state = state if isinstance(state, dict) else {}
        self.dragging = False
        self.drag_position = QPoint()
        self._bridge = _Bridge(self)
        self._bridge.status.connect(self._on_status)
        self._bridge.folder_id.connect(self._on_folder_id)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(460, 560)
        self._init_ui()
        self._load()

    def _cfg(self) -> dict:
        return self.state.setdefault("screenshot", {})

    def _gdrive(self) -> dict:
        return self._cfg().setdefault("gdrive", {})

    def _init_ui(self) -> None:
        self.setStyleSheet(
            """
            QFrame#box {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #0f172a, stop:1 #020617);
                border: 1px solid rgba(56,189,248,0.4); border-radius: 16px;
            }
            QLabel { color: #e2e8f0; font-size: 12px; font-weight: 600; }
            QLabel#title { color: #38bdf8; font-size: 15px; font-weight: 800; }
            QLabel#muted { color: #94a3b8; font-size: 11px; font-weight: 500; }
            QLineEdit {
                background: #020617; color: #f8fafc; border: 1px solid #334155;
                border-radius: 10px; padding: 8px 10px; min-height: 28px;
            }
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #0ea5e9, stop:1 #0284c7);
                border: none; color: white; font-weight: 800; padding: 9px 12px; border-radius: 10px;
            }
            QPushButton:hover { background: #38bdf8; color: #0c4a6e; }
            QPushButton#soft { background: #1e293b; border: 1px solid #334155; color: #e2e8f0; }
            QPushButton#danger { background: #b91c1c; }
            QCheckBox { color: #cbd5e1; font-size: 12px; spacing: 6px; }
            """
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        box = QFrame(objectName="box")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(QLabel("📷 截图（类 Flameshot）", objectName="title"), 1)
        close_btn = QPushButton("×", objectName="soft")
        close_btn.setFixedSize(28, 28)
        close_btn.clicked.connect(self.hide)
        header.addWidget(close_btn)
        lay.addLayout(header)

        tip = QLabel(
            "区域截图：坐标十字瞄准 → 拖选范围 → 图标工具连续标注 →\n"
            "复制 / 保存 / 钉桌面 / 上传云端 完成后自动退出（链接自动进剪贴板）。"
        )
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        act = QHBoxLayout()
        self.btn_region = QPushButton("区域截图")
        self.btn_region.clicked.connect(lambda: self._launch("region"))
        self.btn_full = QPushButton("全屏截图", objectName="soft")
        self.btn_full.clicked.connect(lambda: self._launch("full"))
        act.addWidget(self.btn_region)
        act.addWidget(self.btn_full)
        lay.addLayout(act)

        lay.addWidget(QLabel("全局快捷键（点击输入框 → 直接按键录入）"))
        hk_row1 = QHBoxLayout()
        hk_row1.addWidget(QLabel("区域"))
        self.txt_hk_region = HotkeyCaptureEdit("点击后按下区域截图快捷键…")
        self.txt_hk_region.hotkey_captured.connect(lambda _c: self._on_hotkey_captured("region"))
        self.txt_hk_region.capture_started.connect(self._pause_global_hotkeys)
        self.txt_hk_region.capture_ended.connect(self._on_capture_ended)
        hk_row1.addWidget(self.txt_hk_region, 1)
        lay.addLayout(hk_row1)
        hk_row2 = QHBoxLayout()
        hk_row2.addWidget(QLabel("全屏"))
        self.txt_hk_full = HotkeyCaptureEdit("点击后按下全屏截图快捷键…")
        self.txt_hk_full.hotkey_captured.connect(lambda _c: self._on_hotkey_captured("full"))
        self.txt_hk_full.capture_started.connect(self._pause_global_hotkeys)
        self.txt_hk_full.capture_ended.connect(self._on_capture_ended)
        hk_row2.addWidget(self.txt_hk_full, 1)
        lay.addLayout(hk_row2)
        btn_hk = QPushButton("应用快捷键", objectName="soft")
        btn_hk.clicked.connect(self._apply_hotkeys)
        lay.addWidget(btn_hk)
        self.lbl_hk = QLabel(
            "用法：点输入框变蓝后，按下 Ctrl+Alt+字母 等组合，自动填入并生效。Delete 清空。\n"
            "录入时会暂时释放系统快捷键，避免被旧组合抢走按键。"
        )
        self.lbl_hk.setObjectName("muted")
        self.lbl_hk.setWordWrap(True)
        lay.addWidget(self.lbl_hk)
        self._hk_applying = False

        lay.addWidget(QLabel("本地保存目录"))
        path_row = QHBoxLayout()
        self.txt_dir = QLineEdit()
        self.txt_dir.setPlaceholderText(str(Path.home() / "Pictures" / "ParrotScreenshots"))
        btn_dir = QPushButton("浏览", objectName="soft")
        btn_dir.clicked.connect(self._pick_dir)
        path_row.addWidget(self.txt_dir, 1)
        path_row.addWidget(btn_dir)
        lay.addLayout(path_row)

        self.chk_auto_upload = QCheckBox("完成后自动上传到 Google 云端（需先连接）")
        lay.addWidget(self.chk_auto_upload)

        # Google Drive section
        gbox = QFrame()
        gbox.setStyleSheet(
            "QFrame { background: #0b1220; border: 1px solid #1e3a5f; border-radius: 10px; }"
        )
        gl = QVBoxLayout(gbox)
        gl.setContentsMargins(10, 8, 10, 8)
        gl.setSpacing(6)
        gl.addWidget(QLabel("Google 云端硬盘"))
        gtip = QLabel(
            "1. 打开 Google Cloud Console 创建「桌面应用」OAuth 客户端\n"
            "2. 下载 JSON，点下方「选择密钥文件」\n"
            "3. 连接账号 → 填写文件夹 ID（Drive 网址里 folders/ 后面那段）\n"
            "   或不填 ID，将自动创建/使用「文件夹名」"
        )
        gtip.setObjectName("muted")
        gtip.setWordWrap(True)
        gl.addWidget(gtip)

        self.chk_gdrive = QCheckBox("启用上传到 Google 云端")
        gl.addWidget(self.chk_gdrive)

        gl.addWidget(QLabel("OAuth 客户端 JSON"))
        sec_row = QHBoxLayout()
        self.txt_secrets = QLineEdit()
        self.txt_secrets.setPlaceholderText("client_secret_xxx.json")
        btn_sec = QPushButton("选择…", objectName="soft")
        btn_sec.clicked.connect(self._pick_secrets)
        sec_row.addWidget(self.txt_secrets, 1)
        sec_row.addWidget(btn_sec)
        gl.addLayout(sec_row)

        self.chk_full_scope = QCheckBox("使用完整 Drive 权限（可上传到任意已有文件夹）")
        gl.addWidget(self.chk_full_scope)

        gl.addWidget(QLabel("目标文件夹 ID（可选）"))
        self.txt_folder_id = QLineEdit()
        self.txt_folder_id.setPlaceholderText("从 drive.google.com/drive/folders/XXXX 复制 XXXX")
        gl.addWidget(self.txt_folder_id)

        gl.addWidget(QLabel("自动创建文件夹名（无 ID 时）"))
        self.txt_folder_name = QLineEdit()
        self.txt_folder_name.setPlaceholderText("ToolkitShots")
        gl.addWidget(self.txt_folder_name)

        grow = QHBoxLayout()
        self.btn_connect = QPushButton("连接 Google")
        self.btn_connect.clicked.connect(self._connect_gdrive)
        self.btn_disconnect = QPushButton("断开", objectName="danger")
        self.btn_disconnect.clicked.connect(self._disconnect_gdrive)
        self.btn_test = QPushButton("测试上传", objectName="soft")
        self.btn_test.clicked.connect(self._test_upload)
        grow.addWidget(self.btn_connect)
        grow.addWidget(self.btn_disconnect)
        grow.addWidget(self.btn_test)
        gl.addLayout(grow)

        self.lbl_gstatus = QLabel("未连接")
        self.lbl_gstatus.setObjectName("muted")
        self.lbl_gstatus.setWordWrap(True)
        gl.addWidget(self.lbl_gstatus)
        lay.addWidget(gbox)

        self.lbl_status = QLabel("就绪。点「区域截图」开始，编辑后可保存/上传。")
        self.lbl_status.setObjectName("muted")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        save_row = QHBoxLayout()
        btn_save = QPushButton("保存设置")
        btn_save.clicked.connect(self._save)
        save_row.addWidget(btn_save)
        lay.addLayout(save_row)

        root.addWidget(box)

    def _load(self) -> None:
        cfg = self._cfg()
        gd = self._gdrive()
        self.txt_dir.setText(str(cfg.get("save_dir") or Path.home() / "Pictures" / "ParrotScreenshots"))
        self.chk_auto_upload.setChecked(bool(cfg.get("auto_upload")))
        self.txt_hk_region.setText(str(cfg.get("hotkey_region") or "Ctrl+Alt+A"))
        self.txt_hk_full.setText(str(cfg.get("hotkey_full") or "Ctrl+Alt+Shift+A"))
        self.chk_gdrive.setChecked(bool(gd.get("enabled", False)))
        self.txt_secrets.setText(str(gd.get("client_secrets_path") or ""))
        self.txt_folder_id.setText(str(gd.get("folder_id") or ""))
        self.txt_folder_name.setText(str(gd.get("folder_name") or "ToolkitShots"))
        self.chk_full_scope.setChecked(bool(gd.get("use_full_scope")))
        self._refresh_gstatus()
        self._update_tip_hotkeys()

    def _update_tip_hotkeys(self) -> None:
        r = self.txt_hk_region.text().strip() or "Ctrl+Alt+A"
        f = self.txt_hk_full.text().strip() or "Ctrl+Alt+Shift+A"
        self.lbl_hk.setText(f"当前：区域 {r} · 全屏 {f}（冲突可改组合后点「应用快捷键」）")

    def _pause_global_hotkeys(self) -> None:
        try:
            if self.callbacks and hasattr(self.callbacks, "pause_screenshot_hotkeys"):
                self.callbacks.pause_screenshot_hotkeys()
        except Exception:
            pass

    def _on_capture_ended(self) -> None:
        if getattr(self, "_hk_applying", False):
            return
        try:
            if self.callbacks and hasattr(self.callbacks, "resume_screenshot_hotkeys"):
                self.callbacks.resume_screenshot_hotkeys()
        except Exception:
            pass

    def _on_hotkey_captured(self, which: str) -> None:
        """Auto-save and rebind as soon as user presses a combo."""
        self._apply_hotkeys()
        r = self.txt_hk_region.text().strip() or "（未设）"
        f = self.txt_hk_full.text().strip() or "（未设）"
        self.lbl_status.setText(f"已录入{'区域' if which == 'region' else '全屏'}快捷键 · 区域 {r} · 全屏 {f}")

    def _apply_hotkeys(self) -> None:
        self._hk_applying = True
        try:
            self._save()
            try:
                if self.callbacks and hasattr(self.callbacks, "rebind_screenshot_hotkeys"):
                    msg = self.callbacks.rebind_screenshot_hotkeys()
                    self.lbl_status.setText(str(msg or "快捷键已更新"))
                    self.lbl_hk.setText(str(msg or self.lbl_hk.text()))
                else:
                    self.lbl_status.setText("已保存快捷键（重启应用后生效）")
            except Exception as e:
                self.lbl_status.setText(f"应用快捷键失败：{e}")
            self._update_tip_hotkeys()
        finally:
            self._hk_applying = False

    def _save(self) -> None:
        cfg = self._cfg()
        gd = self._gdrive()
        cfg["save_dir"] = self.txt_dir.text().strip()
        cfg["auto_upload"] = self.chk_auto_upload.isChecked()
        cfg["hotkey_region"] = self.txt_hk_region.text().strip() or "Ctrl+Alt+A"
        cfg["hotkey_full"] = self.txt_hk_full.text().strip() or "Ctrl+Alt+Shift+A"
        gd["enabled"] = self.chk_gdrive.isChecked()
        gd["client_secrets_path"] = self.txt_secrets.text().strip()
        gd["folder_id"] = self.txt_folder_id.text().strip()
        gd["folder_name"] = self.txt_folder_name.text().strip() or "ToolkitShots"
        gd["use_full_scope"] = self.chk_full_scope.isChecked()
        try:
            if self.callbacks and hasattr(self.callbacks, "save_state"):
                self.callbacks.save_state()
        except Exception:
            pass
        self.lbl_status.setText("设置已保存")
        self._refresh_gstatus()
        self._update_tip_hotkeys()

    def _refresh_gstatus(self) -> None:
        try:
            from gdrive_client import GoogleDriveClient

            gd = dict(self._gdrive())
            gd["client_secrets_path"] = self.txt_secrets.text().strip()
            client = GoogleDriveClient(gd)
            if client.is_connected():
                fid = self.txt_folder_id.text().strip() or gd.get("folder_id") or "（自动文件夹）"
                self.lbl_gstatus.setText(f"✅ 已连接 Google · 目标文件夹: {fid}")
            else:
                self.lbl_gstatus.setText("未连接 — 选择密钥 JSON 后点「连接 Google」")
        except Exception as e:
            self.lbl_gstatus.setText(f"状态: {e}")

    def _on_status(self, msg: str) -> None:
        self.lbl_status.setText(msg)
        self.lbl_gstatus.setText(msg)
        self._refresh_gstatus()

    def _on_folder_id(self, fid: str) -> None:
        if fid:
            self.txt_folder_id.setText(fid)
            self._gdrive()["folder_id"] = fid
            try:
                if self.callbacks and hasattr(self.callbacks, "save_state"):
                    self.callbacks.save_state()
            except Exception:
                pass

    def _pick_dir(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "截图保存目录", self.txt_dir.text())
        if p:
            self.txt_dir.setText(p)
            self._save()

    def _pick_secrets(self) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self, "选择 OAuth 客户端 JSON", "", "JSON (*.json);;All (*.*)"
        )
        if p:
            try:
                import os
                import shutil

                try:
                    from storage import app_data_dir

                    dest_dir = app_data_dir()
                except Exception:
                    dest_dir = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DesktopToolkit"
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / "gdrive_client_secrets.json"
                shutil.copy2(p, dest)
                self.txt_secrets.setText(str(dest))
                self.lbl_status.setText(f"密钥已保存到 {dest}，请点「连接 Google」授权")
            except Exception:
                self.txt_secrets.setText(p)
            self._save()
            self._refresh_gstatus()

    def _connect_gdrive(self) -> None:
        self._save()
        self.lbl_status.setText("正在授权…请在浏览器中登录 Google")
        secrets_path = self.txt_secrets.text().strip()
        if not secrets_path:
            self.lbl_status.setText("请先选择 OAuth 客户端 JSON 文件")
            return

        def work() -> None:
            try:
                from gdrive_client import GoogleDriveClient

                gd = dict(self._gdrive())
                client = GoogleDriveClient(gd)
                client.authorize_interactive(on_status=lambda m: self._bridge.status.emit(m))
                try:
                    fid = client.ensure_folder()
                    self._bridge.folder_id.emit(str(fid))
                    self._bridge.status.emit(f"✅ 已连接，文件夹 ID: {fid}")
                except Exception as e:
                    self._bridge.status.emit(f"✅ 已连接（文件夹稍后创建）: {e}")
                self._gdrive().update(client.cfg)
            except Exception as e:
                self._bridge.status.emit(f"连接失败: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _disconnect_gdrive(self) -> None:
        try:
            from gdrive_client import GoogleDriveClient

            GoogleDriveClient(self._gdrive()).clear_token()
            self.lbl_status.setText("已断开 Google 连接")
            self._refresh_gstatus()
        except Exception as e:
            self.lbl_status.setText(f"断开失败: {e}")

    def _test_upload(self) -> None:
        self._save()
        # tiny PNG
        from PyQt6.QtGui import QImage, QColor, QPainter
        import tempfile
        import time

        img = QImage(120, 40, QImage.Format.Format_ARGB32)
        img.fill(QColor(14, 165, 233))
        p = QPainter(img)
        p.setPen(QColor("white"))
        p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, "ParrotShot")
        p.end()
        tmp = Path(tempfile.gettempdir()) / f"parrot_gdrive_test_{int(time.time())}.png"
        img.save(str(tmp))

        def work() -> None:
            try:
                from gdrive_client import GoogleDriveClient

                gd = dict(self._gdrive())
                client = GoogleDriveClient(gd)
                r = client.upload_file(tmp, on_status=lambda m: self._bridge.status.emit(m))
                link = r.get("webViewLink") or ""
                self._bridge.status.emit(f"测试上传成功 {r.get('name','')} {link}")
                self._gdrive().update(gd)
            except Exception as e:
                self._bridge.status.emit(f"测试上传失败: {e}")
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass

        threading.Thread(target=work, daemon=True).start()

    def _launch(self, mode: str) -> None:
        self._save()
        self.hide()
        try:
            from screenshot_app import start_screenshot

            start_screenshot(mode=mode, state=self.state, on_done=lambda _i: None)
            self.lbl_status.setText("截图已启动…")
        except Exception as e:
            self.lbl_status.setText(f"启动失败: {e}")
            self.show()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.dragging = False
