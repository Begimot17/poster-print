import io
import json

import pytest

from app import update


@pytest.mark.parametrize("text,expected", [
    ("v1.2.3", (1, 2, 3)), ("0.10", (0, 10)), ("v2.0.0-beta1", (2, 0, 0)), ("nightly", ()),
])
def test_parse_version(text, expected):
    assert update.parse_version(text) == expected


def test_is_newer_compares_numbers_not_strings():
    assert update.is_newer("0.10.0", "0.9.0")
    assert not update.is_newer("0.2.0", "0.2.0")
    assert not update.is_newer("0.1.9", "0.2.0")
    assert not update.is_newer("garbage", "0.2.0")


def fake_response(payload):
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return Response(json.dumps(payload).encode())


def test_check_returns_newer_release_with_zip_asset(monkeypatch):
    payload = {
        "tag_name": "v99.0.0",
        "html_url": "https://example.test/release",
        "assets": [
            {"name": "notes.txt", "browser_download_url": "https://example.test/notes.txt"},
            {"name": "PosterPrint.zip", "browser_download_url": "https://example.test/p.zip"},
        ],
    }
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda *a, **k: fake_response(payload))
    release = update.check()
    assert release == update.Release("99.0.0", "https://example.test/release", "https://example.test/p.zip")


def test_check_is_silent_when_current_or_offline(monkeypatch):
    same = {"tag_name": "v" + update.__version__, "assets": []}
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda *a, **k: fake_response(same))
    assert update.check() is None

    def offline(*args, **kwargs):
        raise OSError("no network")

    monkeypatch.setattr(update.urllib.request, "urlopen", offline)
    assert update.check() is None
