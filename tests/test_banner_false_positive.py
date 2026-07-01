from types import SimpleNamespace

from PIL import Image

from yourock.bookmark_scan import (
    _contains_you_rock,
    _region_crops,
)


def test_rejects_patreon_slide_prose_false_positive():
    text = "Show the world just how much YOU ROCK!!!!!!!"

    assert not _contains_you_rock(text)


def test_accepts_name_banner_with_hyphen():
    text = "JEREMY DENNIS - YOU ROCK!!!!!!!"

    assert _contains_you_rock(text)


def test_accepts_layout_separator_between_name_and_phrase():
    text = "32bit | YOU ROCK!!!"

    assert _contains_you_rock(text)


def test_banner_mode_uses_only_bottom_banner_region():
    image = Image.new("RGB", (1000, 600))
    config = SimpleNamespace(crop_top_fraction=0.50)

    regions = _region_crops(image, config, "banner")

    assert [name for name, _ in regions] == ["banner"]
    assert regions[0][1].size == (1000, 228)


def test_multi_mode_omits_full_frame_false_positive_region():
    image = Image.new("RGB", (1000, 600))
    config = SimpleNamespace(crop_top_fraction=0.50)

    regions = _region_crops(image, config, "multi")

    assert [name for name, _ in regions] == [
        "banner",
        "configured",
        "lower-left",
        "lower-right",
    ]
