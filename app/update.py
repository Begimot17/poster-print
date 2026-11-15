"""Check GitHub Releases for a newer version (stdlib only)."""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass

__version__ = "0.1.0"

REPO = "Begimot17/poster-print"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"


@dataclass(frozen=True)
class Release:
    version: str
    page_url: str
    download_url: str  # direct link to the portable zip, or the release page


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3); anything unparsable -> ()."""
    return tuple(int(part) for part in re.findall(r"\d+", text.split("-")[0].split("+")[0]))


def is_newer(candidate: str, current: str = __version__) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    return bool(new) and new > old


def latest_release(timeout: float = 8.0) -> Release | None:
    """Latest published release, or None when offline, rate-limited or there is none."""
    request = urllib.request.Request(
        API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "PosterPrint"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
        tag = str(data["tag_name"])
        page = str(data.get("html_url") or RELEASES_URL)
        assets = data.get("assets") or []
    except Exception:  # noqa: BLE001 - an update check must never break the app
        return None
    download = next(
        (
            str(asset["browser_download_url"])
            for asset in assets
            if str(asset.get("name", "")).lower().endswith(".zip")
        ),
        page,
    )
    return Release(tag.lstrip("vV"), page, download)


def check() -> Release | None:
    """The newer release, if there is one."""
    release = latest_release()
    return release if release and is_newer(release.version) else None
