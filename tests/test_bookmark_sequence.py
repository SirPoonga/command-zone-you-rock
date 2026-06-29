from yourock.bookmark_scan import (
    DescriptionBookmark,
    _contains_patreon_url,
    most_recent_prior_marker,
    select_early_bookmarks,
)


def test_select_early_bookmarks_skips_zero_and_limits_to_three():
    bookmarks = [
        DescriptionBookmark(0, "Intro"),
        DescriptionBookmark(900, "Topic one"),
        DescriptionBookmark(1800, "Topic two"),
        DescriptionBookmark(2700, "Topic three"),
        DescriptionBookmark(3600, "Topic four"),
    ]
    assert select_early_bookmarks(bookmarks) == bookmarks[1:4]


def test_patreon_url_detection_tolerates_spacing_and_punctuation():
    assert _contains_patreon_url("PATREON.COM/COMMANDZONE")
    assert _contains_patreon_url("patreon dot com slash command zone")
    assert not _contains_patreon_url("Support us on another website")


def test_most_recent_prior_marker_uses_nearest_marker_within_window():
    assert most_recent_prior_marker([100, 120, 150], 160, max_gap_seconds=45) == 150
    assert most_recent_prior_marker([100], 160, max_gap_seconds=45) is None
