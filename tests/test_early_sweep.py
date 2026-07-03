import inspect

from yourock.bookmark_scan import (
    _full_video_scan_seconds,
    scan_description_bookmarks,
)


def test_full_video_scan_includes_phil_wong_timestamp_neighborhood():
    seconds = _full_video_scan_seconds(900, 5)

    assert 525 in seconds
    assert 530 in seconds


def test_full_video_scan_starts_at_one_minute():
    seconds = _full_video_scan_seconds(205, 5)

    assert seconds[0] == 60
    assert seconds[-1] == 200
    assert all(second < 205 for second in seconds)
    assert all(second % 5 == 0 for second in seconds)


def test_scan_uses_full_video_sweep_and_stops_on_match():
    source = inspect.getsource(scan_description_bookmarks)

    assert "_full_video_scan_seconds" in source
    assert "full-video sweep" in source
    assert 'coarse_mode="banner"' in source
    assert "_save_match(" in source
    assert "moving to next video" in source
    assert "_early_sweep_seconds" not in source
    assert "_seconds_to_scan" not in source
