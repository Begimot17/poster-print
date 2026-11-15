"""PySide6 GUI for PosterPrint. All user-visible strings in Russian."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = None

from PySide6.QtCore import (
    Qt,
    QThread,
    Signal,
    QObject,
    QRectF,
    QPointF,
    QSizeF,
)
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QBrush,
    QFont,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStatusBar,
    QStyle,
    QVBoxLayout,
    QWidget,
)

import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QAbstractSpinBox

from app import pipeline, printer, theme, update
from app.compare import CompareDialog
from app.layout import A4, Layout, Sheet
from app.pipeline import Cancelled, Prepared, Settings
from app import upscale as upscale_mod
from app import tiles as tiles_mod

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_IMAGE_FILTER = "Изображения (*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif)"
_NO_PRINTER_LABEL = "Без принтера (A4, только файлы)"
_PREVIEW_MAX_PX = 2000

_MODEL_LABELS: list[tuple[str, str]] = [
    ("anime", "Аниме"),
    ("photo", "Фото"),
    ("fast", "Быстрое"),
    ("none", "Без апскейла"),
]

_ORIENTATION_LABELS: list[tuple[str, str]] = [
    ("auto", "Авто"),
    ("portrait", "Книжная"),
    ("landscape", "Альбомная"),
]

_PRESETS: list[tuple[str, int, int]] = [
    ("2×2", 2, 2),
    ("3×3", 3, 3),
    ("3×4", 3, 4),
    ("4×4", 4, 4),
]


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class _Worker(QObject):
    """Runs a callable in a QThread, emitting progress/finished/failed."""

    progress = Signal(str, float)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, cancel_event: threading.Event) -> None:
        super().__init__()
        self._fn = fn
        self._cancel_event = cancel_event

    def run(self) -> None:
        try:
            result = self._fn(
                progress=lambda msg, frac: self.progress.emit(msg, frac),
                cancelled=lambda: self._cancel_event.is_set(),
            )
            self.finished.emit(result)
        except Cancelled:
            self.failed.emit("Отменено")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


# ---------------------------------------------------------------------------
# Preview widget
# ---------------------------------------------------------------------------

class Preview(QWidget):
    """Paints the source image placed in the poster exactly as fit_to_poster would."""

    sheetSelected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._layout: Layout | None = None
        self._fill: bool = True
        self._selected: int = -1
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_content(self, pixmap: QPixmap | None, layout: Layout | None, fill: bool) -> None:
        self._pixmap = pixmap
        self._layout = layout
        self._fill = fill
        self._selected = -1
        self.update()

    def set_selected(self, idx: int) -> None:
        self._selected = idx
        self.update()

    # ------------------------------------------------------------------
    def _poster_rect(self, widget_w: int, widget_h: int) -> tuple[float, float, float, float]:
        """Return (x, y, w, h) of the poster rectangle inside the widget."""
        if self._layout is None:
            return 0.0, 0.0, float(widget_w), float(widget_h)
        lw, lh = self._layout.poster_w_px, self._layout.poster_h_px
        ratio = lw / lh
        margin = 8
        aw, ah = widget_w - 2 * margin, widget_h - 2 * margin
        if aw / ah > ratio:
            pw = ah * ratio
            ph = ah
        else:
            pw = aw
            ph = aw / ratio
        x = (widget_w - pw) / 2
        y = (widget_h - ph) / 2
        return x, y, pw, ph

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.FIELD))
        painter.drawRoundedRect(QRectF(self.rect()), 12, 12)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        if self._layout is None or self._pixmap is None:
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter,
                "Перетащите сюда картинку\nили нажмите «Открыть картинку…»",
            )
            return

        lay = self._layout
        ww, wh = self.width(), self.height()
        px, py, pw, ph = self._poster_rect(ww, wh)

        # --- Draw image inside poster area (simulating fit_to_poster) ---
        src_w = self._pixmap.width()
        src_h = self._pixmap.height()
        if src_w > 0 and src_h > 0:
            if self._fill:
                rx, ry = pw / src_w, ph / src_h
                scale = max(rx, ry)
                scaled_w = src_w * scale
                scaled_h = src_h * scale
                crop_x = (scaled_w - pw) / 2
                crop_y = (scaled_h - ph) / 2
                src_rect = QRectF(
                    crop_x / scale, crop_y / scale,
                    pw / scale, ph / scale,
                )
                dst_rect = QRectF(px, py, pw, ph)
                painter.drawPixmap(dst_rect, self._pixmap, src_rect)
            else:
                rx, ry = pw / src_w, ph / src_h
                scale = min(rx, ry)
                dw = src_w * scale
                dh = src_h * scale
                img_x = px + (pw - dw) / 2
                img_y = py + (ph - dh) / 2
                painter.fillRect(QRectF(px, py, pw, ph), QColor(255, 255, 255))
                painter.drawPixmap(
                    QRectF(img_x, img_y, dw, dh),
                    self._pixmap,
                    QRectF(0, 0, src_w, src_h),
                )

        # --- Draw sheet grid ---
        poster_w_px = lay.poster_w_px
        poster_h_px = lay.poster_h_px
        step_px_x = lay.tile_w_px - lay.overlap_px
        step_px_y = lay.tile_h_px - lay.overlap_px
        tile_w_frac = lay.tile_w_px / poster_w_px
        tile_h_frac = lay.tile_h_px / poster_h_px

        idx = 0
        for r in range(lay.rows):
            for c in range(lay.cols):
                tx0 = px + (c * step_px_x / poster_w_px) * pw
                ty0 = py + (r * step_px_y / poster_h_px) * ph
                tw = tile_w_frac * pw
                th = tile_h_frac * ph

                # Overlap bands (translucent)
                if lay.overlap_px > 0:
                    ovx = lay.overlap_px / poster_w_px * pw
                    ovy = lay.overlap_px / poster_h_px * ph
                    band_color = QColor(255, 255, 0, 40)
                    if c < lay.cols - 1:
                        painter.fillRect(QRectF(tx0 + tw - ovx, ty0, ovx, th), band_color)
                    if r < lay.rows - 1:
                        painter.fillRect(QRectF(tx0, ty0 + th - ovy, tw, ovy), band_color)

                # Highlight selected
                if idx == self._selected:
                    painter.fillRect(QRectF(tx0, ty0, tw, th), QColor(124, 92, 255, 70))

                # Sheet border
                pen = QPen(QColor(255, 255, 255, 180) if idx != self._selected else QColor(theme.ACCENT))
                pen.setWidth(1)
                painter.setPen(pen)
                painter.drawRect(QRectF(tx0, ty0, tw, th))

                # Sheet number label
                painter.setPen(QColor(255, 255, 255, 200))
                font = QFont()
                font.setPointSizeF(max(7.0, min(14.0, tw / 4)))
                painter.setFont(font)
                painter.drawText(
                    QRectF(tx0, ty0, tw, th),
                    Qt.AlignmentFlag.AlignCenter,
                    f"{r + 1}×{c + 1}",
                )
                idx += 1

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._layout is None:
            return
        ww, wh = self.width(), self.height()
        px, py, pw, ph = self._poster_rect(ww, wh)
        mx, my = event.position().x(), event.position().y()
        lay = self._layout
        poster_w_px = lay.poster_w_px
        poster_h_px = lay.poster_h_px
        step_px_x = lay.tile_w_px - lay.overlap_px
        step_px_y = lay.tile_h_px - lay.overlap_px

        idx = 0
        for r in range(lay.rows):
            for c in range(lay.cols):
                tx0 = px + (c * step_px_x / poster_w_px) * pw
                ty0 = py + (r * step_px_y / poster_h_px) * ph
                tw = lay.tile_w_px / poster_w_px * pw
                th = lay.tile_h_px / poster_h_px * ph
                if tx0 <= mx <= tx0 + tw and ty0 <= my <= ty0 + th:
                    self._selected = idx
                    self.update()
                    self.sheetSelected.emit(idx)
                    return
                idx += 1


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    _update_found = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PosterPrint")
        self.setMinimumSize(1100, 700)
        self.setAcceptDrops(True)

        # State
        self._image: Image.Image | None = None
        self._image_path: Path | None = None
        self._pixmap: QPixmap | None = None          # downscaled for preview
        self._prepared: Prepared | None = None
        self._layout: Layout | None = None
        self._landscape: bool = False
        self._base_sheet: Sheet = A4
        self._devmode: Any = None
        self._selected_tile: int = -1
        self._thread: QThread | None = None
        self._cancel_event = threading.Event()
        self._running: bool = False
        self._worker: _Worker | None = None
        self._last_result: object = None
        self._last_error: str | None = None
        self._pending_callback = None
        self._release: update.Release | None = None
        self._update_found.connect(self._on_update_found)

        self._build_ui()
        self._populate_printers()
        self._refresh_plan()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        self._preview = Preview()
        self._preview.sheetSelected.connect(self._on_sheet_selected)
        root.addWidget(self._preview, stretch=1)

        panel = QWidget()
        panel.setObjectName("panel")
        column = QVBoxLayout(panel)
        column.setContentsMargins(0, 0, 10, 0)
        column.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(400)
        scroll.setWidget(panel)
        root.addWidget(scroll)

        def card(title: str) -> QVBoxLayout:
            box = QFrame()
            box.setObjectName("card")
            inner = QVBoxLayout(box)
            inner.setContentsMargins(14, 12, 14, 14)
            inner.setSpacing(8)
            head = QLabel(title.upper())
            head.setObjectName("cardTitle")
            inner.addWidget(head)
            column.addWidget(box)
            return inner

        def form(parent: QVBoxLayout) -> QFormLayout:
            layout = QFormLayout()
            layout.setSpacing(8)
            layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            parent.addLayout(layout)
            return layout

        def muted(text: str = "") -> QLabel:
            label = QLabel(text)
            label.setObjectName("muted")
            label.setWordWrap(True)
            return label

        # -- Image --
        box = card("Картинка")
        self._btn_open = QPushButton("Открыть картинку…")
        self._btn_open.clicked.connect(self._open_image_dialog)
        box.addWidget(self._btn_open)
        self._lbl_file = muted("Файл не выбран. Можно перетащить картинку в окно.")
        box.addWidget(self._lbl_file)

        # -- Printer --
        box = card("Принтер")
        self._combo_printer = QComboBox()
        self._combo_printer.currentIndexChanged.connect(self._on_printer_changed)
        box.addWidget(self._combo_printer)
        btn_printer_settings = QPushButton("Настройки принтера…")
        btn_printer_settings.clicked.connect(self._on_printer_settings)
        box.addWidget(btn_printer_settings)
        self._lbl_margins = muted()
        box.addWidget(self._lbl_margins)

        # -- Layout --
        box = card("Раскладка")
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        for label, cols, rows in _PRESETS:
            btn = QPushButton(label)
            btn.setObjectName("preset")
            btn.clicked.connect(lambda checked=False, c=cols, r=rows: self._apply_preset(c, r))
            preset_row.addWidget(btn)
        box.addLayout(preset_row)

        fields = form(box)
        self._spin_cols = QSpinBox()
        self._spin_cols.setRange(1, 10)
        self._spin_cols.setValue(2)
        self._spin_cols.valueChanged.connect(self._on_settings_changed)
        fields.addRow("Листов по ширине", self._spin_cols)

        self._spin_rows = QSpinBox()
        self._spin_rows.setRange(1, 10)
        self._spin_rows.setValue(2)
        self._spin_rows.valueChanged.connect(self._on_settings_changed)
        fields.addRow("Листов по высоте", self._spin_rows)

        self._combo_orient = QComboBox()
        for key, label in _ORIENTATION_LABELS:
            self._combo_orient.addItem(label, key)
        self._combo_orient.currentIndexChanged.connect(self._on_settings_changed)
        fields.addRow("Ориентация листа", self._combo_orient)

        self._combo_fill = QComboBox()
        self._combo_fill.addItem("Заполнить (с обрезкой)", True)
        self._combo_fill.addItem("Вписать (белые поля)", False)
        self._combo_fill.currentIndexChanged.connect(self._on_settings_changed)
        fields.addRow("Размещение", self._combo_fill)

        self._spin_overlap = QDoubleSpinBox()
        self._spin_overlap.setRange(0.0, 20.0)
        self._spin_overlap.setSingleStep(1.0)
        self._spin_overlap.setDecimals(1)
        self._spin_overlap.setValue(8.0)
        self._spin_overlap.setSuffix(" мм")
        self._spin_overlap.valueChanged.connect(self._on_settings_changed)
        fields.addRow("Нахлёст", self._spin_overlap)

        self._chk_marks = QCheckBox("Метки совмещения")
        self._chk_marks.setChecked(True)
        self._chk_marks.stateChanged.connect(self._on_settings_changed)
        box.addWidget(self._chk_marks)

        # -- Quality --
        box = card("Качество")
        fields = form(box)
        self._combo_model = QComboBox()
        for key, label in _MODEL_LABELS:
            self._combo_model.addItem(label, key)
        self._combo_model.currentIndexChanged.connect(self._on_settings_changed)
        fields.addRow("Улучшение", self._combo_model)

        self._spin_dpi = QSpinBox()
        self._spin_dpi.setRange(150, 600)
        self._spin_dpi.setSingleStep(50)
        self._spin_dpi.setValue(300)
        self._spin_dpi.setSuffix(" dpi")
        self._spin_dpi.valueChanged.connect(self._on_settings_changed)
        fields.addRow("Качество", self._spin_dpi)

        self._lbl_info = QLabel("Откройте картинку, чтобы увидеть расчёт.")
        self._lbl_info.setObjectName("info")
        self._lbl_info.setWordWrap(True)
        box.addWidget(self._lbl_info)

        # -- Result --
        box = card("Результат")
        self._btn_prepare = QPushButton("Подготовить")
        self._btn_prepare.setObjectName("primary")
        self._btn_prepare.clicked.connect(self._on_prepare)
        box.addWidget(self._btn_prepare)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._btn_compare = QPushButton("Сравнить до/после")
        self._btn_compare.clicked.connect(self._on_compare)
        self._btn_compare.setEnabled(False)
        row.addWidget(self._btn_compare)
        self._btn_folder = QPushButton("Папка результатов")
        self._btn_folder.clicked.connect(self._on_open_folder)
        row.addWidget(self._btn_folder)
        box.addLayout(row)

        self._btn_print_all = QPushButton("Печать всех листов")
        self._btn_print_all.clicked.connect(lambda: self._on_print(all_tiles=True))
        box.addWidget(self._btn_print_all)

        self._btn_print_sel = QPushButton("Печать выбранного листа")
        self._btn_print_sel.clicked.connect(lambda: self._on_print(all_tiles=False))
        box.addWidget(self._btn_print_sel)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._btn_save_pdf = QPushButton("Сохранить PDF…")
        self._btn_save_pdf.clicked.connect(self._on_save_pdf)
        row.addWidget(self._btn_save_pdf)
        self._btn_save_png = QPushButton("Сохранить PNG…")
        self._btn_save_png.clicked.connect(self._on_save_png)
        row.addWidget(self._btn_save_png)
        box.addLayout(row)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        box.addWidget(self._progress_bar)

        self._lbl_status = muted()
        box.addWidget(self._lbl_status)

        self._btn_cancel = QPushButton("Отмена")
        self._btn_cancel.setVisible(False)
        self._btn_cancel.clicked.connect(self._on_cancel)
        box.addWidget(self._btn_cancel)

        # -- Update notice (hidden until a newer release is found) --
        self._update_card = QFrame()
        self._update_card.setObjectName("card")
        update_box = QVBoxLayout(self._update_card)
        update_box.setContentsMargins(14, 12, 14, 14)
        update_box.setSpacing(8)
        self._lbl_update = QLabel("")
        self._lbl_update.setWordWrap(True)
        update_box.addWidget(self._lbl_update)
        self._btn_update = QPushButton("Скачать обновление")
        self._btn_update.setObjectName("primary")
        self._btn_update.clicked.connect(self._on_download_update)
        update_box.addWidget(self._btn_update)
        self._update_card.setVisible(False)
        column.addWidget(self._update_card)

        version = muted(f"PosterPrint {update.__version__}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(version)
        column.addStretch(1)

        for spin in central.findChildren(QAbstractSpinBox):
            spin.lineEdit().setTextMargins(8, 0, 0, 0)

    # ------------------------------------------------------------------
    # Printer helpers
    # ------------------------------------------------------------------

    def _populate_printers(self) -> None:
        self._combo_printer.blockSignals(True)
        self._combo_printer.clear()
        printers = printer.list_printers()
        for name in printers:
            self._combo_printer.addItem(name, name)
        self._combo_printer.addItem(_NO_PRINTER_LABEL, None)

        # Pre-select default printer
        default = printer.default_printer()
        if default:
            idx = self._combo_printer.findData(default)
            if idx >= 0:
                self._combo_printer.setCurrentIndex(idx)
        else:
            self._combo_printer.setCurrentIndex(self._combo_printer.count() - 1)

        self._combo_printer.blockSignals(False)
        self._on_printer_changed()

    def _current_printer_name(self) -> str | None:
        return self._combo_printer.currentData()

    def _is_no_printer(self) -> bool:
        return self._current_printer_name() is None

    def _on_printer_changed(self) -> None:
        name = self._current_printer_name()
        self._devmode = None
        if name is None:
            self._base_sheet = A4
            self._lbl_margins.setText("Поля: A4 по умолчанию")
        else:
            self._query_printer(name)
        self._prepared = None
        self._update_print_buttons()
        self._refresh_plan()

    def _query_printer(self, name: str) -> None:
        try:
            if self._devmode is None:
                self._devmode = printer.get_devmode(name)
            info = printer.query(name, self._devmode)
            self._base_sheet = info.sheet
            if info.borderless:
                self._lbl_margins.setText("Печать без полей")
                self._spin_overlap.blockSignals(True)
                self._spin_overlap.setValue(0.0)
                self._spin_overlap.blockSignals(False)
            else:
                s = info.sheet
                self._lbl_margins.setText(
                    f"Поля: Л{s.left_mm:.1f}/В{s.top_mm:.1f}/П{s.right_mm:.1f}/Н{s.bottom_mm:.1f} мм"
                )
        except printer.PrinterError as exc:
            QMessageBox.warning(self, "Принтер", str(exc))
            self._base_sheet = A4
            self._devmode = None
            self._lbl_margins.setText("Поля: A4 по умолчанию (ошибка принтера)")

    def _on_printer_settings(self) -> None:
        name = self._current_printer_name()
        if name is None:
            QMessageBox.information(self, "Принтер", "Принтер не выбран.")
            return
        try:
            if self._devmode is None:
                self._devmode = printer.get_devmode(name)
            new_devmode = printer.configure(name, self._devmode, int(self.winId()))
            if new_devmode is not None:
                self._devmode = new_devmode
                self._query_printer(name)
                self._prepared = None
                self._refresh_plan()
        except printer.PrinterError as exc:
            QMessageBox.warning(self, "Принтер", str(exc))

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------

    def _current_settings(self) -> Settings:
        return Settings(
            cols=self._spin_cols.value(),
            rows=self._spin_rows.value(),
            orientation=self._combo_orient.currentData(),
            fill=bool(self._combo_fill.currentData()),
            model=self._combo_model.currentData(),
            want_dpi=self._spin_dpi.value(),
            overlap_mm=self._spin_overlap.value(),
            marks=self._chk_marks.isChecked(),
        )

    def _apply_preset(self, cols: int, rows: int) -> None:
        self._spin_cols.blockSignals(True)
        self._spin_rows.blockSignals(True)
        self._spin_cols.setValue(cols)
        self._spin_rows.setValue(rows)
        self._spin_cols.blockSignals(False)
        self._spin_rows.blockSignals(False)
        self._on_settings_changed()

    def _on_settings_changed(self) -> None:
        self._prepared = None
        self._refresh_plan()

    # ------------------------------------------------------------------
    # Plan refresh (cheap, runs on UI thread)
    # ------------------------------------------------------------------

    def _refresh_plan(self) -> None:
        self._selected_tile = -1
        self._btn_compare.setEnabled(self._prepared is not None and not self._running)
        if self._image is None:
            self._preview.set_content(None, None, True)
            self._lbl_info.setText("Откройте картинку, чтобы увидеть расчёт.")
            return
        try:
            settings = self._current_settings()
            layout, landscape, scale, passes = pipeline.plan(
                settings, self._base_sheet, self._image.size
            )
            self._layout = layout
            self._landscape = landscape
            self._preview.set_content(self._pixmap, layout, settings.fill)
            # Build info string
            pw_cm = layout.poster_w_mm / 10
            ph_cm = layout.poster_h_mm / 10
            n_sheets = layout.cols * layout.rows
            res_w = layout.poster_w_px
            res_h = layout.poster_h_px
            actual_dpi = layout.dpi
            info = (
                f"Постер: {pw_cm:.1f}×{ph_cm:.1f} см\n"
                f"Листов: {n_sheets}\n"
                f"Разрешение: {res_w}×{res_h} пкс, {actual_dpi:.0f} dpi\n"
                f"Увеличение: ×{scale:.2f}\n"
                f"AI-проходов: {passes if settings.model != 'none' else 0}"
            )
            self._lbl_info.setText(info)
        except Exception as exc:  # noqa: BLE001
            self._lbl_info.setText(f"Ошибка: {exc}")
            self._layout = None
            self._preview.set_content(self._pixmap, None, True)

    # ------------------------------------------------------------------
    # Image loading
    # ------------------------------------------------------------------

    def _open_image_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Открыть картинку", "", _IMAGE_FILTER)
        if path:
            self._load_image(Path(path))

    def _load_image(self, path: Path) -> None:
        try:
            img = ImageOps.exif_transpose(Image.open(path))
            img.load()
            self._image = img
            self._image_path = path
            w, h = img.size
            self._lbl_file.setText(f"{path.name}\n{w}×{h} пкс")
            # Downscale for preview
            max_side = _PREVIEW_MAX_PX
            if max(w, h) > max_side:
                scale = max_side / max(w, h)
                thumb = img.convert("RGB").resize(
                    (round(w * scale), round(h * scale)), Image.LANCZOS
                )
            else:
                thumb = img.convert("RGB")
            data = thumb.tobytes("raw", "RGB")
            qimg = QImage(data, thumb.width, thumb.height, thumb.width * 3, QImage.Format.Format_RGB888)
            self._pixmap = QPixmap.fromImage(qimg)
            self._prepared = None
            self._refresh_plan()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть файл:\n{exc}")

    # ------------------------------------------------------------------
    # Drag & drop
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}
            if any(Path(u.toLocalFile()).suffix.lower() in exts for u in urls):
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}
        for u in urls:
            p = Path(u.toLocalFile())
            if p.suffix.lower() in exts:
                self._load_image(p)
                break

    # ------------------------------------------------------------------
    # Sheet selection
    # ------------------------------------------------------------------

    def _on_sheet_selected(self, idx: int) -> None:
        self._selected_tile = idx
        self._preview.set_selected(idx)

    # ------------------------------------------------------------------
    # Long-running job helpers
    # ------------------------------------------------------------------

    def _start_job(self, fn) -> None:
        """Run fn(progress, cancelled) in a worker thread."""
        if self._running:
            return
        self._cancel_event.clear()
        self._running = True
        self._set_buttons_enabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._btn_cancel.setVisible(True)
        self._lbl_status.setText("")
        self._lbl_status.setStyleSheet("")

        worker = _Worker(fn, self._cancel_event)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_job_finished)
        worker.failed.connect(self._on_job_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_done)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_progress(self, msg: str, frac: float) -> None:
        self._lbl_status.setText(msg)
        self._progress_bar.setValue(int(frac * 100))

    def _on_job_finished(self, result: object) -> None:
        self._last_result = result

    def _on_job_failed(self, msg: str) -> None:
        self._last_error = msg

    def _on_thread_done(self) -> None:
        self._running = False
        self._set_buttons_enabled(True)
        self._progress_bar.setVisible(False)
        self._btn_cancel.setVisible(False)
        self._worker = None
        self._thread = None
        result, error = self._last_result, self._last_error
        self._last_result = None
        self._last_error = None
        if error is not None:
            self._pending_callback = None
            if error != "Отменено":
                QMessageBox.critical(self, "Ошибка", error)
            self._lbl_status.setText(error)
        elif result is not None:
            self._on_result(result)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._thread is not None:
            self._cancel_event.set()
            self._thread.quit()
            self._thread.wait(5000)
        super().closeEvent(event)

    def _on_result(self, result: object) -> None:
        if isinstance(result, Prepared):
            self._prepared = result
            self._btn_compare.setEnabled(True)
            if result.note:
                self._lbl_status.setStyleSheet(f"color: {theme.WARN};")
                self._lbl_status.setText(result.note)
            elif result.saved_path is not None:
                self._lbl_status.setText(f"Готово. Постер сохранён: output\\{result.saved_path.name}")
            else:
                self._lbl_status.setText("Готово")
            callback, self._pending_callback = self._pending_callback, None
            if callback is not None:
                callback(result)
        elif isinstance(result, int):
            # print job: pages printed
            self._lbl_status.setText(f"Напечатано листов: {result}")

    def _on_cancel(self) -> None:
        self._cancel_event.set()

    def _set_buttons_enabled(self, enabled: bool) -> None:
        for btn in (
            self._btn_open,
            self._btn_prepare,
            self._btn_print_all,
            self._btn_print_sel,
            self._btn_save_pdf,
            self._btn_save_png,
        ):
            btn.setEnabled(enabled)
        self._btn_compare.setEnabled(enabled and self._prepared is not None)
        # Print buttons also depend on printer
        if enabled:
            self._update_print_buttons()

    def _prepare_job(self):
        """Job callable that prepares the current image with the current settings."""
        image = self._image
        settings = self._current_settings()
        base_sheet = self._base_sheet
        stem = self._image_path.stem if self._image_path else "poster"
        save_dir = pipeline.output_dir()

        def job(progress, cancelled):
            return pipeline.prepare(
                image, settings, base_sheet, progress, cancelled, save_dir=save_dir, stem=stem
            )

        return job

    def check_for_updates(self) -> None:
        """Ask GitHub for a newer release in the background; silent when there is none."""

        def work() -> None:
            release = update.check()
            if release is not None:
                self._update_found.emit(release)

        threading.Thread(target=work, daemon=True).start()

    def _on_update_found(self, release: object) -> None:
        self._release = release
        self._lbl_update.setText(
            f"Доступна новая версия {release.version} (у вас {update.__version__})."
        )
        self._update_card.setVisible(True)

    def _on_download_update(self) -> None:
        if self._release is not None:
            QDesktopServices.openUrl(QUrl(self._release.download_url))

    def _on_compare(self) -> None:
        if self._prepared is None or self._image is None:
            return
        fill = bool(self._combo_fill.currentData())
        CompareDialog(self._image, self._prepared, fill, self).exec()

    def _on_open_folder(self) -> None:
        folder = pipeline.output_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)  # noqa: S606
        except OSError as exc:
            QMessageBox.warning(self, "Папка результатов", str(exc))

    def _update_print_buttons(self) -> None:
        no_printer = self._is_no_printer()
        self._btn_print_all.setEnabled(not no_printer)
        self._btn_print_sel.setEnabled(not no_printer)

    # ------------------------------------------------------------------
    # Prepare
    # ------------------------------------------------------------------

    def _ensure_prepared(self, callback) -> None:
        """Call callback(prepared) after ensuring a Prepared exists."""
        if self._prepared is not None:
            callback(self._prepared)
            return
        if self._image is None:
            QMessageBox.information(self, "Нет изображения", "Сначала откройте изображение.")
            return
        if self._running:
            return
        self._pending_callback = callback
        self._start_job(self._prepare_job())

    def _on_prepare(self) -> None:
        if self._image is None:
            QMessageBox.information(self, "Нет изображения", "Сначала откройте изображение.")
            return
        self._prepared = None  # force re-prepare
        self._start_job(self._prepare_job())

    # ------------------------------------------------------------------
    # Print
    # ------------------------------------------------------------------

    def _on_print(self, all_tiles: bool) -> None:
        if self._is_no_printer():
            return

        def _do_print(prepared: Prepared) -> None:
            n = len(prepared.tiles)
            if all_tiles:
                tiles_to_print = prepared.tiles
                msg = f"Будет напечатано {n} листов. Продолжить?"
            else:
                idx = self._selected_tile
                if idx < 0 or idx >= n:
                    QMessageBox.information(self, "Лист не выбран", "Нажмите на лист в предпросмотре.")
                    return
                tiles_to_print = [prepared.tiles[idx]]
                msg = "Будет напечатан 1 лист. Продолжить?"

            reply = QMessageBox.question(self, "Печать", msg)
            if reply != QMessageBox.StandardButton.Yes:
                return

            name = self._current_printer_name()
            devmode = self._devmode
            landscape = prepared.landscape
            stem = self._image_path.stem if self._image_path else "Poster"

            tiles_snap = list(tiles_to_print)

            def _fn(progress, cancelled):
                def _prog(done, total):
                    progress(f"Печать {done}/{total}", done / total if total else 1.0)

                return printer.print_tiles(
                    name, devmode, tiles_snap, landscape,
                    doc_name=stem,
                    progress=_prog,
                    cancelled=cancelled,
                )

            self._start_job(_fn)

        self._ensure_prepared(_do_print)

    # ------------------------------------------------------------------
    # Save PDF
    # ------------------------------------------------------------------

    def _on_save_pdf(self) -> None:
        def _do_save(prepared: Prepared) -> None:
            default_name = (self._image_path.stem if self._image_path else "poster") + ".pdf"
            path, _ = QFileDialog.getSaveFileName(
                self, "Сохранить PDF", default_name, "PDF (*.pdf)"
            )
            if not path:
                return
            try:
                tiles_mod.save_pdf(prepared.tiles, prepared.layout, path)
                self._lbl_status.setText(f"PDF сохранён: {Path(path).name}")
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить PDF:\n{exc}")

        self._ensure_prepared(_do_save)

    # ------------------------------------------------------------------
    # Save PNG
    # ------------------------------------------------------------------

    def _on_save_png(self) -> None:
        def _do_save(prepared: Prepared) -> None:
            folder = QFileDialog.getExistingDirectory(self, "Выберите папку для PNG")
            if not folder:
                return
            stem = self._image_path.stem if self._image_path else "poster"
            try:
                paths = tiles_mod.save_pngs(prepared.tiles, prepared.layout, folder, stem)
                self._lbl_status.setText(f"PNG сохранено: {len(paths)} файлов")
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить PNG:\n{exc}")

        self._ensure_prepared(_do_save)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply(app)
    window = MainWindow()
    window.setWindowTitle(f"PosterPrint {update.__version__}")
    window.show()
    window.check_for_updates()
    return app.exec()
