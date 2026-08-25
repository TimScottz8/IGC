import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import libigc

from geo_task import (
    build_sector_split_points,
    extract_finish_sector_from_igc,
    extract_glider_start_time,
    extract_start_sector_from_igc,
    extract_task_points_from_igc,
    extract_task_sectors_from_igc,
    format_human_readable_datetime,
    is_point_in_sector,
)


def render_igc_map(file_path: str):
    try:
        flight = libigc.Flight.create_from_file(file_path)
    except Exception as exc:
        st.error(f"Could not parse IGC file: {exc}")
        return

    if not flight.valid:
        st.error("This file was parsed but marked invalid by the IGC library.")
        if flight.notes:
            st.write(flight.notes[:5])
        return

    fix_rows = [{"lat": fix.lat, "lon": fix.lon, "timestamp": fix.timestamp} for fix in flight.fixes]
    trace_df = pd.DataFrame(fix_rows)
    task_df = pd.DataFrame(extract_task_points_from_igc(file_path))
    all_sectors = extract_task_sectors_from_igc(file_path)
    start_sector = extract_start_sector_from_igc(file_path)
    finish_sector = extract_finish_sector_from_igc(file_path)

    if trace_df.empty:
        st.warning("No valid flight fixes were found in the selected file.")
        return

    lat_center = float(trace_df["lat"].mean())
    lon_center = float(trace_df["lon"].mean())

    turnpoint_sectors = [
        sector
        for sector in all_sectors
        if sector.get("idx") not in {start_sector.get("idx") if start_sector else None, finish_sector.get("idx") if finish_sector else None}
        and sector.get("idx") is not None
    ]
    first_turnpoint_sector = min(turnpoint_sectors, key=lambda sector: int(sector.get("idx", 10**9))) if turnpoint_sectors else None
    start_time = extract_glider_start_time(flight.fixes, start_sector, first_turnpoint_sector)
    st.text_input(
        "Glider start time",
        value=format_human_readable_datetime(start_time),
        key="glider_start_time",
        disabled=True,
    )

    fig = go.Figure()
    if not trace_df.empty:
        fig.add_trace(
            go.Scattermapbox(
                lat=trace_df["lat"],
                lon=trace_df["lon"],
                mode="lines",
                line={"color": "#000000", "width": 2},
                name="Glider track",
                hoverinfo="skip",
            )
        )
    if not task_df.empty:
        fig.add_trace(
            go.Scattermapbox(
                lat=task_df["lat"],
                lon=task_df["lon"],
                mode="lines",
                line={"color": "#d62728", "width": 2},
                name="Task route",
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scattermapbox(
                lat=task_df["lat"],
                lon=task_df["lon"],
                mode="markers+text",
                text=task_df["name"],
                textposition="top center",
                marker={"color": "#d62728", "size": 12},
                name="Task",
                hovertemplate="%{text}<extra></extra>",
            )
        )

    def add_sector_overlay(sector, label, arc_color):
        if not sector:
            return
        orientation = sector.get("orientation_deg") or 0.0
        result = build_sector_split_points(
            sector["lat"],
            sector["lon"],
            sector["radius_m"],
            orientation,
            sector.get("a1_deg", 0.0),
            inner_radius_m=sector.get("inner_radius_m", 0.0),
            inner_half_angle_deg=sector.get("a2_deg", 0.0),
        )
        if len(result) == 2:
            clockwise_points, anticlockwise_points = result
            inner_clockwise_points = inner_anticlockwise_points = None
        else:
            clockwise_points, anticlockwise_points, inner_clockwise_points, inner_anticlockwise_points = result

        def draw_arc(points, name_suffix):
            fig.add_trace(
                go.Scattermapbox(
                    lat=[p[0] for p in points],
                    lon=[p[1] for p in points],
                    mode="lines",
                    line={"color": arc_color, "width": 2},
                    name=f"{label} {name_suffix}",
                    hoverinfo="skip",
                )
            )

        if clockwise_points:
            radial_clockwise = [
                (sector["lat"], sector["lon"]),
                clockwise_points[-1],
            ]
            fig.add_trace(
                go.Scattermapbox(
                    lat=[p[0] for p in radial_clockwise],
                    lon=[p[1] for p in radial_clockwise],
                    mode="lines",
                    line={"color": arc_color, "width": 2},
                    name=f"{label} clockwise radial",
                    hoverinfo="skip",
                )
            )
            draw_arc(clockwise_points, "clockwise")

        if anticlockwise_points:
            radial_anticlockwise = [
                (sector["lat"], sector["lon"]),
                anticlockwise_points[-1],
            ]
            fig.add_trace(
                go.Scattermapbox(
                    lat=[p[0] for p in radial_anticlockwise],
                    lon=[p[1] for p in radial_anticlockwise],
                    mode="lines",
                    line={"color": arc_color, "width": 2},
                    name=f"{label} anticlockwise radial",
                    hoverinfo="skip",
                )
            )
            draw_arc(anticlockwise_points, "anticlockwise")

        if inner_clockwise_points is not None:
            draw_arc(inner_clockwise_points, "inner clockwise")
        if inner_anticlockwise_points is not None:
            draw_arc(inner_anticlockwise_points, "inner anticlockwise")
 
        if inner_clockwise_points is not None and inner_anticlockwise_points is not None:
            fig.add_trace(
                go.Scattermapbox(
                    lat=[sector["lat"], inner_clockwise_points[0][0], inner_anticlockwise_points[0][0]],
                    lon=[sector["lon"], inner_clockwise_points[0][1], inner_anticlockwise_points[0][1]],
                    mode="lines",
                    line={"color": arc_color, "width": 2},
                    name=f"{label} inner join",
                    hoverinfo="skip",
                )
            )

    start_idx = start_sector.get("idx") if start_sector else None
    finish_idx = finish_sector.get("idx") if finish_sector else None
    turnpoint_sectors = [
        sector
        for sector in all_sectors
        if sector.get("idx") not in {start_idx, finish_idx} and sector.get("idx") is not None
    ]
    sector_candidates = [sector for sector in [start_sector, finish_sector, *turnpoint_sectors] if sector]

    if start_sector:
        add_sector_overlay(start_sector, "Start sector", "#2ca02c")
    if finish_sector and finish_idx != start_idx:
        add_sector_overlay(finish_sector, "Finish sector", "#ff7f0e")

    for sector in turnpoint_sectors:
        add_sector_overlay(sector, "Turnpoint sector", "#1f77b4")

    sector_fix_mask = trace_df.apply(
        lambda row: any(
            is_point_in_sector(float(row["lat"]), float(row["lon"]), sector)
            for sector in sector_candidates
        ),
        axis=1,
    )

    if sector_fix_mask.any():
        current_segment = []
        current_in_sector = None
        for idx, in_sector in sector_fix_mask.items():
            if current_in_sector is None:
                current_in_sector = bool(in_sector)
            if bool(in_sector) == current_in_sector:
                current_segment.append((float(trace_df.loc[idx, "lat"]), float(trace_df.loc[idx, "lon"])))
            else:
                if current_in_sector:
                    fig.add_trace(
                        go.Scattermapbox(
                            lat=[point[0] for point in current_segment],
                            lon=[point[1] for point in current_segment],
                            mode="lines",
                            line={"color": "#f1c40f", "width": 2},
                            name="Fixes in task sector",
                            hoverinfo="skip",
                        )
                    )
                current_segment = [(float(trace_df.loc[idx, "lat"]), float(trace_df.loc[idx, "lon"]))]
                current_in_sector = bool(in_sector)

        if current_segment and current_in_sector:
            fig.add_trace(
                go.Scattermapbox(
                    lat=[point[0] for point in current_segment],
                    lon=[point[1] for point in current_segment],
                    mode="lines",
                    line={"color": "#f1c40f", "width": 2},
                    name="Fixes in task sector",
                    hoverinfo="skip",
                )
            )

    fig.update_layout(
        mapbox={
            "style": "carto-positron",
            "center": {"lat": lat_center, "lon": lon_center},
            "zoom": 7,
        },
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        legend={"x": 0.01, "y": 0.99, "xanchor": "left", "yanchor": "top"},
    )

    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Flight fixes: {len(trace_df)} | Task points: {len(task_df)}")

    if flight.notes:
        with st.expander("Flight parsing notes"):
            st.write(flight.notes[:10])
