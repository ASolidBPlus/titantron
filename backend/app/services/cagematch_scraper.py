from __future__ import annotations

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
    side: int = 1
    team_name: str | None = None
    role: str = "competitor"


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
class EventComment:
    username: str
    date: date | None = None
    rating: float | None = None
    text: str = ""


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


@dataclass
class WrestlerProfile:
    """Profile data scraped from a wrestler's Cagematch page."""

    name: str
    image_url: str | None = None
    birth_date: date | None = None
    birth_place: str | None = None
    height: str | None = None
    weight: str | None = None
    style: str | None = None
    debut: str | None = None
    roles: str | None = None
    nicknames: str | None = None
    signature_moves: str | None = None
    trainers: str | None = None
    alter_egos: str | None = None
    rating: float | None = None
    votes: int | None = None
    rating: float | None = None
    votes: int | None = None


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
                # Check for title link first
                title_link = type_div.find("a", href=re.compile(r"\?id=5&nr=\d+"))
                if title_link:
                    title_name = title_link.get_text(strip=True)
                    # Get match type text without the title name
                    full_text = type_div.get_text(strip=True)
                    match_type = full_text.replace(title_name, "").strip()
                    # Clean up leftover separators
                    match_type = re.sub(r"^[\s\-:]+|[\s\-:]+$", "", match_type)
                    if not match_type:
                        match_type = None
                else:
                    match_type = type_div.get_text(strip=True)

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
        """Parse wrestler names from a match div, assigning sides.

        Handles both linked wrestlers (<a> tags with id=2) and unlinked (plain text).
        Uses the result text to determine which side each wrestler is on by
        splitting on ' vs. ' and checking which half contains each name.
        Also handles team/stable links (id=28 tag teams, id=29 stables).
        """
        results_div = match_div.find("div", class_="MatchResults")
        if not results_div:
            return []

        # Get the full result text and split into sides (no maxsplit — supports multi-way)
        result_text = results_div.get_text()
        sides_text = re.split(r"\s+vs\.?\s+", result_text)

        participants: list[WrestlerRef] = []
        seen_names: set[str] = set()

        # Collect team/stable names from links (id=28 = tag teams, id=29 = stables)
        # Map each team name to its side number for later association with wrestlers.
        side_team_names: dict[int, str] = {}
        for link in results_div.find_all("a", href=re.compile(r"\?id=2[89]&nr=\d+")):
            team_name = link.get_text(strip=True)
            if team_name:
                side = self._determine_side(team_name, sides_text)
                side_team_names[side] = team_name
                seen_names.add(team_name)

        # Build a set of manager names by finding all wrestlers after a "(w/" marker.
        # The HTML pattern is: `) (w/ <a>Manager1</a> & <a>Manager2</a>)`
        # Or for unlinked managers: `(w/ Max Profit)` as plain text.
        # We walk all children of results_div; once we see "(w/" in a text node,
        # every subsequent wrestler link is a manager until we see a closing ")".
        manager_names: set[str] = set()
        in_manager_block = False
        for child in results_div.children:
            if isinstance(child, str):
                if re.search(r"\(w/", child):
                    in_manager_block = True
                    # Extract any unlinked manager names from this same text node.
                    # e.g. "(w/ Max Profit)" or "(w/ Max Profit &" or "& Name)"
                    # Extract only the text between "(w/" and the first ")" if present.
                    wm = re.search(r"\(w/\s*(.*?)(?:\)|$)", child)
                    if wm:
                        for part in re.split(r"\s*[&,]\s*", wm.group(1)):
                            mgr_name = part.strip()
                            if mgr_name and len(mgr_name) > 1 and not re.match(r"^[\d\s.,():]+$", mgr_name):
                                manager_names.add(mgr_name)
                elif in_manager_block:
                    # Text node inside a manager block — may contain unlinked names
                    # Stop at closing paren if present
                    text = re.sub(r"\).*", "", child).strip()
                    for part in re.split(r"\s*[&,]\s*", text):
                        mgr_name = part.strip()
                        if mgr_name and len(mgr_name) > 1 and not re.match(r"^[\d\s.,():]+$", mgr_name):
                            manager_names.add(mgr_name)
                # A closing paren after manager block ends it, but also
                # "vs." or start of a new side resets it
                if in_manager_block and re.search(r"\)\s*$", child):
                    in_manager_block = False
                if re.search(r"\bvs\.\s*$", child):
                    in_manager_block = False
            elif isinstance(child, Tag) and in_manager_block:
                link_href = child.get("href", "")
                if "id=2&" in link_href:
                    manager_names.add(child.get_text(strip=True))

        # Also extract plain-text team names (not linked) from patterns like
        # "TeamName (Wrestler, Wrestler & Wrestler)"
        for child in results_div.children:
            if isinstance(child, str):
                # Match text like "The Dream Team (" or "CHAOS(" at end of text node
                for team_match in re.finditer(r"([A-Z][\w\s'.-]+?)\s*\(\s*$", child.strip()):
                    team_name = team_match.group(1).strip()
                    if team_name and len(team_name) > 2:
                        side = self._determine_side(team_name, sides_text)
                        if side not in side_team_names:
                            side_team_names[side] = team_name
                        seen_names.add(team_name)

        # Collect all wrestler links (id=2), marking managers separately
        for link in results_div.find_all("a", href=re.compile(r"\?id=2&nr=\d+")):
            name = link.get_text(strip=True)
            if not name or name in seen_names:
                continue

            wrestler_id = _extract_id_from_href(link.get("href", ""))
            is_manager = name in manager_names

            # Determine side by checking which half of the result text contains this name
            side = self._determine_side(name, sides_text)

            participants.append(
                WrestlerRef(
                    name=name, cagematch_id=wrestler_id, is_linked=True,
                    side=side, team_name=side_team_names.get(side),
                    role="manager" if is_manager else "competitor",
                )
            )
            seen_names.add(name)

        # Add unlinked managers (plain text names in manager_names that aren't already added)
        for mgr_name in manager_names:
            if mgr_name not in seen_names:
                side = self._determine_side(mgr_name, sides_text)
                participants.append(WrestlerRef(
                    name=mgr_name, cagematch_id=None, is_linked=False,
                    side=side, team_name=side_team_names.get(side),
                    role="manager",
                ))
                seen_names.add(mgr_name)

        # Look for unlinked wrestler names in plain text nodes
        for child in results_div.children:
            if isinstance(child, str):
                text = child.strip()
                if not text:
                    continue
                for segment in re.split(r"\s*(?:vs\.|&|,|\band\b)\s*", text):
                    name = segment.strip()
                    name = re.sub(r"\(c\)", "", name).strip()
                    name = re.sub(r"\(w/.*?\)?", "", name).strip()
                    name = re.sub(r"\s*(defeat|defeats|draw|by|via)\s.*", "", name, flags=re.IGNORECASE).strip()
                    name = re.sub(r"^[:\s()]+|[:\s()]+$", "", name)

                    if (
                        name
                        and len(name) > 1
                        and name not in seen_names
                        and not re.match(r"^[\d\s.,():]+$", name)
                        and not re.match(r"^\(?(w/|c\))", name, re.IGNORECASE)
                    ):
                        side = self._determine_side(name, sides_text)
                        participants.append(WrestlerRef(
                            name=name, cagematch_id=None, is_linked=False,
                            side=side, team_name=side_team_names.get(side),
                        ))
                        seen_names.add(name)

        return participants

    async def scrape_event_comments(self, cagematch_event_id: int) -> list[EventComment]:
        """Scrape user comments/reviews for an event.

        Page=99 is the comments page. HTML structure:
        - div.Comment contains each review
        - div.CommentHeader has username (as <a> or text) and date
        - div.CommentContents has rating in <span class="Rating"> and review text
        """
        url = _build_url(1, nr=cagematch_event_id, page=99)
        html = await self._fetch_page(url, ttl=TTL_EVENT_DETAIL)
        soup = self._parse_html(html)

        comments: list[EventComment] = []

        for comment_div in soup.find_all("div", class_="Comment"):
            header = comment_div.find("div", class_="CommentHeader")
            contents = comment_div.find("div", class_="CommentContents")
            if not header or not contents:
                continue

            # Username: either a link or plain text
            username_link = header.find("a")
            username = username_link.get_text(strip=True) if username_link else ""
            if not username:
                # Fallback: first text in header before " wrote on"
                header_text = header.get_text(strip=True)
                if " wrote on " in header_text:
                    username = header_text.split(" wrote on ")[0].strip()

            # Date: "wrote on DD.MM.YYYY:"
            header_text = header.get_text(strip=True)
            comment_date = None
            date_match = re.search(r"(\d{2}\.\d{2}\.\d{4})", header_text)
            if date_match:
                comment_date = _parse_dd_mm_yyyy(date_match.group(1))

            # Rating: <span> with class containing "Rating"
            rating = None
            rating_span = contents.find("span", class_=re.compile(r"Rating"))
            if rating_span:
                rating = _parse_float(rating_span.get_text(strip=True))

            # Text: everything after the rating, typically in quotes
            text = ""
            content_text = contents.get_text(strip=True)
            # Remove the rating prefix like "[8.0] " or "8.0 "
            if rating_span:
                rating_text = rating_span.get_text(strip=True)
                idx = content_text.find(rating_text)
                if idx >= 0:
                    text = content_text[idx + len(rating_text):].strip()
            if not text:
                text = content_text
            # Clean up leading brackets/quotes and trailing quotes
            text = re.sub(r'^[\s\]\["\u201c]+|[\s"\u201d]+$', "", text)

            if username or text:
                comments.append(EventComment(
                    username=username,
                    date=comment_date,
                    rating=rating,
                    text=text,
                ))

        return comments

    async def _fetch_wikipedia_image(self, wrestler_name: str) -> str | None:
        """Fetch wrestler image from Wikipedia using the MediaWiki API.

        Strategy: exact title lookup first (most reliable), then
        title with "(professional wrestler)" disambiguation suffix,
        then a search query as last resort.
        """
        api_url = "https://en.wikipedia.org/w/api.php"
        headers = {
            "User-Agent": "Titantron/0.1 (wrestling video organizer; https://github.com/titantron)",
            "Accept": "application/json",
        }
        try:
            async with aiohttp.ClientSession() as session:
                # Try exact title, then with disambiguation suffix
                for title in [wrestler_name, f"{wrestler_name} (professional wrestler)"]:
                    params = {
                        "action": "query",
                        "titles": title,
                        "prop": "pageimages",
                        "pithumbsize": "400",
                        "format": "json",
                        "redirects": "1",
                    }
                    async with session.get(api_url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()
                        pages = data.get("query", {}).get("pages", {})
                        for page_data in pages.values():
                            if int(page_data.get("pageid", -1)) < 0:
                                continue
                            thumb = page_data.get("thumbnail", {})
                            if thumb.get("source"):
                                return thumb["source"]

                # Fallback: search
                params = {
                    "action": "query",
                    "generator": "search",
                    "gsrsearch": f"{wrestler_name} wrestler",
                    "gsrlimit": "1",
                    "prop": "pageimages",
                    "pithumbsize": "400",
                    "format": "json",
                }
                async with session.get(api_url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pages = data.get("query", {}).get("pages", {})
                        for page_data in pages.values():
                            thumb = page_data.get("thumbnail", {})
                            if thumb.get("source"):
                                return thumb["source"]
        except Exception:
            logger.debug(f"Wikipedia image lookup failed for {wrestler_name}")
        return None

    async def scrape_wrestler_profile(self, cagematch_wrestler_id: int) -> WrestlerProfile | None:
        """Scrape a wrestler's profile page for biographical data."""
        url = _build_url(2, nr=cagematch_wrestler_id)
        html = await self._fetch_page(url, ttl=TTL_WRESTLER)
        soup = self._parse_html(html)

        # Name from <h1>
        h1 = soup.find("h1")
        name = h1.get_text(strip=True) if h1 else None
        if not name:
            return None

        # "Also known as" aliases from <h2> immediately after <h1>
        alter_egos = None
        h2 = soup.find("h2")
        if h2:
            h2_text = h2.get_text(strip=True)
            if h2_text.startswith("Also known as"):
                alter_egos = h2_text.removeprefix("Also known as").strip()

        # Image from Wikipedia (Cagematch doesn't host images)
        image_url = await self._fetch_wikipedia_image(name)

        profile = WrestlerProfile(name=name, image_url=image_url, alter_egos=alter_egos)

        # Parse InformationBoxRow fields (same pattern as event detail)
        label_map = {
            "Birthday": "birth_date",
            "Birthplace": "birth_place",
            "Height": "height",
            "Weight": "weight",
            "Beginning of in-ring career": "debut",
            "Wrestling style": "style",
            "Roles": "roles",
            "Trainer": "trainers",
            "Nicknames": "nicknames",
            "Signature moves": "signature_moves",
            "Alter egos": "alter_egos",
        }

        for row in soup.find_all("div", class_="InformationBoxRow"):
            label_el = row.find("div", class_="InformationBoxTitle")
            value_el = row.find("div", class_="InformationBoxContents")
            if not label_el or not value_el:
                continue
            label = label_el.get_text(strip=True).rstrip(":")
            field = label_map.get(label)
            if not field:
                continue

            # Replace <br> with separator before extracting text so list values get proper formatting
            for br in value_el.find_all("br"):
                br.replace_with("\n")
            value = ", ".join(part.strip() for part in value_el.get_text().split("\n") if part.strip())
            if not value:
                continue

            if field == "birth_date":
                profile.birth_date = _parse_dd_mm_yyyy(value)
            elif field == "alter_egos" and profile.alter_egos:
                # Prefer the <h2> "Also known as" header — it's more comprehensive
                pass
            else:
                setattr(profile, field, value)

        # Rating is in a separate RatingsBox div, not in InformationBoxRow
        ratings_box = soup.find("div", class_="RatingsBox")
        if ratings_box:
            rating_el = ratings_box.find("div", class_="RatingsBoxAdjustedRating")
            if rating_el:
                try:
                    profile.rating = float(rating_el.get_text(strip=True))
                except ValueError:
                    pass
            # Votes in RatingsBoxText: "Valid votes: N"
            text_el = ratings_box.find("div", class_="RatingsBoxText")
            if text_el:
                import re
                match = re.search(r"Valid votes:\s*(\d+)", text_el.get_text())
                if match:
                    profile.votes = int(match.group(1))

        return profile

    @staticmethod
    def _determine_side(name: str, sides_text: list[str]) -> int:
        """Determine which side (1-indexed) a wrestler is on based on result text.

        Supports N-way matches (three-way, four-way gauntlet, etc.) by checking
        each chunk from the 'vs.' split.
        """
        if len(sides_text) < 2:
            return 1
        # Check which chunk contains this name (exact match first)
        for i, chunk in enumerate(sides_text):
            if name in chunk:
                return i + 1
        # Case-insensitive fallback
        name_lower = name.lower()
        for i, chunk in enumerate(sides_text):
            if name_lower in chunk.lower():
                return i + 1
        return 1  # default
