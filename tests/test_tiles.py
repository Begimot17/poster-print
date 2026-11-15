"""Tests for app/tiles.py – no network, no GPU."""

from __future__ import annotations

import os
import struct
import tempfile
import zlib
from pathlib import Path

import pytest
from PIL import Image

from app.layout import A4, make_layout
from app.tiles import cut_tiles, fit_to_poster, save_pdf, save_pngs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _small_layout(cols=2, rows=2, overlap_mm=0.0, dpi=72.0):
    return make_layout(A4, cols, rows, overlap_mm, dpi)


def _solid_rgb(w: int, h: int, color=(200, 100, 50)) -> Image.Image:
    return Image.new("RGB", (w, h), color)


def _random_poster(layout) -> Image.Image:
    """Deterministic noise poster matching the layout size."""
    import random
    rng = random.Random(42)
    pw, ph = layout.poster_w_px, layout.poster_h_px
    data = bytes(rng.randint(0, 255) for _ in range(pw * ph * 3))
    return Image.frombytes("RGB", (pw, ph), data)


# ---------------------------------------------------------------------------
# fit_to_poster
# ---------------------------------------------------------------------------

class TestFitToPoster:
    def test_fill_output_size(self):
        lay = _small_layout()
        img = _solid_rgb(100, 200)
        result = fit_to_poster(img, lay, fill=True)
        assert result.size == (lay.poster_w_px, lay.poster_h_px)

    def test_contain_output_size(self):
        lay = _small_layout()
        img = _solid_rgb(100, 200)
        result = fit_to_poster(img, lay, fill=False)
        assert result.size == (lay.poster_w_px, lay.poster_h_px)

    def test_fill_rgba_input(self):
        lay = _small_layout()
        img = Image.new("RGBA", (100, 100), (255, 0, 0, 128))
        result = fit_to_poster(img, lay, fill=True)
        assert result.mode == "RGB"
        assert result.size == (lay.poster_w_px, lay.poster_h_px)

    def test_contain_rgba_input(self):
        lay = _small_layout()
        img = Image.new("RGBA", (50, 200), (0, 255, 0, 200))
        result = fit_to_poster(img, lay, fill=False)
        assert result.mode == "RGB"
        assert result.size == (lay.poster_w_px, lay.poster_h_px)

    def test_output_is_rgb(self):
        lay = _small_layout()
        img = Image.new("L", (80, 80), 128)
        result = fit_to_poster(img, lay, fill=False)
        assert result.mode == "RGB"

    def test_fill_covers_fully(self):
        """fill=True must cover all poster pixels (no background bars)."""
        lay = make_layout(A4, 1, 1, 0, 72)
        img = _solid_rgb(lay.poster_w_px * 2, lay.poster_h_px, color=(255, 0, 0))
        result = fit_to_poster(img, lay, fill=True, background=(255, 255, 255))
        # With a pure-red input the result should not contain white bars.
        assert result.getextrema() == ((255, 255), (0, 0), (0, 0))

    def test_contain_adds_background(self):
        """contain must add background bars when aspect ratios differ."""
        lay = make_layout(A4, 1, 1, 0, 72)
        img = _solid_rgb(lay.poster_w_px, 10, color=(0, 0, 255))
        result = fit_to_poster(img, lay, fill=False, background=(255, 255, 255))
        # Corner pixel should be background white.
        assert result.getpixel((0, 0)) == (255, 255, 255)


# ---------------------------------------------------------------------------
# cut_tiles
# ---------------------------------------------------------------------------

