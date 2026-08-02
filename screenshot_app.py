"""Flameshot-style region screenshot + in-place annotation editor.

Tools (aligned with https://flameshot.org/ feature set):
  pen, marker/highlighter, arrow, rectangle, ellipse, text, number counter,
  pixelate, blur, solid fill box; undo/redo; copy; save; upload; pin.

Capture uses virtual desktop (multi-monitor). Editing is on a fullscreen overlay.
"""

from __future__ import annotations

import math
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QImage,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QColorDialog,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    import mss
except ImportError:
    mss = None  # type: ignore

try:
    from PIL import Image, ImageFilter
except ImportError:
    Image = None  # type: ignore
    ImageFilter = None  # type: ignore


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def virtual_desktop_geometry() -> QRect:
    geo = QRect()
    for screen in QGuiApplication.screens():
        geo = geo.united(screen.geometry())
    if geo.isNull() or geo.width() <= 0:
        screen = QGuiApplication.primaryScreen()
        if screen:
            return screen.geometry()
        return QRect(0, 0, 1920, 1080)
    return geo


def capture_virtual_desktop() -> tuple[QPixmap, QRect]:
    """Grab entire virtual desktop. Returns (pixmap, geometry in global coords)."""
    geo = virtual_desktop_geometry()
    if mss is not None:
        with mss.mss() as sct:
            mon = sct.monitors[0]  # all monitors
            shot = sct.grab(mon)
            # BGRA -> RGBA
            arr = np.frombuffer(shot.raw, dtype=np.uint8).reshape(shot.height, shot.width, 4).copy()
            # mss is BGRA
            rgba = arr[:, :, [2, 1, 0, 3]].copy()
            img = QImage(rgba.data, shot.width, shot.height, shot.width * 4, QImage.Format.Format_RGBA8888).copy()
            left, top = mon["left"], mon["top"]
            return QPixmap.fromImage(img), QRect(left, top, shot.width, shot.height)
    # Fallback: Qt primary / stitched screens
    screens = QGuiApplication.screens()
    if not screens:
        raise RuntimeError("没有可用的显示器")
    # stitch
    geo = virtual_desktop_geometry()
    out = QPixmap(geo.width(), geo.height())
    out.fill(Qt.GlobalColor.black)
    painter = QPainter(out)
    for screen in screens:
        g = screen.geometry()
        pm = screen.grabWindow(0)
        painter.drawPixmap(g.x() - geo.x(), g.y() - geo.y(), pm)
    painter.end()
    return out, geo


# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------

@dataclass
class Stroke:
    kind: str  # pen|marker|arrow|rect|ellipse|text|number|pixelate|blur|fill
    points: list[QPointF] = field(default_factory=list)
    color: QColor = field(default_factory=lambda: QColor(239, 68, 68))
    width: float = 4.0
    text: str = ""
    number: int = 0
    # for pixelate/blur: store processed pixmap of the rect region after apply
    baked: QImage | None = None


# In-canvas dock tools (drawn around selection like Flameshot — always visible)
# kind: tool | action | width_minus | width_plus | color | color_more
# key, icon_id (for vector draw), tooltip, kind
DOCK_TOOL_ROW: list[tuple[str, str, str, str]] = [
    ("pen", "pen", "画笔", "tool"),
    ("marker", "marker", "高亮", "tool"),
    ("arrow", "arrow", "箭头", "tool"),
    ("rect", "rect", "矩形", "tool"),
    ("ellipse", "ellipse", "椭圆", "tool"),
    ("fill", "fill", "色块", "tool"),
    ("text", "text", "文字", "tool"),
    ("number", "number", "序号", "tool"),
    ("pixelate", "pixelate", "马赛克", "tool"),
    ("blur", "blur", "模糊", "tool"),
]
DOCK_ACTION_ROW: list[tuple[str, str, str, str]] = [
    ("undo", "undo", "撤销", "action"),
    ("redo", "redo", "重做", "action"),
    ("reselect", "reselect", "重选区域", "action"),
    ("copy", "copy", "复制", "action"),
    ("save", "save", "保存", "action"),
    ("upload", "upload", "上传云端", "action"),
    ("pin", "pin", "钉住", "action"),
    ("accept", "accept", "完成", "action"),
    ("cancel", "cancel", "取消", "action"),
]
DOCK_COLORS = [
    QColor(239, 68, 68),
    QColor(249, 115, 22),
    QColor(234, 179, 8),
    QColor(34, 197, 94),
    QColor(14, 165, 233),
    QColor(59, 130, 246),
    QColor(168, 85, 247),
    QColor(255, 255, 255),
    QColor(15, 23, 42),
]


class PinnedShot(QWidget):
    """Pin screenshot to desktop (always on top, draggable)."""

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._pm = pixmap
        self.resize(pixmap.size())
        self._drag = False
        self._origin = QPoint()
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setPen(QPen(QColor(56, 189, 248), 2))
        p.setBrush(QBrush(self._pm))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
        p.drawPixmap(1, 1, self.width() - 2, self.height() - 2, self._pm)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = True
            self._origin = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif e.button() == Qt.MouseButton.RightButton:
            self.close()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag:
            self.move(e.globalPosition().toPoint() - self._origin)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._drag = False

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        self.close()


