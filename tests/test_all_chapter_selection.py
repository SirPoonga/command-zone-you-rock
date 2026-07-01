import inspect

from yourock.bookmark_scan import scan_description_bookmarks


def test_scans_all_chapters_at_or_after_one_minute():
    source = inspect.getsource(scan_description_bookmarks)

    assert "select_early_bookmarks" not in source
    assert "bookmark.timestamp_seconds >= 60" in source
    assert "checking all" in source
