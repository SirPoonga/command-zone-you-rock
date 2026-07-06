from pathlib import Path

from yourock.markdown import generate_markdown


def test_generate_markdown_falls_back_to_video_date_and_timestamp_display(tmp_path: Path) -> None:
    shoutouts = tmp_path / "shoutouts.csv"
    videos = tmp_path / "videos.csv"
    output = tmp_path / "YOU_ROCK.md"

    shoutouts.write_text(
        "\n".join(
            [
                "video_id,name,status,timestamp_seconds,timestamp_display,published_date,episode_title,episode_number,screenshot",
                "z6S9-VFFBt4,Planeswalker Project,verified,169,,,,,",
                "",
            ]
        ),
        encoding="utf-8",
    )

    videos.write_text(
        "\n".join(
            [
                "video_id,title,published_date",
                "z6S9-VFFBt4,Mairsil Deck Tech | The Command Zone 177 | Magic Commander,2017-09-06",
                "",
            ]
        ),
        encoding="utf-8",
    )

    generate_markdown(shoutouts, output, videos)

    text = output.read_text(encoding="utf-8")

    assert "Planeswalker Project" in text
    assert "#177" in text
    assert "Sep 6, 2017" in text
    assert "[2:49]" in text
    assert "Date unavailable" not in text
    assert "[Watch]" not in text
