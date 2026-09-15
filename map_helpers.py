import warnings

import libigc
import pandas as pd
import plotly.graph_objects as go


class _UiCompat:
    @staticmethod
    def warning(*args, **kwargs):
        warnings.warn(str(args[0]) if args else "warning")

    @staticmethod
    def error(*args, **kwargs):
        warnings.warn(str(args[0]) if args else "error")

    @staticmethod
    def text_input(*args, **kwargs):
        return kwargs.get("value", "")

    @staticmethod
    def plotly_chart(*args, **kwargs):
        return None

    @staticmethod
    def caption(*args, **kwargs):
        return None

    @staticmethod
    def write(*args, **kwargs):
        return None

    @staticmethod
    def expander(*args, **kwargs):
        class _Expander:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        return _Expander()


ui = _UiCompat()

MAP_TRACE = getattr(go, "Scattermapbox", go.Scattermap)
MAP_LAYOUT_KEY = "mapbox" if hasattr(go, "Scattermapbox") else "map"

from geo_task import (
    build_sector_split_points,
    extract_finish_sector_from_igc,
    extract_glider_start_time,
    extract_start_sector_from_igc,
    extract_task_points_from_igc,
    extract_task_sectors_from_igc,
    format_human_readable_datetime,
    is_point_in_sector,
    segment_crosses_sector,
)


class GliderTrace:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.flight = None
        self.trace_df = pd.DataFrame()
        self.task_points = []
        self.task_df = pd.DataFrame()
        self.sectors = []
        self.all_sectors = []
        self.start_sector = None
        self.finish_sector = None
        self.start_time = None
        self.lat_center = 0.0
        self.lon_center = 0.0
        self.sector_candidates = []
        self.sector_fix_mask = pd.Series([], dtype=bool)
        self._load()

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def _load(self):
        try:
            self.flight = libigc.Flight.create_from_file(self.file_path)
        except Exception as exc:
            ui.error(f"Could not parse IGC file: {exc}")
            self.flight = None
            return

        if not self.flight.valid:
            ui.error("This file was parsed but marked invalid by the IGC library.")
            if self.flight.notes:
                ui.write(self.flight.notes[:5])
            self.flight = None
            return

        fix_rows = [{"lat": fix.lat, "lon": fix.lon, "timestamp": fix.timestamp} for fix in self.flight.fixes]
        self.trace_df = pd.DataFrame(fix_rows)
        self.task_points = extract_task_points_from_igc(self.file_path)
        self.task_df = pd.DataFrame(self.task_points)
        self.sectors = extract_task_sectors_from_igc(self.file_path)
        self.all_sectors = self.sectors
        self.start_sector = extract_start_sector_from_igc(self.file_path)
        self.finish_sector = extract_finish_sector_from_igc(self.file_path)

        if self.trace_df.empty:
            ui.warning("No valid flight fixes were found in the selected file.")
            return

        self.lat_center = float(self.trace_df["lat"].mean())
        self.lon_center = float(self.trace_df["lon"].mean())

        turnpoint_sectors = [
            sector
            for sector in self.sectors
            if sector.get("idx") not in {
                self.start_sector.get("idx") if self.start_sector else None,
                self.finish_sector.get("idx") if self.finish_sector else None,
            }
            and sector.get("idx") is not None
        ]
        first_turnpoint_sector = min(turnpoint_sectors, key=lambda sector: int(sector.get("idx", 10**9))) if turnpoint_sectors else None
        self.start_time = extract_glider_start_time(self.flight.fixes, self.start_sector, first_turnpoint_sector)

        self._compute_zone_fix_mask()

    def _compute_zone_fix_mask(self):
        if self.trace_df.empty:
            self.sector_fix_mask = pd.Series([], dtype=bool)
            return

        start_idx = self.start_sector.get("idx") if self.start_sector else None
        finish_idx = self.finish_sector.get("idx") if self.finish_sector else None
        turnpoint_sectors = [
            sector
            for sector in self.sectors
            if sector.get("idx") not in {start_idx, finish_idx} and sector.get("idx") is not None
        ]
        self.sector_candidates = [sector for sector in [self.start_sector, self.finish_sector, *turnpoint_sectors] if sector]
        self.sector_fix_mask = pd.Series(False, index=self.trace_df.index)

        for idx in range(len(self.trace_df)):
            row = self.trace_df.iloc[idx]
            if any(is_point_in_sector(float(row["lat"]), float(row["lon"]), sector) for sector in self.sector_candidates):
                self.sector_fix_mask.iloc[idx] = True
                if idx > 0:
                    self.sector_fix_mask.iloc[idx - 1] = True
                continue

            if idx == 0:
                continue

            prev_row = self.trace_df.iloc[idx - 1]
            if any(
                segment_crosses_sector(
                    float(prev_row["lat"]),
                    float(prev_row["lon"]),
                    float(row["lat"]),
                    float(row["lon"]),
                    sector,
                )
                for sector in self.sector_candidates
            ):
                self.sector_fix_mask.iloc[idx] = True
                self.sector_fix_mask.iloc[idx - 1] = True

    def get_start_time(self):
        return self.start_time

    def get_task_points(self):
        return self.task_points

    def get_sectors(self):
        return self.sectors

    def get_zone_fix_mask(self):
        return self.sector_fix_mask

    def get_task_route(self):
        return self.task_df

    def fixes_in_zone(self):
        return self.sector_fix_mask.tolist()


