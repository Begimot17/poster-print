"""Before/after viewer: plain enlargement on the left, the prepared poster on the right.

Only the visible region is rendered, so a 100+ megapixel poster costs no extra memory.
"""
from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app import theme, tiles
from app.pipeline import Prepared

MAX_ZOOM = 4.0
_GRAB_PX = 12


def pil_to_pixmap(img: Image.Image) -> QPixmap:
    rgb = img.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    return QPixmap.fromImage(
        QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888).copy()
    )


class CompareView(QWidget):
    """Zoomable view with a draggable divider between 'before' and 'after'."""

    def __init__(self, original: Image.Image, prepared: Prepared, fill: bool) -> None:
        super().__init__()
        self._source = tiles.to_rgb(original)
        self._poster = prepared.poster
        self._scale, self._off_x, self._off_y = tiles.poster_to_source(
            prepared.layout, self._source.size, fill
        )
        self._zoom = 1.0
        self._cx = self._poster.width / 2
        self._cy = self._poster.height / 2
        self._split = 0.5
        self._dst = QRect()
        self._before: QPixmap | None = None
        self._after: QPixmap | None = None
        self._drag: str | None = None
        self._last = QPointF()
        self.setMinimumSize(480, 360)
        self.setMouseTracking(True)

    def fit_zoom(self) -> float:
        return min(self.width() / self._poster.width, self.height() / self._poster.height)

    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        zoom = max(min(self.fit_zoom(), 1.0), min(MAX_ZOOM, zoom))
        if anchor is not None:
            dx, dy = anchor.x() - self.width() / 2, anchor.y() - self.height() / 2
            self._cx += dx / self._zoom - dx / zoom
            self._cy += dy / self._zoom - dy / zoom
        self._zoom = zoom
        self._invalidate()

    def _invalidate(self) -> None:
        self._before = self._after = None
        self.update()

    def _render(self) -> None:
        width, height, zoom = self.width(), self.height(), self._zoom
        poster_w, poster_h = self._poster.size

        def axis(center: float, view: float, total: int, screen: int) -> tuple[float, float, int, float]:
            if view >= total:
                return 0.0, float(total), round((screen - total * zoom) / 2), total / 2
            center = min(max(center, view / 2), total - view / 2)
            return center - view / 2, center + view / 2, 0, center

        x0, x1, dst_x, self._cx = axis(self._cx, width / zoom, poster_w, width)
        y0, y1, dst_y, self._cy = axis(self._cy, height / zoom, poster_h, height)
        size = (max(1, round((x1 - x0) * zoom)), max(1, round((y1 - y0) * zoom)))
        self._dst = QRect(dst_x, dst_y, *size)

        after = self._poster.resize(
            size,
            Image.Resampling.BILINEAR if zoom < 1 else Image.Resampling.BICUBIC,
            box=(x0, y0, x1, y1),
            reducing_gap=2.0 if zoom < 1 else None,
        )
        s = self._scale
        extent = (
            (x0 + self._off_x) / s, (y0 + self._off_y) / s,
            (x1 + self._off_x) / s, (y1 + self._off_y) / s,
        )
        before = self._source.transform(
            size, Image.Transform.EXTENT, extent, Image.Resampling.BICUBIC,
            fillcolor=(255, 255, 255),
        )
        self._after, self._before = pil_to_pixmap(after), pil_to_pixmap(before)

    def _split_x(self) -> int:
        return self._dst.x() + round(self._split * self._dst.width())

    def paintEvent(self, _event) -> None:  # noqa: N802
        if self._after is None:
            self._render()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.FIELD))
        dst, cut = self._dst, self._split_x() - self._dst.x()
        painter.drawPixmap(dst.x(), dst.y(), self._before, 0, 0, cut, dst.height())
        painter.drawPixmap(dst.x() + cut, dst.y(), self._after, cut, 0, dst.width() - cut, dst.height())

        x = self._split_x()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawLine(x, dst.top(), x, dst.bottom())
        painter.setBrush(QColor(theme.ACCENT))
        painter.drawEllipse(QPointF(x, dst.center().y()), 11, 11)

        for text, left in (("Обычное увеличение", True), ("Подготовленный постер", False)):
            box = QRectF(0, 0, painter.fontMetrics().horizontalAdvance(text) + 20, 26)
            box.moveTop(dst.top() + 10)
            if left:
                box.moveLeft(dst.left() + 10)
            else:
                box.moveRight(dst.right() - 10)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 150))
            painter.drawRoundedRect(box, 13, 13)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def resizeEvent(self, _event) -> None:  # noqa: N802
        self.set_zoom(self._zoom)

    def wheelEvent(self, event) -> None:  # noqa: N802
        self.set_zoom(self._zoom * 1.25 ** (event.angleDelta().y() / 120), event.position())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        near = abs(event.position().x() - self._split_x()) <= _GRAB_PX
        self._drag = "split" if near else "pan"
        self._last = event.position()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if self._drag == "split" and self._dst.width() > 0:
            self._split = min(1.0, max(0.0, (pos.x() - self._dst.x()) / self._dst.width()))
            self.update()
        elif self._drag == "pan":
            self._cx -= (pos.x() - self._last.x()) / self._zoom
            self._cy -= (pos.y() - self._last.y()) / self._zoom
            self._last = pos
            self._invalidate()
        else:
            near = abs(pos.x() - self._split_x()) <= _GRAB_PX
            self.setCursor(Qt.CursorShape.SplitHCursor if near else Qt.CursorShape.OpenHandCursor)

    def mouseReleaseEvent(self, _event) -> None:  # noqa: N802
        self._drag = None


class CompareDialog(QDialog):
    def __init__(self, original: Image.Image, prepared: Prepared, fill: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Сравнение: до и после")
        self.resize(1100, 760)
        self.view = CompareView(original, prepared, fill)

        bar = QHBoxLayout()
        for text, zoom in (("Весь постер", 0.0), ("100%", 1.0), ("200%", 2.0), ("400%", 4.0)):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, z=zoom: self.view.set_zoom(z))
            bar.addWidget(button)
        if prepared.passes:
            summary = f"ИИ-апскейл, проходов: {prepared.passes}, увеличение ×{prepared.scale:.2f}"
        else:
            summary = "ИИ-апскейл не применялся: обе половины одинаковы"
        hint = QLabel(f"{summary}.  Колесо: масштаб, перетаскивание: сдвиг, линию можно двигать.")
        hint.setObjectName("muted")
        bar.addWidget(hint, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.addLayout(bar)
        root.addWidget(self.view, 1)
