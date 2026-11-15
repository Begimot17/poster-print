"""Download and cache the Real-ESRGAN ncnn-vulkan binary (stdlib only)."""

from __future__ import annotations

import hashlib
import shutil
import sys
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip"
SHA256 = "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d"
EXE_NAME = "realesrgan-ncnn-vulkan.exe"

_RETRIES = 3
_TIMEOUT = 30


class FetchError(RuntimeError):
    """Raised when the binary cannot be obtained."""


def app_dir() -> Path:
    """Return the folder of the frozen exe or the project root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def bin_dir() -> Path:
    """Return the directory where the Real-ESRGAN binary lives."""
    return app_dir() / "bin" / "realesrgan"


def is_installed() -> bool:
    """Return True when the exe and models/ folder are both present."""
    d = bin_dir()
    return (d / EXE_NAME).is_file() and (d / "models").is_dir()


def _verify_sha256(path: Path) -> None:
    """Raise FetchError if the file's SHA-256 does not match SHA256."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    if digest != SHA256:
        raise FetchError(
            f"SHA-256 mismatch for {path.name}: expected {SHA256}, got {digest}"
        )


def _extract_safe(zip_path: Path, target: Path) -> None:
    """Extract zip_path into target, rejecting members that escape the target dir."""
    target = target.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            dest = (target / member.filename).resolve()
            if not dest.is_relative_to(target):
                raise FetchError(
                    f"Unsafe zip member rejected: {member.filename!r}"
                )
            zf.extract(member, target)


def ensure_upscaler(
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Return the path to the Real-ESRGAN exe, downloading and extracting if needed.

    Raises FetchError with a human-readable message on failure.
    """
    target = bin_dir()
    exe = target / EXE_NAME
    if is_installed():
        return exe

    target.mkdir(parents=True, exist_ok=True)
    zip_path = app_dir() / "bin" / "realesrgan.zip"

    # User may have dropped the zip manually.
    if not zip_path.is_file():
        part_path = zip_path.with_suffix(".zip.part")
        last_exc: Exception | None = None
        for attempt in range(1, _RETRIES + 1):
            try:
                with urllib.request.urlopen(URL, timeout=_TIMEOUT) as resp:
                    total = int(resp.headers.get("Content-Length", 0))
                    done = 0
                    with part_path.open("wb") as out:
                        while True:
                            chunk = resp.read(1 << 16)
                            if not chunk:
                                break
                            out.write(chunk)
                            done += len(chunk)
                            if progress is not None:
                                progress(done, total)
                part_path.rename(zip_path)
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if part_path.exists():
                    part_path.unlink(missing_ok=True)
        if last_exc is not None:
            raise FetchError(
                f"Failed to download Real-ESRGAN after {_RETRIES} attempts: {last_exc}"
            ) from last_exc

    if SHA256 != "TODO":
        try:
            _verify_sha256(zip_path)
        except FetchError:
            zip_path.unlink(missing_ok=True)
            raise

    try:
        _extract_safe(zip_path, target)
    except FetchError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise FetchError(f"Failed to extract Real-ESRGAN: {exc}") from exc

    zip_path.unlink(missing_ok=True)

    if not is_installed():
        raise FetchError(
            "Extraction succeeded but the exe or models/ folder is missing. "
            "The zip layout may have changed."
        )

    return exe
