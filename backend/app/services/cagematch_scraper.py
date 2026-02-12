import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

import aiohttp
from bs4 import BeautifulSoup, Tag

from app.config import settings
from app.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cagematch.net/"

# Cache TTLs
TTL_PROMOTION = timedelta(days=7)
TTL_EVENT_LIST = timedelta(hours=24)
TTL_EVENT_DETAIL = timedelta(days=7)
TTL_WRESTLER = timedelta(days=7)


@dataclass
class EventSummary:
    cagematch_event_id: int
    name: str
    date: date
    location: str | None = None
    rating: float | None = None
    votes: int | None = None


@dataclass
class WrestlerRef:
    """A wrestler reference — may or may not have a Cagematch ID."""

    name: str
    cagematch_id: int | None = None
    is_linked: bool = False


@dataclass
class MatchData:
    match_number: int
    match_type: str | None = None
    stipulation: str | None = None
    title_name: str | None = None
    participants: list[WrestlerRef] = field(default_factory=list)
    result: str | None = None
    rating: float | None = None
    votes: int | None = None
    duration: str | None = None


@dataclass
class EventDetail:
    cagematch_event_id: int
    name: str
    date: date
    promotion_name: str | None = None
    event_type: str | None = None
    location: str | None = None
    arena: str | None = None
    rating: float | None = None
    votes: int | None = None
    matches: list[MatchData] = field(default_factory=list)


def _build_url(db_type: int, nr: int | None = None, page: int | None = None, **params) -> str:
    url_params: dict = {"id": db_type}
    if nr is not None:
        url_params["nr"] = nr
    if page is not None:
        url_params["page"] = page
    url_params.update(params)
    return BASE_URL + "?" + urlencode(url_params)


def _parse_dd_mm_yyyy(text: str) -> date | None:
    """Parse DD.MM.YYYY format used by Cagematch."""
    match = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", text.strip())
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _extract_id_from_href(href: str, param: str = "nr") -> int | None:
    """Extract a numeric ID from a Cagematch href like '?id=1&nr=12345'."""
    match = re.search(rf"{param}=(\d+)", href)
    if match:
        return int(match.group(1))
    return None


def _parse_float(text: str) -> float | None:
    try:
        val = float(text.strip())
        return val if val > 0 else None
    except (ValueError, AttributeError):
        return None


def _parse_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except (ValueError, AttributeError):
        return None


