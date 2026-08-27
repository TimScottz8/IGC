"""Utility helpers for the Qt desktop app.

These functions keep the app shell focused on UI behavior while the data-fetching
and formatting logic remains easy to test and reuse.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from download_helpers import (
    DOWNLOAD_ACCEPT,
    DOWNLOAD_DIR,
    USER_AGENT,
    discover_class_pages,
    extract_daily_links_from_class_html,
    extract_day_from_page,
    extract_day_from_url,
    fetch_url_for_download,
    find_candidates,
    is_download_response_ok,
    save_stream,
    sanitize,
    status_label,
)


def create_session() -> requests.Session:
    """Return a configured requests session for SoaringSpot downloads."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def build_contest_download_plan(
    contest_url: str,
    contest_html: str,
    base: str,
    session: requests.Session | None = None,
) -> list[dict[str, str]]:
    """Flatten discovered contest classes and days into direct IGC download candidates."""
    session = session or create_session()
    base_url = base or f"{urlparse(contest_url).scheme}://{urlparse(contest_url).netloc}"
    discovered = discover_class_pages(contest_html, contest_url, base_url, session)
    plan: list[dict[str, str]] = []
    seen_links: set[tuple[str, str, str]] = set()

    def record(class_name: str, day: str, link: str) -> None:
        if not link:
            return
        key = (class_name, day, link)
        if key in seen_links:
            return
        seen_links.add(key)
        plan.append({"class_name": class_name, "day": day, "link": link})

    soup = BeautifulSoup(contest_html, "html.parser")
    anchor_hrefs: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "").strip()
        if href:
            normalized = href if href.startswith("http") else f"{base_url}{href}" if href.startswith("/") else href
            anchor_hrefs.append(normalized)

    if discovered:
        for class_name, class_url in discovered:
            class_label = class_name or sanitize(class_url.rstrip("/").split("/")[-1])
            class_day_hint = extract_day_from_url(class_url) or "all"
            if class_day_hint == "all":
                matching_days = []
                class_prefix = class_url.rstrip("/").lower()
                for href in anchor_hrefs:
                    href_lower = href.lower()
                    if class_prefix in href_lower:
                        day = extract_day_from_url(href) or extract_day_from_page(contest_html, href)
                        if day and day != "day":
                            matching_days.append(day)
                if matching_days:
                    class_day_hint = matching_days[0]

            try:
                class_response = session.get(class_url, timeout=15)
                class_response.raise_for_status()
            except Exception:
                for link in find_candidates(contest_html, base_url):
                    record(class_label, str(class_day_hint), link)
                continue

            daily_links = extract_daily_links_from_class_html(class_response.text, base_url)
            if daily_links:
                for daily_link in daily_links:
                    day = extract_day_from_url(daily_link) or extract_day_from_page(class_response.text, daily_link) or class_day_hint
                    try:
                        daily_response = session.get(daily_link, timeout=15)
                        daily_response.raise_for_status()
                    except Exception:
                        continue
                    for link in find_candidates(daily_response.text, base_url):
                        record(class_label, str(day), link)
                continue

            page_day = extract_day_from_url(class_url) or extract_day_from_page(class_response.text, class_url) or class_day_hint
            for link in find_candidates(class_response.text, base_url):
                record(class_label, str(page_day), link)

    if not plan:
        for link in find_candidates(contest_html, base_url):
            contest_day = extract_day_from_url(contest_url) or extract_day_from_page(contest_html, contest_url) or "all"
            record("contest", str(contest_day), link)

    return plan


def download_single_candidate(
    session: requests.Session,
    source_url: str,
    link: str,
    destination_dir: str = DOWNLOAD_DIR,
) -> dict[str, str | None]:
    """Download one candidate URL and return a structured result for the UI."""
    fetch = fetch_url_for_download(link)
    headers = session.headers.copy()
    headers.update({"Referer": source_url, "Accept": DOWNLOAD_ACCEPT})
    try:
        response = session.get(fetch, timeout=30, stream=True, headers=headers)
        if is_download_response_ok(response, fetch):
            path = save_stream(response, destination_dir)
            return {"link": link, "status": "ok", "path": path}
        return {"link": link, "status": status_label(response), "path": None}
    except Exception as exc:
        return {"link": link, "status": f"err {exc}", "path": None}


def build_start_time_entries(flights: list[dict[str, str]]) -> list[str]:
    """Convert raw flight metadata into user-friendly start-time rows for the viewer list."""
    entries: list[str] = []
    for item in flights:
        file_path = str(item.get("file_path") or item.get("path") or "unknown.igc")
        start_time = item.get("start_time")
        if not start_time:
            continue
        entries.append(f"{os.path.basename(file_path)} — {start_time}")
    return entries


def build_contest_result_lines(plan: list[dict[str, str]], limit: int = 50) -> list[str]:
    """Turn discovered contest links into a compact result block for the download tab."""
    lines = [f"{item['class_name']} | {item['day']} | {item['link']}" for item in plan[:limit]]
    if len(plan) > limit:
        lines.append(f"... and {len(plan) - limit} more links")
    return lines
