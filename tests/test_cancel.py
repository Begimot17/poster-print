"""Cancelling a running upscale pass kills the process instead of waiting for it."""
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

from app import fetch, pipeline, upscale
from app.layout import A4
from app.pipeline import Cancelled, Settings


def test_run_pass_kills_the_process_on_cancel(tmp_path: Path, monkeypatch):
    script = tmp_path / "slow.py"
    script.write_text(
        "import sys, time\n"
        "for i in range(600):\n"
        "    print(f'{i / 6:.2f}%', flush=True)\n"
        "    time.sleep(0.1)\n"
    )
    real_popen = upscale.subprocess.Popen

    def popen(cmd, **kwargs):
        return real_popen([sys.executable, str(script)], **kwargs)

    monkeypatch.setattr(upscale.subprocess, "Popen", popen)
    seen = []
    started = time.time()
    with pytest.raises(upscale.UpscaleCancelled):
        upscale.run_pass(
            Path(sys.executable), tmp_path / "a.png", tmp_path / "b.png", "anime",
            progress=seen.append, cancelled=lambda: len(seen) >= 3,
        )
    assert time.time() - started < 20


def test_cancel_during_upscale_is_not_a_fallback(monkeypatch):
    def cancelled_upscale(*args, **kwargs):
        raise upscale.UpscaleCancelled()

    monkeypatch.setattr(fetch, "ensure_upscaler", lambda progress=None: Path("x.exe"))
    monkeypatch.setattr(upscale, "upscale", cancelled_upscale)
    settings = Settings(2, 2, "auto", True, "anime", 150, 8.0, True)
    with pytest.raises(Cancelled):
        pipeline.prepare(Image.new("RGB", (400, 600)), settings, A4,
                         lambda name, frac: None, lambda: False)
