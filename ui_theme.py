"""Shared modern UI theme for Quaker Parrot Pet.

Dark glass (music) + light surface (settings / LAN) with consistent
typography, spacing, and interactive states.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Palette — emerald / slate glassmorphism
# ---------------------------------------------------------------------------
C = {
    # Core brand
    "accent": "#34d399",
    "accent_hover": "#10b981",
    "accent_deep": "#059669",
    "accent_soft": "rgba(52, 211, 153, 0.18)",
    "accent_glow": "rgba(52, 211, 153, 0.35)",
    # Dark surfaces (music player, night panels)
    "bg0": "#0b1220",
    "bg1": "#111827",
    "bg2": "#1e293b",
    "bg3": "#334155",
    "border_d": "rgba(148, 163, 184, 0.22)",
    "text_d": "#f1f5f9",
    "text_d_muted": "#94a3b8",
    "text_d_dim": "#64748b",
    # Light surfaces (dashboard / LAN / todos)
    "bg_l": "#f8fafc",
    "bg_l_card": "#ffffff",
    "bg_l_soft": "#f1f5f9",
    "border_l": "#e2e8f0",
    "border_l_strong": "#cbd5e1",
    "text_l": "#0f172a",
    "text_l_muted": "#475569",
    "text_l_dim": "#64748b",
    # Semantic
    "danger": "#f87171",
    "warn": "#fbbf24",
    "info": "#38bdf8",
    "primary": "#0ea5e9",
    "primary_hover": "#0284c7",
}


def dark_glass_qss() -> str:
    """Frameless dark glass panel — music player & similar tools."""
    return f"""
    QWidget#MainFrame, QFrame#shell {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 rgba(17, 24, 39, 242), stop:1 rgba(11, 18, 32, 248));
        border: 1px solid {C['border_d']};
        border-radius: 16px;
    }}
    QLabel {{
        color: {C['text_d']};
        font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
        background: transparent;
    }}
    QLabel#muted, QLabel[role="muted"] {{
        color: {C['text_d_muted']};
        font-size: 11px;
    }}
    QLabel#title {{
        color: {C['accent']};
        font-size: 15px;
        font-weight: 700;
        letter-spacing: 0.3px;
    }}
    QLabel#section {{
        color: {C['text_d_muted']};
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.6px;
        padding-top: 4px;
    }}
    QPushButton {{
        background: rgba(51, 65, 85, 0.75);
        color: {C['text_d']};
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 10px;
        padding: 7px 12px;
        font-size: 12px;
        font-weight: 600;
        min-height: 18px;
    }}
    QPushButton:hover {{
        background: rgba(71, 85, 105, 0.95);
        border: 1px solid rgba(52, 211, 153, 0.35);
    }}
    QPushButton:pressed {{
        background: rgba(15, 23, 42, 0.95);
    }}
    QPushButton:disabled {{
        color: {C['text_d_dim']};
        background: rgba(30, 41, 59, 0.6);
        border-color: transparent;
    }}
    QPushButton#primary {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
            stop:0 {C['accent']}, stop:1 {C['accent_deep']});
        color: #042f1a;
        border: 1px solid rgba(16, 185, 129, 0.5);
        font-weight: 700;
    }}
    QPushButton#primary:hover {{
        background: {C['accent_hover']};
        color: #022c16;
    }}
    QPushButton#ghost {{
        background: transparent;
        border: 1px solid rgba(148, 163, 184, 0.25);
        color: {C['text_d_muted']};
    }}
    QPushButton#ghost:hover {{
        color: {C['text_d']};
        border-color: {C['accent']};
        background: {C['accent_soft']};
    }}
    QPushButton#danger {{
        background: rgba(248, 113, 113, 0.15);
        color: #fecaca;
        border: 1px solid rgba(248, 113, 113, 0.35);
    }}
    QPushButton#danger:hover {{
        background: rgba(248, 113, 113, 0.28);
    }}
    QPushButton#iconBtn {{
        background: transparent;
        border: none;
        color: {C['text_d_muted']};
        padding: 4px;
        border-radius: 8px;
        min-width: 28px;
        max-width: 32px;
        min-height: 28px;
    }}
    QPushButton#iconBtn:hover {{
        background: rgba(255,255,255,0.08);
        color: {C['text_d']};
    }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: rgba(15, 23, 42, 0.85);
        color: {C['text_d']};
        border: 1px solid rgba(148, 163, 184, 0.22);
        border-radius: 10px;
        padding: 7px 10px;
        font-size: 12px;
        selection-background-color: {C['accent_deep']};
        selection-color: white;
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border: 1px solid {C['accent']};
        background: rgba(15, 23, 42, 0.95);
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {C['text_d_muted']};
        width: 0; height: 0;
        margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background: #0f172a;
        color: {C['text_d']};
        border: 1px solid {C['border_d']};
        border-radius: 8px;
        selection-background-color: {C['accent_deep']};
        selection-color: #ffffff;
        outline: none;
        padding: 4px;
    }}
    QComboBox QAbstractItemView::item {{
        min-height: 28px;
        padding: 4px 10px;
        color: {C['text_d']};
        background: #0f172a;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background: {C['accent_soft']};
        color: {C['text_d']};
    }}
    QComboBox QAbstractItemView::item:selected {{
        background: {C['accent_deep']};
        color: #ffffff;
    }}
    QListWidget {{
        background: rgba(15, 23, 42, 0.72);
        border: 1px solid rgba(148, 163, 184, 0.16);
        border-radius: 12px;
        color: {C['text_d']};
        outline: none;
        padding: 4px;
    }}
    QListWidget::item {{
        padding: 8px 10px;
        border-radius: 8px;
        margin: 1px 2px;
        color: #e2e8f0;
    }}
    QListWidget::item:hover {{
        background: rgba(51, 65, 85, 0.55);
    }}
    QListWidget::item:selected {{
        background: {C['accent_soft']};
        color: #ecfdf5;
        border: 1px solid rgba(52, 211, 153, 0.35);
    }}
    QSlider::groove:horizontal {{
        height: 6px;
        background: rgba(51, 65, 85, 0.9);
        border-radius: 3px;
    }}
    QSlider::sub-page:horizontal {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 {C['accent_deep']}, stop:1 {C['accent']});
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: #ffffff;
        border: 2px solid {C['accent']};
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 8px;
    }}
    QSlider::handle:horizontal:hover {{
        background: {C['accent']};
        border-color: #ffffff;
    }}
    QCheckBox {{
        color: {C['text_d_muted']};
        font-size: 11px;
        spacing: 6px;
    }}
    QCheckBox::indicator {{
        width: 16px; height: 16px;
        border-radius: 5px;
        border: 1px solid rgba(148, 163, 184, 0.4);
        background: rgba(15, 23, 42, 0.8);
    }}
    QCheckBox::indicator:checked {{
        background: {C['accent']};
        border-color: {C['accent_deep']};
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        background: rgba(51, 65, 85, 0.8);
        border: none;
        width: 16px;
        border-radius: 4px;
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
        background: {C['accent_soft']};
    }}
    QProgressBar {{
        background: rgba(30, 41, 59, 0.9);
        border: none;
        border-radius: 6px;
        text-align: center;
        color: {C['text_d_muted']};
        height: 10px;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 {C['accent_deep']}, stop:1 {C['accent']});
        border-radius: 6px;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 4px 2px;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(148, 163, 184, 0.35);
        border-radius: 4px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(52, 211, 153, 0.55);
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    """


def light_surface_qss() -> str:
    """Light modern panel — dashboard, LAN, todos, notes."""
    return f"""
    QDialog, QWidget#DashRoot, QFrame#shell {{
        background: {C['bg_l']};
        color: {C['text_l']};
        font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    }}
    QFrame#shell {{
        background: {C['bg_l_card']};
        border: 1px solid {C['border_l']};
        border-radius: 16px;
    }}
    QLabel {{
        color: {C['text_l']};
        background: transparent;
    }}
    QLabel#muted {{
        color: {C['text_l_muted']};
        font-size: 11px;
    }}
    QLabel#title {{
        color: {C['accent_deep']};
        font-size: 14px;
        font-weight: 800;
    }}
    QLabel#section {{
        color: {C['text_l']};
        font-size: 12px;
        font-weight: 800;
    }}
    QPushButton {{
        background: {C['bg_l_card']};
        color: {C['text_l']};
        border: 1px solid {C['border_l_strong']};
        border-radius: 10px;
        padding: 7px 12px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: {C['bg_l_soft']};
        border-color: {C['accent']};
        color: #065f46;
    }}
    QPushButton:pressed {{
        background: #e2e8f0;
    }}
    QPushButton:disabled {{
        color: #94a3b8;
        background: #f1f5f9;
    }}
    QPushButton#primary {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
            stop:0 {C['accent']}, stop:1 {C['accent_deep']});
        color: #042f1a;
        border: 1px solid {C['accent_deep']};
        font-weight: 700;
    }}
    QPushButton#primary:hover {{
        background: {C['accent_hover']};
    }}
    QPushButton#ghost {{
        background: transparent;
        border: 1px solid {C['border_l']};
        color: {C['text_l_muted']};
    }}
    QPushButton#soft {{
        background: #ecfdf5;
        border: 1px solid #a7f3d0;
        color: #065f46;
    }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
        background: #ffffff;
        color: {C['text_l']};
        border: 1px solid {C['border_l_strong']};
        border-radius: 10px;
        padding: 6px 10px;
        font-size: 12px;
        selection-background-color: #a7f3d0;
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
        border: 1px solid {C['accent_deep']};
    }}
    QComboBox QAbstractItemView {{
        background: #ffffff;
        color: {C['text_l']};
        border: 1px solid {C['border_l']};
        selection-background-color: #d1fae5;
        selection-color: {C['text_l']};
        outline: none;
    }}
    QListWidget {{
        background: #ffffff;
        border: 1px solid {C['border_l']};
        border-radius: 12px;
        color: {C['text_l']};
        outline: none;
        padding: 4px;
    }}
    QListWidget::item {{
        padding: 7px 8px;
        border-radius: 8px;
        color: {C['text_l']};
    }}
    QListWidget::item:selected {{
        background: #d1fae5;
        color: #064e3b;
    }}
    QListWidget::item:hover {{
        background: #f0fdf4;
    }}
    QTabWidget::pane {{
        border: 1px solid {C['border_l']};
        border-radius: 12px;
        background: #ffffff;
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {C['text_l_muted']};
        padding: 8px 14px;
        margin-right: 2px;
        border-top-left-radius: 10px;
        border-top-right-radius: 10px;
        font-weight: 600;
        font-size: 12px;
    }}
    QTabBar::tab:selected {{
        background: #ffffff;
        color: {C['accent_deep']};
        border: 1px solid {C['border_l']};
        border-bottom: 1px solid #ffffff;
    }}
    QTabBar::tab:hover:!selected {{
        color: {C['text_l']};
        background: {C['bg_l_soft']};
    }}
    QSlider::groove:horizontal {{
        height: 6px;
        background: #e2e8f0;
        border-radius: 3px;
    }}
    QSlider::sub-page:horizontal {{
        background: {C['accent']};
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: #ffffff;
        border: 2px solid {C['accent_deep']};
        width: 14px; height: 14px;
        margin: -5px 0;
        border-radius: 8px;
    }}
    QCheckBox {{
        color: {C['text_l']};
        font-size: 11px;
        spacing: 6px;
    }}
    QCheckBox::indicator {{
        width: 16px; height: 16px;
        border-radius: 5px;
        border: 1px solid {C['border_l_strong']};
        background: #ffffff;
    }}
    QCheckBox::indicator:checked {{
        background: {C['accent']};
        border-color: {C['accent_deep']};
    }}
    QProgressBar {{
        background: #e2e8f0;
        border: none;
        border-radius: 6px;
        text-align: center;
        color: {C['text_l_muted']};
        height: 10px;
    }}
    QProgressBar::chunk {{
        background: {C['accent']};
        border-radius: 6px;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 4px 2px;
    }}
    QScrollBar::handle:vertical {{
        background: #cbd5e1;
        border-radius: 4px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {C['accent']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QSpinBox::up-button, QSpinBox::down-button {{
        background: {C['bg_l_soft']};
        border: none;
        width: 16px;
        border-radius: 4px;
    }}
    """


def drag_bar_qss(*, dark: bool = False, accent_bg: str | None = None) -> str:
    if dark:
        bg = accent_bg or "rgba(16, 185, 129, 0.15)"
        fg = C["accent"]
        hover = "rgba(255,255,255,0.08)"
        btn = C["text_d_muted"]
        btn_h = C["text_d"]
    else:
        bg = accent_bg or "#d1fae5"
        fg = "#065f46"
        hover = "rgba(0,0,0,0.06)"
        btn = "#64748b"
        btn_h = "#0f172a"
    return f"""
    QFrame#dragBar {{
        background: {bg};
        border: 0;
        border-top-left-radius: 14px;
        border-top-right-radius: 14px;
    }}
    QLabel {{
        color: {fg};
        font-weight: 700;
        font-size: 12px;
        background: transparent;
    }}
    QPushButton {{
        background: transparent;
        border: 0;
        color: {btn};
        font-size: 13px;
        min-width: 28px;
        min-height: 28px;
        border-radius: 8px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: {hover};
        color: {btn_h};
    }}
    """


def apply_window_geometry(
    widget,
    state: dict,
    *,
    key_prefix: str,
    default_w: int,
    default_h: int,
    default_x: int | None = None,
    default_y: int | None = None,
    min_w: int = 280,
    min_h: int = 200,
) -> None:
    """Restore size/position from state dict keys: {prefix}_w/h/x/y."""
    w = max(min_w, int(state.get(f"{key_prefix}_w") or default_w))
    h = max(min_h, int(state.get(f"{key_prefix}_h") or default_h))
    widget.resize(w, h)
    x = state.get(f"{key_prefix}_x")
    y = state.get(f"{key_prefix}_y")
    if x is not None and y is not None:
        try:
            widget.move(int(x), int(y))
            return
        except (TypeError, ValueError):
            pass
    if default_x is not None and default_y is not None:
        widget.move(default_x, default_y)


def save_window_geometry(widget, state: dict, *, key_prefix: str, save_cb=None) -> None:
    state[f"{key_prefix}_w"] = int(widget.width())
    state[f"{key_prefix}_h"] = int(widget.height())
    state[f"{key_prefix}_x"] = int(widget.x())
    state[f"{key_prefix}_y"] = int(widget.y())
    if save_cb:
        try:
            save_cb()
        except Exception:
            pass


def clamp_to_screens(widget) -> None:
    """If window is off-screen (monitor unplugged), snap back."""
    try:
        from PyQt6.QtGui import QGuiApplication

        geo = widget.frameGeometry()
        for screen in QGuiApplication.screens():
            if screen.availableGeometry().intersects(geo):
                return
        # Off all screens — center on primary
        primary = QGuiApplication.primaryScreen()
        if primary:
            ag = primary.availableGeometry()
            widget.move(
                ag.left() + max(0, (ag.width() - widget.width()) // 2),
                ag.top() + max(0, (ag.height() - widget.height()) // 2),
            )
    except Exception:
        pass
