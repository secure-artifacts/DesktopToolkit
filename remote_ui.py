"""Remote control panel — launches bundled RustDesk with unified Toolkit UI."""

from __future__ import annotations

import webbrowser

from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtGui import QGuiApplication, QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rustdesk_bridge import DOWNLOAD_URL, SOURCE_URL, connect_to, launch_rustdesk, probe


class FloatingRemoteBoard(QWidget):
    def __init__(self, host=None, parent=None, *, embedded: bool = False):
        super().__init__(parent)
        self.host = host
        self.embedded = embedded
        self.dragging = False
        self.drag_position = QPoint()
        self._exe = None

        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        else:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.resize(460, 540)
        self._init_ui()
        QTimer.singleShot(0, self.refresh)

    def _prefs(self) -> dict:
        try:
            return self.host.store.state.setdefault("prefs", {})
        except Exception:
            return {}

    def _extra_path(self) -> str | None:
        p = self._prefs().get("rustdesk_path")
        return str(p) if p else None

    def _init_ui(self) -> None:
        self.setStyleSheet(
            """
            QFrame#box {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #0f172a, stop:1 #020617);
                border: 1px solid rgba(99,102,241,0.45); border-radius: 16px;
            }
            QLabel { color: #e2e8f0; font-size: 14px; font-weight: 600; }
            QLabel#title { color: #a5b4fc; font-size: 18px; font-weight: 800; }
            QLabel#muted { color: #94a3b8; font-size: 13px; font-weight: 500; }
            QLabel#idBig {
                color: #f8fafc; font-size: 22px; font-weight: 800;
                background: #020617; border: 1px solid #334155; border-radius: 10px;
                padding: 10px 12px;
            }
            QLineEdit {
                background: #020617; color: #f8fafc; border: 1px solid #334155;
                border-radius: 10px; padding: 10px 12px; min-height: 34px; font-size: 14px;
            }
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #6366f1, stop:1 #4f46e5);
                border: none; color: white; font-weight: 800; font-size: 14px;
                padding: 10px 14px; border-radius: 10px; min-height: 34px;
            }
            QPushButton:hover { background: #818cf8; color: #1e1b4b; }
            QPushButton#soft {
                background: #1e293b; border: 1px solid #475569; color: #f1f5f9;
                font-size: 14px; font-weight: 800; min-height: 34px; padding: 8px 14px;
            }
            """
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        box = QFrame(objectName="box")
        if self.embedded:
            box.setStyleSheet(
                "QFrame#box { background: transparent; border: none; border-radius: 0; }"
            )
        lay = QVBoxLayout(box)
        m = 4 if self.embedded else 14
        lay.setContentsMargins(m, m if self.embedded else 12, m, 10)
        lay.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(QLabel("🖥 远程控制", objectName="title"), 1)
        if not self.embedded:
            close_btn = QPushButton("×", objectName="soft")
            close_btn.setFixedSize(28, 28)
            close_btn.clicked.connect(self.hide)
            header.addWidget(close_btn)
        lay.addLayout(header)

        tip = QLabel(
            "安装包已内置开源远程引擎（RustDesk），一般无需再单独安装。\n"
            "配对与连接用本页；真正操作对方桌面时会打开引擎窗口。"
        )
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self.lbl_status = QLabel("正在检测…")
        self.lbl_status.setObjectName("muted")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        lay.addWidget(QLabel("本机局域网 IP（同一 Wi‑Fi/有线时给对方填这个）"))
        ip_row = QHBoxLayout()
        self.lbl_lan_ip = QLabel("—")
        self.lbl_lan_ip.setObjectName("idBig")
        self.lbl_lan_ip.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_lan_ip.setToolTip("多网卡时会列出多个；优先使用排在最前的地址")
        ip_row.addWidget(self.lbl_lan_ip, 1)
        btn_copy_ip = QPushButton("复制 IP", objectName="soft")
        btn_copy_ip.clicked.connect(self._copy_lan_ip)
        ip_row.addWidget(btn_copy_ip)
        lay.addLayout(ip_row)
        self.lbl_lan_ip_extra = QLabel("")
        self.lbl_lan_ip_extra.setObjectName("muted")
        self.lbl_lan_ip_extra.setWordWrap(True)
        lay.addWidget(self.lbl_lan_ip_extra)

        lay.addWidget(QLabel("本机 ID（跨网/中继时给对方填；局域网也可只用上面的 IP）"))
        id_row = QHBoxLayout()
        self.lbl_id = QLabel("—")
        self.lbl_id.setObjectName("idBig")
        self.lbl_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        id_row.addWidget(self.lbl_id, 1)
        btn_copy = QPushButton("复制 ID", objectName="soft")
        btn_copy.clicked.connect(self._copy_id)
        id_row.addWidget(btn_copy)
        lay.addLayout(id_row)

        lay.addWidget(QLabel("连接到另一台（对方 ID 或局域网 IP）"))
        self.ed_peer = QLineEdit()
        self.ed_peer.setPlaceholderText("例如 192.168.1.20  或  123456789")
        try:
            last = self._prefs().get("rustdesk_last_peer") or ""
            if last:
                self.ed_peer.setText(str(last))
        except Exception:
            pass
        lay.addWidget(self.ed_peer)

        row = QHBoxLayout()
        btn_connect = QPushButton("立即连接")
        btn_connect.clicked.connect(self._connect)
        row.addWidget(btn_connect)
        btn_launch = QPushButton("启动远程引擎", objectName="soft")
        btn_launch.clicked.connect(self._launch)
        row.addWidget(btn_launch)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        btn_refresh = QPushButton("刷新状态", objectName="soft")
        btn_refresh.clicked.connect(self.refresh)
        row2.addWidget(btn_refresh)
        btn_dl = QPushButton("官网备用下载", objectName="soft")
        btn_dl.setToolTip("仅当内置引擎缺失时需要")
        btn_dl.clicked.connect(lambda: webbrowser.open(DOWNLOAD_URL))
        row2.addWidget(btn_dl)
        lay.addLayout(row2)

        guide = QLabel(
            "Win ↔ Mac 互控步骤：\n"
            "1. 两台都打开本软件 → 远程控制 →「启动远程引擎」\n"
            "2. 在引擎设置里设「固定密码」（或用一次性密码）\n"
            "3. 同一局域网：把上面的「本机局域网 IP」发给对方，对方填 IP → 立即连接\n"
            "4. 不在同一局域网：互填本机 ID 连接\n"
            "5. Mac 首次需授权「屏幕录制 / 辅助功能」\n\n"
            "说明：引擎为开源项目 RustDesk（AGPL）。\n"
            f"源码：{SOURCE_URL}\n"
            "本工具不保存对方密码；固定密码勿发到公开场合。"
        )
        guide.setObjectName("muted")
        guide.setWordWrap(True)
        lay.addWidget(guide)
        lay.addStretch(1)
        root.addWidget(box)

    def _lan_ips(self) -> list[str]:
        """LAN IPs ranked for 'share with the other PC on Wi‑Fi' use."""
        try:
            from lan_share import local_ipv4_addresses

            ips = [ip for ip in local_ipv4_addresses() if ip and not str(ip).startswith("127.")]
        except Exception:
            ips = []
        if not ips:
            return []

        def score(ip: str) -> tuple:
            parts = ip.split(".")
            try:
                a, b = int(parts[0]), int(parts[1])
            except Exception:
                return (9, ip)
            # Deprioritize common virtual/host-only / docker adapters
            if a == 192 and b == 56:  # VirtualBox host-only
                return (5, ip)
            if a == 172 and 16 <= b <= 31:  # often Docker / WSL
                return (4, ip)
            if a == 169:  # link-local
                return (8, ip)
            # Prefer typical home / office LAN
            if a == 192 and b == 168:
                return (0, ip)
            if a == 10:
                return (1, ip)  # may be VPN — still common
            if a == 172 and 16 <= b <= 31:
                return (2, ip)
            return (3, ip)

        return sorted(set(ips), key=score)

    def refresh(self) -> None:
        st = probe(self._extra_path())
        self._exe = st.exe
        self.lbl_status.setText(st.message)
        self.lbl_id.setText(st.local_id or "（启动引擎后点刷新）")
        ips = self._lan_ips()
        if ips:
            self.lbl_lan_ip.setText(ips[0])
            if len(ips) > 1:
                self.lbl_lan_ip_extra.setText(
                    "本机其它网卡地址：" + "  ·  ".join(ips[1:6])
                    + (" …" if len(ips) > 6 else "")
                    + "\n（一般选最前面的那个发给同一局域网的对方）"
                )
            else:
                self.lbl_lan_ip_extra.setText("同一 Wi‑Fi / 路由器下，把这个 IP 发给对方即可。")
        else:
            self.lbl_lan_ip.setText("（未检测到局域网 IP）")
            self.lbl_lan_ip_extra.setText("请确认已连接 Wi‑Fi 或有线网络后点「刷新状态」。")

    def _copy_lan_ip(self) -> None:
        text = (self.lbl_lan_ip.text() or "").strip()
        if not text or text.startswith("（"):
            QMessageBox.information(self, "复制", "还没有可用的局域网 IP。")
            return
        QGuiApplication.clipboard().setText(text)
        self.lbl_status.setText(f"局域网 IP 已复制：{text}")

    def _copy_id(self) -> None:
        text = (self.lbl_id.text() or "").strip()
        if not text or text.startswith("（"):
            QMessageBox.information(self, "复制", "还没有可用的本机 ID。")
            return
        QGuiApplication.clipboard().setText(text)
        self.lbl_status.setText("本机 ID 已复制到剪贴板")

    def _launch(self) -> None:
        msg = launch_rustdesk(self._exe, self._extra_path())
        self.lbl_status.setText(msg)
        QTimer.singleShot(800, self.refresh)

    def _connect(self) -> None:
        peer = self.ed_peer.text().strip()
        if not peer:
            QMessageBox.information(self, "远程控制", "请先填写对方 ID 或 IP。")
            return
        try:
            prefs = self._prefs()
            prefs["rustdesk_last_peer"] = peer
            if self.host is not None:
                self.host.store.save_state()
        except Exception:
            pass
        msg = connect_to(peer, self._exe, self._extra_path())
        self.lbl_status.setText(msg)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self.embedded:
            return super().mousePressEvent(e)
        if e.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_position = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self.embedded:
            return super().mouseMoveEvent(e)
        if self.dragging and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self.drag_position)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self.embedded:
            return super().mouseReleaseEvent(e)
        self.dragging = False
