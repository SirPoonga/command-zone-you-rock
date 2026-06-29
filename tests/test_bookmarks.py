from yourock.bookmark_scan import (
    DescriptionBookmark,
    merge_description_bookmarks,
    parse_description_bookmarks,
)


def test_parse_description_bookmarks():
    text = """0:00 Intro
14:52 Main topic
1:02:03 Closing thoughts
"""
    assert parse_description_bookmarks(text) == [
        DescriptionBookmark(0, "Intro"),
        DescriptionBookmark(892, "Main topic"),
        DescriptionBookmark(3723, "Closing thoughts"),
    ]


def test_merge_prefers_labeled_bookmark():
    result = merge_description_bookmarks(
        [DescriptionBookmark(100, "")],
        [DescriptionBookmark(100, "Deck Tech")],
    )
    assert result == [DescriptionBookmark(100, "Deck Tech")]
