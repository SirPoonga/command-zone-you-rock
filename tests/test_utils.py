from yourock.utils import extract_episode_number, format_timestamp, youtube_url


def test_episode_number_from_command_zone_title():
    title = "How to Play Commander | The Command Zone 745 | MTG EDH Magic Gathering"
    assert extract_episode_number(title) == "745"


def test_format_timestamp():
    assert format_timestamp(4786) == "1:19:46"
    assert format_timestamp(65) == "1:05"


def test_youtube_url():
    assert youtube_url("abc123", 65) == "https://www.youtube.com/watch?v=abc123&t=65s"
