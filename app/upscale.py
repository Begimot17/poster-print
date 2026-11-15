"""Real-ESRGAN ncnn-vulkan runner."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from app.layout import upscale_passes

MODELS: dict[str, tuple[str, str]] = {
    "anime": ("realesrgan-x4plus-anime", "Anime / illustration"),
    "photo": ("realesrgan-x4plus", "Photo / general"),
    "fast": ("realesr-animevideov3", "Fast (weak GPU)"),
}

CREATE_NO_WINDOW = 0x08000000
_TAIL_LINES = 20
MAX_PASS_OUTPUT_PX = 200_000_000


class UpscaleError(RuntimeError):
    """Raised when Real-ESRGAN exits non-zero or the output file is missing."""


class UpscaleCancelled(Exception):
    """Raised when the caller cancelled a running pass; the process is killed."""


def run_pass(
    exe: Path,
    src_png: Path,
    dst_png: Path,
    model_key: str,
    tile: int = 0,
    gpu: int | None = None,
    progress=None,
    cancelled=None,
) -> None:
    """Run one x4 upscale pass with Real-ESRGAN ncnn-vulkan."""
    model_name = MODELS[model_key][0]
    cmd = [
        str(exe),
        "-i", str(src_png),
        "-o", str(dst_png),
        "-n", model_name,
        "-s", "4",
        "-t", str(tile),
        "-f", "png",
    ]
    if gpu is not None:
        cmd += ["-g", str(gpu)]

    output_lines: list[str] = []

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=exe.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError as exc:
        raise UpscaleError(f"Cannot start Real-ESRGAN: {exc}") from exc

    assert proc.stdout is not None
    for raw_line in proc.stdout:
        if cancelled is not None and cancelled():
            proc.kill()
            proc.wait()
            raise UpscaleCancelled()
        line = raw_line.decode(errors="replace").rstrip()
        output_lines.append(line)
        if len(output_lines) > _TAIL_LINES:
            output_lines.pop(0)
        if progress is not None:
            stripped = line.strip().rstrip("%")
            try:
                pct = float(stripped)
                progress(pct / 100.0)
            except ValueError:
                pass

    ret = proc.wait()
    if ret != 0 or not dst_png.is_file():
        tail = "\n".join(output_lines)
        raise UpscaleError(
            f"Real-ESRGAN failed (exit {ret}). Last output:\n{tail}"
        )


def upscale(
    img: Image.Image,
    scale: float,
    model_key: str,
    exe: Path,
    workdir: Path,
    progress=None,
    cancelled=None,
) -> Image.Image:
    """Run n AI upscale passes and return the resulting image.

    n == 0: return img unchanged.
    The caller is responsible for the final exact resize.
    """
    n = upscale_passes(scale)
    if n == 0:
        return img

    Image.MAX_IMAGE_PIXELS = None
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    src_path = workdir / "_up_src.png"
    img.save(src_path)

    current = src_path
    size = img.size
    remaining = scale
    for i in range(n):
        shrink = _input_shrink(size, remaining, passes_left=n - i, first=i == 0)
        if shrink < 1.0:
            size = (max(1, round(size[0] * shrink)), max(1, round(size[1] * shrink)))
            with Image.open(current) as opened:
                smaller = opened.resize(size, Image.LANCZOS)
            smaller.save(current)

        dst_path = workdir / f"_up_pass{i + 1}.png"

        pass_progress = None
        if progress is not None:
            def pass_progress(frac: float, _i=i, _n=n) -> None:
                progress(((_i + frac) / _n))

        run_pass(
            exe, current, dst_path, model_key, progress=pass_progress, cancelled=cancelled
        )

        current.unlink(missing_ok=True)
        current = dst_path
        size = (size[0] * 4, size[1] * 4)
        remaining /= 4 * shrink

    result = Image.open(current)
    result.load()
    current.unlink(missing_ok=True)
    return result


def _input_shrink(
    size: tuple[int, int], remaining: float, passes_left: int, first: bool
) -> float:
    """Factor (<= 1) to shrink a pass input by, so a x4 pass never overshoots wildly.

    The original image is only shrunk when its x4 output would exceed
    MAX_PASS_OUTPUT_PX; an AI-made intermediate is shrunk to exactly what is needed.
    """
    need = remaining / 4**passes_left
    if not first:
        return min(1.0, need)
    if passes_left > 1:
        return 1.0
    cap = (MAX_PASS_OUTPUT_PX / (size[0] * size[1] * 16)) ** 0.5
    return min(1.0, max(need, cap))


def has_vulkan(exe: Path) -> bool:
    """Best-effort check for Vulkan support by running the exe on a tiny image."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tiny = Image.new("RGB", (16, 16), (128, 128, 128))
            src = tmp_path / "tiny_src.png"
            dst = tmp_path / "tiny_dst.png"
            tiny.save(src)
            run_pass(exe, src, dst, "fast", tile=0)
            return dst.is_file()
    except Exception:  # noqa: BLE001
        return False
