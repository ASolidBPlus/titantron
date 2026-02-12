import re
from datetime import date


# Common wrestling filename patterns:
# "WWE.Raw.2024.01.15.720p.WEB.h264-HEEL.mkv"     -> 2024-01-15
# "AEW Dynamite 01-17-2024 HDTV.mp4"               -> 2024-01-17
# "NJPW.2024.01.04.Wrestle.Kingdom.18.mkv"          -> 2024-01-04
# "ROH_Death_Before_Dishonor_2024-07-26.mp4"        -> 2024-07-26
# "2024.01.15 - WWE Monday Night Raw.mkv"           -> 2024-01-15

# YYYY.MM.DD or YYYY-MM-DD or YYYY/MM/DD
_PATTERN_YMD = re.compile(r"(?<!\d)(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})(?!\d)")
# MM-DD-YYYY or MM.DD.YYYY or MM/DD/YYYY
_PATTERN_MDY = re.compile(r"(?<!\d)(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})(?!\d)")


def _is_valid_date(year: int, month: int, day: int) -> bool:
    try:
        date(year, month, day)
        return True
    except ValueError:
        return False


def _make_date(year: int, month: int, day: int) -> date | None:
    if _is_valid_date(year, month, day):
        return date(year, month, day)
    return None


def parse_date_from_filename(filename: str) -> date | None:
    """Extract a date from a wrestling video filename.

    Tries YYYY.MM.DD first (most common for scene releases),
    then MM-DD-YYYY (US format). Ambiguous MM/DD vs DD/MM
    defaults to US (MM-DD).
    """
    # Strip file extension
    name = re.sub(r"\.\w{2,4}$", "", filename)

    # Try YYYY.MM.DD first
    match = _PATTERN_YMD.search(name)
    if match:
        year, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if 1990 <= year <= 2040:
            result = _make_date(year, m, d)
            if result:
                return result
            # Try swapping month/day
            result = _make_date(year, d, m)
            if result:
                return result

    # Try MM-DD-YYYY
    match = _PATTERN_MDY.search(name)
    if match:
        a, b, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if 1990 <= year <= 2040:
            # Prefer US format: a=month, b=day
            result = _make_date(year, a, b)
            if result:
                return result
            # Try European: a=day, b=month
            result = _make_date(year, b, a)
            if result:
                return result

    return None


def extract_date(
    premiere_date: str | None = None,
    filename: str | None = None,
    date_created: str | None = None,
) -> date | None:
    """Extract date using priority chain:
    1. Jellyfin PremiereDate
    2. Filename regex
    3. Jellyfin DateCreated (fallback, least reliable)
    """
    # Try PremiereDate
    if premiere_date:
        try:
            return date.fromisoformat(premiere_date[:10])
        except (ValueError, IndexError):
            pass

    # Try filename
    if filename:
        result = parse_date_from_filename(filename)
        if result:
            return result

    # Fallback to DateCreated
    if date_created:
        try:
            return date.fromisoformat(date_created[:10])
        except (ValueError, IndexError):
            pass

    return None
