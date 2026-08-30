"""Cross-network file transfer UI (Cloudflare zero-storage signaling/relay)."""

from __future__ import annotations

import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QObject
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from p2p_transfer import P2PSession, make_room_code


class _Bridge(QObject):
    status = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)
    usage = pyqtSignal(str, int, int)  # text, used, limit


class FloatingP2PBoard(QWidget):
    def __init__(self, callbacks=None, state=None, parent=None, *, embedded: bool = False):
        super().__init__(parent)
        self.callbacks = callbacks
        self.state = state if isinstance(state, dict) else {}
        self.embedded = embedded
        self.session: P2PSession | None = None
        self.dragging = False
        self.drag_position = QPoint()
        self._bridge = _Bridge(self)
        self._bridge.status.connect(self._on_status)
        self._bridge.progress.connect(self._on_progress)
        self._bridge.usage.connect(self._on_usage)

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
            self.resize(440, 500)
        self._init_ui()
        self._load()
        self._refresh_usage()

    def _cfg(self) -> dict:
        return self.state.setdefault("p2p", {})

    def _init_ui(self) -> None:
        self.setStyleSheet(
            """
            QFrame#box {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #0f172a, stop:1 #020617);
                border: 1px solid rgba(56,189,248,0.35); border-radius: 16px;
            }
            QLabel { color: #e2e8f0; font-size: 14px; font-weight: 600; }
            QLabel#title { color: #38bdf8; font-size: 18px; font-weight: 800; }
            QLabel#muted { color: #cbd5e1; font-size: 13px; font-weight: 500; }
            QLabel#quotaTitle { color: #e2e8f0; font-size: 14px; font-weight: 800; }
            QLineEdit {
                background: #020617; color: #f8fafc; border: 1px solid #334155;
                border-radius: 10px; padding: 10px 12px; min-height: 34px; font-size: 14px;
            }
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #0ea5e9, stop:1 #0284c7);
                border: none; color: white; font-weight: 800; font-size: 14px;
                padding: 10px 14px; border-radius: 10px; min-height: 34px;
            }
            QPushButton:hover { background: #38bdf8; color: #0c4a6e; }
            QPushButton#soft {
                background: #1e293b; border: 1px solid #475569; color: #f1f5f9;
                font-size: 14px; font-weight: 800; min-height: 34px; padding: 8px 14px;
            }
            QPushButton#danger { background: #dc2626; font-size: 14px; }
            QProgressBar {
                background: #1e293b; border: none; border-radius: 8px; height: 22px;
                text-align: center; color: #f8fafc; font-size: 13px; font-weight: 700;
            }
            QProgressBar::chunk { background: #0ea5e9; border-radius: 8px; }
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
        lay.setContentsMargins(4 if self.embedded else 14, 4 if self.embedded else 12, 4 if self.embedded else 14, 10)
        lay.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(QLabel("☁ 跨网点对点传输", objectName="title"), 1)
        if not self.embedded:
            close_btn = QPushButton("×", objectName="soft")
            close_btn.setFixedSize(28, 28)
            close_btn.clicked.connect(self.hide)
            header.addWidget(close_btn)
        lay.addLayout(header)

        tip = QLabel(
            "Cloudflare 只做「房间牵线 / 内存转发」，不存文件。\n"
            "双方填写同一 Worker 地址 + 同一房间号，即可跨网传文件。"
        )
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        lay.addWidget(QLabel("中转地址（Cloudflare Worker）"))
        url_row = QHBoxLayout()
        self.txt_url = QLineEdit()
        self.txt_url.setPlaceholderText("wss://your-worker.example.workers.dev")
        from p2p_transfer import DEFAULT_SIGNAL_URL

        if DEFAULT_SIGNAL_URL:
            self.txt_url.setText(DEFAULT_SIGNAL_URL)
        url_row.addWidget(self.txt_url, 1)
        self.btn_test = QPushButton("测试中转", objectName="soft")
        self.btn_test.setMinimumHeight(36)
        self.btn_test.setMinimumWidth(88)
        self.btn_test.clicked.connect(self._test_relay)
        url_row.addWidget(self.btn_test)
        lay.addLayout(url_row)

        # Free-plan request quota hint
        quota_box = QFrame()
        quota_box.setStyleSheet(
            "QFrame { background: #0b1220; border: 1px solid #1e3a5f; border-radius: 12px; }"
        )
        qlay = QVBoxLayout(quota_box)
        qlay.setContentsMargins(12, 10, 12, 10)
        qlay.setSpacing(8)
        qhead = QHBoxLayout()
        qtitle = QLabel("免费额度（今日）")
        qtitle.setObjectName("quotaTitle")
        qhead.addWidget(qtitle, 1)
        self.btn_usage = QPushButton("刷新额度", objectName="soft")
        self.btn_usage.setMinimumHeight(36)
        self.btn_usage.setMinimumWidth(100)
        self.btn_usage.clicked.connect(self._refresh_usage)
        qhead.addWidget(self.btn_usage)
        qlay.addLayout(qhead)
        self.quota_bar = QProgressBar()
        self.quota_bar.setRange(0, 100000)
        self.quota_bar.setValue(0)
        self.quota_bar.setFormat("已用 %v / %m")
        self.quota_bar.setTextVisible(True)
        self.quota_bar.setMinimumHeight(26)
        qlay.addWidget(self.quota_bar)
        self.lbl_usage = QLabel(
            "点右侧「刷新额度」查看今日请求用量。\n"
            "建连计请求，传文件块不计；一次传输双方各连 ≈ 扣 2 次。额度全账户共享。"
        )
        self.lbl_usage.setObjectName("muted")
        self.lbl_usage.setWordWrap(True)
        qlay.addWidget(self.lbl_usage)
        lay.addWidget(quota_box)

        room_row = QHBoxLayout()
        room_row.addWidget(QLabel("房间号"))
        self.txt_room = QLineEdit()
        self.txt_room.setPlaceholderText("6 位房间码")
        self.txt_room.setMaxLength(8)
        self.txt_room.setMinimumHeight(36)
        btn_gen = QPushButton("生成", objectName="soft")
        btn_gen.setMinimumHeight(36)
        btn_gen.setMinimumWidth(72)
        btn_gen.clicked.connect(self._gen_room)
        room_row.addWidget(self.txt_room, 1)
        room_row.addWidget(btn_gen)
        lay.addLayout(room_row)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("接收目录"))
        self.txt_dest = QLineEdit()
        self.txt_dest.setPlaceholderText("对方发来的文件保存到…")
        btn_dest = QPushButton("浏览", objectName="soft")
        btn_dest.clicked.connect(self._pick_dest)
        path_row.addWidget(self.txt_dest, 1)
        path_row.addWidget(btn_dest)
        lay.addLayout(path_row)

        act = QHBoxLayout()
        self.btn_send = QPushButton("发送文件…")
        self.btn_send.setToolTip("可多选文件；多个文件会打成 zip 再传")
        self.btn_send.clicked.connect(self._send_files)
        self.btn_send_folder = QPushButton("发送文件夹…", objectName="soft")
        self.btn_send_folder.setToolTip("选择整个文件夹打包发送（zip）")
        self.btn_send_folder.clicked.connect(self._send_folder)
        self.btn_recv = QPushButton("等待接收", objectName="soft")
        self.btn_recv.clicked.connect(self._recv)
        self.btn_stop = QPushButton("停止", objectName="danger")
        self.btn_stop.clicked.connect(self._stop)
        act.addWidget(self.btn_send)
        act.addWidget(self.btn_send_folder)
        act.addWidget(self.btn_recv)
        act.addWidget(self.btn_stop)
        lay.addLayout(act)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        lay.addWidget(self.progress)

        self.lbl_status = QLabel("就绪。先部署 Worker（见 cloudflare/ 目录），再填地址。")
        self.lbl_status.setObjectName("muted")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        help_l = QLabel(
            "部署：在 cloudflare/ 目录执行 wrangler deploy，把输出的 *.workers.dev 填到上方。\n"
            "正确顺序：双方同一中转 + 同一房间号 → 接收方先「等待接收」→ 发送方再发送。\n"
            "「发送文件」可多选；「发送文件夹」传整个目录。多文件/文件夹会打成 zip，"
            "对方收到后自动解压到接收目录。\n"
            "等对方超时多半是中转未开房间粘连：点「测试中转」，须 durable_rooms=true；"
            "否则请更新 cloudflare/ 后重新 wrangler deploy。"
        )
        help_l.setObjectName("muted")
        help_l.setWordWrap(True)
        lay.addWidget(help_l)
        root.addWidget(box)

    def _load(self) -> None:
        cfg = self._cfg()
        from p2p_transfer import DEFAULT_SIGNAL_URL

        if cfg.get("signal_url"):
            self.txt_url.setText(str(cfg["signal_url"]))
        elif DEFAULT_SIGNAL_URL:
            self.txt_url.setText(DEFAULT_SIGNAL_URL)
        if cfg.get("dest_dir"):
            self.txt_dest.setText(str(cfg["dest_dir"]))
        else:
            self.txt_dest.setText(str(Path.home() / "Downloads" / "ParrotP2P"))
        if cfg.get("room"):
            self.txt_room.setText(str(cfg["room"]))
        else:
            self._gen_room()

    def _save(self) -> None:
        cfg = self._cfg()
        cfg["signal_url"] = self.txt_url.text().strip()
        cfg["dest_dir"] = self.txt_dest.text().strip()
        cfg["room"] = self.txt_room.text().strip().upper()
        try:
            if self.callbacks and hasattr(self.callbacks, "save_state"):
                self.callbacks.save_state()
        except Exception:
            pass

    def _gen_room(self) -> None:
        self.txt_room.setText(make_room_code(6))

    def _pick_dest(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "接收保存目录", self.txt_dest.text())
        if p:
            self.txt_dest.setText(p)
            self._save()

    def _on_status(self, msg: str) -> None:
        self.lbl_status.setText(msg)
        if msg.startswith("✅"):
            self.progress.setValue(100)
            # Transfer done — refresh remaining quota so user knows if more is OK
            self._refresh_usage()

    def _on_progress(self, cur: int, total: int, name: str) -> None:
        pct = int(cur * 100 / max(1, total))
        self.progress.setValue(pct)
        self.lbl_status.setText(f"传输中 {name} · {cur}/{total} ({pct}%)")

    def _on_usage(self, text: str, used: int, limit: int) -> None:
        self.lbl_usage.setText(text)
        limit = max(1, int(limit or 100_000))
        used = max(0, int(used or 0))
        self.quota_bar.setRange(0, limit)
        self.quota_bar.setValue(min(used, limit))
        rem = max(0, limit - used)
        self.quota_bar.setFormat(f"已用 {used:,} / {limit:,} · 剩余约 {rem:,}")
        self.btn_usage.setEnabled(True)
        self.btn_usage.setText("刷新额度")

    def _refresh_usage(self) -> None:
        url = self.txt_url.text().strip()
        if not url:
            self.lbl_usage.setText("请先填写中转地址，再刷新额度。")
            return
        self.btn_usage.setEnabled(False)
        self.btn_usage.setText("查询中…")
        self.lbl_usage.setText("正在查询今日请求用量…")

        def work() -> None:
            try:
                from p2p_transfer import fetch_worker_usage, format_usage_line, FREE_DAILY_REQUEST_LIMIT

                info = fetch_worker_usage(url)
                line = format_usage_line(info)
                used = int(info.get("worker_requests_today") or 0)
                limit = int(info.get("daily_limit") or FREE_DAILY_REQUEST_LIMIT)
                self._bridge.usage.emit(line, used, limit)
            except Exception as e:
                # Fallback: show free-plan reminder without live numbers
                msg = (
                    f"未能读取实时额度：{e}\n"
                    "请确认已重新部署含 /usage 的 Worker（cloudflare/ 目录 wrangler deploy）。\n"
                    "参考：免费约 10 万次请求/天；建连计次，传文件块不计。"
                )
                self._bridge.usage.emit(msg, 0, 100_000)

        threading.Thread(target=work, daemon=True).start()

    def _test_relay(self) -> None:
        """Ping /health so user can verify Worker URL + Durable Object rooms."""
        url = self.txt_url.text().strip()
        if not url:
            self.lbl_status.setText("请先填写中转地址再测试。")
            return
        self.btn_test.setEnabled(False)
        self.btn_test.setText("测试中…")
        self.lbl_status.setText("正在测试中转…")

        def work() -> None:
            try:
                from p2p_transfer import fetch_worker_health, normalize_http_base

                info = fetch_worker_health(url)
                base = normalize_http_base(url)
                durable = bool(info.get("durable_rooms"))
                if durable:
                    msg = (
                        f"✅ 中转正常：{base}\n"
                        f"房间粘连 durable_rooms=true（可跨网配对）\n"
                        f"名称：{info.get('name') or 'ok'}"
                    )
                else:
                    msg = (
                        f"⚠️ 中转能访问，但 durable_rooms=false\n"
                        f"双方很容易「永远等对方」。\n"
                        f"请在本机 cloudflare/ 目录执行：npx wrangler deploy\n"
                        f"然后再测一次，必须看到 durable_rooms=true。"
                    )
                self._bridge.status.emit(msg)
            except Exception as e:
                self._bridge.status.emit(
                    f"❌ 中转不可用：{e}\n"
                    "请核对地址（如 https://xxx.workers.dev），并确认已 wrangler deploy。"
                )
            finally:
                try:
                    self.btn_test.setEnabled(True)
                    self.btn_test.setText("测试中转")
                except Exception:
                    pass

        threading.Thread(target=work, daemon=True).start()

    def _session(self) -> P2PSession | None:
        self._save()
        url = self.txt_url.text().strip()
        room = self.txt_room.text().strip()
        if not url:
            self.lbl_status.setText("请先填写 Cloudflare Worker 地址")
            return None
        if len(room) < 4:
            self.lbl_status.setText("房间号至少 4 位")
            return None
        return P2PSession(
            url,
            room,
            on_status=lambda m: self._bridge.status.emit(m),
            on_progress=lambda a, b, c: self._bridge.progress.emit(a, b, c),
        )

    def _start_send(self, paths: list[str]) -> None:
        if not paths:
            return
        sess = self._session()
        if not sess:
            return
        if self.session:
            self.session.stop()
        self.session = sess
        self.progress.setValue(0)
        if len(paths) == 1:
            self.lbl_status.setText(f"准备发送：{Path(paths[0]).name}")
        else:
            self.lbl_status.setText(f"准备发送 {len(paths)} 项（将打包为 zip）…")
        sess.send_paths_async(paths)

    def _send_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "选择要发送的文件（可多选）")
        self._start_send(list(paths or []))

    def _send_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择要发送的文件夹")
        if path:
            self._start_send([path])

    def _recv(self) -> None:
        dest = self.txt_dest.text().strip() or str(Path.home() / "Downloads")
        sess = self._session()
        if not sess:
            return
        if self.session:
            self.session.stop()
        self.session = sess
        self.progress.setValue(0)
        self.lbl_status.setText("等待对方发送…")
        sess.receive_file_async(dest)

    def _stop(self) -> None:
        if self.session:
            self.session.stop()
            self.session = None
        self.lbl_status.setText("已停止")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.dragging = False
