"""Image -> printable tiles. No Qt imports, so it can be tested headless."""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image

from app import fetch, tiles, upscale
from app.layout import (
    Layout,
    Sheet,
    best_orientation,
    make_layout,
    needed_scale,
    pick_dpi,
    upscale_passes,
)

Progress = Callable[[str, float], None]


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    cols: int
    rows: int
    orientation: str  # "auto" | "portrait" | "landscape"
    fill: bool
    model: str  # key of upscale.MODELS or "none"
    want_dpi: int
    overlap_mm: float
    marks: bool


@dataclass
class Prepared:
    layout: Layout
    landscape: bool
    tiles: list[Image.Image]
    poster: Image.Image
    scale: float
    passes: int
    note: str
    saved_path: Path | None = None


def output_dir() -> Path:
    """Folder next to the program where finished posters are kept."""
    return fetch.app_dir() / "output"


def plan(
    settings: Settings, base_sheet: Sheet, image_size: tuple[int, int]
) -> tuple[Layout, bool, float, int]:
    """Cheap layout computation; base_sheet is portrait.

    Returns (layout, landscape, scale, passes).
    """
    width, height = image_size
    landscape_sheet = base_sheet.rotated()
    if settings.orientation == "landscape":
        sheet = landscape_sheet
    elif settings.orientation == "portrait":
        sheet = base_sheet
    else:
        sheet = best_orientation(
            base_sheet, settings.cols, settings.rows, settings.overlap_mm, width, height
        )
    dpi = pick_dpi(
        sheet, settings.cols, settings.rows, settings.overlap_mm, want_dpi=settings.want_dpi
    )
    layout = make_layout(sheet, settings.cols, settings.rows, settings.overlap_mm, dpi)
    scale = needed_scale(width, height, layout.poster_w_px, layout.poster_h_px, settings.fill)
    passes = 0 if settings.model == "none" else upscale_passes(scale)
    return layout, sheet == landscape_sheet and sheet != base_sheet, scale, passes


def prepare(
    image: Image.Image,
    settings: Settings,
    base_sheet: Sheet,
    progress: Progress,
    cancelled: Callable[[], bool],
    save_dir: Path | None = None,
    stem: str = "poster",
) -> Prepared:
    """Upscale if needed, fit to the poster and cut into sheets.

    With save_dir the finished poster is also written there as a JPEG.
    """

    def check() -> None:
        if cancelled():
            raise Cancelled()

    layout, landscape, scale, passes = plan(settings, base_sheet, image.size)
    source = image
    note = ""
    if passes > 0:
        try:
            progress("Загрузка апскейлера", 0.0)
            exe = fetch.ensure_upscaler(
                lambda done, total: progress("Загрузка апскейлера", done / total if total else 0.0)
            )
            check()
            progress("Апскейл", 0.0)
            with tempfile.TemporaryDirectory() as tmp:
                source = upscale.upscale(
                    image, scale, settings.model, exe, Path(tmp),
                    progress=lambda frac: progress("Апскейл", frac),
                    cancelled=cancelled,
                )
        except upscale.UpscaleCancelled:
            raise Cancelled() from None
        except (fetch.FetchError, upscale.UpscaleError) as exc:
            reason = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            note = f"Апскейлер недоступен ({reason}), использовано обычное увеличение"
            source = image
            passes = 0
    check()
    progress("Подгонка", 0.0)
    poster = tiles.fit_to_poster(source, layout, settings.fill)
    check()
    progress("Нарезка", 0.0)
    cut = tiles.cut_tiles(poster, layout, marks=settings.marks)
    saved_path = None
    if save_dir is not None:
        check()
        progress("Сохранение", 0.0)
        name = f"{stem}_{settings.cols}x{settings.rows}_{settings.model if passes else 'plain'}.jpg"
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            saved_path = save_dir / name
            poster.save(saved_path, quality=95, subsampling=0, dpi=(layout.dpi, layout.dpi))
        except OSError as exc:
            saved_path = None
            note = note or f"Не удалось сохранить постер: {exc}"
    progress("Готово", 1.0)
    return Prepared(layout, landscape, cut, poster, scale, passes, note, saved_path)
