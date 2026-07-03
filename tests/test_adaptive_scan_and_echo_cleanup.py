from types import SimpleNamespace

from yourock.bookmark_scan import _analysis_contains_scan_trigger
from yourock.detection import _remove_matching_trailing_echo_letter


def test_removes_matching_trailing_echo_letter() -> None:
    assert _remove_matching_trailing_echo_letter("Don Kim M") == "Don Kim"
    assert _remove_matching_trailing_echo_letter("Abe Hazway Y") == "Abe Hazway"


def test_does_not_remove_nonmatching_or_lowercase_letter() -> None:
    assert _remove_matching_trailing_echo_letter("Don Kim X") == "Don Kim X"
    assert _remove_matching_trailing_echo_letter("Don Kim m") == "Don Kim m"


def test_detects_intro_and_sponsor_markers() -> None:
    assert _analysis_contains_scan_trigger(
        SimpleNamespace(text="Visit commandzone.com today")
    )
    assert _analysis_contains_scan_trigger(
        SimpleNamespace(lines=["ULTRA PRO"])
    )
    assert _analysis_contains_scan_trigger(
        SimpleNamespace(raw_text="patreon.com/commandzone")
    )


def test_ignores_unrelated_ocr_text() -> None:
    assert not _analysis_contains_scan_trigger(
        SimpleNamespace(text="AUGUSTUS WARD YOU ROCK")
    )
