from yourock.bookmark_scan import (
    _clean_name_only_candidate,
    _parse_name_only_banner,
)


def test_name_only_scroll() -> None:
    assert _parse_name_only_banner("GABBI THOMPSON") == "Gabbi Thompson"


def test_split_name_only_scroll() -> None:
    assert _parse_name_only_banner("GABBI\nTHOMPSON") == "Gabbi Thompson"


def test_matching_echo_letter_removed() -> None:
    assert _parse_name_only_banner("DON KIM M") == "Don Kim"


def test_nonmatching_echo_letter_preserved() -> None:
    assert _clean_name_only_candidate("DON KIM X") == "Don Kim X"


def test_sponsor_text_rejected() -> None:
    assert _parse_name_only_banner("PATREON.COM/COMMANDZONE") == ""
    assert _parse_name_only_banner("ULTRA PRO") == ""
