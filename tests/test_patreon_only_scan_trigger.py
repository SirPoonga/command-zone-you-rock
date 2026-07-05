from pathlib import Path

from yourock.bookmark_scan import _scan_entries_for_match


def test_full_video_scan_no_longer_uses_intro_marker_trigger() -> None:
    source = Path(_scan_entries_for_match.__code__.co_filename).read_text(
        encoding="utf-8"
    )

    assert "_analysis_contains_scan_trigger(analysis)" not in source
    assert "POST_MARKER_PATREON_SEARCH_SECONDS" not in source
    assert "analysis.has_patreon_url" in source
    assert "(second - anchor) % 10 != 0" in source
