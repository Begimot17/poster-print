"""Pure-math layout calculations for PosterPrint (no Pillow, no I/O)."""

from __future__ import annotations

import math
from dataclasses import dataclass

MM_PER_INCH = 25.4


@dataclass(frozen=True)
class Sheet:
    """Physical paper sheet with unprintable margins (all in mm)."""

    width_mm: float
    height_mm: float
    left_mm: float
    top_mm: float
    right_mm: float
    bottom_mm: float

    @property
    def print_w_mm(self) -> float:
        """Printable width in mm."""
        return self.width_mm - self.left_mm - self.right_mm

    @property
    def print_h_mm(self) -> float:
        """Printable height in mm."""
        return self.height_mm - self.top_mm - self.bottom_mm

    def rotated(self) -> "Sheet":
        """Return landscape version: swap w/h and rotate margins 90° clockwise."""
        return Sheet(
            width_mm=self.height_mm,
            height_mm=self.width_mm,
            left_mm=self.bottom_mm,
            top_mm=self.left_mm,
            right_mm=self.top_mm,
            bottom_mm=self.right_mm,
        )


A4 = Sheet(210, 297, 3.4, 3.0, 3.4, 16.7)


@dataclass(frozen=True)
class Rect:
    """Rectangle in pixel space."""

    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Tile:
    """One poster tile: its grid position and source rectangle in the poster bitmap."""

    row: int
    col: int
    src: Rect


@dataclass(frozen=True)
class Layout:
    """Complete tiling layout derived from sheet, grid dimensions and DPI."""

    sheet: Sheet
    cols: int
    rows: int
    overlap_mm: float
    dpi: float
    poster_w_mm: float
    poster_h_mm: float
    poster_w_px: int
    poster_h_px: int
    tile_w_px: int
    tile_h_px: int
    overlap_px: int
    tiles: tuple[Tile, ...]


def make_layout(
    sheet: Sheet,
    cols: int,
    rows: int,
    overlap_mm: float,
    dpi: float,
) -> Layout:
    """Build a Layout from sheet and grid parameters.

    Raises ValueError for invalid inputs.
    """
    if cols < 1 or rows < 1:
        raise ValueError(f"cols and rows must be >= 1, got cols={cols} rows={rows}")
    if dpi <= 0:
        raise ValueError(f"dpi must be > 0, got {dpi}")
    half_min = min(sheet.print_w_mm, sheet.print_h_mm) / 2
    if not (0 <= overlap_mm < half_min):
        raise ValueError(
            f"overlap_mm must be in [0, {half_min}), got {overlap_mm}"
        )

    tile_w_px = round(sheet.print_w_mm / MM_PER_INCH * dpi)
    tile_h_px = round(sheet.print_h_mm / MM_PER_INCH * dpi)
    overlap_px = round(overlap_mm / MM_PER_INCH * dpi)

    step_x = tile_w_px - overlap_px
    step_y = tile_h_px - overlap_px

    poster_w_px = cols * tile_w_px - (cols - 1) * overlap_px
    poster_h_px = rows * tile_h_px - (rows - 1) * overlap_px

    poster_w_mm = cols * sheet.print_w_mm - (cols - 1) * overlap_mm
    poster_h_mm = rows * sheet.print_h_mm - (rows - 1) * overlap_mm

    tiles = tuple(
        Tile(row=r, col=c, src=Rect(x=c * step_x, y=r * step_y, w=tile_w_px, h=tile_h_px))
        for r in range(rows)
        for c in range(cols)
    )

    return Layout(
        sheet=sheet,
        cols=cols,
        rows=rows,
        overlap_mm=overlap_mm,
        dpi=dpi,
        poster_w_mm=poster_w_mm,
        poster_h_mm=poster_h_mm,
        poster_w_px=poster_w_px,
        poster_h_px=poster_h_px,
        tile_w_px=tile_w_px,
        tile_h_px=tile_h_px,
        overlap_px=overlap_px,
        tiles=tiles,
    )


def pick_dpi(
    sheet: Sheet,
    cols: int,
    rows: int,
    overlap_mm: float,
    want_dpi: float = 300,
    max_megapixels: float = 120,
    min_dpi: float = 150,
) -> float:
    """Return the largest DPI <= want_dpi whose poster fits within max_megapixels.

    Never returns below min_dpi.
    """
    dpi = want_dpi
    while dpi >= min_dpi:
        layout = make_layout(sheet, cols, rows, overlap_mm, dpi)
        megapixels = layout.poster_w_px * layout.poster_h_px / 1_000_000
        if megapixels <= max_megapixels:
            return dpi
        dpi -= 1
    return min_dpi


def best_orientation(
    sheet: Sheet,
    cols: int,
    rows: int,
    overlap_mm: float,
    image_w: int,
    image_h: int,
) -> Sheet:
    """Return the sheet orientation whose poster aspect ratio best matches the image."""
    image_ratio = image_w / image_h

    portrait = make_layout(sheet, cols, rows, overlap_mm, 72)
    portrait_ratio = portrait.poster_w_px / portrait.poster_h_px

    rotated = sheet.rotated()
    landscape = make_layout(rotated, cols, rows, overlap_mm, 72)
    landscape_ratio = landscape.poster_w_px / landscape.poster_h_px

    err_portrait = abs(math.log(portrait_ratio / image_ratio))
    err_landscape = abs(math.log(landscape_ratio / image_ratio))

    return sheet if err_portrait <= err_landscape else rotated


def needed_scale(
    src_w: int,
    src_h: int,
    poster_w_px: int,
    poster_h_px: int,
    fill: bool,
) -> float:
    """Scale factor to fit source into the poster.

    fill=True: cover (crop excess), fill=False: contain.
    """
    rx = poster_w_px / src_w
    ry = poster_h_px / src_h
    return max(rx, ry) if fill else min(rx, ry)


def upscale_passes(scale: float, lanczos_slack: float = 1.3) -> int:
    """Number of native x4 AI upscale passes needed, capped at 2.

    Up to lanczos_slack plain resampling is indistinguishable on paper, so no pass.
    """
    if scale <= lanczos_slack:
        return 0
    for n in range(1, 3):
        if 4**n * lanczos_slack >= scale:
            return n
    return 2
