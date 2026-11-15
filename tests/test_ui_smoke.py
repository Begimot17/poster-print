"""Headless smoke test: open an image, prepare in the worker thread, export a PDF."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import tiles  # noqa: E402
from app.ui import MainWindow  # noqa: E402


def test_open_prepare_export(tmp_path, monkeypatch):
    from app import pipeline, theme
    from app.compare import CompareDialog

    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    monkeypatch.setattr(pipeline, "output_dir", lambda: tmp_path / "output")
    src = tmp_path / "in.png"
    Image.new("RGB", (600, 900), (200, 80, 80)).save(src)

    win = MainWindow()
    win._combo_printer.setCurrentIndex(win._combo_printer.count() - 1)
    win._combo_model.setCurrentIndex(win._combo_model.findData("none"))
    win._spin_dpi.setValue(150)
    win._load_image(src)
    assert win._layout is not None and "Листов: 4" in win._lbl_info.text()
    win.show()
    win._preview.repaint()

    win._on_prepare()
    deadline = time.time() + 60
    while win._prepared is None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert win._prepared is not None and len(win._prepared.tiles) == 4
    assert not win._running and win._btn_prepare.isEnabled()
    assert not win._btn_print_all.isEnabled()

    saved = win._prepared.saved_path
    assert saved is not None and saved.parent == tmp_path / "output" and saved.stat().st_size > 0
    assert win._btn_compare.isEnabled()

    dialog = CompareDialog(win._image, win._prepared, True, win)
    dialog.show()
    for zoom in (0.0, 1.0, 4.0):
        dialog.view.set_zoom(zoom)
        dialog.view._render()
    half = dialog.view._dst.width() // 2
    before = dialog.view._before.toImage().pixelColor(half, 10)
    after = dialog.view._after.toImage().pixelColor(half, 10)
    assert abs(before.red() - after.red()) <= 3 and abs(before.blue() - after.blue()) <= 3
    dialog.close()

    pdf = tmp_path / "out.pdf"
    tiles.save_pdf(win._prepared.tiles, win._prepared.layout, pdf)
    assert pdf.read_bytes().startswith(b"%PDF")

    from app import update

    assert win._update_card.isHidden()
    win._on_update_found(update.Release("9.9.9", "https://example.test/r", "https://example.test/p.zip"))
    assert not win._update_card.isHidden() and "9.9.9" in win._lbl_update.text()

    win._apply_preset(3, 4)
    assert win._prepared is None and "Листов: 12" in win._lbl_info.text()
    win.close()
