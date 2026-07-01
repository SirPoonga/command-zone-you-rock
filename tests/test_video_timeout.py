import time

import pytest

from yourock.bookmark_scan import _remaining_video_timeout_ms


def test_video_timeout_reports_expired_deadline():
    with pytest.raises(TimeoutError, match="Video scan exceeded"):
        _remaining_video_timeout_ms(
            time.monotonic() - 1,
            stage="testing",
        )


def test_video_timeout_returns_remaining_milliseconds():
    remaining = _remaining_video_timeout_ms(
        time.monotonic() + 2,
        stage="testing",
    )
    assert 1 <= remaining <= 2_000
