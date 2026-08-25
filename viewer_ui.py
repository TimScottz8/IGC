import streamlit as st

from download_helpers import list_downloaded_igc_files
from map_helpers import render_igc_map


def render_viewer_tab() -> None:
    available_igc_files = list_downloaded_igc_files()
    if not available_igc_files:
        return

    file_path = st.selectbox(
        "Select a downloaded IGC file",
        options=available_igc_files,
        index=0,
        disabled=not available_igc_files,
    )

    if st.button("Open flight", key="open_igc_file"):
        render_igc_map(file_path)


__all__ = ["render_viewer_tab"]