class CagematchScraper:
    def __init__(self):
        self.rate_limiter = RateLimiter(
            requests_per_second=settings.scrape_rate_limit,
            burst=settings.scrape_burst,
        )
        self._cache: dict[str, tuple[str, datetime]] = {}

    async def _fetch_page(self, url: str, ttl: timedelta = TTL_EVENT_LIST) -> str:
        """Fetch a page with rate limiting. Returns HTML string."""
        # Check in-memory cache
        if url in self._cache:
            html, expires = self._cache[url]
            if datetime.now() < expires:
                return html

        await self.rate_limiter.acquire()

        headers = {
            "User-Agent": settings.scrape_user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        retries = 3
        for attempt in range(retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status == 429:
                            wait = 2 ** (attempt + 1)
                            logger.warning(f"Rate limited by Cagematch, waiting {wait}s")
                            await __import__("asyncio").sleep(wait)
                            continue
                        resp.raise_for_status()
                        html = await resp.text()
                        self._cache[url] = (html, datetime.now() + ttl)
                        return html
            except aiohttp.ClientError as e:
                if attempt == retries - 1:
                    logger.error(f"Failed to fetch {url}: {e}")
                    raise
                await __import__("asyncio").sleep(2 ** attempt)

        raise RuntimeError(f"Failed to fetch {url} after {retries} retries")

    def _parse_html(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    async def scrape_promotion_events(
        self,
        cagematch_promotion_id: int,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[EventSummary]:
        """Scrape events for a promotion within a date range.

        Cagematch uses form fields: vDay, vMonth, vYear for date filtering.
        When only vMonth and vYear are set, it returns all events in that month.
        For range queries spanning multiple months, we make multiple requests.
        """
        params: dict = {}
        # Cagematch date filter: vDay (optional), vMonth, vYear
        # This filters to a specific month/year. For a single day, set all three.
        if date_from:
            if date_to and date_from.month == date_to.month and date_from.year == date_to.year:
                # Same month — use month filter
                params["vMonth"] = f"{date_from.month:02d}"
                params["vYear"] = str(date_from.year)
                if date_from.day == date_to.day:
                    params["vDay"] = f"{date_from.day:02d}"
            else:
                # Default to the from-date's month
                params["vMonth"] = f"{date_from.month:02d}"
                params["vYear"] = str(date_from.year)

        url = _build_url(8, nr=cagematch_promotion_id, page=4, **params)
        html = await self._fetch_page(url, ttl=TTL_EVENT_LIST)
        soup = self._parse_html(html)

        events: list[EventSummary] = []
        # Events are in table rows. Find all rows with event links.
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            # Look for a date cell and an event link
            event_date = None
            event_id = None
            event_name = None
            location = None
            rating = None
            votes = None

            for cell in cells:
                text = cell.get_text(strip=True)

                # Try to find date (DD.MM.YYYY)
                if not event_date and re.match(r"\d{2}\.\d{2}\.\d{4}", text):
                    event_date = _parse_dd_mm_yyyy(text)

                # Try to find event link
                link = cell.find("a", href=re.compile(r"\?id=1&nr=\d+"))
                if link and not event_id:
                    event_id = _extract_id_from_href(link.get("href", ""))
                    event_name = link.get_text(strip=True)

            if not (event_date and event_id and event_name):
                continue

            # Location is typically after the event name cell
            # Rating and votes are in the last cells
            for cell in reversed(cells):
                text = cell.get_text(strip=True)
                if votes is None and text.isdigit():
                    votes = int(text)
                elif rating is None:
                    rating = _parse_float(text)

            # Location: find the cell after the event name
            for i, cell in enumerate(cells):
                if cell.find("a", href=re.compile(r"\?id=1&nr=")):
                    if i + 1 < len(cells):
                        loc_text = cells[i + 1].get_text(strip=True)
                        if loc_text and not re.match(r"^[\d.]+$", loc_text):
                            location = loc_text
                    break

            events.append(
                EventSummary(
                    cagematch_event_id=event_id,
                    name=event_name,
                    date=event_date,
                    location=location,
                    rating=rating,
                    votes=votes,
                )
            )

        return events

    async def scrape_event_detail(self, cagematch_event_id: int) -> EventDetail | None:
        """Scrape event overview page for metadata."""
        url = _build_url(1, nr=cagematch_event_id)
        html = await self._fetch_page(url, ttl=TTL_EVENT_DETAIL)
        soup = self._parse_html(html)

        name = None
        event_date = None
        promotion_name = None
        event_type = None
        location = None
        arena = None
        rating = None
        votes = None

        # The event page uses an information block with label-value pairs
        for row in soup.find_all("div", class_="InformationBoxRow"):
            label_el = row.find("div", class_="InformationBoxTitle")
            value_el = row.find("div", class_="InformationBoxContents")
            if not label_el or not value_el:
                continue
            label = label_el.get_text(strip=True).rstrip(":")
            value = value_el.get_text(strip=True)

            if label == "Name of the event":
                name = value
            elif label == "Date":
                event_date = _parse_dd_mm_yyyy(value)
            elif label == "Promotion":
                promotion_name = value
            elif label == "Type":
                event_type = value
            elif label == "Location":
                location = value
            elif label == "Arena":
                arena = value

        # Try alternate layout: some pages use table-based info
        if not name:
            title_el = soup.find("h1") or soup.find("div", class_="EventHeader")
            if title_el:
                name = title_el.get_text(strip=True)

        if not name:
            return None

        # Try to get rating from the page
        rating_el = soup.find("div", class_="star-rating") or soup.find("span", class_="star-rating")
        if rating_el:
            rating = _parse_float(rating_el.get_text(strip=True))

        return EventDetail(
            cagematch_event_id=cagematch_event_id,
            name=name,
            date=event_date or date.today(),
            promotion_name=promotion_name,
            event_type=event_type,
            location=location,
            arena=arena,
            rating=rating,
            votes=votes,
        )

    async def scrape_event_matches(self, cagematch_event_id: int) -> list[MatchData]:
        """Scrape the match card for an event.

        Page=3 is the "Card" view. The HTML uses:
        - div.Matches as the container
        - div.Match for each match
        - div.MatchType for the match type/stipulation
        - div.MatchResults for results text
        - div.MatchRecommendedLine for ratings
        - Wrestler links: <a href="?id=2&nr={id}">Name</a>
        - Unlinked wrestlers: plain text nodes
        """
        url = _build_url(1, nr=cagematch_event_id, page=3)
        html = await self._fetch_page(url, ttl=TTL_EVENT_DETAIL)
        soup = self._parse_html(html)

        matches: list[MatchData] = []

        # Find the container with all matches
        matches_container = soup.find("div", class_="Matches")
        if not matches_container:
            logger.warning(f"No div.Matches found for event {cagematch_event_id}")
            return matches

        # Each match is in a div.Match
        for match_number, match_div in enumerate(matches_container.find_all("div", class_="Match"), start=1):
            match_type = None
            title_name = None
            result = None
            rating = None
            votes = None
            duration = None

            # Extract match type
            type_div = match_div.find("div", class_="MatchType")
            if type_div:
                match_type = type_div.get_text(strip=True)
                # Check for title link
                title_link = type_div.find("a", href=re.compile(r"\?id=5&nr=\d+"))
                if title_link:
                    title_name = title_link.get_text(strip=True)

            # Extract results
            results_div = match_div.find("div", class_="MatchResults")
            if results_div:
                result = results_div.get_text(strip=True)
                # Try to extract duration from result text: (12:34)
                dur_match = re.search(r"\((\d+:\d+)\)", result)
                if dur_match:
                    duration = dur_match.group(1)

            # Extract rating from MatchRecommendedLine
            rating_div = match_div.find("div", class_="MatchRecommendedLine")
            if rating_div:
                rating_text = rating_div.get_text(strip=True)
                rating_match = re.search(r"(\d+\.\d+)", rating_text)
                if rating_match:
                    rating = float(rating_match.group(1))
                votes_match = re.search(r"(\d+)\s*votes", rating_text)
                if votes_match:
                    votes = int(votes_match.group(1))

            # Extract participants
            participants = self._parse_participants(match_div)

            matches.append(
                MatchData(
                    match_number=match_number,
                    match_type=match_type,
                    title_name=title_name,
                    participants=participants,
                    result=result,
                    rating=rating,
                    votes=votes,
                    duration=duration,
                )
            )

        return matches

    def _parse_participants(self, match_div: Tag) -> list[WrestlerRef]:
        """Parse wrestler names from a match div.

        Handles both linked wrestlers (<a> tags with id=2) and unlinked (plain text).
        Ignores non-wrestler links (titles, events, etc.)
        """
        participants: list[WrestlerRef] = []
        seen_names: set[str] = set()

        # Find all wrestler links within the match div
        for link in match_div.find_all("a", href=re.compile(r"\?id=2&nr=\d+")):
            name = link.get_text(strip=True)
            if name and name not in seen_names:
                wrestler_id = _extract_id_from_href(link.get("href", ""))
                participants.append(
                    WrestlerRef(name=name, cagematch_id=wrestler_id, is_linked=True)
                )
                seen_names.add(name)

        # Look for unlinked wrestler names in the match results text
        # These appear as plain text nodes mixed with "vs." separators
        results_div = match_div.find("div", class_="MatchResults")
        if results_div:
            # Walk through children to find text nodes not inside <a> tags
            for child in results_div.children:
                if isinstance(child, str):
                    # Plain text node — may contain unlinked wrestler names
                    text = child.strip()
                    if not text:
                        continue
                    # Split by common separators
                    for segment in re.split(r"\s*(?:vs\.|&|,|\band\b)\s*", text):
                        name = segment.strip()
                        # Clean up noise
                        name = re.sub(r"\(c\)", "", name).strip()
                        name = re.sub(r"\(w/.*?\)", "", name).strip()
                        name = re.sub(r"\s*(defeat|defeats|draw|by|via)\s.*", "", name, flags=re.IGNORECASE).strip()
                        name = re.sub(r"^[:\s]+|[:\s]+$", "", name)

                        if (
                            name
                            and len(name) > 1
                            and name not in seen_names
                            and not re.match(r"^[\d\s.,():]+$", name)
                        ):
                            participants.append(WrestlerRef(name=name, cagematch_id=None, is_linked=False))
                            seen_names.add(name)

        return participants
