from datetime import date

from app.utils.date_parser import extract_date, parse_date_from_filename


class TestParseDateFromFilename:
    def test_yyyy_mm_dd_dot_separated(self):
        assert parse_date_from_filename("WWE.Raw.2024.01.15.720p.WEB.h264-HEEL.mkv") == date(2024, 1, 15)

    def test_yyyy_mm_dd_dash_separated(self):
        assert parse_date_from_filename("NJPW-2024-01-04-Wrestle-Kingdom-18.mkv") == date(2024, 1, 4)

    def test_mm_dd_yyyy_dash_separated(self):
        assert parse_date_from_filename("AEW Dynamite 01-17-2024 HDTV.mp4") == date(2024, 1, 17)

    def test_date_at_beginning(self):
        assert parse_date_from_filename("2024.01.15 - WWE Monday Night Raw.mkv") == date(2024, 1, 15)

    def test_underscore_separators_in_name(self):
        assert parse_date_from_filename("ROH_Death_Before_Dishonor_2024-07-26.mp4") == date(2024, 7, 26)

    def test_no_date_returns_none(self):
        assert parse_date_from_filename("random_video_no_date.mp4") is None

    def test_invalid_date_returns_none(self):
        assert parse_date_from_filename("show.2024.13.45.mp4") is None

    def test_year_out_of_range(self):
        assert parse_date_from_filename("show.1850.01.01.mp4") is None

    def test_strips_extension(self):
        result = parse_date_from_filename("2024.06.15.mkv")
        assert result == date(2024, 6, 15)


class TestExtractDate:
    def test_premiere_date_priority(self):
        result = extract_date(
            premiere_date="2024-03-15T00:00:00.0000000Z",
            filename="show.2024.01.01.mkv",
        )
        assert result == date(2024, 3, 15)

    def test_falls_back_to_filename(self):
        result = extract_date(premiere_date=None, filename="show.2024.06.20.mkv")
        assert result == date(2024, 6, 20)

    def test_falls_back_to_date_created(self):
        result = extract_date(
            premiere_date=None,
            filename="no_date_here.mkv",
            date_created="2024-09-01T12:00:00Z",
        )
        assert result == date(2024, 9, 1)

    def test_all_none_returns_none(self):
        assert extract_date() is None

    def test_invalid_premiere_date_falls_through(self):
        result = extract_date(
            premiere_date="not-a-date",
            filename="show.2024.01.01.mkv",
        )
        assert result == date(2024, 1, 1)
