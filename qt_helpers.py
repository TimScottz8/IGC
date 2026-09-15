"""Utility helpers for the Qt desktop app.

These functions keep the app shell focused on UI behavior while the data-fetching
and formatting logic remains easy to test and reuse.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from PySide6.QtCore import Qt

from download_helpers import (
    DOWNLOAD_ACCEPT,
    DOWNLOAD_DIR,
    USER_AGENT,
    canonical_url,
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
from geo_task import format_human_readable_datetime


def create_session() -> requests.Session:
    """Return a configured requests session for SoaringSpot downloads."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def contest_name_from_url(contest_url: str) -> str:
    """Convert a SoaringSpot contest URL into a readable contest label."""
    parsed = urlparse(contest_url)
    path = parsed.path.strip("/")
    if not path:
        return "Contest"
    last = path.split("/")[-1]
    if last in {"contest", "results"}:
        return "Contest"
    return last.replace("-", " ").title()


def group_contest_download_plan(plan: list[dict[str, str]]) -> dict[str, dict[str, list[str]]]:
    """Cluster contest entries by class and day so the UI can render a collapsible tree."""
    grouped: dict[str, dict[str, list[str]]] = {}
    for item in sorted(plan, key=lambda entry: (
        str(entry.get("class_name") or ""),
        str(entry.get("day") or ""),
        str(entry.get("link") or ""),
    )):
        class_name = str(item.get("class_name") or "contest")
        day = str(item.get("day") or "all")
        grouped.setdefault(class_name, {}).setdefault(day, []).append(str(item.get("link") or ""))
    return grouped


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
        canonical_link = canonical_url(link)
        key = (class_name, day, canonical_link)
        if key in seen_links:
            return
        seen_links.add(key)
        plan.append({"class_name": class_name, "day": day, "link": canonical_link})

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
        formatted = format_human_readable_datetime(start_time)
        entries.append(f"{os.path.basename(file_path)} — {formatted}")
    return entries


def group_start_time_entries(flights: list[dict[str, str]]) -> dict[str, dict[str, list[dict[str, str]]]]:
    """Group start-time flight metadata by day and class for the viewer tree."""
    grouped: dict[str, dict[str, list[dict[str, str]]]] = {}
    for flight in flights:
        start_time = flight.get("start_time")
        if not start_time:
            continue
        file_path = str(flight.get("file_path") or flight.get("path") or "unknown.igc")
        day = str(flight.get("day") or flight.get("contest_day") or "Unsorted")
        class_name = str(flight.get("class_name") or "Flights")
        formatted = format_human_readable_datetime(start_time)
        grouped.setdefault(day, {}).setdefault(class_name, []).append(
            {"file_path": file_path, "label": f"{os.path.basename(file_path)} — {formatted}"}
        )
    return grouped


