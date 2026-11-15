"""End-to-end image -> tiles, with the upscaler stubbed out."""
import pytest
from PIL import Image

from app import fetch, pipeline
from app.layout import A4
from app.pipeline import Cancelled, Settings, plan, prepare


def settings(**over) -> Settings:
    base = dict(cols=2, rows=2, orientation="auto", fill=True, model="none",
                want_dpi=150, overlap_mm=8.0, marks=True)
    base.update(over)
    return Settings(**base)


def test_plan_picks_landscape_for_wide_image():
    layout, landscape, scale, passes = plan(settings(), A4, (1600, 900))
    assert landscape and layout.sheet.width_mm > layout.sheet.height_mm
    assert scale > 1 and passes == 0


def test_plan_respects_forced_orientation():
    assert plan(settings(orientation="portrait"), A4, (1600, 900))[1] is False
    assert plan(settings(orientation="landscape"), A4, (900, 1600))[1] is True


def test_plan_counts_passes_only_with_a_model():
    assert plan(settings(model="anime"), A4, (400, 600))[3] >= 1
    assert plan(settings(model="none"), A4, (400, 600))[3] == 0


def test_prepare_without_upscaler():
    steps = []
    done = prepare(Image.new("RGB", (400, 600), "red"), settings(), A4,
                   lambda name, frac: steps.append(name), lambda: False)
    assert len(done.tiles) == 4 and done.note == ""
    assert done.poster.size == (done.layout.poster_w_px, done.layout.poster_h_px)
    assert all(t.size == (done.layout.tile_w_px, done.layout.tile_h_px) for t in done.tiles)
    assert steps[-1] == "Готово"


def test_prepare_falls_back_when_upscaler_is_unavailable(monkeypatch):
    def broken(progress=None):
        raise fetch.FetchError("no network")

    monkeypatch.setattr(fetch, "ensure_upscaler", broken)
    done = prepare(Image.new("RGB", (400, 600), "red"), settings(model="anime"), A4,
                   lambda name, frac: None, lambda: False)
    assert "no network" in done.note and done.passes == 0 and len(done.tiles) == 4


def test_prepare_can_be_cancelled():
    with pytest.raises(Cancelled):
        prepare(Image.new("RGB", (400, 600)), settings(), A4, lambda n, f: None, lambda: True)
