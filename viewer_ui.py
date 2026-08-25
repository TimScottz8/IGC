import streamlit as st

from download_helpers import list_downloaded_igc_files
from map_helpers import GliderTrace, plot_traces_on_map, render_igc_map


def render_viewer_tab() -> None:
    available_igc_files = list_downloaded_igc_files()
    if not available_igc_files:
        return

    selection_mode = st.radio(
        "Open mode",
        ["Single file", "Multiple files"],
        horizontal=True,
        index=0,
    )

    if selection_mode == "Single file":
        file_path = st.selectbox(
            "Select a downloaded IGC file",
            options=available_igc_files,
            index=0,
            disabled=not available_igc_files,
        )

        if st.button("Open flight", key="open_igc_file"):
            render_igc_map(file_path)
        return

    selected_files = st.multiselect(
        "Select downloaded IGC files",
        options=available_igc_files,
        default=available_igc_files[:1],
    )

    if not selected_files:
        return

    st.caption(f"Selected files: {len(selected_files)}")
    if st.button("Open selected files", key="open_selected_igc"):
        traces = []
        for file_path in selected_files:
            trace = GliderTrace(file_path)
            if trace.flight is not None:
                traces.append(trace)
        if traces:
            plot_traces_on_map(traces)


__all__ = ["render_viewer_tab"]