def dedupe_download_plan_entries(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    """Remove duplicate contest entries while preserving the first occurrence."""
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in entries:
        key = (
            str(entry.get("class_name") or ""),
            str(entry.get("day") or ""),
            str(entry.get("link") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def group_local_contest_paths(contest_paths: list[str]) -> dict[str, dict[str, dict[str, list[str]]]]:
    """Cluster downloaded contest paths by contest, class, and day for the local tree."""
    grouped: dict[str, dict[str, dict[str, list[str]]]] = {}
    for file_path in contest_paths:
        relative = os.path.relpath(file_path, start=DOWNLOAD_DIR)
        parts = relative.split(os.sep)
        if len(parts) < 3:
            contest_name = os.path.basename(os.path.dirname(file_path)) or "Contest"
            class_name = "Unsorted"
            day = "all"
        else:
            contest_name = parts[0]
            class_name = parts[1]
            day = parts[2]
        grouped.setdefault(contest_name, {}).setdefault(class_name, {}).setdefault(day, []).append(file_path)
    return grouped


def selected_download_plan_items(selected_items: list, contest_plan: list[dict[str, str]]) -> list[dict[str, str]]:
    """Resolve the current tree selection into the corresponding contest download entries."""
    if not selected_items:
        return list(contest_plan)

    targets: list[dict[str, str]] = []
    for item in selected_items:
        kind = item.data(0, Qt.ItemDataRole.UserRole)
        class_name = item.data(0, Qt.ItemDataRole.UserRole + 1) or ""
        day = item.data(0, Qt.ItemDataRole.UserRole + 2) or ""
        link = item.data(0, Qt.ItemDataRole.UserRole + 3) or ""

        if kind == "contest":
            targets.extend(contest_plan)
        elif kind == "class":
            targets.extend([
                entry for entry in contest_plan if str(entry.get("class_name") or "") == class_name
            ])
        elif kind == "day":
            targets.extend([
                entry for entry in contest_plan
                if str(entry.get("class_name") or "") == class_name and str(entry.get("day") or "") == day
            ])
        elif kind == "link":
            targets.extend([
                entry for entry in contest_plan
                if str(entry.get("class_name") or "") == class_name
                and str(entry.get("day") or "") == day
                and str(entry.get("link") or "") == link
            ])

    return dedupe_download_plan_entries(targets)


def selected_local_flight_paths(selected_items: list) -> list[str]:
    """Resolve the selected local tree items into their backing IGC file paths."""
    if not selected_items:
        return []

    targets: list[str] = []
    seen: set[str] = set()

    def is_descendant(node, ancestor) -> bool:
        parent = node.parent()
        while parent is not None:
            if parent is ancestor:
                return True
            parent = parent.parent()
        return False

    # Keep the most specific selected nodes. If both an ancestor and descendant
    # are selected, only the descendant should contribute paths.
    effective_items: list = []
    for item in selected_items:
        if any(other is not item and is_descendant(other, item) for other in selected_items):
            continue
        effective_items.append(item)

    def add_item_paths(item) -> None:
        file_path = item.data(0, Qt.ItemDataRole.UserRole + 4) or ""
        if file_path:
            if file_path not in seen:
                seen.add(file_path)
                targets.append(file_path)
            return
        for child_index in range(item.childCount()):
            add_item_paths(item.child(child_index))

    for item in effective_items:
        add_item_paths(item)
    return targets


def unique_file_paths(file_paths: list[str]) -> list[str]:
    """Canonicalize and deduplicate a list of IGC paths while preserving the caller-provided ordering."""
    unique_paths: list[str] = []
    seen: set[str] = set()
    for file_path in file_paths:
        normalized = os.path.abspath(file_path)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_paths.append(file_path)
    return unique_paths


def normalize_file_selection(file_paths: list[str]) -> list[str]:
    """Return a unique list of file paths using the same normalization rules throughout the UI."""
    return unique_file_paths(file_paths)


def infer_contest_class_day_from_path(file_path: str) -> dict[str, str]:
    """Infer contest/class/day labels from a downloaded IGC path when possible."""
    normalized = os.path.abspath(str(file_path or ""))
    if not normalized:
        return {"contest_name": "", "class_name": "Flights", "day": "Unsorted"}

    parts = normalized.split(os.sep)
    if "igc_downloads" in parts:
        root_index = parts.index("igc_downloads")
        if root_index + 3 < len(parts):
            return {
                "contest_name": parts[root_index + 1],
                "class_name": parts[root_index + 2],
                "day": parts[root_index + 3],
            }

    return {"contest_name": "", "class_name": "Flights", "day": "Unsorted"}


def selected_files_label(file_paths: list[str]) -> str:
    """Return the selected-file text shown in the viewer header for a file set."""
    if not file_paths:
        return "Selected files: 0"
    if len(file_paths) > 1:
        return f"Selected files: {len(file_paths)}"
    return f"Selected file: {file_paths[0]}"


def iter_downloaded_igc_paths(root_dir: str = DOWNLOAD_DIR) -> list[str]:
    """Return all downloaded IGC files under the configured download directory."""
    if not os.path.isdir(root_dir):
        return []

    paths: list[str] = []
    for root, _, files in os.walk(root_dir):
        for file_name in sorted(files):
            if file_name.lower().endswith(".igc"):
                paths.append(os.path.join(root, file_name))
    return sorted(paths)


def build_contest_tree_items(root_name: str, plan: list[dict[str, str]]) -> list:
    """Build a Qt-friendly contest tree structure grouped by class and day."""
    from PySide6.QtWidgets import QTreeWidgetItem
    from PySide6.QtCore import Qt

    contest_root = QTreeWidgetItem([root_name])
    contest_root.setData(0, Qt.ItemDataRole.UserRole, "contest")
    contest_root.setExpanded(True)

    grouped = group_contest_download_plan(plan)
    for class_name in sorted(grouped):
        class_item = QTreeWidgetItem([class_name])
        class_item.setData(0, Qt.ItemDataRole.UserRole, "class")
        class_item.setData(0, Qt.ItemDataRole.UserRole + 1, class_name)
        class_item.setExpanded(True)
        for day in sorted(grouped[class_name]):
            day_item = QTreeWidgetItem([day])
            day_item.setData(0, Qt.ItemDataRole.UserRole, "day")
            day_item.setData(0, Qt.ItemDataRole.UserRole + 1, class_name)
            day_item.setData(0, Qt.ItemDataRole.UserRole + 2, day)
            day_item.setExpanded(True)
            for link in grouped[class_name][day]:
                link_item = QTreeWidgetItem([link])
                link_item.setData(0, Qt.ItemDataRole.UserRole, "link")
                link_item.setData(0, Qt.ItemDataRole.UserRole + 1, class_name)
                link_item.setData(0, Qt.ItemDataRole.UserRole + 2, day)
                link_item.setData(0, Qt.ItemDataRole.UserRole + 3, link)
                day_item.addChild(link_item)
            class_item.addChild(day_item)
        contest_root.addChild(class_item)
    return [contest_root]


def build_local_contest_tree_items(contest_paths: list[str]) -> list:
    """Build a local contest tree grouped by contest, class, and day."""
    from PySide6.QtWidgets import QTreeWidgetItem
    from PySide6.QtCore import Qt

    grouped = group_local_contest_paths(contest_paths)
    root_items: list = []
    for contest_name in sorted(grouped):
        contest_item = QTreeWidgetItem([contest_name])
        contest_item.setData(0, Qt.ItemDataRole.UserRole, "local_contest")
        contest_item.setExpanded(True)
        for class_name in sorted(grouped[contest_name]):
            class_item = QTreeWidgetItem([class_name])
            class_item.setData(0, Qt.ItemDataRole.UserRole, "local_class")
            class_item.setExpanded(True)
            for day in sorted(grouped[contest_name][class_name]):
                day_item = QTreeWidgetItem([day])
                day_item.setData(0, Qt.ItemDataRole.UserRole, "local_day")
                day_item.setExpanded(True)
                for file_path in sorted(grouped[contest_name][class_name][day]):
                    file_name = os.path.basename(file_path)
                    file_item = QTreeWidgetItem([file_name])
                    file_item.setData(0, Qt.ItemDataRole.UserRole, "local_flight")
                    file_item.setData(0, Qt.ItemDataRole.UserRole + 4, file_path)
                    day_item.addChild(file_item)
                class_item.addChild(day_item)
            contest_item.addChild(class_item)
        root_items.append(contest_item)
    return root_items


from PySide6.QtCore import Qt


def selected_start_time_paths(selected_items: list) -> list[str]:
    """Resolve selected start-time tree entries into their backing IGC file paths."""
    if not selected_items:
        return []

    targets: list[str] = []
    seen: set[str] = set()

    def is_descendant(node, ancestor) -> bool:
        parent = node.parent()
        while parent is not None:
            if parent is ancestor:
                return True
            parent = parent.parent()
        return False

    # Keep only most specific selected nodes so selecting a day does not also
    # include an entire class/competition if those ancestor nodes are selected.
    effective_items: list = []
    for item in selected_items:
        if any(other is not item and is_descendant(other, item) for other in selected_items):
            continue
        effective_items.append(item)

    def add_item_paths(item) -> None:
        file_path = item.data(0, Qt.ItemDataRole.UserRole) or ""
        if file_path:
            if file_path not in seen:
                seen.add(file_path)
                targets.append(file_path)
            return
        for child_index in range(item.childCount()):
            add_item_paths(item.child(child_index))

    for item in effective_items:
        add_item_paths(item)
    return targets


def build_contest_result_lines(plan: list[dict[str, str]], limit: int = 50) -> list[str]:
    """Turn discovered contest links into a class/day grouped result block for the download tab."""
    ordered = sorted(plan, key=lambda item: (str(item.get("class_name") or ""), str(item.get("day") or ""), str(item.get("link") or "")))
    grouped = group_contest_download_plan(ordered[:limit])

    lines: list[str] = []
    for class_name, days in grouped.items():
        lines.append(f"[{class_name}]")
        for day, links in days.items():
            lines.append(f"  [{day}]")
            for link in links:
                lines.append(f"    - {link}")

    remaining = len(plan) - len(ordered)
    if remaining > 0:
        lines.append(f"... and {remaining} more links")
    return lines
