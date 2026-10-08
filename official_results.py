"""Official start/finish times scraped from SoaringSpot daily results pages."""

from __future__ import annotations

import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from download_helpers import (
    build_session_headers,
    discover_class_pages,
    extract_daily_links_from_class_html,
    extract_day_from_page,
    extract_day_from_url,
    sanitize,
)

_TIME_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")


def seconds_of_day(value: str | None) -> int | None:
    if not value or not _TIME_RE.match(value):
        return None
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def parse_daily_results(html: str) -> dict[str, dict[str, str | None]]:
    """Return {contest_id: {"start": "HH:MM:SS", "finish": "HH:MM:SS"|None}} in the page's local time."""
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not {"cn", "start", "finish"} <= set(headers):
            continue
        columns = {name: headers.index(name) for name in ("cn", "start", "finish")}
        pilots: dict[str, dict[str, str | None]] = {}
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) != len(headers):
                continue
            contest_id = cells[columns["cn"]].get_text(strip=True)
            start = cells[columns["start"]].get_text(strip=True)
            finish = cells[columns["finish"]].get_text(strip=True)
            if contest_id:
                pilots[contest_id] = {
                    "start": start if _TIME_RE.match(start) else None,
                    "finish": finish if _TIME_RE.match(finish) else None,
                }
        return pilots
    return {}


def contest_id_from_igc_path(path: str | Path) -> str:
    stem = Path(path).stem
    return stem.split("_", 1)[1] if "_" in stem else stem


def _get_html(session: requests.Session, url: str, attempts: int = 4) -> str:
    """Fetch a page slowly, backing off when SoaringSpot resets the connection."""
    for attempt in range(attempts):
        time.sleep(1.0)
        try:
            response = session.get(url, timeout=20)
            if response.status_code in {429, 500, 502, 503, 504}:
                raise requests.HTTPError(f"HTTP {response.status_code}")
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            if attempt == attempts - 1:
                raise
            time.sleep(5.0 * (2**attempt))
    raise RuntimeError("unreachable")


def fetch_contest_results(contest_url: str, session: requests.Session | None = None) -> list[dict]:
    """Fetch every daily results page of a contest.

    Returns dicts with the folder-style class name and day, the page URL, and the pilots' local times.
    """
    session = session or requests.Session()
    session.headers.update(build_session_headers(contest_url))
    base = re.match(r"https?://[^/]+", contest_url).group(0)

    contest_html = _get_html(session, contest_url)
    results: list[dict] = []
    for class_name, class_url in discover_class_pages(contest_html, contest_url, base, session):
        class_label = class_name or sanitize(class_url.rstrip("/").split("/")[-1])
        class_html = _get_html(session, class_url)
        for daily_url in extract_daily_links_from_class_html(class_html, base):
            daily_html = _get_html(session, daily_url)
            day = extract_day_from_url(daily_url) or extract_day_from_page(daily_html, daily_url)
            pilots = parse_daily_results(daily_html)
            if pilots:
                results.append(
                    {"class_name": sanitize(class_label), "day": sanitize(day), "url": daily_url, "pilots": pilots}
                )
    return results
