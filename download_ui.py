import os
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
import streamlit as st

from download_helpers import (
    DOWNLOAD_ACCEPT,
    DOWNLOAD_DIR,
    USER_AGENT,
    dedupe_contest_links,
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


@dataclass(frozen=True)
class DownloadResult:
    link: str
    status: str
    path: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch_url_with_check(session: requests.Session, url: str, timeout: int = 15):
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response


def download_single_candidate(
    session: requests.Session,
    source_url: str,
    link: str,
    destination_dir: str = DOWNLOAD_DIR,
) -> DownloadResult:
    fetch = fetch_url_for_download(link)
    headers = session.headers.copy()
    headers.update({"Referer": source_url, "Accept": DOWNLOAD_ACCEPT})
    try:
        response = session.get(fetch, timeout=30, stream=True, headers=headers)
        if is_download_response_ok(response, fetch):
            return DownloadResult(link=link, status="ok", path=save_stream(response, destination_dir))
        return DownloadResult(link=link, status=status_label(response), path=None)
    except Exception as exc:
        return DownloadResult(link=link, status=f"err {exc}", path=None)


def render_download_results(results: list[DownloadResult]) -> None:
    st.dataframe([{"link": result.link, "status": result.status, "path": result.path} for result in results])
    ok_count = sum(1 for result in results if result.ok)
    st.success(f"Downloaded {ok_count} files into {DOWNLOAD_DIR}")


def download_candidate_links(
    session: requests.Session,
    source_url: str,
    links: list[str],
    destination_dir: str = DOWNLOAD_DIR,
) -> list[DownloadResult]:
    results: list[DownloadResult] = []
    progress = st.progress(0)
    for index, link in enumerate(links, start=1):
        result = download_single_candidate(session, source_url, link, destination_dir)
        results.append(result)
        progress.progress(index / len(links) * 100)
    return results


def render_download_tab() -> None:
    url = st.text_input("SoaringSpot URL", "https://www.soaringspot.com/en_gb/...")
    contest_mode = st.checkbox("Download entire contest (classes & days)", key="contest_mode")
    download = st.button("Download IGCs")

    if contest_mode:
        if not url or "soaringspot.com" not in url:
            st.info("Enter a valid SoaringSpot contest URL to discover classes.")
            return

        session = make_session()
        try:
            response = fetch_url_with_check(session, url)
        except Exception as exc:
            st.error(f"Fetch failed: {exc}")
            return

        base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        st.info("Discovering classes...")
        contest_name = sanitize(urlparse(url).path.split("/")[-2] if "/" in urlparse(url).path else "contest")
        html_classes: dict[str, str] = {}
        class_names: list[str] = []

        for name, page_url in discover_class_pages(response.text, url, base, session):
            class_names.append(name)
            html_classes[name] = page_url

        class_names = sorted(set(class_names))
        if not class_names:
            st.info("No classes found on contest page.")
            return

        st.write("Discovered classes:")
        st.write(class_names)
        with st.form(key="contest_class_form"):
            selected = st.multiselect(
                "Select classes to download",
                options=class_names,
                default=class_names,
                key="contest_selected_classes",
            )
            submitted = st.form_submit_button("Download selected classes")

        if not submitted or not selected:
            return

        all_links: list[tuple[str, str, str, str]] = []
        for name in selected:
            class_url = html_classes.get(name)
            if not class_url:
                continue
            st.write(f"### Fetching class: `{name}`")
            st.write(f"URL: `{class_url}`")
            try:
                class_response = fetch_url_with_check(session, class_url, timeout=12)
                found_daily = extract_daily_links_from_class_html(class_response.text, base)
                st.info(f"Found **{len(found_daily)}** daily page links for {name}")
                for daily_link in found_daily[:3]:
                    st.write(f"  - {daily_link[-80:]}")
                if len(found_daily) > 3:
                    st.write(f"  ... and {len(found_daily) - 3} more")

                if found_daily:
                    for daily_link in found_daily:
                        try:
                            daily_response = fetch_url_with_check(session, daily_link, timeout=12)
                            day = (
                                extract_day_from_url(daily_link)
                                or extract_day_from_page(daily_response.text, daily_link)
                                or sanitize(daily_link.rstrip("/").split("/")[-1])
                            )
                            for link in find_candidates(daily_response.text, base):
                                all_links.append((link, contest_name, name, day))
                        except Exception:
                            continue
                else:
                    page_day = extract_day_from_url(class_url) or extract_day_from_page(class_response.text, class_url) or "all"
                    for link in find_candidates(class_response.text, base):
                        all_links.append((link, contest_name, name, page_day))
            except Exception:
                continue

        final_links = dedupe_contest_links(all_links)
        by_day: dict[str, int] = {}
        for _link, _contest_name, _class_name, day in final_links:
            by_day[str(day)] = by_day.get(str(day), 0) + 1

        st.info(f"**Found {len(final_links)} unique links across {len(by_day)} days:**")
        for day in sorted(by_day):
            st.write(f"  • {day}: {by_day[day]} files")
        st.write("---")

        st.info(f"Downloading {len(final_links)} files across {len(by_day)} unique days...")
        rows: list[DownloadResult] = []
        for index, (link, c_name, cls_name, day) in enumerate(final_links, start=1):
            st.write(f"**{index}/{len(final_links)}** Day: `{day}` | Link: {link[-50:]}")
            out_dir = os.path.join(DOWNLOAD_DIR, sanitize(c_name), sanitize(cls_name), sanitize(str(day)))
            result = download_single_candidate(session, url, link, out_dir)
            rows.append(result)
            if result.ok:
                st.success(f"✓ Saved to {out_dir}")
            elif result.status.startswith("err"):
                st.error(f"✗ Error: {str(result.status)[4:84]}")
            else:
                st.warning(f"✗ Skipped: {result.status[:80]}")

        st.dataframe([{"link": result.link, "status": result.status, "path": result.path} for result in rows])
        st.success(f'Downloaded {sum(1 for result in rows if result.ok)} files into {DOWNLOAD_DIR}')
        return

    if download and not contest_mode:
        if not url or "soaringspot.com" not in url:
            st.error("Enter a valid SoaringSpot URL")
            st.stop()

        session = make_session()
        try:
            response = fetch_url_with_check(session, url)
        except Exception as exc:
            st.error(f"Fetch failed: {exc}")
            st.stop()

        candidates = find_candidates(response.text, f"{urlparse(url).scheme}://{urlparse(url).netloc}")
        if not candidates:
            st.info("No direct .igc or download links found.")
            return

        st.info(f"Found {len(candidates)} candidate link(s).")
        results = download_candidate_links(session, url, candidates, DOWNLOAD_DIR)
        render_download_results(results)


__all__ = [
    "DownloadResult",
    "make_session",
    "fetch_url_with_check",
    "download_single_candidate",
    "render_download_results",
    "download_candidate_links",
    "render_download_tab",
]