class TestCutTiles:
    def test_count(self):
        lay = _small_layout(cols=3, rows=2)
        poster = _solid_rgb(lay.poster_w_px, lay.poster_h_px)
        tiles = cut_tiles(poster, lay, marks=False)
        assert len(tiles) == 6

    def test_size(self):
        lay = _small_layout(cols=2, rows=3)
        poster = _solid_rgb(lay.poster_w_px, lay.poster_h_px)
        tiles = cut_tiles(poster, lay, marks=False)
        for tile_img in tiles:
            assert tile_img.size == (lay.tile_w_px, lay.tile_h_px)

    def test_reassembly_exact(self):
        """Pasting tiles at their src positions reproduces the poster byte-for-byte."""
        lay = make_layout(A4, 3, 2, 0, 72)
        poster = _random_poster(lay)
        tiles = cut_tiles(poster, lay, marks=False)

        canvas = Image.new("RGB", (lay.poster_w_px, lay.poster_h_px))
        for tile_img, tile in zip(tiles, lay.tiles):
            canvas.paste(tile_img, (tile.src.x, tile.src.y))

        assert canvas.tobytes() == poster.tobytes()

    def test_reassembly_with_overlap_exact(self):
        """With overlap, pasting tiles (last writer wins) still reproduces the poster."""
        lay = make_layout(A4, 2, 2, 5.0, 72)
        poster = _random_poster(lay)
        tiles = cut_tiles(poster, lay, marks=False)

        canvas = Image.new("RGB", (lay.poster_w_px, lay.poster_h_px))
        for tile_img, tile in zip(tiles, lay.tiles):
            canvas.paste(tile_img, (tile.src.x, tile.src.y))

        assert canvas.tobytes() == poster.tobytes()


# ---------------------------------------------------------------------------
# save_pdf
# ---------------------------------------------------------------------------

class TestSavePdf:
    def test_writes_pdf_header(self):
        lay = _small_layout(cols=1, rows=1)
        poster = _solid_rgb(lay.poster_w_px, lay.poster_h_px)
        tiles = cut_tiles(poster, lay, marks=False)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "out.pdf"
            save_pdf(tiles, lay, p)
            assert p.is_file()
            header = p.read_bytes()[:4]
            assert header == b"%PDF"

    def test_multipage(self):
        """A 2x2 layout should produce a file larger than a 1x1 layout."""
        lay1 = _small_layout(cols=1, rows=1)
        lay2 = _small_layout(cols=2, rows=2)
        poster1 = _solid_rgb(lay1.poster_w_px, lay1.poster_h_px)
        poster2 = _solid_rgb(lay2.poster_w_px, lay2.poster_h_px)
        tiles1 = cut_tiles(poster1, lay1, marks=False)
        tiles2 = cut_tiles(poster2, lay2, marks=False)
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "1x1.pdf"
            p2 = Path(tmp) / "2x2.pdf"
            save_pdf(tiles1, lay1, p1)
            save_pdf(tiles2, lay2, p2)
            assert p2.stat().st_size > p1.stat().st_size


# ---------------------------------------------------------------------------
# save_pngs
# ---------------------------------------------------------------------------

class TestSavePngs:
    def test_names(self):
        lay = make_layout(A4, 2, 3, 0, 72)
        poster = _solid_rgb(lay.poster_w_px, lay.poster_h_px)
        tiles = cut_tiles(poster, lay, marks=False)
        with tempfile.TemporaryDirectory() as tmp:
            paths = save_pngs(tiles, lay, tmp, "myprint")
            names = {p.name for p in paths}
            expected = {
                f"myprint_r{r}_c{c}.png"
                for r in range(1, 4)
                for c in range(1, 3)
            }
            assert names == expected

    def test_all_files_exist(self):
        lay = _small_layout(cols=2, rows=2)
        poster = _solid_rgb(lay.poster_w_px, lay.poster_h_px)
        tiles = cut_tiles(poster, lay, marks=False)
        with tempfile.TemporaryDirectory() as tmp:
            paths = save_pngs(tiles, lay, tmp, "test")
            for p in paths:
                assert p.is_file()

    def test_returns_correct_count(self):
        lay = _small_layout(cols=3, rows=2)
        poster = _solid_rgb(lay.poster_w_px, lay.poster_h_px)
        tiles = cut_tiles(poster, lay, marks=False)
        with tempfile.TemporaryDirectory() as tmp:
            paths = save_pngs(tiles, lay, tmp, "stem")
            assert len(paths) == 6
