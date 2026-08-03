"""Floating todo / notes / pomodoro boards with multi-item + theme colors."""

from __future__ import annotations

import uuid

from PyQt6.QtCore import Qt, QPoint, QRect, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QMouseEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from productivity import NoteManager, PomodoroTimer, TodoBoardsStore, TodoManager

NOTE_COLORS = [
    "#fef08a",
    "#bbf7d0",
    "#bfdbfe",
    "#fecaca",
    "#e9d5ff",
    "#fed7aa",
    "#f1f5f9",
]


def _luma(hex_color: str) -> float:
    c = QColor(hex_color)
    # relative luminance
    return 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()


def _fg_on(bg: str) -> str:
    """Readable text color on background."""
    return "#0f172a" if _luma(bg) > 0.55 else "#f8fafc"


def _muted_on(bg: str) -> str:
    return "#334155" if _luma(bg) > 0.55 else "#94a3b8"


def _clamp_widget_to_screens(w: QWidget, *, min_w: int = 200, min_h: int = 140) -> None:
    """Keep floating boards on a visible screen after multi-monitor / DPI changes."""
    try:
        screens = QGuiApplication.screens()
        if not screens:
            return
        # Prefer screen under the window center; else primary
        center = w.frameGeometry().center()
        scr = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        if scr is None:
            return
        ag: QRect = scr.availableGeometry()
        # Clamp size so it never exceeds available area
        nw = max(min_w, min(w.width(), max(min_w, ag.width() - 16)))
        nh = max(min_h, min(w.height(), max(min_h, ag.height() - 16)))
        if nw != w.width() or nh != w.height():
            w.resize(nw, nh)
        x = int(w.x())
        y = int(w.y())
        # Keep fully on-screen with a small margin
        x = max(ag.left() + 4, min(x, ag.right() - w.width() - 4))
        y = max(ag.top() + 4, min(y, ag.bottom() - w.height() - 4))
        if x != w.x() or y != w.y():
            w.move(x, y)
    except Exception:
        pass


# Pet-style pastel presets: (body, bar/accent, fg)
PET_TODO_PRESETS = [
    ("#f0fdf4", "#86efac", "#14532d"),  # mint green (default, matches pet screenshot)
    ("#fffceb", "#fde047", "#713f12"),  # yellow
    ("#eff6ff", "#93c5fd", "#1e3a8a"),  # blue
    ("#fdf2f8", "#f9a8d4", "#9d174d"),  # pink
    ("#faf5ff", "#d8b4fe", "#6b21a8"),  # purple
]
PET_NOTE_PRESETS = [
    ("#dbeafe", "#93c5fd", "#1e3a8a"),  # soft blue (matches pet screenshot)
    ("#fef08a", "#fde047", "#713f12"),
    ("#bbf7d0", "#86efac", "#14532d"),
    ("#fbcfe8", "#f9a8d4", "#9d174d"),
    ("#e9d5ff", "#d8b4fe", "#6b21a8"),
]


def _pet_board_qss(body: str, bar: str, fg: str) -> str:
    """Soft rounded pet-cottage style (matches floating pet todo / sticky)."""
    return f"""
    QFrame#box {{
        background: {body};
        border: 1px solid {bar};
        border-radius: 12px;
    }}
    QFrame#titleBar {{
        background: {bar};
        border: 0;
        border-top-left-radius: 12px;
        border-top-right-radius: 12px;
    }}
    QLabel {{ color: {fg}; background: transparent; }}
    QLabel#hint {{ color: {fg}; font-size: 11px; font-weight: 500; }}
    /* Do NOT style all QWidget — it hides QCheckBox indicators */
    QLineEdit#boardTitle, QLineEdit#noteTitle {{
        background: transparent; border: none; color: {fg};
        font-weight: 700; font-size: 13px; padding: 2px 6px;
    }}
    QLineEdit#todoInput, QLineEdit, QTextEdit {{
        background: rgba(255,255,255,0.72); color: {fg};
        border: 1px solid {bar}; border-radius: 8px;
        padding: 7px 9px; font-size: 13px;
        selection-background-color: {bar}; selection-color: {fg};
    }}
    QListWidget {{
        background: transparent; border: 0; outline: 0; color: {fg};
        font-size: 13px;
    }}
    QListWidget::item {{
        padding: 8px 6px 8px 4px; border-radius: 8px; margin: 3px 0;
        border: 1px solid rgba(15,23,42,0.08);
        background: rgba(255,255,255,0.45);
        min-height: 28px;
    }}
    QListWidget::item:hover {{
        background: rgba(255,255,255,0.75);
        border: 1px dashed {fg};
    }}
    QListWidget::item:selected {{
        background: {bar}aa;
        border: 1px solid {fg};
    }}
    /* Drop indicator line while reordering */
    QListWidget::item:selected:!active {{
        background: {bar}66;
    }}
    QPushButton#iconBtn {{
        background: transparent; border: 0; color: {fg};
        font-size: 14px; min-width: 28px; min-height: 28px; border-radius: 8px;
        padding: 2px;
    }}
    QPushButton#iconBtn:hover {{ background: rgba(0,0,0,0.08); }}
    /* Pin icon only — solid fill when on top, ghost when not */
    QPushButton#pinOn {{
        background: rgba(20, 83, 45, 0.92); color: #ecfdf5;
        border: 0; font-size: 15px; min-width: 28px; min-height: 28px;
        border-radius: 8px; padding: 2px;
    }}
    QPushButton#pinOn:hover {{ background: rgba(22, 101, 52, 1); }}
    QPushButton#pinOff {{
        background: transparent; color: {fg};
        border: 0; font-size: 15px; min-width: 28px; min-height: 28px;
        border-radius: 8px; padding: 2px;
    }}
    QPushButton#pinOff:hover {{ background: rgba(0,0,0,0.08); }}
    QPushButton#act {{
        background: {bar}; border: 1px solid {bar}; border-radius: 10px;
        padding: 7px 12px; font-weight: 700; color: {fg}; font-size: 12px;
    }}
    QPushButton#act:hover {{ background: {bar}cc; }}
    QPushButton#addBtn {{
        background: {bar}; border: 1px solid {bar}; border-radius: 10px;
        padding: 7px 14px; font-weight: 800; color: {fg}; font-size: 12px;
        min-width: 56px;
    }}
    QPushButton#addBtn:hover {{ background: {bar}dd; }}
    """


def _board_qss(bg: str = "#f0fdf4", accent: str = "#86efac") -> str:
    """Backward-compatible wrapper → pet soft style."""
    fg = _fg_on(bg)
    return _pet_board_qss(bg, accent, fg)


