import inspect
from types import SimpleNamespace

from PIL import Image

from yourock.bookmark_scan import (
    _early_sweep_seconds,
    _region_crops,
    scan_description_bookmarks,
)


def test_early_sweep_covers_linked_example_time():
    seconds = _early_sweep_seconds(900, 5)

    assert seconds[0] == 60
    assert seconds[-1] == 480
    assert 200 in seconds


def test_short_video_early_sweep_stops_before_duration():
    seconds = _early_sweep_seconds(203, 5)

    assert seconds[-1] == 200
    assert all(second < 203 for second in seconds)


def test_multi_region_mode_includes_old_and_modern_layouts():
    image = Image.new("RGB", (1000, 600))
    config = SimpleNamespace(crop_top_fraction=0.50)

    regions = _region_crops(image, config, "multi")

    assert [name for name, _ in regions] == [
        "banner",
        "configured",
        "lower-left",
        "lower-right",
    ]


def test_scan_runs_early_sweep_then_all_chapters():
    source = inspect.getsource(scan_description_bookmarks)

    assert "_early_sweep_seconds" in source
    assert "checking all" in source
    assert "select_early_bookmarks" not in source
    assert "moving to next video" in source
