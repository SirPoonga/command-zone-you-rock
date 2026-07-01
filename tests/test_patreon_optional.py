import inspect

from yourock.bookmark_scan import scan_description_bookmarks


def test_you_rock_does_not_require_patreon_marker():
    source = inspect.getsource(scan_description_bookmarks)

    assert "patreon_seconds" not in source
    assert "most_recent_prior_marker" not in source
    assert "marker is not None" not in source
    assert "analysis.has_patreon_url" not in source


def test_you_rock_still_moves_to_next_video_after_match():
    source = inspect.getsource(scan_description_bookmarks)

    assert "moving to next video" in source
    assert "_save_match(" in source
    assert "return bookmarks" in source
