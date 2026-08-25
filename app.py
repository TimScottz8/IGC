import streamlit as st

from download_helpers import (
    DOWNLOAD_ACCEPT,
    DOWNLOAD_DIR,
    USER_AGENT,
    canonical_url,
    dedupe_contest_links,
    discover_class_pages,
    extract_daily_links_from_class_html,
    extract_day_from_page,
    extract_day_from_url,
    fetch_url_for_download,
    find_candidates,
    find_class_pages_from_contest,
    infer_class_pages_from_task_links,
    is_download_response_ok,
    list_downloaded_igc_files,
    save_stream,
    sanitize,
    status_label,
)
from download_ui import render_download_tab
from geo_task import (
    build_sector_points,
    extract_start_sector_from_igc,
    extract_task_points_from_igc,
    extract_task_sectors_from_igc,
    parse_igc_lat_lon,
    project_point_from_bearing,
)
from map_helpers import render_igc_map
from viewer_ui import render_viewer_tab

# Keep compatibility for direct imports into the original app module surface.
__all__ = [
    "DOWNLOAD_DIR",
    "USER_AGENT",
    "DOWNLOAD_ACCEPT",
    "sanitize",
    "list_downloaded_igc_files",
    "parse_igc_lat_lon",
    "extract_task_points_from_igc",
    "extract_start_sector_from_igc",
    "extract_task_sectors_from_igc",
    "project_point_from_bearing",
    "build_sector_points",
    "render_igc_map",
    "fetch_url_for_download",
    "is_download_response_ok",
    "status_label",
    "extract_daily_links_from_class_html",
    "dedupe_contest_links",
    "infer_class_pages_from_task_links",
    "discover_class_pages",
    "find_class_pages_from_contest",
    "find_candidates",
    "extract_day_from_url",
    "extract_day_from_page",
    "canonical_url",
    "save_stream",
    "render_download_tab",
    "render_viewer_tab",
]


def main() -> None:
    st.set_page_config(page_title="Soaring IGC Downloader", layout="wide")
    st.title("Soaring IGC Downloader")
    st.markdown("Paste a SoaringSpot page URL. Only explicit .igc and download endpoints will be fetched.")

    download_tab, viewer_tab = st.tabs(["Download", "Flight viewer"])
    with download_tab:
        render_download_tab()
    with viewer_tab:
        render_viewer_tab()


if __name__ == "__main__":
    main()
