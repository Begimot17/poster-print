"""Dark theme: palette and stylesheet."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication

BG = "#14161b"
CARD = "#1c1f26"
FIELD = "#12141a"
BORDER = "#343a47"
TEXT = "#e6e8ee"
MUTED = "#9aa3b5"
ACCENT = "#7c5cff"
ACCENT_HOVER = "#8d70ff"
WARN = "#ffb454"

QSS = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-family: "Segoe UI"; font-size: 10pt; }}
QLabel, QCheckBox {{ background: transparent; }}
QScrollArea, #panel {{ background: transparent; border: none; }}
#card {{ background: {CARD}; border: 1px solid #2a2e38; border-radius: 12px; }}
#cardTitle {{ color: {MUTED}; font-size: 8pt; font-weight: 700; }}
#muted {{ color: {MUTED}; }}
#info {{ color: {TEXT}; background: {FIELD}; border-radius: 8px; padding: 10px; }}

QPushButton {{
    background: #272b35; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 12px;
}}
QPushButton:hover {{ background: #303542; }}
QPushButton:pressed {{ background: #3a4050; }}
QPushButton:disabled {{ color: #5d6474; background: #20232b; border-color: #272b35; }}
QPushButton#primary {{
    background: {ACCENT}; border: none; color: white; font-weight: 600; padding: 10px 12px;
}}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: #3a3558; color: #8a86a8; }}
QPushButton#preset {{ padding: 6px 0; }}

QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {FIELD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 5px 8px;
    min-height: 20px; selection-background-color: {ACCENT};
}}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QSpinBox, QDoubleSpinBox {{ padding-left: 10px; padding-right: 26px; }}
QComboBox::down-arrow, QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url(@ICONS@/down.png); width: 10px; height: 10px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url(@ICONS@/up.png); width: 10px; height: 10px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right;
    width: 24px; border: none; background: transparent;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 24px; border: none; background: transparent;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: #272b35; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border: 1px solid {BORDER}; border-radius: 4px; background: {FIELD};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT}; image: url(@ICONS@/check.png);
}}
QComboBox QAbstractItemView {{
    background: {CARD}; border: 1px solid {BORDER}; selection-background-color: {ACCENT};
    outline: none;
}}

QProgressBar {{ background: {FIELD}; border: none; border-radius: 4px; max-height: 8px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


def apply(app: QApplication) -> None:
    """Fusion with a dark palette, so the look does not depend on the Windows theme."""
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, BG),
        (QPalette.ColorRole.Base, FIELD),
        (QPalette.ColorRole.AlternateBase, CARD),
        (QPalette.ColorRole.Button, "#272b35"),
        (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.ButtonText, TEXT),
        (QPalette.ColorRole.ToolTipBase, CARD),
        (QPalette.ColorRole.ToolTipText, TEXT),
        (QPalette.ColorRole.Highlight, ACCENT),
        (QPalette.ColorRole.HighlightedText, "#ffffff"),
        (QPalette.ColorRole.PlaceholderText, MUTED),
    ):
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#5d6474"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#5d6474"))
    app.setPalette(palette)
    app.setStyleSheet(QSS.replace("@ICONS@", _icons_dir()))


def _icons_dir() -> str:
    """Draw the small glyphs the stylesheet refers to; returns a path with forward slashes."""
    global _icons
    if _icons is None:
        folder = Path(tempfile.mkdtemp(prefix="posterprint-"))
        shapes = {
            "down": ([(4, 9), (12, 17), (20, 9)], MUTED),
            "up": ([(4, 15), (12, 7), (20, 15)], MUTED),
            "check": ([(5, 12), (10, 17), (19, 7)], "#ffffff"),
        }
        for name, (points, color) in shapes.items():
            pixmap = QPixmap(24, 24)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(color), 2.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))
            painter.end()
            pixmap.save(str(folder / f"{name}.png"))
        _icons = folder.as_posix()
    return _icons


_icons: str | None = None
