"""LAN remote control panel — host (share screen) + client (view & control)."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QPoint, QTimer, QObject, pyqtSignal, QByteArray
from PyQt6.QtGui import (
    QGuiApplication,
    QMouseEvent,
    QKeyEvent,
    QWheelEvent,
    QPixmap,
    QImage,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QScrollArea,
)

from lan_remote import DEFAULT_PORT, LanRemoteClient, LanRemoteHost
from lan_share import local_ipv4_addresses


class _Bridge(QObject):
    status = pyqtSignal(str)
    frame = pyqtSignal(object, int, int)  # jpeg bytes, w, h
    closed = pyqtSignal()


class RemoteScreenView(QLabel):
    """Displays remote frames and forwards mouse/keyboard to the client."""

    def __init__(self, client: LanRemoteClient, parent=None):
        super().__init__(parent)
        self._client = client
        self._pix_w = 1
        self._pix_h = 1
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(480, 300)
        self.setStyleSheet(
            "QLabel { background: #0b1220; color: #94a3b8; border: 1px solid #334155; border-radius: 10px; }"
        )
        self.setText("连接后将显示对方桌面\n点击此处聚焦后可用鼠标键盘操控")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    def set_frame(self, jpeg: bytes, w: int, h: int) -> None:
        self._pix_w = max(1, w)
        self._pix_h = max(1, h)
        img = QImage.fromData(QByteArray(jpeg), "JPG")
        if img.isNull():
            return
        pix = QPixmap.fromImage(img)
        scaled = pix.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)

    def _norm_pos(self, event: QMouseEvent) -> tuple[float, float] | None:
        pix = self.pixmap()
        if pix is None or pix.isNull():
            return None
        # Content is centered KeepAspectRatio
        pw, ph = pix.width(), pix.height()
        x0 = (self.width() - pw) // 2
        y0 = (self.height() - ph) // 2
        x = event.position().x() - x0
        y = event.position().y() - y0
        if x < 0 or y < 0 or x > pw or y > ph:
            return None
        return (x / max(1, pw), y / max(1, ph))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        n = self._norm_pos(event)
        if n and self._client.connected:
            self._client.send_mouse("move", n[0], n[1])
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self.setFocus()
        n = self._norm_pos(event)
        if n and self._client.connected:
            btn = "left"
            if event.button() == Qt.MouseButton.RightButton:
                btn = "right"
            elif event.button() == Qt.MouseButton.MiddleButton:
                btn = "middle"
            self._client.send_mouse("down", n[0], n[1], button=btn)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        n = self._norm_pos(event)
        if n and self._client.connected:
            btn = "left"
            if event.button() == Qt.MouseButton.RightButton:
                btn = "right"
            elif event.button() == Qt.MouseButton.MiddleButton:
                btn = "middle"
            self._client.send_mouse("up", n[0], n[1], button=btn)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # type: ignore[override]
        n = self._norm_pos(event)  # type: ignore[arg-type]
        if n and self._client.connected:
            dy = float(event.angleDelta().y())
            self._client.send_mouse("wheel", n[0], n[1], dy=dy)
        super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if self._client.connected and not event.isAutoRepeat():
            key, mods = _qt_key(event)
            if key:
                self._client.send_key("down", key, mods)
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if self._client.connected and not event.isAutoRepeat():
            key, mods = _qt_key(event)
            if key:
                self._client.send_key("up", key, mods)
        super().keyReleaseEvent(event)


def _qt_key(event: QKeyEvent) -> tuple[str, list[str]]:
    mods: list[str] = []
    m = event.modifiers()
    if m & Qt.KeyboardModifier.ControlModifier:
        mods.append("ctrl")
    if m & Qt.KeyboardModifier.AltModifier:
        mods.append("alt")
    if m & Qt.KeyboardModifier.ShiftModifier:
        mods.append("shift")
    if m & Qt.KeyboardModifier.MetaModifier:
        mods.append("cmd")

    mapping = {
        Qt.Key.Key_Return: "enter",
        Qt.Key.Key_Enter: "enter",
        Qt.Key.Key_Tab: "tab",
        Qt.Key.Key_Escape: "esc",
        Qt.Key.Key_Backspace: "backspace",
        Qt.Key.Key_Delete: "delete",
        Qt.Key.Key_Space: "space",
        Qt.Key.Key_Left: "left",
        Qt.Key.Key_Right: "right",
        Qt.Key.Key_Up: "up",
        Qt.Key.Key_Down: "down",
        Qt.Key.Key_Home: "home",
        Qt.Key.Key_End: "end",
        Qt.Key.Key_PageUp: "pageup",
        Qt.Key.Key_PageDown: "pagedown",
    }
    if event.key() in mapping:
        return mapping[event.key()], mods
    t = event.text()
    if t:
        return t, mods
    return "", mods


class FloatingRemoteBoard(QWidget):
    """Embedded or floating LAN remote panel (replaces RustDesk-first UI)."""

    def __init__(self, host=None, parent=None, *, embedded: bool = False):
        super().__init__(parent)
        self.host = host
        self.embedded = embedded
        self.dragging = False
        self.drag_position = QPoint()

        self._lan_host = LanRemoteHost()
        self._lan_client = LanRemoteClient()
        self._bridge = _Bridge()
        self._bridge.status.connect(self._on_client_status)
        self._bridge.frame.connect(self._on_frame)
        self._bridge.closed.connect(self._on_client_closed)
        self._lan_host.set_status_callback(lambda s: QTimer.singleShot(0, lambda: self._set_host_status(s)))
        self._lan_client.on_status = lambda s: self._bridge.status.emit(s)
        self._lan_client.on_frame = lambda b, w, h: self._bridge.frame.emit(b, w, h)
        self._lan_client.on_closed = lambda: self._bridge.closed.emit()

        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        else:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        root = QFrame(objectName="glassCard" if not embedded else "panel")
        lay = QVBoxLayout(self if embedded else root)
        if not embedded:
            outer = QVBoxLayout(self)
            outer.setContentsMargins(8, 8, 8, 8)
            outer.addWidget(root)
            lay = QVBoxLayout(root)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        title = QLabel("远程控制 · 局域网")
        title.setObjectName("section")
        lay.addWidget(title)
        tip = QLabel(
            "不依赖 RustDesk。同一 Wi‑Fi 下：一方「开启被控」，另一方填 IP+密码连接。"
        )
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        # ---- Host ----
        lay.addWidget(QLabel("被控端（让别人控制这台电脑）", objectName="section"))
        row_h = QHBoxLayout()
        self.txt_host_pass = QLineEdit()
        self.txt_host_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_host_pass.setPlaceholderText("设置被控密码（至少4位）")
        self.txt_host_port = QLineEdit(str(DEFAULT_PORT))
        self.txt_host_port.setFixedWidth(72)
        self.txt_host_port.setPlaceholderText("端口")
        row_h.addWidget(self.txt_host_pass, 1)
        row_h.addWidget(QLabel("端口"))
        row_h.addWidget(self.txt_host_port)
        lay.addLayout(row_h)

        row_hb = QHBoxLayout()
        self.btn_host_start = QPushButton("开启被控", objectName="primary")
        self.btn_host_stop = QPushButton("关闭被控", objectName="soft")
        self.btn_host_stop.setEnabled(False)
        self.btn_copy_ip = QPushButton("复制本机 IP", objectName="soft")
        row_hb.addWidget(self.btn_host_start)
        row_hb.addWidget(self.btn_host_stop)
        row_hb.addWidget(self.btn_copy_ip)
        row_hb.addStretch(1)
        lay.addLayout(row_hb)

        self.lbl_lan_ips = QLabel("")
        self.lbl_lan_ips.setObjectName("muted")
        self.lbl_lan_ips.setWordWrap(True)
        self.lbl_lan_ips.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.lbl_lan_ips)
        self.lbl_host_status = QLabel("被控未开启")
        self.lbl_host_status.setObjectName("muted")
        lay.addWidget(self.lbl_host_status)

        # ---- Client ----
        lay.addWidget(QLabel("主控端（控制对方电脑）", objectName="section"))
        row_c = QHBoxLayout()
        self.txt_peer_ip = QLineEdit()
        self.txt_peer_ip.setPlaceholderText("对方局域网 IP，如 192.168.110.61")
        self.txt_peer_port = QLineEdit(str(DEFAULT_PORT))
        self.txt_peer_port.setFixedWidth(72)
        self.txt_peer_pass = QLineEdit()
        self.txt_peer_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_peer_pass.setPlaceholderText("对方被控密码")
        row_c.addWidget(self.txt_peer_ip, 2)
        row_c.addWidget(self.txt_peer_port)
        row_c.addWidget(self.txt_peer_pass, 1)
        lay.addLayout(row_c)

        row_cb = QHBoxLayout()
        self.btn_connect = QPushButton("连接对方", objectName="primary")
        self.btn_disconnect = QPushButton("断开", objectName="soft")
        self.btn_disconnect.setEnabled(False)
        row_cb.addWidget(self.btn_connect)
        row_cb.addWidget(self.btn_disconnect)
        row_cb.addStretch(1)
        lay.addLayout(row_cb)
        self.lbl_client_status = QLabel("未连接")
        self.lbl_client_status.setObjectName("muted")
        lay.addWidget(self.lbl_client_status)

        self.view = RemoteScreenView(self._lan_client)
        lay.addWidget(self.view, 1)

        help_l = QLabel(
            "Mac 被控需授权：系统设置 → 隐私与安全性 → 屏幕录制、辅助功能。\n"
            "Windows 若连不上：防火墙放行入站 TCP 端口（默认 8766）。"
        )
        help_l.setObjectName("muted")
        help_l.setWordWrap(True)
        lay.addWidget(help_l)

        self.btn_host_start.clicked.connect(self._start_host)
        self.btn_host_stop.clicked.connect(self._stop_host)
        self.btn_copy_ip.clicked.connect(self._copy_ip)
        self.btn_connect.clicked.connect(self._connect)
        self.btn_disconnect.clicked.connect(self._disconnect)

        # Restore last peer from prefs
        try:
            prefs = (self.host.store.state.get("prefs") or {}) if self.host else {}
            self.txt_peer_ip.setText(str(prefs.get("lan_remote_peer") or ""))
            saved_pw = str(prefs.get("lan_remote_host_pass") or "")
            if saved_pw:
                self.txt_host_pass.setText(saved_pw)
        except Exception:
            pass

        self._refresh_ips()
        QTimer.singleShot(0, self._refresh_ips)

    def refresh(self) -> None:
        self._refresh_ips()
        st = self._lan_host.status()
        if st.running:
            self.lbl_host_status.setText(f"被控运行中 · 端口 {st.port} · 连接数 {st.clients}")
            self.btn_host_start.setEnabled(False)
            self.btn_host_stop.setEnabled(True)
        else:
            self.btn_host_start.setEnabled(True)
            self.btn_host_stop.setEnabled(False)

    def _preferred_ips(self) -> list[str]:
        ips = local_ipv4_addresses() or []
        ranked: list[str] = []
        for ip in ips:
            if ip.startswith("192.168."):
                ranked.append(ip)
        for ip in ips:
            if ip not in ranked and not ip.startswith(("127.", "169.254.", "172.1", "172.2", "172.3")):
                # keep other private ranges but deprioritize common virtual (172.16-31 still ok)
                ranked.append(ip)
        for ip in ips:
            if ip not in ranked:
                ranked.append(ip)
        return ranked

    def _refresh_ips(self) -> None:
        ips = self._preferred_ips()
        if not ips:
            self.lbl_lan_ips.setText("本机 IP：未检测到")
            return
        primary = ips[0]
        extra = "、".join(ips[1:3]) if len(ips) > 1 else ""
        text = f"本机局域网 IP（给对方填）：{primary}"
        if extra:
            text += f"\n其他地址：{extra}"
        self.lbl_lan_ips.setText(text)
        self._primary_ip = primary

    def _set_host_status(self, msg: str) -> None:
        self.lbl_host_status.setText(msg)
        self.refresh()

    def _start_host(self) -> None:
        pw = self.txt_host_pass.text().strip()
        try:
            port = int(self.txt_host_port.text().strip() or DEFAULT_PORT)
        except ValueError:
            QMessageBox.warning(self, "被控", "端口无效")
            return
        msg = self._lan_host.start(pw, port=port)
        self.lbl_host_status.setText(msg)
        if "已开启" in msg:
            self.btn_host_start.setEnabled(False)
            self.btn_host_stop.setEnabled(True)
            try:
                if self.host:
                    prefs = self.host.store.state.setdefault("prefs", {})
                    prefs["lan_remote_host_pass"] = pw
                    self.host.store.save_state()
            except Exception:
                pass
            self._refresh_ips()
            QMessageBox.information(
                self,
                "被控已开启",
                f"{msg}\n\n把本机 IP 和密码发给对方：\n"
                f"IP：{getattr(self, '_primary_ip', '')}\n端口：{port}\n\n"
                "对方在「主控端」填入后点连接。",
            )

    def _stop_host(self) -> None:
        msg = self._lan_host.stop()
        self.lbl_host_status.setText(msg)
        self.btn_host_start.setEnabled(True)
        self.btn_host_stop.setEnabled(False)

    def _copy_ip(self) -> None:
        self._refresh_ips()
        ip = getattr(self, "_primary_ip", "") or ""
        if not ip:
            return
        QGuiApplication.clipboard().setText(ip)
        self.lbl_host_status.setText(f"已复制 IP：{ip}")

    def _connect(self) -> None:
        ip = self.txt_peer_ip.text().strip()
        pw = self.txt_peer_pass.text().strip()
        try:
            port = int(self.txt_peer_port.text().strip() or DEFAULT_PORT)
        except ValueError:
            QMessageBox.warning(self, "连接", "端口无效")
            return
        msg = self._lan_client.connect(ip, pw, port=port)
        self.lbl_client_status.setText(msg)
        self.btn_connect.setEnabled(False)
        self.btn_disconnect.setEnabled(True)
        try:
            if self.host:
                prefs = self.host.store.state.setdefault("prefs", {})
                prefs["lan_remote_peer"] = ip
                self.host.store.save_state()
        except Exception:
            pass

    def _disconnect(self) -> None:
        self._lan_client.disconnect()
        self.lbl_client_status.setText("已断开")
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self.view.setText("已断开")

    def _on_client_status(self, msg: str) -> None:
        self.lbl_client_status.setText(msg)
        if "失败" in msg or "认证失败" in msg:
            self.btn_connect.setEnabled(True)
            self.btn_disconnect.setEnabled(False)

    def _on_frame(self, jpeg, w: int, h: int) -> None:
        try:
            self.view.set_frame(bytes(jpeg), int(w), int(h))
        except Exception:
            pass

    def _on_client_closed(self) -> None:
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        if "失败" not in (self.lbl_client_status.text() or ""):
            self.lbl_client_status.setText("连接已关闭")

    # Floating drag (non-embedded)
    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if not self.embedded and event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if not self.embedded and self.dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self.dragging = False
        super().mouseReleaseEvent(event)
