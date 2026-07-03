from yourock.bookmark_scan import _contains_you_rock
from yourock.detection import parse_name_from_ocr


def test_accepts_stacked_old_banner() -> None:
    text = "AUGUSTUS WARD\nYOU ROCK!!!"
    assert _contains_you_rock(text)
    assert parse_name_from_ocr(text) == "Augustus Ward"


def test_accepts_flattened_old_banner_without_separator() -> None:
    text = "AUGUSTUS WARD YOU ROCK!!!"
    assert _contains_you_rock(text)
    assert parse_name_from_ocr(text) == "Augustus Ward"


def test_accepts_modern_banner_with_separator() -> None:
    text = "JEREMY DENNIS - YOU ROCK!!!"
    assert _contains_you_rock(text)


def test_rejects_patreon_benefit_prose() -> None:
    assert not _contains_you_rock(
        "SHOW THE WORLD JUST HOW MUCH YOU ROCK"
    )
