"""Upscale pass planning (no GPU: the exe is replaced by a x4 nearest-neighbour stub)."""
from pathlib import Path

import pytest
from PIL import Image

from app import upscale
from app.upscale import MAX_PASS_OUTPUT_PX, _input_shrink


def test_small_original_is_never_shrunk():
    assert _input_shrink((1000, 1500), 3.0, passes_left=1, first=True) == 1.0
    assert _input_shrink((500, 700), 10.0, passes_left=2, first=True) == 1.0


def test_big_original_is_shrunk_only_to_the_output_cap():
    size = (6000, 8000)
    shrink = _input_shrink(size, 1.5, passes_left=1, first=True)
    assert 1.5 / 4 < shrink < 1.0
    assert size[0] * size[1] * shrink**2 * 16 == pytest.approx(MAX_PASS_OUTPUT_PX)


def test_shrink_never_goes_below_what_the_target_needs():
    assert _input_shrink((20000, 20000), 3.9, passes_left=1, first=True) == pytest.approx(3.9 / 4)


@pytest.mark.parametrize("scale", [2.0, 4.0, 5.3, 10.0, 16.0])
def test_result_is_never_smaller_than_requested(tmp_path: Path, monkeypatch, scale: float):
    def fake_pass(exe, src, dst, model_key, tile=0, gpu=None, progress=None, cancelled=None):
        with Image.open(src) as im:
            im.resize((im.width * 4, im.height * 4), Image.NEAREST).save(dst)

    monkeypatch.setattr(upscale, "run_pass", fake_pass)
    src = Image.new("RGB", (60, 90), (10, 20, 30))
    out = upscale.upscale(src, scale, "anime", Path("unused.exe"), tmp_path)

    assert out.width >= 60 * scale - 4 and out.height >= 90 * scale - 4
    assert out.width <= 60 * max(scale, 4) + 4
    assert list(tmp_path.iterdir()) == []
