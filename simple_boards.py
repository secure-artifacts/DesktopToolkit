"""Floating todo / notes / pomodoro boards with multi-item + theme colors."""

from __future__ import annotations

import uuid

from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtGui import QColor, QMouseEvent
from PyQt6.QtWidgets import (
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
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


def _board_qss(bg: str = "#bfdbfe", accent: str = "#4f46e5") -> str:
    """High-contrast board styles that override app dark palette."""
    fg = _fg_on(bg)
    muted = _muted_on(bg)
    # Opaque input surfaces so text never washes out on yellow stickies
    light = _luma(bg) > 0.55
    input_bg = "#ffffff" if light else "#0f172a"
    soft_bg = "rgba(15,23,42,0.14)" if light else "rgba(255,255,255,0.14)"
    item_bg = "rgba(15,23,42,0.06)" if light else "rgba(255,255,255,0.06)"
    return f"""
    QFrame#box {{
        background: {bg}; border: 2px solid {accent}; border-radius: 14px;
    }}
    QWidget {{ color: {fg}; }}
    QLabel {{ color: {fg}; font-weight: 600; background: transparent; }}
    QLabel#title {{
        color: {fg}; font-size: 16px; font-weight: 900; background: transparent;
    }}
    QLineEdit, QTextEdit, QListWidget {{
        background: {input_bg}; color: {fg};
        border: 1px solid {muted}; border-radius: 8px; padding: 6px;
        selection-background-color: {accent}; selection-color: white;
        font-size: 13px;
    }}
    QLineEdit#boardTitle, QLineEdit#noteTitle {{
        background: transparent; border: none; color: {fg};
        font-weight: 900; font-size: 16px; padding: 2px 4px;
    }}
    QListWidget {{ outline: none; }}
    QListWidget::item {{
        color: {fg}; background: {item_bg}; border-radius: 6px;
        padding: 8px 6px; margin: 2px 0; font-size: 13px;
    }}
    QListWidget::item:selected {{
        background: {accent}; color: white;
    }}
    QPushButton {{
        background: {accent}; color: white; border: none; border-radius: 8px;
        padding: 8px 12px; font-weight: 800; font-size: 13px;
    }}
    QPushButton#soft {{
        background: {soft_bg}; border: 1px solid {fg}; color: {fg};
        font-weight: 800; font-size: 12px; padding: 4px 8px;
    }}
    """


class _DragBase(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dragging = False
        self.drag_pos = QPoint()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self.dragging and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self.drag_pos)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self.dragging = False


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
        self.color = str(board.get("color") or "#fef08a")
        self._pinned = True
        self._collapsed = False
        self._full_h = 420
        self.resize(340, self._full_h)
        self._build()
        self._apply_color()
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
        self.lay.setContentsMargins(12, 10, 12, 12)
        self.lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(5)
        head.setContentsMargins(0, 0, 0, 0)
        # Editable board title — larger, high contrast
        self.title_edit = QLineEdit(str(self.board.get("title") or "待办"))
        self.title_edit.setObjectName("boardTitle")
        self.title_edit.setPlaceholderText("待办列表名称…")
        self.title_edit.setMinimumHeight(28)
        self.title_edit.editingFinished.connect(self._rename)
        head.addWidget(self.title_edit, 1)
        # ＋ open another todo board
        self.btn_new = QPushButton("＋")
        self.btn_new.setFixedSize(32, 30)
        self.btn_new.setToolTip("再开一个待办窗口")
        self.btn_new.clicked.connect(self._add_another)
        head.addWidget(self.btn_new)
        self.btn_pin = QPushButton("置顶")
        self.btn_pin.setFixedHeight(30)
        self.btn_pin.setMinimumWidth(48)
        self.btn_pin.setToolTip("置顶 / 取消置顶")
        self.btn_pin.clicked.connect(self._toggle_pin)
        head.addWidget(self.btn_pin)
        self.btn_fold = QPushButton("折叠")
        self.btn_fold.setFixedHeight(30)
        self.btn_fold.setMinimumWidth(48)
        self.btn_fold.setToolTip("折叠成细条")
        self.btn_fold.clicked.connect(self._toggle_collapse)
        head.addWidget(self.btn_fold)
        self.btn_color = QPushButton("颜色")
        self.btn_color.setFixedHeight(30)
        self.btn_color.setMinimumWidth(48)
        self.btn_color.clicked.connect(self._pick_color)
        head.addWidget(self.btn_color)
        self.btn_close = QPushButton("关闭")
        self.btn_close.setFixedHeight(30)
        self.btn_close.setMinimumWidth(48)
        self.btn_close.clicked.connect(self._close)
        head.addWidget(self.btn_close)
        self.lay.addLayout(head)
        # legacy alias used by collapse
        self.lbl_title = self.title_edit

        self.body_wrap = QWidget()
        bl = QVBoxLayout(self.body_wrap)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        self.list = QListWidget()
        self.list.setMinimumHeight(140)
        bl.addWidget(self.list, 1)
        tip = QLabel("列表内可加多条 · 点标题栏「＋」可多开窗口")
        tip.setStyleSheet("font-size:12px; font-weight:700;")
        bl.addWidget(tip)
        row = QHBoxLayout()
        self.inp = QLineEdit()
        self.inp.setPlaceholderText("输入新待办内容…")
        self.inp.setMinimumHeight(34)
        self.inp.returnPressed.connect(self._add)
        self.btn_add = QPushButton("＋ 添加")
        self.btn_add.setMinimumHeight(34)
        self.btn_add.setMinimumWidth(80)
        self.btn_add.clicked.connect(self._add)
        row.addWidget(self.inp, 1)
        row.addWidget(self.btn_add)
        bl.addLayout(row)
        row2 = QHBoxLayout()
        del_btn = QPushButton("删除选中", objectName="soft")
        del_btn.setMinimumHeight(30)
        del_btn.clicked.connect(self._delete)
        clr = QPushButton("清已完成", objectName="soft")
        clr.setMinimumHeight(30)
        clr.clicked.connect(self._clear_done)
        row2.addWidget(del_btn)
        row2.addWidget(clr)
        bl.addLayout(row2)
        self.lay.addWidget(self.body_wrap, 1)
        root.addWidget(self.box)
        self.list.itemChanged.connect(self._on_item_changed)

    def _header_btn_style(self, fg: str, bg: str) -> str:
        return (
            f"QPushButton {{ background:rgba(0,0,0,0.18); color:{fg}; border:1px solid {fg}; "
            f"border-radius:8px; padding:4px 8px; font-weight:800; font-size:13px; }}"
            f"QPushButton:hover {{ background:rgba(0,0,0,0.28); }}"
        )

    def _apply_color(self) -> None:
        qss = _board_qss(self.color, "#4f46e5")
        self.box.setStyleSheet(qss)
        fg = _fg_on(self.color)
        self.list.setStyleSheet(qss)
        for i in range(self.list.count()):
            self.list.item(i).setForeground(QColor(fg))
        soft = self._header_btn_style(fg, self.color)
        for b in (self.btn_pin, self.btn_fold, self.btn_color, self.btn_close):
            b.setStyleSheet(soft)
        self.btn_new.setStyleSheet(
            f"QPushButton {{ background:{fg}; color:{self.color}; border:none; "
            f"border-radius:8px; font-weight:900; font-size:18px; }}"
            f"QPushButton:hover {{ background:#111827; color:#fef08a; }}"
        )
        self.title_edit.setStyleSheet(
            f"QLineEdit#boardTitle {{ background:transparent; border:none; color:{fg}; "
            f"font-weight:900; font-size:16px; padding:2px 4px; }}"
        )
        self.board["color"] = self.color
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
        self._rename()
        self.hide()
        if callable(self.on_close_board):
            self.on_close_board(self.board_id())

    def _apply_pin(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._pinned:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        self.btn_pin.setText("已置顶" if self._pinned else "置顶")

    def _toggle_pin(self) -> None:
        self._pinned = not self._pinned
        self._apply_pin()

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self.body_wrap.setVisible(not self._collapsed)
        if self._collapsed:
            self.title_edit.setText(self._summary_title())
            self.title_edit.setReadOnly(True)
            self.btn_fold.setText("展开")
            self.btn_new.hide()
            self.btn_pin.hide()
            self.btn_color.hide()
            self.btn_close.hide()
            self._full_h = max(self.height(), 280)
            self.lay.setContentsMargins(8, 4, 6, 4)
            self.lay.setSpacing(0)
            self.setMinimumHeight(0)
            self.setMaximumHeight(36)
            self.setFixedHeight(36)
            self.btn_fold.setFixedHeight(28)
            self.btn_fold.setFixedWidth(48)
        else:
            self.title_edit.setReadOnly(False)
            self.title_edit.setText(str(self.board.get("title") or "待办"))
            self.btn_fold.setText("折叠")
            self.btn_new.show()
            self.btn_pin.show()
            self.btn_color.show()
            self.btn_close.show()
            self.btn_fold.setFixedHeight(30)
            self.btn_fold.setMinimumWidth(48)
            self.btn_fold.setMaximumWidth(16777215)
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.resize(self.width(), self._full_h)
            self.lay.setContentsMargins(12, 10, 12, 12)
            self.lay.setSpacing(8)

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(self.color), self, "待办主题色")
        if c.isValid():
            self.color = c.name()
            self._apply_color()

    def refresh(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        fg = QColor(_fg_on(self.color))
        for t in self.mgr.list_items():
            it = QListWidgetItem(str(t.get("text") or ""))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
            it.setCheckState(Qt.CheckState.Checked if t.get("done") else Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, t.get("id"))
            it.setForeground(fg)
            self.list.addItem(it)
        self.list.blockSignals(False)
        if self._collapsed:
            self.title_edit.setText(self._summary_title())

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
        self.inp.setPlaceholderText("输入新待办内容…")
        self.on_save()
        self.refresh()
        self.inp.setFocus()
        if self.list.count():
            self.list.setCurrentRow(0)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        tid = item.data(Qt.ItemDataRole.UserRole)
        if not tid:
            return
        for t in self.mgr.list_items():
            if t.get("id") == tid:
                want = item.checkState() == Qt.CheckState.Checked
                if bool(t.get("done")) != want:
                    self.mgr.toggle(str(tid))
                new_text = item.text().strip()
                if new_text and new_text != str(t.get("text") or ""):
                    t["text"] = new_text[:200]
                break
        self.on_save()
        if self._collapsed:
            self.title_edit.setText(self._summary_title())

    def _delete(self) -> None:
        it = self.list.currentItem()
        if not it:
            return
        tid = it.data(Qt.ItemDataRole.UserRole)
        if tid:
            self.mgr.remove(str(tid))
            self.on_save()
            self.refresh()

    def _clear_done(self) -> None:
        self.mgr.clear_done()
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
        boards = self.store.list_boards()
        if not boards:
            self.add_board()
            return
        for b in boards:
            self._ensure_window(b)

    def add_board(self) -> None:
        b = self.store.add_board()
        self.on_save()
        self._ensure_window(b)

    def _ensure_window(self, board: dict) -> None:
        bid = str(board.get("id") or "")
        if not bid:
            return
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
        off = 28 * (len(self.windows) % 10)
        w.move(100 + off, 100 + off)
        w.show()
        w.raise_()
        self.windows[bid] = w

    def _on_close(self, board_id: str) -> None:
        self.windows.pop(board_id, None)


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
        self.resize(280, 260)
        self.color = str(note.get("color") or NOTE_COLORS[0])
        self._pinned = True
        self._collapsed = False
        self._full_h = 260
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.box = QFrame(objectName="box")
        lay = QVBoxLayout(self.box)
        lay.setContentsMargins(10, 8, 10, 10)
        head = QHBoxLayout()
        head.setSpacing(3)
        self.title = QLineEdit(str(note.get("title") or "便签"))
        self.title.setObjectName("noteTitle")
        self.title.setPlaceholderText("便签标题…")
        head.addWidget(self.title, 1)
        # ＋ 新建另一张便签（可多个）
        self.btn_new = QPushButton("＋")
        self.btn_new.setFixedSize(26, 24)
        self.btn_new.setToolTip("再加一张便签")
        self.btn_new.clicked.connect(self._add_another)
        head.addWidget(self.btn_new)
        self.btn_pin = QPushButton("置顶", objectName="soft")
        self.btn_pin.setFixedHeight(22)
        self.btn_pin.clicked.connect(self._toggle_pin)
        head.addWidget(self.btn_pin)
        self.btn_fold = QPushButton("折叠", objectName="soft")
        self.btn_fold.setFixedHeight(22)
        self.btn_fold.clicked.connect(self._toggle_collapse)
        head.addWidget(self.btn_fold)
        self.btn_color = QPushButton("颜色", objectName="soft")
        self.btn_color.setFixedHeight(22)
        self.btn_color.clicked.connect(self._pick_color)
        head.addWidget(self.btn_color)
        self.btn_close = QPushButton("关闭", objectName="soft")
        self.btn_close.setFixedHeight(22)
        self.btn_close.clicked.connect(self._close_and_save)
        head.addWidget(self.btn_close)
        lay.addLayout(head)
        self.body = QTextEdit()
        self.body.setPlainText(str(note.get("body") or ""))
        lay.addWidget(self.body, 1)
        root.addWidget(self.box)
        self._apply_note_style()
        self.title.editingFinished.connect(self._persist)
        self.body.textChanged.connect(self._persist)

    def _apply_note_style(self) -> None:
        fg = _fg_on(self.color)
        self.box.setStyleSheet(_board_qss(self.color, "#ca8a04"))
        self.title.setStyleSheet(
            f"QLineEdit#noteTitle {{ background:transparent; border:none; color:{fg}; "
            f"font-weight:800; font-size:13px; padding:2px 4px; }}"
        )
        self.body.setStyleSheet(
            f"QTextEdit {{ background:rgba(255,255,255,0.55); border:none; color:{fg}; "
            f"border-radius:8px; padding:6px; }}"
            if _luma(self.color) > 0.55
            else f"QTextEdit {{ background:rgba(15,23,42,0.45); border:none; color:{fg}; "
            f"border-radius:8px; padding:6px; }}"
        )
        soft = (
            f"QPushButton {{ background:rgba(0,0,0,0.16); color:{fg}; border:1px solid {fg}; "
            f"border-radius:6px; padding:2px 6px; font-weight:800; font-size:11px; }}"
        )
        for b in (self.btn_new, self.btn_pin, self.btn_fold, self.btn_color, self.btn_close):
            b.setStyleSheet(soft)
        # ＋ 更醒目
        self.btn_new.setStyleSheet(
            f"QPushButton {{ background:{fg}; color:{self.color}; border:none; "
            f"border-radius:6px; font-weight:900; font-size:16px; }}"
        )

    def _add_another(self) -> None:
        self._persist()
        if callable(self.on_add_note):
            self.on_add_note()

    def _toggle_pin(self) -> None:
        self._pinned = not self._pinned
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._pinned:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        self.btn_pin.setText("已置顶" if self._pinned else "置顶")

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self.body.setVisible(not self._collapsed)
        if self._collapsed:
            # Thin bar with title always readable (dark text forced)
            name = self.title.text().strip() or "便签"
            self.title.setText(name)
            self.title.setReadOnly(True)
            self.title.show()
            self.title.setMinimumHeight(22)
            self.body.hide()
            self.btn_fold.setText("展开")
            self.btn_new.hide()
            self.btn_pin.hide()
            self.btn_color.hide()
            self.btn_close.hide()
            self._full_h = max(self.height(), 180)
            # margins tight so 36px bar fits title + expand
            self.box.layout().setContentsMargins(8, 4, 6, 4)
            self.setMinimumHeight(0)
            self.setMaximumHeight(36)
            self.setFixedHeight(36)
            self.btn_fold.setFixedHeight(24)
            self.btn_fold.setFixedWidth(44)
            fg = _fg_on(self.color)
            self.title.setStyleSheet(
                f"QLineEdit#noteTitle {{ background: transparent; border: none; color: {fg}; "
                f"font-weight: 900; font-size: 13px; padding: 0 4px; }}"
            )
            self.setToolTip(name)
        else:
            self.title.setReadOnly(False)
            self.title.setMinimumHeight(0)
            self.body.show()
            self.btn_fold.setText("折叠")
            self.btn_new.show()
            self.btn_pin.show()
            self.btn_color.show()
            self.btn_close.show()
            self.btn_fold.setFixedHeight(22)
            self.btn_fold.setMinimumWidth(0)
            self.btn_fold.setMaximumWidth(16777215)
            self.box.layout().setContentsMargins(10, 8, 10, 10)
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.resize(self.width(), self._full_h)
            self.setToolTip("")
            self._apply_note_style()

    def _persist(self) -> None:
        nid = str(self.note.get("id") or "")
        if not nid:
            return
        self.mgr.update(nid, self.title.text(), self.body.toPlainText())
        # keep color
        for n in self.mgr.list_items():
            if n.get("id") == nid:
                n["color"] = self.note.get("color") or NOTE_COLORS[0]
                break
        self.on_save()

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(str(self.note.get("color") or NOTE_COLORS[0])), self, "便签颜色")
        if c.isValid():
            self.note["color"] = c.name()
            self.color = c.name()
            self._apply_note_style()
            self._persist()

    def _close_and_save(self) -> None:
        self._persist()
        self.on_close_note(str(self.note.get("id") or ""))
        self.hide()


class NotesController:
    """Manages multiple sticky note windows. Each note has ＋ to create another."""

    def __init__(self, state: dict, on_save):
        self.state = state
        self.on_save = on_save
        self.mgr = NoteManager(state)
        self.windows: dict[str, StickyNoteWindow] = {}

    def show_all(self) -> None:
        notes = self.mgr.list_items()
        if not notes:
            self.add_note()
            return
        for n in notes:
            self._ensure_window(n)

    def add_note(self) -> None:
        n = len(self.mgr.list_items()) + 1
        note = self.mgr.add(f"便签 {n}", "")
        note["color"] = NOTE_COLORS[(n - 1) % len(NOTE_COLORS)]
        self.on_save()
        self._ensure_window(note)

    def _ensure_window(self, note: dict) -> None:
        nid = str(note.get("id") or "")
        if not nid:
            return
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
        # cascade so new notes don't fully stack
        off = 28 * (len(self.windows) % 10)
        w.move(140 + off, 140 + off)
        w.show()
        w.raise_()
        self.windows[nid] = w

    def _on_close(self, nid: str) -> None:
        """Hide window only — note data stays so it can reappear via 便签入口."""
        w = self.windows.pop(nid, None)
        if w is not None:
            try:
                w.hide()
            except Exception:
                pass


class PomodoroBoard(_DragBase):
    """Tomato-red pomodoro — clock-like: big time on top, status text below (like alarm)."""

    def __init__(self, state: dict, on_save, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QSpinBox

        self.state = state
        self.on_save = on_save
        self.timer = PomodoroTimer(state)
        self.resize(360, 340)
        self.setStyleSheet(
            """
            QFrame#box {
                background: #1c0a0a; border: 1px solid #7f1d1d; border-radius: 16px;
            }
            QLabel { color: #fecaca; font-size: 12px; font-weight: 600; }
            QLabel#title { color: #f87171; font-size: 15px; font-weight: 800; }
            QLabel#bigTime {
                color: #fca5a5; font-size: 48px; font-weight: 900;
                font-family: Consolas, 'Cascadia Mono', monospace;
                background: #0c0a09; border-radius: 14px;
                border: 1px solid #7f1d1d; padding: 18px 12px;
                min-height: 72px;
            }
            QLabel#statusLine {
                color: #fecaca; font-size: 15px; font-weight: 800;
                background: #291414; border-radius: 10px;
                border: 1px solid #7f1d1d; padding: 10px 12px;
            }
            QLabel#section { color: #fecaca; font-size: 11px; font-weight: 800; }
            QLabel#muted { color: #a8a29e; font-size: 11px; }
            QSpinBox {
                background: #0c0a09; color: #fff1f2; font-size: 16px; font-weight: 800;
                border: 2px solid #ef4444; border-radius: 10px; padding: 6px 8px; min-width: 72px;
            }
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ef4444, stop:1 #b91c1c);
                border: none; color: white; font-weight: 800; font-size: 12px;
                padding: 10px 12px; border-radius: 10px; min-height: 20px;
            }
            QPushButton:hover { background: #f87171; color: #450a0a; }
            QPushButton#soft {
                background: #292524; color: #fecaca; border: 1px solid #7f1d1d;
            }
            QPushButton#soft:hover { background: #44403c; }
            QPushButton#danger {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #dc2626, stop:1 #7f1d1d);
                color: white;
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
        x = QPushButton("✕ 关闭", objectName="soft")
        x.setFixedHeight(30)
        x.setMinimumWidth(72)
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
        tip = QLabel("上方大号倒计时 · 下方状态文字（与闹钟一致）")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        root.addWidget(box)
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._refresh)
        self._tick.start(1000)
        self._refresh()

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
