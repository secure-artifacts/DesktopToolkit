"""Timer & alarm floating board with ringtones and clearer UI."""

from __future__ import annotations

import uuid

from PyQt6.QtCore import Qt, QPoint, QTimer, QTime
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from alarm_sounds import RINGTONES, ensure_ringtones, play_ringtone, stop_ringtone


class FloatingAlarmBoard(QWidget):
    def __init__(self, callbacks, state, parent=None):
        super().__init__(parent)
        self.callbacks = callbacks
        self.state = state
        self.dragging = False
        self.drag_position = QPoint()
        ensure_ringtones()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(380, 460)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._update_ui_state)
        self.refresh_timer.start(400)
        self._init_ui()

    def _init_ui(self) -> None:
        self.setStyleSheet(
            """
            QFrame#mainContainer {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #1e293b, stop:1 #0f172a);
                border: 1px solid rgba(251,191,36,0.35);
                border-radius: 16px;
            }
            QLabel { color: #e2e8f0; font-size: 12px; font-weight: 600; }
            QLabel#title { color: #fbbf24; font-size: 15px; font-weight: 800; }
            QLabel#bigTime {
                color: #fbbf24; font-size: 42px; font-weight: 900;
                font-family: Consolas, 'Cascadia Mono', monospace;
                background: #020617; border-radius: 14px;
                border: 1px solid #334155; padding: 16px;
            }
            QLabel#section {
                color: #fde68a; font-size: 11px; font-weight: 800;
                letter-spacing: 0.5px;
            }
            QLabel#muted { color: #94a3b8; font-size: 11px; font-weight: 500; }
            QTabWidget::pane {
                border: 1px solid #334155; border-radius: 12px;
                background: #0f172a; top: -1px;
            }
            QTabBar::tab {
                background: #1e293b; color: #94a3b8; padding: 8px 16px;
                border-top-left-radius: 10px; border-top-right-radius: 10px;
                margin-right: 3px; font-weight: 700; font-size: 12px;
            }
            QTabBar::tab:selected {
                background: #0f172a; color: #fbbf24;
                border: 1px solid #334155; border-bottom: 1px solid #0f172a;
            }
            QSpinBox, QComboBox, QLineEdit, QTimeEdit, QListWidget {
                background: #020617; color: #f8fafc;
                border: 1px solid #475569; border-radius: 10px;
                padding: 8px 10px; min-height: 28px; font-size: 13px;
            }
            QSpinBox { font-size: 16px; font-weight: 800; min-width: 72px; }
            QTimeEdit { font-size: 18px; font-weight: 800; min-height: 36px; }
            QComboBox QAbstractItemView {
                background: #0f172a; color: #f8fafc;
                selection-background-color: #b45309;
            }
            QListWidget::item {
                padding: 10px; border-radius: 8px; margin: 2px;
                color: #e2e8f0; background: #1e293b;
            }
            QListWidget::item:selected { background: #78350f; color: #fffbeb; }
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #f59e0b, stop:1 #d97706);
                border: none; color: #111; font-weight: 800; font-size: 12px;
                padding: 10px 14px; border-radius: 10px; min-height: 20px;
            }
            QPushButton:hover { background: #fbbf24; }
            QPushButton:disabled { background: #334155; color: #94a3b8; }
            QPushButton#danger {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ef4444, stop:1 #b91c1c);
                color: white;
            }
            QPushButton#soft {
                background: #1e293b; color: #e2e8f0; border: 1px solid #475569;
            }
            QCheckBox { color: #cbd5e1; font-size: 12px; spacing: 6px; }
            """
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        box = QFrame(objectName="mainContainer")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(QLabel("⏰ 定时器与闹钟", objectName="title"), 1)
        close_btn = QPushButton("✕ 关闭")
        close_btn.setObjectName("soft")
        close_btn.setMinimumWidth(72)
        close_btn.setMinimumHeight(32)
        close_btn.setStyleSheet(
            "QPushButton#soft { background:#334155; color:#f8fafc; border:1px solid #94a3b8; "
            "font-weight:900; font-size:13px; border-radius:8px; }"
            "QPushButton#soft:hover { background:#ef4444; color:white; border-color:#fca5a5; }"
        )
        close_btn.clicked.connect(self.hide)
        header.addWidget(close_btn)
        lay.addLayout(header)

        tabs = QTabWidget()
        tabs.addTab(self._build_timer_tab(), "倒计时")
        tabs.addTab(self._build_alarm_tab(), "闹钟")
        lay.addWidget(tabs)
        root.addWidget(box)

    def _build_timer_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        lay.setContentsMargins(10, 12, 10, 8)

        lay.addWidget(QLabel("剩余时间", objectName="section"))
        self.lbl_timer_display = QLabel("00:00:00", objectName="bigTime")
        self.lbl_timer_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_timer_display)

        lay.addWidget(QLabel("设定时长", objectName="section"))
        inputs = QHBoxLayout()
        self.spin_h = QSpinBox()
        self.spin_h.setRange(0, 23)
        self.spin_h.setSuffix(" 时")
        self.spin_m = QSpinBox()
        self.spin_m.setRange(0, 59)
        self.spin_m.setSuffix(" 分")
        self.spin_m.setValue(5)
        self.spin_s = QSpinBox()
        self.spin_s.setRange(0, 59)
        self.spin_s.setSuffix(" 秒")
        for s in (self.spin_h, self.spin_m, self.spin_s):
            s.setMinimumHeight(40)
            inputs.addWidget(s)
        lay.addLayout(inputs)

        self.txt_timer_name = QLineEdit()
        self.txt_timer_name.setPlaceholderText("提示文字，例如：烧水、小憩、提醒拉伸")
        self.txt_timer_name.setMinimumHeight(36)
        lay.addWidget(self.txt_timer_name)

        ring_row = QHBoxLayout()
        ring_row.addWidget(QLabel("铃声"))
        self.cmb_timer_ring = QComboBox()
        for rid, name in RINGTONES:
            self.cmb_timer_ring.addItem(name, rid)
        self.cmb_timer_ring.setMinimumHeight(36)
        btn_preview = QPushButton("试听", objectName="soft")
        btn_preview.clicked.connect(lambda: play_ringtone(self.cmb_timer_ring.currentData() or "beep"))
        ring_row.addWidget(self.cmb_timer_ring, 1)
        ring_row.addWidget(btn_preview)
        lay.addLayout(ring_row)

        self.chk_timer_tts = QCheckBox("结束时语音播报")
        self.chk_timer_tts.setChecked(True)
        lay.addWidget(self.chk_timer_tts)

        btns = QHBoxLayout()
        self.btn_timer_start = QPushButton("▶ 开始")
        self.btn_timer_start.clicked.connect(self._start_timer)
        self.btn_timer_pause = QPushButton("⏸ 暂停", objectName="soft")
        self.btn_timer_pause.clicked.connect(self._pause_timer)
        self.btn_timer_pause.setEnabled(False)
        self.btn_timer_reset = QPushButton("重置", objectName="danger")
        self.btn_timer_reset.clicked.connect(self._reset_timer)
        btns.addWidget(self.btn_timer_start)
        btns.addWidget(self.btn_timer_pause)
        btns.addWidget(self.btn_timer_reset)
        lay.addLayout(btns)
        tip = QLabel("大号数字显示剩余时间 · 到时可响铃 + 语音")
        tip.setObjectName("muted")
        lay.addWidget(tip)
        return w

    def _build_alarm_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)
        lay.setContentsMargins(10, 12, 10, 8)

        lay.addWidget(QLabel("已添加的闹钟", objectName="section"))
        self.list_alarms = QListWidget()
        self.list_alarms.setMinimumHeight(130)
        self.list_alarms.setStyleSheet(
            "QListWidget { background: #020617; border: 1px solid #475569; border-radius: 12px; }"
        )
        lay.addWidget(self.list_alarms, 1)

        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.addWidget(QLabel("时间"), 0, 0)
        self.time_alarm = QTimeEdit(QTime.currentTime())
        self.time_alarm.setDisplayFormat("HH:mm")
        self.time_alarm.setMinimumHeight(40)
        form.addWidget(self.time_alarm, 0, 1)
        form.addWidget(QLabel("重复"), 0, 2)
        self.cmb_alarm_repeat = QComboBox()
        self.cmb_alarm_repeat.addItems(["仅一次", "每天"])
        self.cmb_alarm_repeat.setMinimumHeight(40)
        form.addWidget(self.cmb_alarm_repeat, 0, 3)
        form.addWidget(QLabel("备注"), 1, 0)
        self.txt_alarm_name = QLineEdit()
        self.txt_alarm_name.setPlaceholderText("例如：起床、吃药、开会")
        self.txt_alarm_name.setMinimumHeight(36)
        form.addWidget(self.txt_alarm_name, 1, 1, 1, 3)
        form.addWidget(QLabel("铃声"), 2, 0)
        self.cmb_alarm_ring = QComboBox()
        for rid, name in RINGTONES:
            self.cmb_alarm_ring.addItem(name, rid)
        self.cmb_alarm_ring.setMinimumHeight(36)
        form.addWidget(self.cmb_alarm_ring, 2, 1, 1, 2)
        btn_prev2 = QPushButton("试听", objectName="soft")
        btn_prev2.clicked.connect(lambda: play_ringtone(self.cmb_alarm_ring.currentData() or "beep"))
        form.addWidget(btn_prev2, 2, 3)
        lay.addLayout(form)

        self.chk_alarm_tts = QCheckBox("响铃同时语音播报备注")
        self.chk_alarm_tts.setChecked(True)
        lay.addWidget(self.chk_alarm_tts)

        btns = QHBoxLayout()
        self.btn_alarm_add = QPushButton("＋ 添加闹钟")
        self.btn_alarm_add.clicked.connect(self._add_alarm)
        self.btn_alarm_del = QPushButton("删除选中", objectName="danger")
        self.btn_alarm_del.clicked.connect(self._delete_alarm)
        btns.addWidget(self.btn_alarm_add)
        btns.addWidget(self.btn_alarm_del)
        lay.addLayout(btns)
        tip = QLabel("列表显示：时间 · 重复 · 备注 · 铃声 · 状态")
        tip.setObjectName("muted")
        lay.addWidget(tip)
        self._refresh_alarm_list()
        return w

    def _update_ui_state(self) -> None:
        t_cfg = self.state.get("timer") or {}
        active = bool(t_cfg.get("active"))
        rem = int(t_cfg.get("remaining") or 0)
        h, m, s = rem // 3600, (rem % 3600) // 60, rem % 60
        self.lbl_timer_display.setText(f"{h:02d}:{m:02d}:{s:02d}")
        if active and rem > 0:
            self.lbl_timer_display.setStyleSheet(
                "QLabel#bigTime { color: #4ade80; font-size: 42px; font-weight: 900; "
                "font-family: Consolas, monospace; background: #052e16; border-radius: 14px; "
                "border: 1px solid #16a34a; padding: 16px; }"
            )
        else:
            self.lbl_timer_display.setStyleSheet("")
        self.btn_timer_start.setEnabled(not active)
        self.btn_timer_pause.setEnabled(active or bool(t_cfg.get("paused")))
        if active:
            self.btn_timer_pause.setText("⏸ 暂停" if not t_cfg.get("paused") else "▶ 继续")
        else:
            self.btn_timer_pause.setText("⏸ 暂停")

    def _start_timer(self) -> None:
        t_cfg = self.state.setdefault("timer", {})
        total = self.spin_h.value() * 3600 + self.spin_m.value() * 60 + self.spin_s.value()
        if total <= 0:
            return
        t_cfg["active"] = True
        t_cfg["remaining"] = total
        t_cfg["label"] = self.txt_timer_name.text().strip() or "倒计时"
        t_cfg["paused"] = False
        t_cfg["ringtone"] = self.cmb_timer_ring.currentData() or "beep"
        t_cfg["tts"] = bool(self.chk_timer_tts.isChecked())
        self.callbacks.save_state()
        self._update_ui_state()

    def _pause_timer(self) -> None:
        t_cfg = self.state.setdefault("timer", {})
        if t_cfg.get("active"):
            t_cfg["active"] = False
            t_cfg["paused"] = True
        elif t_cfg.get("paused") and int(t_cfg.get("remaining") or 0) > 0:
            t_cfg["active"] = True
            t_cfg["paused"] = False
        self.callbacks.save_state()
        self._update_ui_state()

    def _reset_timer(self) -> None:
        t_cfg = self.state.setdefault("timer", {})
        t_cfg["active"] = False
        t_cfg["remaining"] = 0
        t_cfg["paused"] = False
        stop_ringtone()
        self.callbacks.save_state()
        self._update_ui_state()

    def _add_alarm(self) -> None:
        time_str = self.time_alarm.time().toString("HH:mm")
        name = self.txt_alarm_name.text().strip() or "闹钟"
        repeat = "once" if self.cmb_alarm_repeat.currentIndex() == 0 else "daily"
        alarm = {
            "id": str(uuid.uuid4())[:8],
            "time": time_str,
            "name": name,
            "repeat": repeat,
            "enabled": True,
            "ringtone": self.cmb_alarm_ring.currentData() or "beep",
            "tts": bool(self.chk_alarm_tts.isChecked()),
            "last_triggered_date": "",
        }
        self.state.setdefault("alarms", []).append(alarm)
        self.callbacks.save_state()
        self._refresh_alarm_list()
        self.txt_alarm_name.clear()

    def _delete_alarm(self) -> None:
        curr = self.list_alarms.currentItem()
        if not curr:
            return
        alarm_id = curr.data(Qt.ItemDataRole.UserRole)
        self.state["alarms"] = [a for a in (self.state.get("alarms") or []) if a.get("id") != alarm_id]
        self.callbacks.save_state()
        self._refresh_alarm_list()

    def _refresh_alarm_list(self) -> None:
        self.list_alarms.clear()
        name_map = {rid: name for rid, name in RINGTONES}
        for a in self.state.get("alarms") or []:
            rep = "每天" if a.get("repeat") == "daily" else "仅一次"
            st = "开" if a.get("enabled") else "关"
            ring = name_map.get(str(a.get("ringtone") or "beep"), "经典哔哔")
            text = f"⏰ {a.get('time')}  ·  {rep}  ·  {a.get('name')}\n   铃声：{ring}  ·  状态：{st}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, a.get("id"))
            self.list_alarms.addItem(item)
        if self.list_alarms.count() == 0:
            self.list_alarms.addItem("（还没有闹钟，在下方添加）")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.dragging = False
