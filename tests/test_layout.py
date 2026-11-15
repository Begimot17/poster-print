"""Tests for app/layout.py – no network, no GPU, no Pillow."""

from __future__ import annotations

import math

import pytest

from app.layout import (
    A4,
    Layout,
    Sheet,
    best_orientation,
    make_layout,
    needed_scale,
    pick_dpi,
    upscale_passes,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _layout(cols=1, rows=1, overlap_mm=0.0, dpi=300.0, sheet=A4) -> Layout:
    return make_layout(sheet, cols, rows, overlap_mm, dpi)


# ---------------------------------------------------------------------------
# Poster-size formulas
# ---------------------------------------------------------------------------

class TestPosterSize:
    def test_1x1_no_overlap(self):
        lay = _layout(cols=1, rows=1, overlap_mm=0)
        assert lay.poster_w_px == lay.tile_w_px
        assert lay.poster_h_px == lay.tile_h_px

    def test_2x2_no_overlap(self):
        lay = _layout(cols=2, rows=2, overlap_mm=0)
        assert lay.poster_w_px == 2 * lay.tile_w_px
        assert lay.poster_h_px == 2 * lay.tile_h_px

    def test_3x4_with_overlap(self):
        overlap_mm = 5.0
        lay = _layout(cols=3, rows=4, overlap_mm=overlap_mm)
        expected_w = 3 * lay.tile_w_px - 2 * lay.overlap_px
        expected_h = 4 * lay.tile_h_px - 3 * lay.overlap_px
        assert lay.poster_w_px == expected_w
        assert lay.poster_h_px == expected_h

    def test_overlap_px_consistent(self):
        lay = _layout(cols=2, rows=2, overlap_mm=10.0)
        assert lay.overlap_px == round(10.0 / 25.4 * lay.dpi)


# ---------------------------------------------------------------------------
# Tiles cover the poster exactly
# ---------------------------------------------------------------------------

class TestTileCoverage:
    @pytest.mark.parametrize("cols,rows,overlap_mm", [
        (1, 1, 0),
        (2, 2, 0),
        (3, 4, 5.0),
        (1, 3, 10.0),
    ])
    def test_tiles_cover_poster(self, cols, rows, overlap_mm):
        lay = _layout(cols=cols, rows=rows, overlap_mm=overlap_mm)
        covered = [[False] * lay.poster_w_px for _ in range(lay.poster_h_px)]
        for tile in lay.tiles:
            for y in range(tile.src.y, tile.src.y + tile.src.h):
                for x in range(tile.src.x, tile.src.x + tile.src.w):
                    if 0 <= y < lay.poster_h_px and 0 <= x < lay.poster_w_px:
                        covered[y][x] = True
        assert all(covered[y][x] for y in range(lay.poster_h_px) for x in range(lay.poster_w_px))

    @pytest.mark.parametrize("cols,rows,overlap_mm", [
        (1, 1, 0),
        (2, 3, 5.0),
    ])
    def test_tiles_in_bounds(self, cols, rows, overlap_mm):
        lay = _layout(cols=cols, rows=rows, overlap_mm=overlap_mm)
        for tile in lay.tiles:
            assert tile.src.x >= 0
            assert tile.src.y >= 0
            assert tile.src.x + tile.src.w <= lay.poster_w_px
            assert tile.src.y + tile.src.h <= lay.poster_h_px

    def test_neighbours_overlap_exactly(self):
        overlap_mm = 8.0
        lay = _layout(cols=3, rows=3, overlap_mm=overlap_mm)
        step_x = lay.tile_w_px - lay.overlap_px

        for tile in lay.tiles:
            if tile.col < lay.cols - 1:
                right_tile = next(
                    t for t in lay.tiles if t.row == tile.row and t.col == tile.col + 1
                )
                shared = tile.src.x + tile.src.w - right_tile.src.x
                assert shared == lay.overlap_px

            if tile.row < lay.rows - 1:
                bottom_tile = next(
                    t for t in lay.tiles if t.row == tile.row + 1 and t.col == tile.col
                )
                shared = tile.src.y + tile.src.h - bottom_tile.src.y
                assert shared == lay.overlap_px

    def test_tile_count(self):
        lay = _layout(cols=3, rows=4)
        assert len(lay.tiles) == 12

    def test_row_major_order(self):
        lay = _layout(cols=2, rows=3)
        coords = [(t.row, t.col) for t in lay.tiles]
        assert coords == [(r, c) for r in range(3) for c in range(2)]


# ---------------------------------------------------------------------------
# Sheet.rotated()
# ---------------------------------------------------------------------------

class TestRotated:
    def test_dimensions_swapped(self):
        s = A4.rotated()
        assert s.width_mm == A4.height_mm
        assert s.height_mm == A4.width_mm

    def test_margins_rotate_clockwise(self):
        s = A4.rotated()
        # new top = old left, new right = old top, new bottom = old right, new left = old bottom
        assert s.top_mm == A4.left_mm
        assert s.right_mm == A4.top_mm
        assert s.bottom_mm == A4.right_mm
        assert s.left_mm == A4.bottom_mm

    def test_four_rotations_are_identity(self):
        assert A4.rotated().rotated().rotated().rotated() == A4


# ---------------------------------------------------------------------------
# ValueError cases
# ---------------------------------------------------------------------------

class TestValidation:
    def test_cols_zero(self):
        with pytest.raises(ValueError):
            make_layout(A4, 0, 1, 0, 300)

    def test_rows_zero(self):
        with pytest.raises(ValueError):
            make_layout(A4, 1, 0, 0, 300)

    def test_dpi_zero(self):
        with pytest.raises(ValueError):
            make_layout(A4, 1, 1, 0, 0)

    def test_dpi_negative(self):
        with pytest.raises(ValueError):
            make_layout(A4, 1, 1, 0, -10)

    def test_overlap_too_large(self):
        half = min(A4.print_w_mm, A4.print_h_mm) / 2
        with pytest.raises(ValueError):
            make_layout(A4, 2, 2, half, 300)

    def test_overlap_negative(self):
        with pytest.raises(ValueError):
            make_layout(A4, 1, 1, -1, 300)


# ---------------------------------------------------------------------------
# pick_dpi
# ---------------------------------------------------------------------------

class TestPickDpi:
    def test_caps_megapixels(self):
        dpi = pick_dpi(A4, 4, 4, 0, want_dpi=300, max_megapixels=120)
        lay = make_layout(A4, 4, 4, 0, dpi)
        assert lay.poster_w_px * lay.poster_h_px <= 120 * 1_000_000

    def test_respects_min_dpi(self):
        dpi = pick_dpi(A4, 10, 10, 0, want_dpi=300, max_megapixels=1, min_dpi=150)
        assert dpi == 150

    def test_does_not_exceed_want_dpi(self):
        dpi = pick_dpi(A4, 1, 1, 0, want_dpi=200)
        assert dpi <= 200

    def test_small_poster_returns_want_dpi(self):
        dpi = pick_dpi(A4, 1, 1, 0, want_dpi=300, max_megapixels=120)
        assert dpi == 300


# ---------------------------------------------------------------------------
# best_orientation
# ---------------------------------------------------------------------------

class TestBestOrientation:
    def test_wide_image_gets_landscape(self):
        # Wide image (4:1) should prefer landscape on a 1x1 grid.
        result = best_orientation(A4, 1, 1, 0, image_w=4000, image_h=1000)
        assert result == A4.rotated()

    def test_tall_image_gets_portrait(self):
        # Tall image should prefer portrait (default A4 orientation).
        result = best_orientation(A4, 1, 1, 0, image_w=1000, image_h=4000)
        assert result == A4


# ---------------------------------------------------------------------------
# needed_scale
# ---------------------------------------------------------------------------

class TestNeededScale:
    def test_fill_uses_max_ratio(self):
        scale = needed_scale(100, 200, 400, 400, fill=True)
        assert scale == pytest.approx(max(400 / 100, 400 / 200))

    def test_contain_uses_min_ratio(self):
        scale = needed_scale(100, 200, 400, 400, fill=False)
        assert scale == pytest.approx(min(400 / 100, 400 / 200))

    def test_fill_covers_poster(self):
        scale = needed_scale(100, 50, 400, 400, fill=True)
        assert 100 * scale >= 400
        assert 50 * scale >= 400

    def test_contain_fits_poster(self):
        scale = needed_scale(100, 50, 400, 400, fill=False)
        assert max(100 * scale, 50 * scale) <= 400 + 1e-9


# ---------------------------------------------------------------------------
# upscale_passes
# ---------------------------------------------------------------------------

class TestUpscalePasses:
    @pytest.mark.parametrize("scale,expected", [
        (0.8, 0),
        (1.0, 0),
        (1.3, 0),    # plain resampling is enough up to the slack
        (1.31, 1),
        (4.0, 1),    # 4^1 * 1.3 = 5.2 >= 4.0
        (5.2, 1),    # 4^1 * 1.3 = 5.2 >= 5.2
        (5.3, 2),    # 4^1 * 1.3 = 5.2 < 5.3 -> need 2 passes
        (16.0, 2),   # capped at 2
        (100.0, 2),  # capped at 2
    ])
    def test_passes(self, scale, expected):
        assert upscale_passes(scale) == expected