class _CornerResizeGrip(QWidget):
    """Bottom-right drag handle to resize frameless floating boards (pet-style)."""

    def __init__(self, host: QWidget, *, min_w: int = 220, min_h: int = 160, on_resized=None):
        super().__init__(host)
        self._host = host
        self._min_w = min_w
        self._min_h = min_h
        self._on_resized = on_resized
        self._drag_origin: QPoint | None = None
        self._start_size: QSize | None = None
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setStyleSheet(
            "background: transparent; border: none;"
            "border-right: 3px solid rgba(15,23,42,0.35);"
            "border-bottom: 3px solid rgba(15,23,42,0.35);"
            "border-bottom-right-radius: 4px;"
        )
        self.reposition()
        self.raise_()

    def reposition(self) -> None:
        self.move(max(0, self._host.width() - self.width() - 4), max(0, self._host.height() - self.height() - 4))

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = e.globalPosition().toPoint()
            self._start_size = self._host.size()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_origin is None or self._start_size is None:
            return
        delta = e.globalPosition().toPoint() - self._drag_origin
        nw = max(self._min_w, self._start_size.width() + delta.x())
        nh = max(self._min_h, self._start_size.height() + delta.y())
        self._host.resize(nw, nh)
        self.reposition()
        e.accept()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self._drag_origin is not None and callable(self._on_resized):
            try:
                self._on_resized(self._host.width(), self._host.height())
            except Exception:
                pass
        self._drag_origin = None
        self._start_size = None
        super().mouseReleaseEvent(e)


