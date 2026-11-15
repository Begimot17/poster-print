"""Windows printing: printer discovery, real printable area, direct GDI output.

The device is always driven in portrait; landscape sheets are rotated here, so the
driver never rescales or re-orients a tile on its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from PIL import Image, ImageWin

from app.layout import MM_PER_INCH, Sheet

try:
    import pywintypes
    import win32con
    import win32gui
    import win32print
    import win32ui
except ImportError:  # non-Windows or pywin32 missing: export-only mode
    win32print = None  # type: ignore[assignment]

# GetDeviceCaps indexes
_HORZRES, _VERTRES = 8, 10
_LOGPIXELSX, _LOGPIXELSY = 88, 90
_PHYSICALWIDTH, _PHYSICALHEIGHT = 110, 111
_PHYSICALOFFSETX, _PHYSICALOFFSETY = 112, 113

_DMORIENT_PORTRAIT = 1
_DM_ORIENTATION = 0x1
_DM_OUT_BUFFER, _DM_IN_PROMPT, _DM_IN_BUFFER = 2, 4, 8
_IDOK = 1


class PrinterError(RuntimeError):
    pass


@dataclass(frozen=True)
class PrinterInfo:
    """What the driver reports for the current settings (portrait)."""

    sheet: Sheet
    dpi_x: int
    dpi_y: int
    borderless: bool


def available() -> bool:
    return win32print is not None


def list_printers() -> list[str]:
    """Installed printer names; empty when the spooler is unreachable."""
    if not available():
        return []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    try:
        return [p[2] for p in win32print.EnumPrinters(flags)]
    except pywintypes.error:
        return []


def default_printer() -> str | None:
    if not available():
        return None
    try:
        return win32print.GetDefaultPrinter()
    except (pywintypes.error, RuntimeError):
        return None


def _force_portrait(devmode: Any) -> Any:
    devmode.Orientation = _DMORIENT_PORTRAIT
    devmode.Fields |= _DM_ORIENTATION
    return devmode


def get_devmode(name: str) -> Any:
    """The printer's default settings (driver-private data included)."""
    try:
        handle = win32print.OpenPrinter(name)
        try:
            devmode = win32print.GetPrinter(handle, 2)["pDevMode"]
        finally:
            win32print.ClosePrinter(handle)
    except pywintypes.error as exc:
        raise PrinterError(f"Cannot open printer '{name}': {exc.strerror}") from exc
    if devmode is None:
        raise PrinterError(f"Printer '{name}' has no default settings")
    return _force_portrait(devmode)


def configure(name: str, devmode: Any, hwnd: int = 0) -> Any | None:
    """Show the driver's own settings dialog (paper type, quality, borderless).

    Returns the updated devmode, or None if the user cancelled.
    """
    try:
        handle = win32print.OpenPrinter(name)
        try:
            result = win32print.DocumentProperties(
                hwnd, handle, name, devmode, devmode,
                _DM_IN_BUFFER | _DM_IN_PROMPT | _DM_OUT_BUFFER,
            )
        finally:
            win32print.ClosePrinter(handle)
    except pywintypes.error as exc:
        raise PrinterError(f"Printer settings failed: {exc.strerror}") from exc
    if result != _IDOK:
        return None
    return _force_portrait(devmode)


def _create_dc(name: str, devmode: Any) -> int:
    try:
        return win32gui.CreateDC("WINSPOOL", name, devmode)
    except pywintypes.error as exc:
        raise PrinterError(f"Cannot start printer '{name}': {exc.strerror}") from exc


def query(name: str, devmode: Any) -> PrinterInfo:
    """Paper size and unprintable margins as the driver will really apply them."""
    hdc = _create_dc(name, _force_portrait(devmode))
    try:
        cap = lambda index: win32print.GetDeviceCaps(hdc, index)  # noqa: E731
        dpi_x, dpi_y = cap(_LOGPIXELSX), cap(_LOGPIXELSY)
        phys_w, phys_h = cap(_PHYSICALWIDTH), cap(_PHYSICALHEIGHT)
        off_x, off_y = cap(_PHYSICALOFFSETX), cap(_PHYSICALOFFSETY)
        res_w, res_h = cap(_HORZRES), cap(_VERTRES)
    finally:
        win32gui.DeleteDC(hdc)
    if min(dpi_x, dpi_y, phys_w, phys_h, res_w, res_h) <= 0:
        raise PrinterError(f"Printer '{name}' reported an invalid page size")

    def mm(pixels: int, dpi: int) -> float:
        return max(0.0, pixels / dpi * MM_PER_INCH)

    sheet = Sheet(
        width_mm=mm(phys_w, dpi_x),
        height_mm=mm(phys_h, dpi_y),
        left_mm=mm(off_x, dpi_x),
        top_mm=mm(off_y, dpi_y),
        right_mm=mm(phys_w - off_x - res_w, dpi_x),
        bottom_mm=mm(phys_h - off_y - res_h, dpi_y),
    )
    margins = (sheet.left_mm, sheet.top_mm, sheet.right_mm, sheet.bottom_mm)
    return PrinterInfo(sheet, dpi_x, dpi_y, borderless=max(margins) < 0.5)


def print_tiles(
    name: str,
    devmode: Any,
    tiles: Sequence[Image.Image],
    landscape: bool,
    doc_name: str = "Poster",
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> int:
    """Print each tile on its own page, filling the printable area. Returns pages sent."""
    hdc = _create_dc(name, _force_portrait(devmode))
    dc = win32ui.CreateDCFromHandle(hdc)
    sent = 0
    try:
        width = dc.GetDeviceCaps(_HORZRES)
        height = dc.GetDeviceCaps(_VERTRES)
        win32gui.SetStretchBltMode(hdc, win32con.HALFTONE)
        dc.StartDoc(doc_name)
        try:
            for index, tile in enumerate(tiles):
                if cancelled and cancelled():
                    break
                page = tile.convert("RGB")
                if landscape:
                    # landscape top edge == portrait left edge
                    page = page.rotate(90, expand=True)
                dc.StartPage()
                ImageWin.Dib(page).draw(dc.GetHandleOutput(), (0, 0, width, height))
                dc.EndPage()
                sent += 1
                if progress:
                    progress(index + 1, len(tiles))
        except Exception:
            dc.AbortDoc()
            raise
        else:
            dc.EndDoc()
    except (pywintypes.error, win32ui.error) as exc:
        raise PrinterError(f"Printing failed: {exc}") from exc
    finally:
        dc.DeleteDC()
    return sent
