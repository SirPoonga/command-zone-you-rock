from yourock.scanner import _should_scan_playlist_item
from yourock.youtube import PlaylistVideo


def item(title: str) -> PlaylistVideo:
    return PlaylistVideo(
        video_id="test",
        playlist_index=0,
        title=title,
        webpage_url="https://example.test/watch?v=test",
    )


def test_scans_command_zone_episode_greater_than_170() -> None:
    assert _should_scan_playlist_item(
        item("Mairsil, The Pretender DECK TECH | The Command Zone 177")
    )


def test_skips_command_zone_episode_170_or_lower() -> None:
    assert not _should_scan_playlist_item(
        item("Some Topic | The Command Zone 170 | Magic Commander")
    )
    assert not _should_scan_playlist_item(
        item("Some Topic | The Command Zone 001 | Magic Commander")
    )


def test_keeps_unknown_episode_titles() -> None:
    assert _should_scan_playlist_item(item("Nonstandard title without a number"))