class _DragBase(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dragging = False
        self.drag_pos = QPoint()
        self._pinned = True
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(220, 160)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        # Don't start window drag from resize grip or interactive children
        if e.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(e.position().toPoint())
            if isinstance(child, _CornerResizeGrip):
                return
            # Only drag from empty frame areas / title line edits handled separately
            if isinstance(child, (QListWidget, QTextEdit, QLineEdit, QPushButton)):
                return
            self.dragging = True
            self.drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self.dragging and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self.drag_pos)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self.dragging = False

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        grip = getattr(self, "_grip", None)
        if grip is not None:
            grip.reposition()

    def _apply_pin_flags(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._pinned:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()


class _TodoCheckBtn(QPushButton):
    """Soft pet-style checkbox (always visible; native indicators fail on translucent boards)."""

    def __init__(self, done: bool = False, fg: str = "#14532d", parent=None):
        super().__init__(parent)
        self._fg = fg or "#14532d"
        self.setObjectName("todoCheckBtn")
        self.setCheckable(True)
        self.setChecked(bool(done))
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("勾选完成 · 再点取消")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.toggled.connect(lambda _on: self._sync_look())
        self._sync_look()

    def set_fg(self, fg: str) -> None:
        self._fg = fg or "#14532d"
        self._sync_look()

    def _sync_look(self) -> None:
        # Soft cottage style: thin border, gentle green when done
        if self.isChecked():
            self.setText("✓")
            self.setStyleSheet(
                """
                QPushButton#todoCheckBtn {
                    background: #86efac; color: #14532d;
                    border: 1px solid #4ade80; border-radius: 5px;
                    font-weight: 800; font-size: 11px; padding: 0;
                }
                QPushButton#todoCheckBtn:hover { background: #4ade80; }
                """
            )
        else:
            self.setText("")
            fg = self._fg
            self.setStyleSheet(
                f"""
                QPushButton#todoCheckBtn {{
                    background: rgba(255,255,255,0.95); color: {fg};
                    border: 1.5px solid rgba(15,23,42,0.28); border-radius: 5px;
                    font-weight: 700; font-size: 11px; padding: 0;
                }}
                QPushButton#todoCheckBtn:hover {{
                    background: #ffffff; border-color: {fg};
                }}
                """
            )


class _TodoRow(QFrame):
    """One todo row: soft check | text | up/down — original pet list look."""

    toggled = pyqtSignal(str, bool)  # id, done
    move_up = pyqtSignal(str)
    move_down = pyqtSignal(str)
    activated = pyqtSignal(str)  # selected for delete etc.

    def __init__(self, tid: str, text: str, done: bool, fg: str, parent=None, bar: str = "#86efac"):
        super().__init__(parent)
        self.tid = tid
        self._fg = fg
        self._bar = bar or "#86efac"
        self.setObjectName("todoRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 4, 5)
        lay.setSpacing(8)

        self.check = _TodoCheckBtn(done, fg)
        self.check.toggled.connect(self._on_check)
        lay.addWidget(self.check, 0, Qt.AlignmentFlag.AlignVCenter)

        self.lbl = QLabel(text)
        self.lbl.setWordWrap(True)
        self.lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl.setToolTip("点文字也可切换完成")
        self.lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.lbl.mousePressEvent = self._label_click  # type: ignore[method-assign]
        self._apply_done_style(done, fg)
        lay.addWidget(self.lbl, 1)

        self.btn_up = QPushButton("▲")
        self.btn_up.setObjectName("orderBtn")
        self.btn_up.setFixedSize(24, 22)
        self.btn_up.setToolTip("上移")
        self.btn_up.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_up.clicked.connect(lambda: self.move_up.emit(self.tid))
        lay.addWidget(self.btn_up)

        self.btn_down = QPushButton("▼")
        self.btn_down.setObjectName("orderBtn")
        self.btn_down.setFixedSize(24, 22)
        self.btn_down.setToolTip("下移")
        self.btn_down.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_down.clicked.connect(lambda: self.move_down.emit(self.tid))
        lay.addWidget(self.btn_down)

        self._restyle_row(fg, selected=False)

    def _restyle_row(self, fg: str, selected: bool = False) -> None:
        self._fg = fg
        bar = self._bar
        # Soft white cards like original pet list items (not dark slate)
        if selected:
            bg = f"{bar}55"
            bd = f"1px solid {bar}"
        else:
            bg = "rgba(255,255,255,0.72)"
            bd = "1px solid rgba(15,23,42,0.08)"
        self.setStyleSheet(
            f"""
            QFrame#todoRow {{
                background: {bg};
                border: {bd};
                border-radius: 8px;
            }}
            QFrame#todoRow:hover {{
                background: rgba(255,255,255,0.92);
                border: 1px solid {bar};
            }}
            QPushButton#orderBtn {{
                background: transparent; color: {fg};
                border: 0; border-radius: 5px;
                font-size: 10px; font-weight: 700; padding: 0;
            }}
            QPushButton#orderBtn:hover {{ background: rgba(15,23,42,0.08); }}
            QPushButton#orderBtn:disabled {{ color: rgba(15,23,42,0.22); background: transparent; }}
            """
        )
        if hasattr(self, "check") and isinstance(self.check, _TodoCheckBtn):
            self.check.set_fg(fg)

    def set_selected(self, on: bool) -> None:
        self._restyle_row(self._fg, selected=on)

    def _label_click(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.tid)
            self.check.setChecked(not self.check.isChecked())
            e.accept()
            return
        QLabel.mousePressEvent(self.lbl, e)

    def _on_check(self, on: bool) -> None:
        self._apply_done_style(on, self._fg)
        self.toggled.emit(self.tid, on)

    def _apply_done_style(self, done: bool, fg: str | None) -> None:
        font = self.lbl.font()
        font.setStrikeOut(bool(done))
        font.setBold(False)
        self.lbl.setFont(font)
        base = self.lbl.text().replace("  ✓", "").replace(" ✓", "").strip()
        if done:
            self.lbl.setStyleSheet(
                "color: rgba(100,116,139,0.95); background: transparent; font-size: 13px;"
            )
            self.lbl.setText(base)
        else:
            color = fg or self._fg or "#14532d"
            self.lbl.setStyleSheet(
                f"color: {color}; background: transparent; font-size: 13px; font-weight: 600;"
            )
            self.lbl.setText(base)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.tid)
        super().mousePressEvent(e)


class TodoBoard(_DragBase):
    """One floating todo list. Use ＋ to open another list board."""

    def __init__(
        self,
        board: dict,
        on_save,
        parent=None,
        *,
        on_add_board=None,
        on_close_board=None,
    ):
        super().__init__(parent)
        self.board = board
        self.on_save = on_save
        self.on_add_board = on_add_board
        self.on_close_board = on_close_board
        self.mgr = TodoManager(board)
        # Default mint green like pet screenshot
        self.color = str(board.get("color") or "#f0fdf4")
        self.bar_color = str(board.get("bar_color") or "#86efac")
        self._pinned = bool(board.get("pinned", True))
        self._collapsed = False
        self._full_h = int(board.get("height") or 380)
        self._selected_tid: str | None = None
        self._rows: dict[str, _TodoRow] = {}
        self.resize(int(board.get("width") or 300), self._full_h)
        self._build()
        self._apply_color()
        self._apply_pin_flags()
        self.refresh()

    def board_id(self) -> str:
        return str(self.board.get("id") or "")

    def _summary_title(self) -> str:
        items = self.mgr.list_items()
        open_items = [str(t.get("text") or "").strip() for t in items if not t.get("done")]
        open_items = [t for t in open_items if t]
        title = self.title_edit.text().strip() or str(self.board.get("title") or "待办")
        n = len(items)
        done = n - len(open_items)
        if open_items:
            first = open_items[0]
            if len(first) > 14:
                first = first[:14] + "…"
            extra = f" 等{len(open_items)}项" if len(open_items) > 1 else ""
            return f"{title} · ☐ {first}{extra}"
        if n:
            return f"{title} · 全部完成 ({done}/{n})"
        return f"{title} · 暂无事项"

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.box = QFrame(objectName="box")
        self.lay = QVBoxLayout(self.box)
        self.lay.setContentsMargins(0, 0, 0, 10)
        self.lay.setSpacing(8)

        # —— Title bar (pet style) ——
        self.title_bar = QFrame(objectName="titleBar")
        head = QHBoxLayout(self.title_bar)
        head.setContentsMargins(10, 4, 6, 4)
        head.setSpacing(2)
        self.title_edit = QLineEdit(str(self.board.get("title") or "✓ 待办清单"))
        self.title_edit.setObjectName("boardTitle")
        self.title_edit.setPlaceholderText("待办清单")
        self.title_edit.setMinimumHeight(26)
        self.title_edit.editingFinished.connect(self._rename)
        head.addWidget(self.title_edit, 1)

        def _icon(text: str, tip: str, slot) -> QPushButton:
            b = QPushButton(text, objectName="iconBtn")
            b.setFixedSize(28, 28)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            head.addWidget(b)
            return b

        self.btn_color = _icon("🎨", "更改面板颜色", self._pick_color)
        self.btn_new = _icon("＋", "再开一个待办窗口", self._add_another)
        # Pin: icon only; hover tooltip explains 已置顶 / 未置顶
        self.btn_pin = QPushButton("📌", objectName="pinOn")
        self.btn_pin.setFixedSize(28, 28)
        self.btn_pin.clicked.connect(self._toggle_pin)
        head.addWidget(self.btn_pin)
        self.btn_fold = _icon("▾", "折叠：只显示名称", self._toggle_collapse)
        self.btn_del_board = _icon("🗑", "永久删除此待办窗口", self._delete_board)
        self.btn_close = _icon("✕", "关闭（下次不自动打开）", self._close)
        self.lay.addWidget(self.title_bar)
        self.lbl_title = self.title_edit
        self._sync_pin_btn()
        # Drag window from title bar (pet-style)
        self.title_bar.mousePressEvent = self._bar_press  # type: ignore[method-assign]
        self.title_bar.mouseMoveEvent = self._bar_move  # type: ignore[method-assign]
        self.title_bar.mouseReleaseEvent = self._bar_release  # type: ignore[method-assign]

        self.body_wrap = QWidget()
        bl = QVBoxLayout(self.body_wrap)
        bl.setContentsMargins(12, 0, 12, 0)
        bl.setSpacing(8)

        row = QHBoxLayout()
        self.inp = QLineEdit()
        self.inp.setObjectName("todoInput")
        self.inp.setPlaceholderText("写一条待办，回车添加…")
        self.inp.setMinimumHeight(34)
        self.inp.returnPressed.connect(self._add)
        self.btn_add = QPushButton("添加", objectName="addBtn")
        self.btn_add.setMinimumHeight(34)
        self.btn_add.clicked.connect(self._add)
        row.addWidget(self.inp, 1)
        row.addWidget(self.btn_add)
        bl.addLayout(row)

        # Scroll list — keep viewport transparent so soft white rows sit on pastel board
        self.scroll = QScrollArea()
        self.scroll.setObjectName("todoScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(140)
        self.scroll.setStyleSheet(
            "QScrollArea#todoScroll, QScrollArea#todoScroll > QWidget > QWidget {"
            " background: transparent; border: 0; }"
            "QScrollBar:vertical { width: 8px; background: transparent; margin: 2px; }"
            "QScrollBar::handle:vertical { background: rgba(15,23,42,0.18); border-radius: 4px; min-height: 24px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        self.list_host = QWidget()
        self.list_host.setObjectName("todoListHost")
        self.list_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.list_host.setStyleSheet("QWidget#todoListHost { background: transparent; }")
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(4)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(self.list_host)
        try:
            self.scroll.viewport().setStyleSheet("background: transparent;")
            self.scroll.viewport().setAutoFillBackground(False)
        except Exception:
            pass
        bl.addWidget(self.scroll, 1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        for text, slot in (
            ("完成/取消", self._toggle_selected),
            ("删除", self._delete),
            ("清已完成", self._clear_done),
        ):
            b = QPushButton(text, objectName="act")
            b.setMinimumHeight(32)
            b.clicked.connect(slot)
            row2.addWidget(b)
        bl.addLayout(row2)

        tip = QLabel("勾选完成 · 点文字也可 · ▲▼ 调序 · 拖标题栏移动")
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        bl.addWidget(tip)

        self.lay.addWidget(self.body_wrap, 1)
        root.addWidget(self.box)
        self._grip = _CornerResizeGrip(self, min_w=260, min_h=240, on_resized=self._on_resized)
        self._grip.raise_()

    def _toggle_selected(self) -> None:
        tid = self._selected_tid
        if not tid:
            # fallback first item
            items = self.mgr.list_items()
            if not items:
                return
            tid = str(items[0].get("id") or "")
        if tid:
            self.mgr.toggle(tid)
            self.on_save()
            self.refresh()

    def _bar_press(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            # Don't start drag when clicking buttons
            child = self.title_bar.childAt(e.position().toPoint())
            if isinstance(child, QPushButton):
                return
            self.dragging = True
            self.drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def _bar_move(self, e: QMouseEvent) -> None:
        if self.dragging and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self.drag_pos)
            e.accept()

    def _bar_release(self, e: QMouseEvent) -> None:
        if self.dragging:
            self._persist_geometry()
        self.dragging = False
        e.accept()

    def _persist_geometry(self) -> None:
        """Remember screen position + size for next open."""
        if self._collapsed:
            return
        self.board["x"] = int(self.x())
        self.board["y"] = int(self.y())
        self.board["width"] = int(self.width())
        self.board["height"] = int(self.height())
        self._full_h = int(self.height())
        self.on_save()

    def _on_resized(self, w: int, h: int) -> None:
        if self._collapsed:
            return
        self.board["width"] = int(w)
        self.board["height"] = int(h)
        self.board["x"] = int(self.x())
        self.board["y"] = int(self.y())
        self._full_h = int(h)
        self.on_save()

    def _sync_pin_btn(self) -> None:
        """Icon-only pin; state via style + hover tooltip (悬浮字)."""
        if self._pinned:
            self.btn_pin.setObjectName("pinOn")
            self.btn_pin.setText("📌")  # solid green bg = 钉住
            self.btn_pin.setToolTip("已置顶：固定在所有窗口最前面\n再点一下取消置顶")
        else:
            self.btn_pin.setObjectName("pinOff")
            self.btn_pin.setText("📍")  # hollow / outline feel via transparent bg
            self.btn_pin.setToolTip("未置顶：可被其他窗口挡住\n点此固定到所有窗口最前面")
        self.btn_pin.style().unpolish(self.btn_pin)
        self.btn_pin.style().polish(self.btn_pin)
        self.btn_pin.update()

    def _move_item(self, tid: str, delta: int) -> None:
        ids = [str(t.get("id") or "") for t in self.mgr.list_items()]
        if tid not in ids:
            return
        i = ids.index(tid)
        j = i + delta
        if j < 0 or j >= len(ids):
            return
        ids[i], ids[j] = ids[j], ids[i]
        self.mgr.reorder(ids)
        self.on_save()
        self._selected_tid = tid
        self.refresh()

    def _on_row_toggled(self, tid: str, done: bool) -> None:
        for t in self.mgr.list_items():
            if str(t.get("id") or "") == tid:
                if bool(t.get("done")) != done:
                    self.mgr.toggle(tid)
                break
        self.on_save()
        row = self._rows.get(tid)
        if row is not None:
            row.check.blockSignals(True)
            row.check.setChecked(done)
            row.check.blockSignals(False)
            row._apply_done_style(done, _fg_on(self.color))

    def _apply_color(self) -> None:
        fg = _fg_on(self.color)
        # Prefer stored bar; else derive from presets
        bar = self.bar_color or "#86efac"
        for body, b, f in PET_TODO_PRESETS:
            if body.lower() == self.color.lower() or b.lower() == bar.lower():
                self.color, bar, fg = body, b, f
                break
        self.bar_color = bar
        qss = _pet_board_qss(self.color, bar, fg)
        self.box.setStyleSheet(qss)
        self.board["color"] = self.color
        self.board["bar_color"] = bar
        self.on_save()

    def _rename(self) -> None:
        name = self.title_edit.text().strip() or "待办"
        self.title_edit.setText(name)
        self.board["title"] = name
        self.on_save()

    def _add_another(self) -> None:
        self._rename()
        if callable(self.on_add_board):
            self.on_add_board()

    def _close(self) -> None:
        """Hide and mark auto_open=False so next launch / 打开待办 won't reopen it."""
        self._rename()
        self._persist_geometry()
        self.board["auto_open"] = False
        self.on_save()
        self.hide()
        if callable(self.on_close_board):
            self.on_close_board(self.board_id(), delete=False)

    def _delete_board(self) -> None:
        """Permanently remove this todo board from storage."""
        from PyQt6.QtWidgets import QMessageBox

        n = len(self.mgr.list_items())
        title = self.title_edit.text().strip() or "待办"
        msg = f"确定永久删除待办窗口「{title}」吗？"
        if n:
            msg += f"\n其中还有 {n} 条事项，删除后不可恢复。"
        reply = QMessageBox.question(
            self,
            "删除待办窗口",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.hide()
        if callable(self.on_close_board):
            self.on_close_board(self.board_id(), delete=True)

    def _toggle_pin(self) -> None:
        self._pinned = not self._pinned
        self.board["pinned"] = self._pinned
        self.on_save()
        self._apply_pin_flags()
        self._sync_pin_btn()
        if hasattr(self, "_grip") and self._grip is not None:
            self._grip.raise_()

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self.body_wrap.setVisible(not self._collapsed)
        if self._collapsed:
            self._persist_geometry()
            title = self.title_edit.text().strip() or str(self.board.get("title") or "✓ 待办清单")
            n = len(self.mgr.list_items())
            open_n = sum(1 for t in self.mgr.list_items() if not t.get("done"))
            self.title_edit.setText(f"{title}  ·  {open_n}/{n}" if n else title)
            self.title_edit.setReadOnly(True)
            self.btn_fold.setText("▸")
            self.btn_fold.setToolTip("展开详情")
            for b in (self.btn_new, self.btn_pin, self.btn_color, self.btn_del_board, self.btn_close):
                b.hide()
            if hasattr(self, "_grip") and self._grip is not None:
                self._grip.hide()
            self._full_h = max(self.height(), 280)
            self.setMinimumHeight(0)
            self.setMaximumHeight(40)
            self.setFixedHeight(40)
        else:
            self.title_edit.setReadOnly(False)
            self.title_edit.setText(str(self.board.get("title") or "✓ 待办清单"))
            self.btn_fold.setText("▾")
            self.btn_fold.setToolTip("折叠：只显示名称")
            for b in (self.btn_new, self.btn_pin, self.btn_color, self.btn_del_board, self.btn_close):
                b.show()
            self._sync_pin_btn()
            if hasattr(self, "_grip") and self._grip is not None:
                self._grip.show()
                self._grip.reposition()
            self.setMinimumHeight(240)
            self.setMaximumHeight(16777215)
            self.resize(self.width(), self._full_h)

    def _pick_color(self) -> None:
        # Cycle pet presets (same as pet color menu simplicity)
        names = [p[0].lower() for p in PET_TODO_PRESETS]
        try:
            idx = names.index(self.color.lower())
        except ValueError:
            idx = 0
        idx = (idx + 1) % len(PET_TODO_PRESETS)
        self.color, self.bar_color, _fg = PET_TODO_PRESETS[idx]
        self._apply_color()
        self.refresh()

    def refresh(self) -> None:
        # Clear rows
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows.clear()
        fg = _fg_on(self.color)
        bar = self.bar_color or "#86efac"
        items = self.mgr.list_items()
        if not items:
            empty = QLabel("还没有待办，在上方添加一条吧")
            empty.setObjectName("hint")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list_lay.addWidget(empty)
        else:
            for i, t in enumerate(items):
                tid = str(t.get("id") or "")
                if not tid:
                    continue
                row = _TodoRow(
                    tid,
                    str(t.get("text") or ""),
                    bool(t.get("done")),
                    fg,
                    bar=bar,
                )
                row.toggled.connect(self._on_row_toggled)
                row.move_up.connect(lambda i=tid: self._move_item(i, -1))
                row.move_down.connect(lambda i=tid: self._move_item(i, 1))
                row.activated.connect(self._select_row)
                row.btn_up.setEnabled(i > 0)
                row.btn_down.setEnabled(i < len(items) - 1)
                if self._selected_tid == tid:
                    row.set_selected(True)
                self.list_lay.addWidget(row)
                self._rows[tid] = row
        self.list_lay.addStretch(1)
        if self._collapsed:
            title = str(self.board.get("title") or "待办")
            n = len(items)
            open_n = sum(1 for t in items if not t.get("done"))
            self.title_edit.setText(f"{title}  ·  {open_n}/{n}" if n else title)

    def _select_row(self, tid: str) -> None:
        self._selected_tid = tid
        for k, row in self._rows.items():
            row.set_selected(k == tid)

    def _add(self) -> None:
        text = self.inp.text().strip()
        if not text:
            self.inp.setFocus()
            self.inp.setPlaceholderText("请先输入内容再添加…")
            return
        if self._collapsed:
            self._toggle_collapse()
        self.mgr.add(text)
        self.inp.clear()
        self.inp.setPlaceholderText("写一条待办，回车添加…")
        self.on_save()
        self.refresh()
        self.inp.setFocus()

    def _delete(self) -> None:
        tid = self._selected_tid
        if not tid:
            items = self.mgr.list_items()
            if not items:
                return
            tid = str(items[0].get("id") or "")
        if tid:
            self.mgr.remove(str(tid))
            self._selected_tid = None
            self.on_save()
            self.refresh()

    def _clear_done(self) -> None:
        self.mgr.clear_done()
        self._selected_tid = None
        self.on_save()
        self.refresh()


class TodosController:
    """Manages multiple TodoBoard windows (like multi sticky notes)."""

    def __init__(self, state: dict, on_save):
        self.state = state
        self.on_save = on_save
        self.store = TodoBoardsStore(state)
        self.windows: dict[str, TodoBoard] = {}

    def show_all(self) -> None:
        """Only open boards that are still auto_open (not closed/cleaned by user)."""
        boards = [b for b in self.store.list_boards() if b.get("auto_open", True)]
        if boards:
            for b in boards:
                self._ensure_window(b)
            return
        # None currently open — open a fresh board (closed ones stay closed until ＋ or 删除)
        self.add_board()

    def add_board(self) -> None:
        b = self.store.add_board()
        b["auto_open"] = True
        self.on_save()
        self._ensure_window(b)

    def _ensure_window(self, board: dict) -> None:
        bid = str(board.get("id") or "")
        if not bid:
            return
        board["auto_open"] = True
        if bid in self.windows:
            w = self.windows[bid]
            if not w.isVisible():
                w.show()
            w.raise_()
            w.activateWindow()
            return
        w = TodoBoard(
            board,
            self.on_save,
            on_add_board=self.add_board,
            on_close_board=self._on_close,
        )
        # Restore last position if remembered; otherwise cascade once
        if board.get("x") is not None and board.get("y") is not None:
            try:
                w.move(int(board["x"]), int(board["y"]))
            except (TypeError, ValueError):
                off = 28 * (len(self.windows) % 10)
                w.move(100 + off, 100 + off)
        else:
            off = 28 * (len(self.windows) % 10)
            w.move(100 + off, 100 + off)
        _clamp_widget_to_screens(w, min_w=260, min_h=240)
        w.show()
        w.raise_()
        self.windows[bid] = w

    def _on_close(self, board_id: str, delete: bool = False) -> None:
        w = self.windows.pop(board_id, None)
        if w is not None:
            try:
                if not delete:
                    w._persist_geometry()
                w.hide()
                w.deleteLater()
            except Exception:
                pass
        if delete:
            self.store.remove_board(board_id)
            self.on_save()


class StickyNoteWindow(_DragBase):
    """One floating sticky note with color. Use ＋ to open another note."""

    def __init__(
        self,
        note: dict,
        mgr: NoteManager,
        on_save,
        on_close_note,
        parent=None,
        *,
        on_add_note=None,
    ):
        super().__init__(parent)
        self.note = note
        self.mgr = mgr
        self.on_save = on_save
        self.on_close_note = on_close_note
        self.on_add_note = on_add_note
        self.resize(int(note.get("width") or 260), int(note.get("height") or 240))
        # Soft blue like pet screenshot by default
        self.color = str(note.get("color") or "#dbeafe")
        self.bar_color = str(note.get("bar_color") or "#93c5fd")
        self._pinned = bool(note.get("pinned", True))
        self._collapsed = False
        self._full_h = int(note.get("height") or 240)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.box = QFrame(objectName="box")
        lay = QVBoxLayout(self.box)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(6)

        # Title bar — pet sticky style
        self.title_bar = QFrame(objectName="titleBar")
        head = QHBoxLayout(self.title_bar)
        head.setContentsMargins(10, 4, 6, 4)
        head.setSpacing(2)
        self.title = QLineEdit(str(note.get("title") or "便签"))
        self.title.setObjectName("noteTitle")
        self.title.setPlaceholderText("便签")
        head.addWidget(self.title, 1)

        def _icon(text: str, tip: str, slot) -> QPushButton:
            b = QPushButton(text, objectName="iconBtn")
            b.setFixedSize(28, 28)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            head.addWidget(b)
            return b

        self.btn_new = _icon("＋", "再加一张便签", self._add_another)
        self.btn_color = _icon("🎨", "更改颜色", self._pick_color)
        self.btn_pin = QPushButton("📌", objectName="pinOn")
        self.btn_pin.setFixedSize(28, 28)
        self.btn_pin.clicked.connect(self._toggle_pin)
        head.addWidget(self.btn_pin)
        self.btn_fold = _icon("▾", "折叠只显示标题", self._toggle_collapse)
        self.btn_delete = _icon("🗑", "永久删除这张便签", self._delete_note)
        self.btn_close = _icon("✕", "关闭（下次不自动打开）", self._close_and_save)
        lay.addWidget(self.title_bar)
        self.title_bar.mousePressEvent = self._note_bar_press  # type: ignore[method-assign]
        self.title_bar.mouseMoveEvent = self._note_bar_move  # type: ignore[method-assign]
        self.title_bar.mouseReleaseEvent = self._note_bar_release  # type: ignore[method-assign]

        body_wrap = QWidget()
        bw = QVBoxLayout(body_wrap)
        bw.setContentsMargins(10, 0, 10, 4)
        bw.setSpacing(4)
        self.body = QTextEdit()
        self.body.setPlaceholderText("写点什么… 右下角可拖动改大小")
        self.body.setPlainText(str(note.get("body") or ""))
        bw.addWidget(self.body, 1)
        lay.addWidget(body_wrap, 1)
        self._body_wrap = body_wrap

        root.addWidget(self.box)
        self._apply_note_style()
        self.title.editingFinished.connect(self._persist)
        self.body.textChanged.connect(self._persist)
        self._grip = _CornerResizeGrip(self, min_w=200, min_h=160, on_resized=self._on_note_resized)
        self._apply_pin_flags()
        self._sync_pin_btn()

    def _on_note_resized(self, w: int, h: int) -> None:
        if self._collapsed:
            return
        self.note["width"] = int(w)
        self.note["height"] = int(h)
        self.note["x"] = int(self.x())
        self.note["y"] = int(self.y())
        self._full_h = int(h)
        self.on_save()

    def _note_bar_press(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            child = self.title_bar.childAt(e.position().toPoint())
            if isinstance(child, QPushButton):
                return
            self.dragging = True
            self.drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def _note_bar_move(self, e: QMouseEvent) -> None:
        if self.dragging and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self.drag_pos)
            e.accept()

    def _note_bar_release(self, e: QMouseEvent) -> None:
        if self.dragging:
            self._persist_note_geometry()
        self.dragging = False
        e.accept()

    def _persist_note_geometry(self) -> None:
        if self._collapsed:
            return
        self.note["x"] = int(self.x())
        self.note["y"] = int(self.y())
        self.note["width"] = int(self.width())
        self.note["height"] = int(self.height())
        self._full_h = int(self.height())
        self.on_save()

    def _sync_pin_btn(self) -> None:
        if self._pinned:
            self.btn_pin.setObjectName("pinOn")
            self.btn_pin.setText("📌")
            self.btn_pin.setToolTip("已置顶：固定在所有窗口最前面\n再点一下取消置顶")
        else:
            self.btn_pin.setObjectName("pinOff")
            self.btn_pin.setText("📍")
            self.btn_pin.setToolTip("未置顶：可被其他窗口挡住\n点此固定到所有窗口最前面")
        self.btn_pin.style().unpolish(self.btn_pin)
        self.btn_pin.style().polish(self.btn_pin)
        self.btn_pin.update()

    def _apply_note_style(self) -> None:
        fg = _fg_on(self.color)
        bar = self.bar_color or "#93c5fd"
        for body, b, f in PET_NOTE_PRESETS:
            if body.lower() == self.color.lower() or b.lower() == bar.lower():
                self.color, bar, fg = body, b, f
                break
        self.bar_color = bar
        self.box.setStyleSheet(_pet_board_qss(self.color, bar, fg))
        self.note["color"] = self.color
        self.note["bar_color"] = bar
        self._sync_pin_btn()

    def _add_another(self) -> None:
        self._persist()
        if callable(self.on_add_note):
            self.on_add_note()

    def _toggle_pin(self) -> None:
        self._pinned = not self._pinned
        self.note["pinned"] = self._pinned
        self.on_save()
        self._apply_pin_flags()
        self._sync_pin_btn()
        if hasattr(self, "_grip") and self._grip is not None:
            self._grip.raise_()

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self._body_wrap.setVisible(not self._collapsed)
        if self._collapsed:
            self._persist_note_geometry()
            name = self.title.text().strip() or "便签"
            self.title.setText(name)
            self.title.setReadOnly(True)
            self.btn_fold.setText("▸")
            self.btn_fold.setToolTip("展开")
            for b in (self.btn_new, self.btn_pin, self.btn_color, self.btn_delete, self.btn_close):
                b.hide()
            if hasattr(self, "_grip") and self._grip is not None:
                self._grip.hide()
            self._full_h = max(self.height(), 180)
            self.setMinimumHeight(0)
            self.setMaximumHeight(36)
            self.setFixedHeight(36)
            self.setToolTip(name)
        else:
            self.title.setReadOnly(False)
            self.btn_fold.setText("▾")
            self.btn_fold.setToolTip("折叠只显示标题")
            for b in (self.btn_new, self.btn_pin, self.btn_color, self.btn_delete, self.btn_close):
                b.show()
            self._sync_pin_btn()
            if hasattr(self, "_grip") and self._grip is not None:
                self._grip.show()
                self._grip.reposition()
            self.setMinimumHeight(160)
            self.setMaximumHeight(16777215)
            self.resize(self.width(), self._full_h)
            self.setToolTip("")
            self._apply_note_style()

    def _persist(self) -> None:
        nid = str(self.note.get("id") or "")
        if not nid:
            return
        self.mgr.update(nid, self.title.text(), self.body.toPlainText())
        for n in self.mgr.list_items():
            if n.get("id") == nid:
                n["color"] = self.note.get("color") or self.color
                n["bar_color"] = self.note.get("bar_color") or self.bar_color
                break
        self._persist_note_geometry()

    def _pick_color(self) -> None:
        names = [p[0].lower() for p in PET_NOTE_PRESETS]
        try:
            idx = names.index(self.color.lower())
        except ValueError:
            idx = 0
        idx = (idx + 1) % len(PET_NOTE_PRESETS)
        self.color, self.bar_color, _fg = PET_NOTE_PRESETS[idx]
        self._apply_note_style()
        self._persist()

    def _close_and_save(self) -> None:
        """Close window; mark auto_open=False so next 打开便签 won't auto-show it."""
        self._persist()
        self._persist_note_geometry()
        self.note["auto_open"] = False
        self.on_save()
        self.on_close_note(str(self.note.get("id") or ""), delete=False)
        self.hide()

    def _delete_note(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        title = self.title.text().strip() or "便签"
        reply = QMessageBox.question(
            self,
            "删除便签",
            f"确定永久删除「{title}」吗？内容不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        nid = str(self.note.get("id") or "")
        self.on_close_note(nid, delete=True)
        self.hide()


class NotesController:
    """Manages multiple sticky note windows. Each note has ＋ to create another."""

    def __init__(self, state: dict, on_save):
        self.state = state
        self.on_save = on_save
        self.mgr = NoteManager(state)
        self.windows: dict[str, StickyNoteWindow] = {}

    def show_all(self) -> None:
        """Only open notes that are still auto_open (user closed/cleaned ones stay away)."""
        notes = [n for n in self.mgr.list_items() if n.get("auto_open", True)]
        if notes:
            for n in notes:
                self._ensure_window(n)
            return
        # None currently open — create one new (closed notes stay closed until 删除)
        self.add_note()

    def add_note(self) -> None:
        n = len(self.mgr.list_items()) + 1
        note = self.mgr.add("便签", "")
        body, bar, _fg = PET_NOTE_PRESETS[(n - 1) % len(PET_NOTE_PRESETS)]
        note["color"] = body
        note["bar_color"] = bar
        note["auto_open"] = True
        self.on_save()
        self._ensure_window(note)

    def _ensure_window(self, note: dict) -> None:
        nid = str(note.get("id") or "")
        if not nid:
            return
        note["auto_open"] = True
        if nid in self.windows:
            w = self.windows[nid]
            # revive closed-but-cached window
            if not w.isVisible():
                w.show()
            w.raise_()
            w.activateWindow()
            return
        w = StickyNoteWindow(
            note,
            self.mgr,
            self.on_save,
            self._on_close,
            on_add_note=self.add_note,
        )
        if note.get("x") is not None and note.get("y") is not None:
            try:
                w.move(int(note["x"]), int(note["y"]))
            except (TypeError, ValueError):
                off = 28 * (len(self.windows) % 10)
                w.move(140 + off, 140 + off)
        else:
            off = 28 * (len(self.windows) % 10)
            w.move(140 + off, 140 + off)
        _clamp_widget_to_screens(w, min_w=200, min_h=160)
        w.show()
        w.raise_()
        self.windows[nid] = w

    def _on_close(self, nid: str, delete: bool = False) -> None:
        w = self.windows.pop(nid, None)
        if w is not None:
            try:
                if not delete:
                    w._persist_note_geometry()
                w.hide()
                w.deleteLater()
            except Exception:
                pass
        if delete and nid:
            self.mgr.remove(nid)
            self.on_save()


class PomodoroBoard(_DragBase):
    """Tomato-red pomodoro — ripe tomato palette + pin-to-front."""

    def __init__(self, state: dict, on_save, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QSpinBox

        self.state = state
        self.on_save = on_save
        self.timer = PomodoroTimer(state)
        pcfg = state.setdefault("pomodoro_ui", {})
        self._pinned = bool(pcfg.get("pinned", True))
        self.resize(int(pcfg.get("width") or 360), int(pcfg.get("height") or 360))
        # Ripe tomato: deep red flesh, green stem accents, warm highlight
        self.setStyleSheet(
            """
            QFrame#box {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #b91c1c, stop:0.45 #dc2626, stop:1 #7f1d1d);
                border: 2px solid #fca5a5; border-radius: 20px;
            }
            QLabel { color: #fff7ed; font-size: 12px; font-weight: 600; background: transparent; }
            QLabel#title { color: #fef2f2; font-size: 16px; font-weight: 900; }
            QLabel#bigTime {
                color: #450a0a; font-size: 52px; font-weight: 900;
                font-family: Consolas, 'Cascadia Mono', 'SF Mono', monospace;
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #fef2f2, stop:1 #fecaca);
                border-radius: 16px;
                border: 2px solid #f87171; padding: 16px 12px;
                min-height: 76px;
            }
            QLabel#statusLine {
                color: #fff7ed; font-size: 14px; font-weight: 800;
                background: rgba(0,0,0,0.22); border-radius: 12px;
                border: 1px solid rgba(254,202,202,0.45); padding: 10px 12px;
            }
            QLabel#section { color: #fee2e2; font-size: 11px; font-weight: 800; }
            QLabel#muted { color: #fecaca; font-size: 11px; }
            QSpinBox {
                background: rgba(0,0,0,0.28); color: #fff7ed; font-size: 15px; font-weight: 800;
                border: 2px solid #86efac; border-radius: 10px; padding: 6px 8px; min-width: 72px;
            }
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #fef2f2, stop:1 #fecaca);
                border: none; color: #7f1d1d; font-weight: 900; font-size: 12px;
                padding: 10px 12px; border-radius: 10px; min-height: 20px;
            }
            QPushButton:hover { background: #fff; color: #991b1b; }
            QPushButton#soft {
                background: rgba(0,0,0,0.22); color: #fee2e2; border: 1px solid #fca5a5;
            }
            QPushButton#soft:hover { background: rgba(0,0,0,0.35); }
            QPushButton#danger {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #450a0a, stop:1 #7f1d1d);
                color: #fecaca; border: 1px solid #f87171;
            }
            QPushButton#pinOn {
                background: #86efac; color: #14532d; font-weight: 900;
            }
            """
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        box = QFrame(objectName="box")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(QLabel("🍅 番茄钟", objectName="title"), 1)
        self.btn_pin = QPushButton("📌", objectName="soft")
        self.btn_pin.setFixedSize(32, 30)
        self.btn_pin.clicked.connect(self._toggle_pin)
        head.addWidget(self.btn_pin)
        x = QPushButton("✕", objectName="soft")
        x.setFixedSize(32, 30)
        x.setToolTip("关闭")
        x.clicked.connect(self.hide)
        head.addWidget(x)
        lay.addLayout(head)

        # Clock face: time only (MM:SS) — never wrap long Chinese into big digits
        self.lbl_time = QLabel("25:00")
        self.lbl_time.setObjectName("bigTime")
        self.lbl_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_time.setWordWrap(False)
        lay.addWidget(self.lbl_time)

        # Status under the clock (paused / 专注中 / …)
        self.lbl_status = QLabel("就绪 · 点击开始")
        self.lbl_status.setObjectName("statusLine")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)
        # keep alias for any external refs
        self.lbl = self.lbl_status

        lay.addWidget(QLabel("时长设置（数字调节）", objectName="section"))
        cfg = self.timer.cfg
        sett = QHBoxLayout()
        sett.addWidget(QLabel("专注"))
        self.spin_work = QSpinBox()
        self.spin_work.setRange(1, 120)
        self.spin_work.setValue(int(cfg.get("work_min") or 25))
        self.spin_work.setSuffix(" 分")
        self.spin_work.setMinimumHeight(36)
        sett.addWidget(self.spin_work)
        sett.addWidget(QLabel("休息"))
        self.spin_break = QSpinBox()
        self.spin_break.setRange(1, 60)
        self.spin_break.setValue(int(cfg.get("break_min") or 5))
        self.spin_break.setSuffix(" 分")
        self.spin_break.setMinimumHeight(36)
        sett.addWidget(self.spin_break)
        lay.addLayout(sett)
        self.spin_work.valueChanged.connect(self._apply_settings)
        self.spin_break.valueChanged.connect(self._apply_settings)

        row = QHBoxLayout()
        for text, slot, oname in (
            ("开始", self._start, "primary"),
            ("暂停", self._pause, "soft"),
            ("继续", self._resume, "soft"),
            ("跳过", self._skip, "soft"),
            ("停止", self._stop, "danger"),
        ):
            b = QPushButton(text, objectName=oname if oname != "primary" else "")
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)
        tip = QLabel("番茄配色 · 📌 可置顶 · 右下角拖动改大小")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        root.addWidget(box)
        self._grip = _CornerResizeGrip(self, min_w=300, min_h=300, on_resized=self._on_pomo_resized)
        self._apply_pin_flags()
        self._sync_pin_btn()
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._refresh)
        self._tick.start(1000)
        self._refresh()

    def _on_pomo_resized(self, w: int, h: int) -> None:
        ui = self.state.setdefault("pomodoro_ui", {})
        ui["width"] = int(w)
        ui["height"] = int(h)
        ui["x"] = int(self.x())
        ui["y"] = int(self.y())
        self.on_save()

    def _sync_pin_btn(self) -> None:
        # Pomodoro uses inline soft/pin styles on dark tomato panel
        if self._pinned:
            self.btn_pin.setText("📌")
            self.btn_pin.setStyleSheet(
                "QPushButton { background:#14532d; color:#bbf7d0; border:none; "
                "border-radius:8px; font-size:15px; font-weight:800; }"
                "QPushButton:hover { background:#166534; }"
            )
            self.btn_pin.setToolTip("已置顶：固定在所有窗口最前面\n再点一下取消置顶")
        else:
            self.btn_pin.setText("📍")
            self.btn_pin.setStyleSheet(
                "QPushButton { background:rgba(0,0,0,0.22); color:#fee2e2; border:1px solid #fca5a5; "
                "border-radius:8px; font-size:15px; }"
                "QPushButton:hover { background:rgba(0,0,0,0.35); }"
            )
            self.btn_pin.setToolTip("未置顶：可被其他窗口挡住\n点此固定到所有窗口最前面")

    def _toggle_pin(self) -> None:
        self._pinned = not self._pinned
        ui = self.state.setdefault("pomodoro_ui", {})
        ui["pinned"] = self._pinned
        ui["x"] = int(self.x())
        ui["y"] = int(self.y())
        self.on_save()
        self._apply_pin_flags()
        self._sync_pin_btn()
        if hasattr(self, "_grip") and self._grip is not None:
            self._grip.raise_()

    def _apply_settings(self) -> None:
        self.timer.configure(
            work_min=int(self.spin_work.value()),
            break_min=int(self.spin_break.value()),
        )
        self.on_save()
        self._refresh()

    def _display_parts(self) -> tuple[str, str]:
        """Return (MM:SS, status line) — clock style, no mixed Chinese in big digits."""
        cfg = self.timer.cfg
        phase = str(cfg.get("phase") or "idle")
        labels = {
            "idle": "空闲",
            "work": "专注中",
            "break": "短休中",
            "long_break": "长休中",
        }
        label = labels.get(phase, phase)
        if phase == "idle":
            mins = int(cfg.get("work_min") or 25)
            return f"{mins:02d}:00", f"就绪 · 专注 {mins} 分 / 休息 {int(cfg.get('break_min') or 5)} 分"
        remaining = self.timer.remaining_seconds()
        mm, ss = divmod(max(0, remaining), 60)
        time_s = f"{mm:02d}:{ss:02d}"
        paused = bool(cfg.get("paused"))
        if paused:
            status = f"已暂停 · {label} · 完成 {int(cfg.get('cycle_count') or 0)} 轮"
        else:
            status = f"{label} · 完成 {int(cfg.get('cycle_count') or 0)} 轮"
        return time_s, status

    def _refresh(self) -> None:
        self.timer.tick()
        time_s, status = self._display_parts()
        self.lbl_time.setText(time_s)
        self.lbl_status.setText(status)

    def _start(self) -> None:
        self._apply_settings()
        self.timer.start_work()
        self.on_save()
        self._refresh()

    def _pause(self) -> None:
        self.timer.pause()
        self.on_save()
        self._refresh()

    def _resume(self) -> None:
        self.timer.resume()
        self.on_save()
        self._refresh()

    def _skip(self) -> None:
        self.timer.skip()
        self.on_save()
        self._refresh()

    def _stop(self) -> None:
        self.timer.stop()
        self.on_save()
        self._refresh()
