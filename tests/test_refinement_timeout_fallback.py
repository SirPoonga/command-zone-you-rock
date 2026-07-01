import inspect
from types import SimpleNamespace

import yourock.bookmark_scan as bookmark_scan


def test_video_scan_timeout_allows_long_scans():
    assert bookmark_scan.VIDEO_SCAN_TIMEOUT_SECONDS == 10_800


def test_refinement_timeout_preserves_coarse_detection(monkeypatch):
    coarse = SimpleNamespace(timestamp_seconds=275)

    def raise_timeout(*args, **kwargs):
        raise TimeoutError("test timeout")

    monkeypatch.setattr(
        bookmark_scan,
        "_refine_you_rock_candidate",
        raise_timeout,
    )

    result = bookmark_scan._refine_or_use_coarse(
        None,
        None,
        None,
        coarse,
        deadline=0,
        timeout_ms=0,
        duration=0,
    )

    assert result is coarse


def test_scan_uses_timeout_safe_refinement_wrapper():
    source = inspect.getsource(bookmark_scan._scan_entries_for_match)

    assert "_refine_or_use_coarse(" in source