def _build_trace(file_path: str):
    return GliderTrace(file_path)


def plot_traces_on_map(traces):
    if not traces:
        ui.warning("No traces to plot.")
        return

    fig = go.Figure()
    palette = [
        "#000000",
        "#d62728",
        "#2ca02c",
        "#ff7f0e",
        "#1f77b4",
        "#9467bd",
        "#8c564b",
    ]

    lat_values = []
    lon_values = []
    for index, trace in enumerate(traces):
        trace_df = trace.trace_df if hasattr(trace, "trace_df") else trace["trace_df"]
        task_df = trace.task_df if hasattr(trace, "task_df") else trace["task_df"]
        if trace_df.empty:
            continue

        color = palette[index % len(palette)]
        lat_values.extend(trace_df["lat"].tolist())
        lon_values.extend(trace_df["lon"].tolist())

        fig.add_trace(
            MAP_TRACE(
                lat=trace_df["lat"],
                lon=trace_df["lon"],
                mode="lines",
                line={"color": color, "width": 2},
                name=f"Flight {index + 1}",
                hoverinfo="skip",
            )
        )

        if not task_df.empty:
            fig.add_trace(
                MAP_TRACE(
                    lat=task_df["lat"],
                    lon=task_df["lon"],
                    mode="lines",
                    line={"color": color, "width": 2},
                    name=f"Task route {index + 1}",
                    hoverinfo="skip",
                )
            )
            fig.add_trace(
                MAP_TRACE(
                    lat=task_df["lat"],
                    lon=task_df["lon"],
                    mode="markers+text",
                    text=task_df["name"],
                    textposition="top center",
                    marker={"color": color, "size": 12},
                    name=f"Task {index + 1}",
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
                    MAP_TRACE(
                        lat=[p[0] for p in points],
                        lon=[p[1] for p in points],
                        mode="lines",
                        line={"color": arc_color, "width": 2},
                        name=f"{label} {name_suffix}",
                        hoverinfo="skip",
                    )
                )

            if clockwise_points:
                radial_clockwise = [(sector["lat"], sector["lon"]), clockwise_points[-1]]
                fig.add_trace(
                    MAP_TRACE(
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
                radial_anticlockwise = [(sector["lat"], sector["lon"]), anticlockwise_points[-1]]
                fig.add_trace(
                    MAP_TRACE(
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
                    MAP_TRACE(
                        lat=[sector["lat"], inner_clockwise_points[0][0], inner_anticlockwise_points[0][0]],
                        lon=[sector["lon"], inner_clockwise_points[0][1], inner_anticlockwise_points[0][1]],
                        mode="lines",
                        line={"color": arc_color, "width": 2},
                        name=f"{label} inner join",
                        hoverinfo="skip",
                    )
                )

        all_sectors = getattr(trace, "all_sectors", None)
        if all_sectors is None:
            all_sectors = getattr(trace, "sectors", [])

        start_sector = getattr(trace, "start_sector", None)
        finish_sector = getattr(trace, "finish_sector", None)
        start_idx = start_sector.get("idx") if start_sector else None
        finish_idx = finish_sector.get("idx") if finish_sector else None
        turnpoint_sectors = [
            sector
            for sector in all_sectors
            if sector.get("idx") not in {start_idx, finish_idx} and sector.get("idx") is not None
        ]

        if start_sector:
            add_sector_overlay(start_sector, f"Start sector {index + 1}", color)
        if finish_sector and finish_idx != start_idx:
            add_sector_overlay(finish_sector, f"Finish sector {index + 1}", color)
        for sector in turnpoint_sectors:
            add_sector_overlay(sector, f"Turnpoint sector {index + 1}", color)

        if trace.get_zone_fix_mask().any():
            current_segment = []
            current_in_sector = None
            for idx, in_sector in trace.get_zone_fix_mask().items():
                if current_in_sector is None:
                    current_in_sector = bool(in_sector)
                if bool(in_sector) == current_in_sector:
                    current_segment.append((float(trace.trace_df.loc[idx, "lat"]), float(trace.trace_df.loc[idx, "lon"])))
                else:
                    if current_in_sector:
                        fig.add_trace(
                            MAP_TRACE(
                                lat=[point[0] for point in current_segment],
                                lon=[point[1] for point in current_segment],
                                mode="lines",
                                line={"color": "#f1c40f", "width": 2},
                                name=f"Zone fixes {index + 1}",
                                hoverinfo="skip",
                            )
                        )
                    current_segment = [(float(trace.trace_df.loc[idx, "lat"]), float(trace.trace_df.loc[idx, "lon"]))]
                    current_in_sector = bool(in_sector)

            if current_segment and current_in_sector:
                fig.add_trace(
                    MAP_TRACE(
                        lat=[point[0] for point in current_segment],
                        lon=[point[1] for point in current_segment],
                        mode="lines",
                        line={"color": "#f1c40f", "width": 2},
                        name=f"Zone fixes {index + 1}",
                        hoverinfo="skip",
                    )
                )

    if not lat_values or not lon_values:
        ui.warning("No valid trace data available to plot.")
        return

    layout_args = {
        MAP_LAYOUT_KEY: {
            "style": "carto-positron",
            "center": {"lat": sum(lat_values) / len(lat_values), "lon": sum(lon_values) / len(lon_values)},
            "zoom": 7,
        },
        "margin": {"l": 0, "r": 0, "t": 0, "b": 0},
        "legend": {"x": 0.01, "y": 0.99, "xanchor": "left", "yanchor": "top"},
    }
    fig.update_layout(**layout_args)
    ui.plotly_chart(fig, use_container_width=True)


def render_igc_map(file_path: str):
    trace = _build_trace(file_path)
    if trace is None or trace.flight is None:
        return None

    ui.text_input(
        "Glider start time",
        value=format_human_readable_datetime(trace.get_start_time()),
        key="glider_start_time",
        disabled=True,
    )

    fig = go.Figure()
    fig.add_trace(
        MAP_TRACE(
            lat=trace.trace_df["lat"],
            lon=trace.trace_df["lon"],
            mode="lines",
            line={"color": "#000000", "width": 2},
            name="Glider track",
            hoverinfo="skip",
        )
    )

    if not trace.task_df.empty:
        fig.add_trace(
            MAP_TRACE(
                lat=trace.task_df["lat"],
                lon=trace.task_df["lon"],
                mode="lines",
                line={"color": "#d62728", "width": 2},
                name="Task route",
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            MAP_TRACE(
                lat=trace.task_df["lat"],
                lon=trace.task_df["lon"],
                mode="markers+text",
                text=trace.task_df["name"],
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
                MAP_TRACE(
                    lat=[p[0] for p in points],
                    lon=[p[1] for p in points],
                    mode="lines",
                    line={"color": arc_color, "width": 2},
                    name=f"{label} {name_suffix}",
                    hoverinfo="skip",
                )
            )

        if clockwise_points:
            radial_clockwise = [(sector["lat"], sector["lon"]), clockwise_points[-1]]
            fig.add_trace(
                MAP_TRACE(
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
            radial_anticlockwise = [(sector["lat"], sector["lon"]), anticlockwise_points[-1]]
            fig.add_trace(
                MAP_TRACE(
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
                MAP_TRACE(
                    lat=[sector["lat"], inner_clockwise_points[0][0], inner_anticlockwise_points[0][0]],
                    lon=[sector["lon"], inner_clockwise_points[0][1], inner_anticlockwise_points[0][1]],
                    mode="lines",
                    line={"color": arc_color, "width": 2},
                    name=f"{label} inner join",
                    hoverinfo="skip",
                )
            )

    start_sector = trace.start_sector
    finish_sector = trace.finish_sector
    all_sectors = trace.all_sectors
    start_idx = start_sector.get("idx") if start_sector else None
    finish_idx = finish_sector.get("idx") if finish_sector else None
    turnpoint_sectors = [
        sector
        for sector in all_sectors
        if sector.get("idx") not in {start_idx, finish_idx} and sector.get("idx") is not None
    ]

    if start_sector:
        add_sector_overlay(start_sector, "Start sector", "#2ca02c")
    if finish_sector and finish_idx != start_idx:
        add_sector_overlay(finish_sector, "Finish sector", "#ff7f0e")
    for sector in turnpoint_sectors:
        add_sector_overlay(sector, "Turnpoint sector", "#1f77b4")

    if trace.get_zone_fix_mask().any():
        current_segment = []
        current_in_sector = None
        for idx, in_sector in trace.get_zone_fix_mask().items():
            if current_in_sector is None:
                current_in_sector = bool(in_sector)
            if bool(in_sector) == current_in_sector:
                current_segment.append((float(trace.trace_df.loc[idx, "lat"]), float(trace.trace_df.loc[idx, "lon"])))
            else:
                if current_in_sector:
                    fig.add_trace(
                        MAP_TRACE(
                            lat=[point[0] for point in current_segment],
                            lon=[point[1] for point in current_segment],
                            mode="lines",
                            line={"color": "#f1c40f", "width": 2},
                            name="Fixes in task sector",
                            hoverinfo="skip",
                        )
                    )
                current_segment = [(float(trace.trace_df.loc[idx, "lat"]), float(trace.trace_df.loc[idx, "lon"]))]
                current_in_sector = bool(in_sector)

        if current_segment and current_in_sector:
            fig.add_trace(
                MAP_TRACE(
                    lat=[point[0] for point in current_segment],
                    lon=[point[1] for point in current_segment],
                    mode="lines",
                    line={"color": "#f1c40f", "width": 2},
                    name="Fixes in task sector",
                    hoverinfo="skip",
                )
            )

    layout_args = {
        MAP_LAYOUT_KEY: {
            "style": "carto-positron",
            "center": {"lat": trace.lat_center, "lon": trace.lon_center},
            "zoom": 7,
        },
        "margin": {"l": 0, "r": 0, "t": 0, "b": 0},
        "legend": {"x": 0.01, "y": 0.99, "xanchor": "left", "yanchor": "top"},
    }
    fig.update_layout(**layout_args)

    ui.plotly_chart(fig, use_container_width=True)
    ui.caption(f"Flight fixes: {len(trace.trace_df)} | Task points: {len(trace.task_df)}")

    if trace.flight.notes:
        with ui.expander("Flight parsing notes"):
            ui.write(trace.flight.notes[:10])

    return trace