class ScreenshotEditor(QWidget):
    """Fullscreen selection + annotation (Flameshot workflow)."""

    finished = pyqtSignal(object)  # QImage | None

    def __init__(
        self,
        bg: QPixmap,
        desk_geo: QRect,
        *,
        mode: str = "region",  # region | full
        cfg: dict | None = None,
        on_upload: Callable[[Path], str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.bg = bg
        self.desk_geo = desk_geo
        self.mode = mode
        self.cfg = cfg if isinstance(cfg, dict) else {}
        self.on_upload = on_upload
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(desk_geo)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Keep mouse events even after clicking toolbar buttons
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # phase: "select" = aim crosshair + drag region; "edit" = multi-tool annotation
        # (Flameshot-style: stay in edit until save/exit/cancel — never auto re-select)
        self.phase = "select" if mode == "region" else "edit"
        # IMPORTANT: selecting starts False — only True while left-button drag.
        # Previously True on open made any mouse-move draw a huge box from (0,0).
        self.selecting = False
        self.sel_origin = QPoint()
        self.sel = QRect()
        if mode == "full":
            self.sel = QRect(0, 0, desk_geo.width(), desk_geo.height())
            self.selecting = False
            self.phase = "edit"

        self.tool = "pen"
        self.color = QColor(239, 68, 68)
        self.pen_w = 4  # brush thickness (not QWidget.width)
        self.drawing = False
        self.cur_stroke: Stroke | None = None
        self.strokes: list[Stroke] = []
        self.redo_stack: list[Stroke] = []
        self.number_seq = 1
        # Track cursor for Flameshot-style crosshair (local coords)
        try:
            gp = QCursor.pos()
            self.hover = QPoint(gp.x() - desk_geo.x(), gp.y() - desk_geo.y())
        except Exception:
            self.hover = QPoint(desk_geo.width() // 2, desk_geo.height() // 2)
        self._status_hint = ""
        self._last_upload_link = ""
        # Painted Flameshot-style dock around selection: list of (key, label, kind, QRect)
        # dock hits: key, icon_id, tip, kind, rect
        self._dock_hits: list[tuple[str, str, str, str, QRect]] = []
        self._dock_panel = QRect()
        self._hover_dock_key = ""
        self._text_edit: QLineEdit | None = None
        self._text_panel: QWidget | None = None
        self._text_anchor = QPoint()

        self._pinned: list[PinnedShot] = []

        # Shortcuts must NOT steal Enter while typing annotation text
        QShortcut(QKeySequence("Esc"), self, activated=self._on_esc_shortcut)
        self._sc_return = QShortcut(QKeySequence("Return"), self)
        self._sc_return.activated.connect(self._on_enter_shortcut)
        self._sc_enter = QShortcut(QKeySequence("Enter"), self)
        self._sc_enter.activated.connect(self._on_enter_shortcut)
        QShortcut(QKeySequence("Ctrl+C"), self, activated=lambda: self._on_action("copy"))
        QShortcut(QKeySequence("Ctrl+S"), self, activated=lambda: self._on_action("save"))
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=lambda: self._on_action("undo"))
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=lambda: self._on_action("redo"))
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=lambda: self._on_action("redo"))

        if mode == "full":
            QTimer.singleShot(0, self._enter_edit_mode)
        else:
            # Region mode: blank cursor so painted crosshair is the only aim
            self.setCursor(Qt.CursorShape.BlankCursor)
            QTimer.singleShot(0, self._sync_hover_from_global)

    def _sync_hover_from_global(self) -> None:
        try:
            gp = QCursor.pos()
            self.hover = QPoint(gp.x() - self.desk_geo.x(), gp.y() - self.desk_geo.y())
            self.update()
        except Exception:
            pass

    def _set_tool(self, t: str) -> None:
        self.tool = t
        self.drawing = False
        self.cur_stroke = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._status_hint = f"当前工具：{t} · 在选区内拖动画图"
        self._rebuild_dock()
        self.update()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.MouseFocusReason)

    def _set_color(self, c: QColor) -> None:
        self.color = QColor(c)
        self._status_hint = f"颜色 {self.color.name()}"
        self.update()

    def _set_width(self, w: int) -> None:
        self.pen_w = max(1, min(40, int(w)))
        self._status_hint = f"粗细 {self.pen_w}"
        self.update()

    def _enter_edit_mode(self) -> None:
        """Lock selection and enable continuous multi-tool annotation."""
        self.phase = "edit"
        self.selecting = False
        self.drawing = False
        self.cur_stroke = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._status_hint = "点选区周边工具切换 · 在框内绘制 · 完成/取消在工具条上"
        self._rebuild_dock()
        self.setFocus()
        self.update()

    def _enter_select_mode(self, *, clear_strokes: bool = True) -> None:
        """Flameshot-style aim mode: crosshair + coordinates, no box until drag."""
        if clear_strokes:
            self.strokes.clear()
            self.redo_stack.clear()
            self.number_seq = 1
        self.cur_stroke = None
        self.drawing = False
        self.sel = QRect()
        self.phase = "select"
        self.selecting = False
        self._dock_hits = []
        self._dock_panel = QRect()
        self.setCursor(Qt.CursorShape.BlankCursor)
        self._status_hint = "移动准星对准目标，按住左键拖选范围 · 空格=全屏 · Esc=取消"
        self._sync_hover_from_global()
        self.update()

    def _rebuild_dock(self) -> None:
        """Compute Flameshot-like tool dock rects around the selection (local coords)."""
        self._dock_hits = []
        self._dock_panel = QRect()
        if self.phase != "edit" or self.sel.isNull() or self.sel.width() < 4:
            return
        s = self.sel.normalized()
        btn_w, btn_h, gap = 42, 36, 4
        pad = 8

        def layout_row(items: list[tuple[str, str, str, str]], y: int) -> tuple[list, int, int]:
            n = len(items)
            row_w = n * btn_w + (n - 1) * gap + pad * 2
            x0 = s.center().x() - row_w // 2
            x0 = max(6, min(x0, self.width() - row_w - 6))
            hits = []
            x = x0 + pad
            for key, icon_id, tip, kind in items:
                hits.append((key, icon_id, tip, kind, QRect(x, y, btn_w, btn_h)))
                x += btn_w + gap
            return hits, x0, row_w

        row1_h = btn_h
        row2_h = btn_h
        color_h = 28
        total_h = pad + row1_h + gap + row2_h + gap + color_h + pad
        below_y = s.bottom() + 10
        above_y = s.top() - total_h - 10
        if below_y + total_h <= self.height() - 6:
            panel_y = below_y
        elif above_y >= 6:
            panel_y = above_y
        else:
            panel_y = max(6, self.height() - total_h - 8)

        y1 = panel_y + pad
        hits1, x0, row_w = layout_row(DOCK_TOOL_ROW, y1)
        y2 = y1 + row1_h + gap
        hits2, x0b, row_w2 = layout_row(DOCK_ACTION_ROW, y2)
        panel_x = min(x0, x0b)
        panel_w = max(row_w, row_w2)

        y3 = y2 + row2_h + gap
        cx = panel_x + pad
        hits2.append(("width_minus", "w_minus", "更细", "width_minus", QRect(cx, y3, 36, color_h)))
        cx += 40
        hits2.append(("width_label", "w_label", str(self.pen_w), "width_label", QRect(cx, y3, 36, color_h)))
        cx += 40
        hits2.append(("width_plus", "w_plus", "更粗", "width_plus", QRect(cx, y3, 36, color_h)))
        cx += 48
        for i, col in enumerate(DOCK_COLORS):
            r = QRect(cx, y3 + 2, 24, 24)
            hits2.append((f"color_{i}", "color", col.name(), "color", r))
            cx += 28
        hits2.append(("color_more", "color_more", "更多颜色", "color_more", QRect(cx, y3, 32, color_h)))
        cx += 36
        panel_w = max(panel_w, cx - panel_x + pad)
        panel_w = min(panel_w, self.width() - 12)
        panel_x = max(6, min(panel_x, self.width() - panel_w - 6))

        self._dock_hits = hits1 + hits2
        self._dock_panel = QRect(panel_x, panel_y, panel_w, total_h)

    def _hit_dock(self, pos: QPoint) -> tuple[str, str, str, str] | None:
        for key, icon_id, tip, kind, rect in self._dock_hits:
            if rect.contains(pos):
                return key, icon_id, tip, kind
        return None

    def _draw_icon(self, p: QPainter, icon_id: str, rect: QRect, fg: QColor) -> None:
        """Vector icon for dock buttons (Flameshot-style recognition)."""
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = rect.center().x(), rect.center().y()
        pen = QPen(fg, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if icon_id == "pen":
            p.drawLine(cx - 8, cy + 8, cx + 8, cy - 8)
            p.setBrush(fg)
            p.drawEllipse(QPoint(cx + 8, cy - 8), 3, 3)
        elif icon_id == "marker":
            p.setBrush(QColor(fg.red(), fg.green(), fg.blue(), 100))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(cx - 10, cy - 6, 20, 12, 3, 3)
            p.setPen(pen)
            p.drawLine(cx - 10, cy + 8, cx + 10, cy + 8)
        elif icon_id == "arrow":
            p.drawLine(cx - 10, cy + 8, cx + 8, cy - 8)
            p.drawLine(cx + 8, cy - 8, cx + 2, cy - 8)
            p.drawLine(cx + 8, cy - 8, cx + 8, cy - 2)
        elif icon_id == "rect":
            p.drawRect(cx - 9, cy - 7, 18, 14)
        elif icon_id == "ellipse":
            p.drawEllipse(QPoint(cx, cy), 10, 7)
        elif icon_id == "fill":
            p.setBrush(fg)
            p.drawRect(cx - 9, cy - 7, 18, 14)
        elif icon_id == "text":
            p.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "T")
        elif icon_id == "number":
            p.setBrush(fg)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPoint(cx, cy), 9, 9)
            p.setPen(QPen(QColor(15, 23, 42), 2))
            p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "1")
        elif icon_id == "pixelate":
            for i in range(3):
                for j in range(3):
                    if (i + j) % 2 == 0:
                        p.fillRect(cx - 9 + i * 6, cy - 9 + j * 6, 5, 5, fg)
        elif icon_id == "blur":
            p.setBrush(QColor(fg.red(), fg.green(), fg.blue(), 80))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPoint(cx, cy), 10, 10)
            p.setBrush(QColor(fg.red(), fg.green(), fg.blue(), 160))
            p.drawEllipse(QPoint(cx, cy), 5, 5)
        elif icon_id == "undo":
            path = QPainterPath()
            path.moveTo(cx + 6, cy - 6)
            path.arcTo(cx - 8, cy - 8, 16, 16, 30, 200)
            p.drawPath(path)
            p.drawLine(cx - 8, cy - 2, cx - 2, cy - 8)
            p.drawLine(cx - 8, cy - 2, cx - 2, cy + 2)
        elif icon_id == "redo":
            path = QPainterPath()
            path.moveTo(cx - 6, cy - 6)
            path.arcTo(cx - 8, cy - 8, 16, 16, 150, -200)
            p.drawPath(path)
            p.drawLine(cx + 8, cy - 2, cx + 2, cy - 8)
            p.drawLine(cx + 8, cy - 2, cx + 2, cy + 2)
        elif icon_id == "reselect":
            # Marquee / crop corners (distinct from copy)
            p.setPen(QPen(fg, 2, Qt.PenStyle.DashLine, Qt.PenCapStyle.SquareCap))
            p.drawRect(cx - 9, cy - 7, 18, 14)
            p.setPen(QPen(fg, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
            # corner L marks
            for ox, oy, dx, dy in (
                (-9, -7, 5, 0),
                (-9, -7, 0, 5),
                (9, -7, -5, 0),
                (9, -7, 0, 5),
                (-9, 7, 5, 0),
                (-9, 7, 0, -5),
                (9, 7, -5, 0),
                (9, 7, 0, -5),
            ):
                p.drawLine(cx + ox, cy + oy, cx + ox + dx, cy + oy + dy)
        elif icon_id == "copy":
            # Clipboard: board + clipped page (clearly not reselect)
            p.setPen(QPen(fg, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            # board body
            p.drawRoundedRect(cx - 8, cy - 4, 16, 14, 2, 2)
            # clip on top
            p.drawRoundedRect(cx - 4, cy - 9, 8, 6, 2, 2)
            p.drawLine(cx - 3, cy + 1, cx + 3, cy + 1)
            p.drawLine(cx - 3, cy + 5, cx + 3, cy + 5)
        elif icon_id == "save":
            p.drawRoundedRect(cx - 8, cy - 8, 16, 16, 2, 2)
            p.drawRect(cx - 4, cy - 8, 8, 6)
            p.drawLine(cx - 3, cy + 2, cx + 3, cy + 2)
        elif icon_id == "upload":
            p.drawLine(cx, cy + 8, cx, cy - 6)
            p.drawLine(cx, cy - 6, cx - 5, cy)
            p.drawLine(cx, cy - 6, cx + 5, cy)
            p.drawLine(cx - 8, cy + 8, cx + 8, cy + 8)
        elif icon_id == "pin":
            p.drawEllipse(QPoint(cx, cy - 4), 5, 5)
            p.drawLine(cx, cy + 1, cx, cy + 9)
        elif icon_id == "accept":
            p.setPen(QPen(fg, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawLine(cx - 7, cy, cx - 2, cy + 6)
            p.drawLine(cx - 2, cy + 6, cx + 8, cy - 6)
        elif icon_id == "cancel":
            p.setPen(QPen(fg, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(cx - 7, cy - 7, cx + 7, cy + 7)
            p.drawLine(cx + 7, cy - 7, cx - 7, cy + 7)
        elif icon_id == "w_minus":
            p.setPen(QPen(fg, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(cx - 7, cy, cx + 7, cy)
        elif icon_id == "w_plus":
            p.setPen(QPen(fg, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(cx - 7, cy, cx + 7, cy)
            p.drawLine(cx, cy - 7, cx, cy + 7)
        elif icon_id == "color_more":
            p.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "…")
        p.restore()

    def _paint_dock(self, p: QPainter) -> None:
        if not self._dock_hits:
            self._rebuild_dock()
        if not self._dock_hits or self._dock_panel.isNull():
            return
        panel = self._dock_panel
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(15, 23, 42, 250))
        p.setPen(QPen(QColor(56, 189, 248), 2))
        p.drawRoundedRect(panel, 10, 10)

        for key, icon_id, tip, kind, rect in self._dock_hits:
            if kind == "color":
                idx = int(key.split("_")[1])
                col = DOCK_COLORS[idx]
                p.setBrush(col)
                selected = col.rgb() == QColor(self.color).rgb()
                p.setPen(QPen(QColor(255, 255, 255) if selected else QColor(100, 116, 139), 2 if selected else 1))
                p.drawEllipse(rect)
                continue
            if kind == "width_label":
                p.setPen(QColor(125, 211, 252))
                p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(self.pen_w))
                continue

            active_tool = kind == "tool" and key == self.tool
            hover = key == self._hover_dock_key
            if key == "cancel":
                bg = QColor(220, 38, 38, 240)
                fg = QColor(255, 255, 255)
            elif key in ("accept", "upload"):
                bg = QColor(14, 165, 233, 250)
                fg = QColor(15, 23, 42)
            elif active_tool or hover:
                bg = QColor(56, 189, 248, 250)
                fg = QColor(15, 23, 42)
            else:
                bg = QColor(30, 41, 59, 250)
                fg = QColor(226, 232, 240)
            p.setBrush(bg)
            p.setPen(QPen(QColor(51, 65, 85), 1))
            p.drawRoundedRect(rect, 8, 8)
            self._draw_icon(p, icon_id, rect, fg)

        # hover tooltip under panel
        if self._hover_dock_key:
            for key, icon_id, tip, kind, rect in self._dock_hits:
                if key == self._hover_dock_key and tip:
                    p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
                    p.setPen(QColor(253, 224, 71))
                    p.drawText(panel.left() + 10, panel.bottom() - 4, tip)
                    break

        p.setBrush(self.color)
        p.setPen(QPen(Qt.GlobalColor.white, 2))
        p.drawEllipse(panel.right() - 22, panel.top() + 8, 14, 14)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, self.bg)

        # ---------- SELECT: Flameshot crosshair + coordinates ----------
        if self.phase == "select":
            dim = QColor(0, 0, 0, 120)
            hx = max(0, min(self.hover.x(), self.width() - 1))
            hy = max(0, min(self.hover.y(), self.height() - 1))
            if self.selecting and not self.sel.isNull() and self.sel.width() > 0:
                s = self.sel.normalized()
                r = self.rect()
                p.fillRect(0, 0, r.width(), s.top(), dim)
                p.fillRect(0, s.bottom() + 1, r.width(), r.height() - s.bottom() - 1, dim)
                p.fillRect(0, s.top(), s.left(), s.height(), dim)
                p.fillRect(s.right() + 1, s.top(), r.width() - s.right() - 1, s.height(), dim)
                p.setPen(QPen(QColor(56, 189, 248), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(s)
                p.setPen(QColor(255, 255, 255))
                p.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
                p.drawText(s.left() + 6, max(20, s.top() - 8), f"{s.width()} × {s.height()}  px")
            else:
                p.fillRect(self.rect(), dim)
                p.setPen(QColor(226, 232, 240, 220))
                p.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
                p.drawText(
                    self.rect().adjusted(0, -100, 0, 0),
                    Qt.AlignmentFlag.AlignCenter,
                    "十字准星瞄准 · 按住左键拖出选区\n空格 = 全屏 · Esc = 取消",
                )

            # Full-screen crosshair (high contrast)
            p.setPen(QPen(QColor(14, 165, 233), 1))
            p.drawLine(0, hy, self.width(), hy)
            p.drawLine(hx, 0, hx, self.height())
            p.setPen(QPen(QColor(255, 255, 255), 1, Qt.PenStyle.DashLine))
            p.drawLine(0, hy, self.width(), hy)
            p.drawLine(hx, 0, hx, self.height())
            # Aim ring
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(239, 68, 68), 2))
            p.drawEllipse(QPointF(hx, hy), 8, 8)
            p.setBrush(QColor(239, 68, 68))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(hx, hy), 3, 3)

            # Large coordinate HUD (always visible near cursor + top-left)
            gx = self.desk_geo.x() + hx
            gy = self.desk_geo.y() + hy
            badge = f"  X = {gx}    Y = {gy}  "
            p.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
            fm = p.fontMetrics()
            bw = fm.horizontalAdvance(badge) + 16
            bh = fm.height() + 14
            bx = min(max(12, hx + 18), self.width() - bw - 12)
            by = min(max(12, hy + 18), self.height() - bh - 12)
            p.setBrush(QColor(15, 23, 42, 235))
            p.setPen(QPen(QColor(56, 189, 248), 2))
            p.drawRoundedRect(bx, by, bw, bh, 8, 8)
            p.setPen(QColor(125, 211, 252))
            p.drawText(bx + 8, by + bh - 10, badge)
            # Fixed corner readout
            p.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
            corner = f"坐标  X:{gx}  Y:{gy}"
            p.setBrush(QColor(15, 23, 42, 220))
            p.setPen(QPen(QColor(56, 189, 248), 1))
            p.drawRoundedRect(16, 16, 220, 36, 8, 8)
            p.setPen(QColor(255, 255, 255))
            p.drawText(28, 40, corner)
            return

        # ---------- EDIT: dim outside + annotations + dock around selection ----------
        if not self.sel.isNull() and self.sel.width() > 0:
            dim = QColor(0, 0, 0, 140)
            r = self.rect()
            s = self.sel.normalized()
            p.fillRect(0, 0, r.width(), s.top(), dim)
            p.fillRect(0, s.bottom() + 1, r.width(), r.height() - s.bottom() - 1, dim)
            p.fillRect(0, s.top(), s.left(), s.height(), dim)
            p.fillRect(s.right() + 1, s.top(), r.width() - s.right() - 1, s.height(), dim)
            p.setPen(QPen(QColor(56, 189, 248), 2, Qt.PenStyle.SolidLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(s)
            p.setPen(QColor(255, 255, 255))
            p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            label = f"{s.width()} × {s.height()}  ·  已标注 {len(self.strokes)} 笔"
            p.drawText(s.left() + 4, max(16, s.top() - 8), label)

        # Annotations clipped to selection
        if not self.sel.isNull():
            p.save()
            p.setClipRect(self.sel.normalized())
            for st in self.strokes:
                self._paint_stroke(p, st)
            if self.cur_stroke:
                self._paint_stroke(p, self.cur_stroke)
            p.restore()
        else:
            for st in self.strokes:
                self._paint_stroke(p, st)
            if self.cur_stroke:
                self._paint_stroke(p, self.cur_stroke)

        # Flameshot-style tools painted around selection (always on top of dim)
        self._paint_dock(p)
        if self._status_hint and not self.sel.isNull():
            s = self.sel.normalized()
            p.setPen(QColor(125, 211, 252))
            p.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
            # Put status opposite the dock
            if not self._dock_panel.isNull() and self._dock_panel.top() >= s.bottom():
                ty = max(16, s.top() - 8)
            else:
                ty = min(self.height() - 12, s.bottom() + 18)
            p.drawText(s.left() + 4, ty, self._status_hint)

    def _paint_stroke(self, p: QPainter, st: Stroke) -> None:
        if st.kind in ("pixelate", "blur") and st.baked is not None and len(st.points) >= 2:
            r = QRectF(st.points[0], st.points[1]).normalized().toRect()
            p.drawImage(r.topLeft(), st.baked)
            return
        col = QColor(st.color)
        if st.kind == "marker":
            col.setAlpha(90)
        pen = QPen(col, st.width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        if st.kind in ("pen", "marker"):
            if len(st.points) >= 2:
                path = QPainterPath(st.points[0])
                for pt in st.points[1:]:
                    path.lineTo(pt)
                p.drawPath(path)
            elif len(st.points) == 1:
                p.drawPoint(st.points[0])
        elif st.kind == "arrow" and len(st.points) >= 2:
            a, b = st.points[0], st.points[-1]
            p.drawLine(a, b)
            self._draw_arrow_head(p, a, b, col, st.width)
        elif st.kind in ("rect", "fill", "ellipse") and len(st.points) >= 2:
            r = QRectF(st.points[0], st.points[1]).normalized()
            if st.kind == "fill":
                fill = QColor(col)
                fill.setAlpha(180)
                p.setBrush(fill)
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRect(r)
            elif st.kind == "rect":
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(r)
            else:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(r)
        elif st.kind == "text" and st.points:
            p.setFont(QFont("Segoe UI", max(10, int(st.width * 3))))
            p.setPen(col)
            p.drawText(st.points[0], st.text or "")
        elif st.kind == "number" and st.points:
            r = 12 + st.width
            c = st.points[0]
            p.setBrush(col)
            p.setPen(QPen(Qt.GlobalColor.white, 2))
            p.drawEllipse(c, r, r)
            p.setPen(Qt.GlobalColor.white)
            p.setFont(QFont("Segoe UI", max(10, int(r)), QFont.Weight.Bold))
            p.drawText(QRectF(c.x() - r, c.y() - r, r * 2, r * 2), Qt.AlignmentFlag.AlignCenter, str(st.number))
        elif st.kind in ("pixelate", "blur") and len(st.points) >= 2:
            r = QRectF(st.points[0], st.points[1]).normalized()
            p.setPen(QPen(col, 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r)

    def _draw_arrow_head(self, p: QPainter, a: QPointF, b: QPointF, col: QColor, w: float) -> None:
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        size = 10 + w * 1.5
        p1 = QPointF(b.x() - size * math.cos(ang - 0.4), b.y() - size * math.sin(ang - 0.4))
        p2 = QPointF(b.x() - size * math.cos(ang + 0.4), b.y() - size * math.sin(ang + 0.4))
        path = QPainterPath(b)
        path.lineTo(p1)
        path.lineTo(p2)
        path.closeSubpath()
        p.setBrush(col)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)

    def _text_input_active(self) -> bool:
        return self._text_edit is not None or self._text_panel is not None

    def _on_esc_shortcut(self) -> None:
        if self._text_input_active():
            self._cancel_text_input()
            return
        self._on_action("cancel")

    def _on_enter_shortcut(self) -> None:
        # Enter while typing = confirm text only (never exit the whole editor)
        if self._text_input_active():
            self._commit_text_input()
            return
        self._on_action("accept")

    def keyPressEvent(self, e) -> None:
        if self._text_input_active() and e.key() == Qt.Key.Key_Escape:
            self._cancel_text_input()
            return
        if self._text_input_active() and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._commit_text_input()
            e.accept()
            return
        if e.key() == Qt.Key.Key_Space and self.phase == "select":
            self.sel = self.rect()
            self._enter_edit_mode()
            return
        super().keyPressEvent(e)

    def _clamp_to_sel(self, pos: QPoint) -> QPoint:
        s = self.sel.normalized()
        if s.isNull() or s.width() < 2:
            return pos
        return QPoint(
            max(s.left(), min(pos.x(), s.right())),
            max(s.top(), min(pos.y(), s.bottom())),
        )

    def _handle_dock_click(self, key: str, kind: str) -> bool:
        """Handle in-canvas dock button. Returns True if consumed."""
        if kind == "tool":
            self._set_tool(key)
            return True
        if kind == "action":
            self._on_action(key)
            return True
        if kind == "width_minus":
            self._set_width(self.pen_w - 1)
            self._rebuild_dock()
            return True
        if kind == "width_plus":
            self._set_width(self.pen_w + 1)
            self._rebuild_dock()
            return True
        if kind == "width_label":
            return True
        if kind == "color":
            idx = int(key.split("_")[1])
            self._set_color(DOCK_COLORS[idx])
            self._rebuild_dock()
            return True
        if kind == "color_more":
            c = QColorDialog.getColor(self.color, self, "选择颜色")
            if c.isValid():
                self._set_color(c)
                self._rebuild_dock()
            return True
        return False

    def _begin_text_input(self, pos: QPoint) -> None:
        """Visible in-place text field + 确认/取消 (Enter only commits text, not exit)."""
        self._cancel_text_input()
        self._text_anchor = QPoint(pos)
        fs = max(14, int(self.pen_w * 3))

        panel = QWidget(self)
        panel.setObjectName("textPanel")
        panel.setStyleSheet(
            """
            QWidget#textPanel {
                background: rgba(15, 23, 42, 0.96);
                border: 2px solid #38bdf8;
                border-radius: 10px;
            }
            QPushButton {
                background: #0ea5e9; color: white; border: none; border-radius: 6px;
                padding: 6px 12px; font-weight: 800;
            }
            QPushButton#soft { background: #334155; }
            """
        )
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        edit = QLineEdit(panel)
        edit.setStyleSheet(
            f"""
            QLineEdit {{
                background: #020617;
                color: {self.color.name()};
                border: 1px solid #38bdf8;
                border-radius: 6px;
                padding: 6px 8px;
                font-size: {fs}px;
                font-weight: 700;
                selection-background-color: #0ea5e9;
            }}
            """
        )
        edit.setPlaceholderText("在此输入文字…")
        edit.setMinimumWidth(200)
        # returnPressed only commits text (shortcut handler also checks text mode)
        edit.returnPressed.connect(self._commit_text_input)
        lay.addWidget(edit)

        row = QHBoxLayout()
        btn_ok = QPushButton("确认")
        btn_ok.setToolTip("把文字画到截图上（不会退出截图）")
        btn_ok.clicked.connect(self._commit_text_input)
        btn_cancel = QPushButton("取消", objectName="soft")
        btn_cancel.clicked.connect(self._cancel_text_input)
        row.addWidget(btn_ok)
        row.addWidget(btn_cancel)
        row.addStretch(1)
        lay.addLayout(row)

        panel.adjustSize()
        pw = max(panel.sizeHint().width(), 260)
        ph = max(panel.sizeHint().height(), fs + 70)
        panel.resize(pw, ph)

        s = self.sel.normalized()
        x = max(s.left() + 2, min(pos.x(), s.right() - pw - 2))
        y = max(s.top() + 2, min(pos.y(), s.bottom() - ph - 2))
        panel.move(x, y)
        panel.show()
        panel.raise_()
        edit.setFocus(Qt.FocusReason.OtherFocusReason)

        self._text_panel = panel
        self._text_edit = edit
        # Disable global Enter→accept while typing
        try:
            self._sc_return.setEnabled(False)
            self._sc_enter.setEnabled(False)
        except Exception:
            pass
        self._status_hint = "文字输入：Enter 或点「确认」写入 · Esc/取消 放弃 · 不会退出截图"
        self.update()

    def _destroy_text_ui(self) -> None:
        if self._text_panel is not None:
            self._text_panel.hide()
            self._text_panel.deleteLater()
            self._text_panel = None
        elif self._text_edit is not None:
            self._text_edit.hide()
            self._text_edit.deleteLater()
        self._text_edit = None
        try:
            self._sc_return.setEnabled(True)
            self._sc_enter.setEnabled(True)
        except Exception:
            pass

    def _commit_text_input(self) -> None:
        edit = self._text_edit
        if edit is None and self._text_panel is None:
            return
        text = (edit.text().strip() if edit is not None else "")
        pos = QPoint(self._text_anchor)
        self._destroy_text_ui()
        if text:
            st = Stroke(
                kind="text",
                points=[QPointF(pos)],
                color=QColor(self.color),
                width=float(self.pen_w),
                text=text,
            )
            self.strokes.append(st)
            self.redo_stack.clear()
            self._status_hint = f"已添加文字「{text[:20]}」· 共 {len(self.strokes)} 笔 · 可继续标注"
        else:
            self._status_hint = "未输入文字（已取消）"
        self.setFocus()
        self.update()

    def _cancel_text_input(self) -> None:
        if not self._text_input_active():
            return
        self._destroy_text_ui()
        self._status_hint = "已取消文字输入 · 可继续标注"
        self.setFocus()
        self.update()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.RightButton:
            if self._text_input_active():
                self._cancel_text_input()
                return
            if self.drawing:
                self.drawing = False
                self.cur_stroke = None
                self.update()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position().toPoint()

        # Click outside text panel commits (if has text) — panel geometry in parent coords
        if self._text_input_active() and self._text_panel is not None:
            if not self._text_panel.geometry().contains(pos):
                self._commit_text_input()
            else:
                return
        elif self._text_edit is not None:
            if not self._text_edit.geometry().contains(pos):
                self._commit_text_input()
            else:
                return

        # ---- SELECT PHASE: drag out a region ----
        if self.phase == "select":
            self.selecting = True
            self.sel_origin = pos
            self.sel = QRect(pos, pos)
            self.update()
            return

        # ---- EDIT: dock first (outside selection is OK for tools) ----
        hit = self._hit_dock(pos)
        if hit is not None:
            key, _icon, _tip, kind = hit
            self._handle_dock_click(key, kind)
            return

        s = self.sel.normalized()
        if s.isNull() or s.width() < 4:
            return
        if not s.contains(pos):
            self._status_hint = "请点选区周边工具，或在蓝框内绘制"
            self.update()
            return

        pos = self._clamp_to_sel(pos)
        self.drawing = True
        self.redo_stack.clear()

        if self.tool == "text":
            self.drawing = False
            self._begin_text_input(pos)
            return

        if self.tool == "number":
            st = Stroke(
                kind="number",
                points=[QPointF(pos)],
                color=QColor(self.color),
                width=float(self.pen_w),
                number=self.number_seq,
            )
            self.number_seq += 1
            self.strokes.append(st)
            self.drawing = False
            self._status_hint = f"已添加序号 {st.number} · 共 {len(self.strokes)} 笔"
            self.update()
            return

        self.cur_stroke = Stroke(
            kind=self.tool,
            points=[QPointF(pos)],
            color=QColor(self.color),
            width=float(self.pen_w),
        )
        self.update()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        pos = e.position().toPoint()
        self.hover = pos
        if self.phase == "select":
            if self.selecting:
                self.sel = QRect(self.sel_origin, pos).normalized()
            self.update()
            return
        if self.phase == "edit":
            hit = self._hit_dock(pos)
            new_key = hit[0] if hit else ""
            if new_key != self._hover_dock_key:
                self._hover_dock_key = new_key
                if not self.drawing:
                    self.update()
            if self.drawing and self.cur_stroke:
                pos = self._clamp_to_sel(pos)
                if self.cur_stroke.kind in ("pen", "marker"):
                    self.cur_stroke.points.append(QPointF(pos))
                else:
                    if len(self.cur_stroke.points) == 1:
                        self.cur_stroke.points.append(QPointF(pos))
                    else:
                        self.cur_stroke.points[1] = QPointF(pos)
                self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self.phase == "select" and self.selecting:
            self.selecting = False
            self.sel = self.sel.normalized()
            if self.sel.width() < 4 or self.sel.height() < 4:
                self.sel = QRect()
                self.phase = "select"
            else:
                self._enter_edit_mode()
            self.update()
            return
        if self.phase == "edit" and self.drawing and self.cur_stroke:
            st = self.cur_stroke
            self.cur_stroke = None
            self.drawing = False
            if st.kind in ("pixelate", "blur") and len(st.points) >= 2:
                self._bake_region_effect(st)
            if st.kind in ("pen", "marker") and len(st.points) < 1:
                return
            if st.kind not in ("pen", "marker", "text", "number") and len(st.points) < 2:
                return
            self.strokes.append(st)
            self._status_hint = f"已添加 · 共 {len(self.strokes)} 笔 · 可继续换工具"
            self.update()
            return

    def _bake_region_effect(self, st: Stroke) -> None:
        r = QRectF(st.points[0], st.points[1]).normalized().toRect()
        r = r.intersected(self.rect())
        if r.width() < 2 or r.height() < 2:
            return
        # base from background + already baked strokes drawn... approximate: from bg only then overlay prior
        # Better: render composite crop
        composite = self._render_full_composite()
        crop = composite.copy(r)
        if Image is None:
            # simple pixelate with Qt
            if st.kind == "pixelate":
                scale = max(2, int(self.pen_w))
                small = crop.scaled(
                    max(1, r.width() // scale),
                    max(1, r.height() // scale),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
                st.baked = small.scaled(r.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
            else:
                st.baked = crop.scaled(
                    max(1, r.width() // 8),
                    max(1, r.height() // 8),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ).scaled(r.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            return
        try:
            from PIL.ImageQt import fromqimage as pil_from_qimage, ImageQt as PilImageQt

            pil = pil_from_qimage(crop)
        except Exception:
            # Fallback: Qt soft scale
            st.baked = crop.scaled(
                max(1, r.width() // 8),
                max(1, r.height() // 8),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ).scaled(r.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            return
        if st.kind == "pixelate":
            block = max(4, int(self.pen_w * 2))
            small = pil.resize((max(1, pil.width // block), max(1, pil.height // block)), Image.Resampling.NEAREST)
            pil = small.resize(pil.size, Image.Resampling.NEAREST)
        else:
            rad = max(2, int(self.pen_w))
            pil = pil.filter(ImageFilter.GaussianBlur(radius=rad))
        try:
            st.baked = pil.toqimage()
        except Exception:
            st.baked = PilImageQt(pil)

    def _render_full_composite(self) -> QImage:
        img = self.bg.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for st in self.strokes:
            self._paint_stroke(p, st)
        p.end()
        return img

    def export_image(self) -> QImage | None:
        s = self.sel.normalized()
        if s.width() < 2 or s.height() < 2:
            return None
        full = self._render_full_composite()
        return full.copy(s)

    def _default_save_dir(self) -> Path:
        d = self.cfg.get("save_dir") or str(Path.home() / "Pictures" / "ParrotScreenshots")
        p = Path(d)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _on_action(self, act: str) -> None:
        if act == "cancel":
            self.finished.emit(None)
            self.close()
            return
        if act == "reselect":
            # Explicit only — never happens by accident while annotating
            if self.strokes:
                reply = QMessageBox.question(
                    self,
                    "重新框选",
                    "重新框选会清空当前标注，确定吗？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            self._enter_select_mode(clear_strokes=True)
            return
        if act == "undo":
            if self.strokes:
                self.redo_stack.append(self.strokes.pop())
                self._status_hint = f"已撤销 · 剩余 {len(self.strokes)} 笔，可继续标注"
                self.update()
            return
        if act == "redo":
            if self.redo_stack:
                self.strokes.append(self.redo_stack.pop())
                self._status_hint = f"已重做 · 共 {len(self.strokes)} 笔"
                self.update()
            return
        img = self.export_image()
        if img is None or img.isNull():
            if act in ("copy", "save", "upload", "pin", "accept"):
                QMessageBox.information(self, "截图", "请先框选有效区域")
            return
        if act == "copy":
            QApplication.clipboard().setImage(img)
            self._status_hint = "已复制到剪贴板 · 可继续编辑，不会退出"
            self.update()
            return
        if act == "save":
            path = self._default_save_dir() / f"shot_{time.strftime('%Y%m%d_%H%M%S')}.png"
            chosen, _ = QFileDialog.getSaveFileName(
                self, "保存截图", str(path), "PNG (*.png);;JPEG (*.jpg)"
            )
            if chosen:
                img.save(chosen)
                self.cfg["last_save"] = chosen
                self._status_hint = f"已保存 {Path(chosen).name} · 可继续编辑"
                self.update()
            return
        if act == "pin":
            pm = QPixmap.fromImage(img)
            pin = PinnedShot(pm)
            pin.move(self.desk_geo.x() + self.sel.x() + 20, self.desk_geo.y() + self.sel.y() + 20)
            pin.show()
            self._pinned.append(pin)
            self._status_hint = "已钉在桌面 · 编辑器仍可继续标注"
            self.update()
            return
        if act == "upload":
            if not self.on_upload:
                self._status_hint = "未配置云端：请在截图设置里连接 Google Drive"
                self.update()
                return
            tmp = Path(tempfile.gettempdir()) / f"parrot_shot_{int(time.time())}.png"
            img.save(str(tmp), "PNG")
            try:
                result = self.on_upload(tmp)
                link, name = _parse_upload_result(result)
                self._last_upload_link = link
                if link:
                    QApplication.clipboard().setText(link)
                    self._status_hint = f"✅ 已上传并复制链接到剪贴板 · {name or link[:48]}"
                else:
                    self._status_hint = f"✅ 已上传 · {name or '完成'}"
                self.update()
            except Exception as e:
                self._status_hint = f"上传失败：{e}"
                self.update()
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
            return
        if act == "accept":
            # auto save + copy image then exit
            path = self._default_save_dir() / f"shot_{time.strftime('%Y%m%d_%H%M%S')}.png"
            img.save(str(path))
            QApplication.clipboard().setImage(img)
            auto = bool(self.cfg.get("auto_upload"))
            if auto and self.on_upload:
                try:
                    result = self.on_upload(path)
                    link, name = _parse_upload_result(result)
                    if link:
                        QApplication.clipboard().setText(link)
                        self._last_upload_link = link
                except Exception:
                    pass
            self.finished.emit(img)
            self.close()
            return

    def closeEvent(self, e) -> None:
        super().closeEvent(e)


# Keep pinned windows alive
_PINNED_REFS: list[PinnedShot] = []
_EDITOR_REF: ScreenshotEditor | None = None


def _parse_upload_result(result) -> tuple[str, str]:
    """Normalize upload callback return → (link, name)."""
    if isinstance(result, dict):
        link = str(result.get("link") or result.get("webViewLink") or "").strip()
        name = str(result.get("name") or "").strip()
        fid = str(result.get("id") or "").strip()
        if not link and fid:
            link = f"https://drive.google.com/file/d/{fid}/view"
        return link, name
    text = str(result or "").strip()
    if not text:
        return "", ""
    # "name\nlink" legacy format
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    link = ""
    name = lines[0] if lines else ""
    for ln in lines:
        if ln.startswith("http://") or ln.startswith("https://"):
            link = ln
            break
    if link and name == link:
        name = "截图"
    return link, name


def show_upload_link_dialog(
    parent,
    *,
    name: str = "",
    link: str = "",
    auto_exit_hint: bool = False,
) -> None:
    """Show image URL after cloud upload; auto-copy + one-click copy again."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("上传成功 · 图片链接")
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    dlg.setMinimumWidth(480)
    dlg.setStyleSheet(
        """
        QDialog { background: #0f172a; }
        QLabel { color: #e2e8f0; font-size: 12px; }
        QLabel#title { color: #38bdf8; font-size: 15px; font-weight: 800; }
        QLineEdit {
            background: #020617; color: #7dd3fc; border: 1px solid #334155;
            border-radius: 8px; padding: 8px; font-size: 12px;
        }
        QPushButton {
            background: #0ea5e9; color: white; border: none; border-radius: 8px;
            padding: 8px 14px; font-weight: 800;
        }
        QPushButton#soft { background: #1e293b; border: 1px solid #334155; }
        """
    )
    lay = QVBoxLayout(dlg)
    lay.setSpacing(10)
    title = QLabel("✅ 已上传到 Google 云端硬盘")
    title.setObjectName("title")
    lay.addWidget(title)
    if name:
        lay.addWidget(QLabel(f"文件名：{name}"))
    if link:
        lay.addWidget(QLabel("图片链接（已自动复制到剪贴板）："))
        row = QHBoxLayout()
        edit = QLineEdit(link)
        edit.setReadOnly(True)
        edit.selectAll()
        row.addWidget(edit, 1)

        def _copy() -> None:
            QApplication.clipboard().setText(link)
            tip.setText("链接已复制到剪贴板 ✓")

        btn_copy = QPushButton("复制链接")
        btn_copy.clicked.connect(_copy)
        row.addWidget(btn_copy)
        lay.addLayout(row)
        tip = QLabel("可直接粘贴分享。编辑器仍保持打开，可继续标注。")
        if auto_exit_hint:
            tip.setText("链接已复制。关闭此窗口后截图将结束。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#94a3b8;")
        lay.addWidget(tip)
        # Ensure clipboard has the link
        QApplication.clipboard().setText(link)
    else:
        lay.addWidget(QLabel("上传成功，但未返回可分享链接（请检查 Drive 权限/分享设置）。"))
    btns = QHBoxLayout()
    if link:
        btn_open = QPushButton("浏览器打开", objectName="soft")

        def _open() -> None:
            import webbrowser

            webbrowser.open(link)

        btn_open.clicked.connect(_open)
        btns.addWidget(btn_open)
    btns.addStretch(1)
    btn_ok = QPushButton("好的")
    btn_ok.clicked.connect(dlg.accept)
    btns.addWidget(btn_ok)
    lay.addLayout(btns)
    dlg.exec()


def start_screenshot(
    *,
    mode: str = "region",
    state: dict | None = None,
    on_done: Callable[[QImage | None], None] | None = None,
) -> ScreenshotEditor | None:
    """Launch capture+editor. mode: region | full."""
    global _EDITOR_REF
    cfg = {}
    if isinstance(state, dict):
        cfg = state.setdefault("screenshot", {})

    # brief delay so menus close
    app = QApplication.instance()
    if app is None:
        return None

    def _run() -> None:
        global _EDITOR_REF
        try:
            bg, geo = capture_virtual_desktop()
        except Exception as e:
            QMessageBox.warning(None, "截图失败", str(e))
            return

        def do_upload(path: Path) -> dict:
            from gdrive_client import GoogleDriveClient

            gcfg = dict(cfg.get("gdrive") or {})
            client = GoogleDriveClient(gcfg)
            result = client.upload_file(path)
            cfg.setdefault("gdrive", {}).update(gcfg)
            if state is not None and hasattr(state, "get"):
                state.setdefault("screenshot", cfg)
            fid = str(result.get("id") or "")
            link = str(result.get("webViewLink") or "").strip()
            if not link and fid:
                link = f"https://drive.google.com/file/d/{fid}/view"
            return {
                "id": fid,
                "name": str(result.get("name") or path.name),
                "link": link,
                "webViewLink": link,
            }

        on_upload = None
        g = cfg.get("gdrive") or {}
        if g.get("enabled"):
            try:
                from gdrive_client import GoogleDriveClient

                if GoogleDriveClient(g).is_connected():
                    on_upload = do_upload
            except Exception:
                on_upload = None

        ed = ScreenshotEditor(bg, geo, mode=mode, cfg=cfg, on_upload=on_upload)
        _EDITOR_REF = ed

        def _fin(img):
            if on_done:
                on_done(img)
            # keep pins
            for pin in ed._pinned:
                _PINNED_REFS.append(pin)

        ed.finished.connect(_fin)
        ed.show()
        ed.raise_()
        ed.activateWindow()
        ed.setFocus()

    QTimer.singleShot(120, _run)
    return None
