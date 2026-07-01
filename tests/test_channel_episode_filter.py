from types import SimpleNamespace

from yourock.youtube import _filter_command_zone_entries


def test_channel_source_keeps_only_numbered_command_zone_episodes():
    videos = [
        SimpleNamespace(title="The Command Zone 750 | MTG"),
        SimpleNamespace(title="The Command Zone #745 | MTG"),
        SimpleNamespace(title="Game Knights 80"),
        SimpleNamespace(title=""),
    ]

    filtered = _filter_command_zone_entries(
        "https://www.youtube.com/@commandcast/videos",
        videos,
    )

    assert [video.title for video in filtered] == [
        "The Command Zone 750 | MTG",
        "The Command Zone #745 | MTG",
    ]


def test_playlist_source_is_not_filtered():
    videos = [
        SimpleNamespace(title="The Command Zone 750 | MTG"),
        SimpleNamespace(title="Game Knights 80"),
    ]

    filtered = _filter_command_zone_entries(
        "https://www.youtube.com/playlist?list=example",
        videos,
    )

    assert filtered == videos
