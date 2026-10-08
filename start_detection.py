"""Start-time detection following FAI SC3 Annex A para 7.4.

Line starts (and semi-cylinders, treated as lines) use the last valid crossing of the start
line before the first turnpoint. Cylinder starts use the last PEV inside the cylinder, or the
last cylinder exit when no PEV is present.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from flight_fix_utils import fix_timestamp
from sector_geometry import (
    _bearing_between_points,
    _distance_between_points_m,
    _normalize_bearing_deg,
    is_point_in_sector,
)
from task_parsing import extract_pev_times_from_igc

EARTH_RADIUS_M = 6371000.0
PEV_CLUSTER_WINDOW_S = 30.0
OFFICIAL_MATCH_TOLERANCE_S = 20.0
GATE_TIME_MIN_SHARED = 3


@dataclass(frozen=True)
class StartResult:
    method: str | None = None  # "line" or "cylinder"
    source: str | None = None  # "crossing", "pev" or "exit"
    timestamp: float | None = None
    lat: float | None = None
    lon: float | None = None
    crossing_count: int = 0
    candidates: tuple[float, ...] = ()  # every valid start found, earliest first
    reason: str | None = None  # set when no start was found

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_start_sector(sector: dict) -> str:
    """Line and semi-cylinder starts use the line method; only full cylinders use the cylinder method."""
    if sector.get("line_flag"):
        return "line"
    return "cylinder" if float(sector.get("a1_deg") or 0.0) >= 180.0 else "line"


def _round_to_second(value: float) -> float:
    return float(math.floor(value + 0.5))


def _fix_points(fixes: Sequence[Any]) -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    for fix in fixes:
        if isinstance(fix, dict):
            lat, lon, raw_ts = fix.get("lat"), fix.get("lon"), fix.get("timestamp")
            try:
                ts = None if raw_ts is None else float(raw_ts)
            except (TypeError, ValueError):
                ts = None
        else:
            lat, lon, ts = getattr(fix, "lat", None), getattr(fix, "lon", None), fix_timestamp(fix)
        if lat is None or lon is None or ts is None:
            continue
        points.append((float(lat), float(lon), ts))
    return points


def _first_turnpoint_index(points: list[tuple[float, float, float]], tp_sector: dict | None) -> int:
    if not tp_sector:
        return len(points)
    for index, (lat, lon, _) in enumerate(points):
        if is_point_in_sector(lat, lon, tp_sector):
            return index
    return len(points)


def _course_bearing_deg(start_sector: dict, tp_sector: dict | None) -> float | None:
    if tp_sector and tp_sector.get("lat") is not None and tp_sector.get("lon") is not None:
        return _bearing_between_points(
            float(start_sector["lat"]), float(start_sector["lon"]), float(tp_sector["lat"]), float(tp_sector["lon"])
        )
    orientation = start_sector.get("orientation_deg")
    if orientation is None:
        return None
    # Start sector axes point back along the track, away from the first turnpoint.
    return _normalize_bearing_deg(float(orientation) + 180.0)


def _line_offsets_m(origin: tuple[float, float], line_bearing_deg: float, lat: float, lon: float) -> tuple[float, float]:
    """Return (distance ahead of the line in the course direction, signed distance along the line)."""
    distance = _distance_between_points_m(origin[0], origin[1], lat, lon)
    if distance <= 0.0:
        return 0.0, 0.0
    angular = distance / EARTH_RADIUS_M
    delta = math.radians(_bearing_between_points(origin[0], origin[1], lat, lon) - line_bearing_deg)
    cross_track = math.asin(max(-1.0, min(1.0, math.sin(angular) * math.sin(delta))))
    along = math.acos(max(-1.0, min(1.0, math.cos(angular) / math.cos(cross_track))))
    if math.cos(delta) < 0.0:
        along = -along
    return cross_track * EARTH_RADIUS_M, along * EARTH_RADIUS_M


def _detect_line_start(points, limit: int, start_sector: dict, tp_sector: dict | None) -> StartResult:
    half_length = float(start_sector.get("radius_m") or 0.0)
    course = _course_bearing_deg(start_sector, tp_sector)
    if half_length <= 0.0 or course is None:
        return StartResult(method="line", reason="no_start_zone")

    origin = (float(start_sector["lat"]), float(start_sector["lon"]))
    # A heading of course - 90 puts the course direction on the right, so ahead of the line is positive.
    line_bearing = _normalize_bearing_deg(course - 90.0)

    crossings: list[tuple[float, float, float]] = []
    previous = None
    for index in range(limit):
        lat, lon, ts = points[index]
        ahead, along = _line_offsets_m(origin, line_bearing, lat, lon)
        if previous is not None and previous[3] < 0.0 <= ahead and ts > previous[2]:
            fraction = -previous[3] / (ahead - previous[3])
            lateral = previous[4] + fraction * (along - previous[4])
            if abs(lateral) <= half_length:
                crossings.append(
                    (
                        previous[2] + fraction * (ts - previous[2]),
                        previous[0] + fraction * (lat - previous[0]),
                        previous[1] + fraction * (lon - previous[1]),
                    )
                )
        previous = (lat, lon, ts, ahead, along)

    if not crossings:
        return StartResult(method="line", reason="no_crossing")
    ts, lat, lon = crossings[-1]
    return StartResult(
        method="line",
        source="crossing",
        timestamp=_round_to_second(ts),
        lat=lat,
        lon=lon,
        crossing_count=len(crossings),
        candidates=tuple(_round_to_second(crossing[0]) for crossing in crossings),
    )


def _position_at(points, timestamps: list[float], ts: float) -> tuple[float, float] | None:
    if not points or ts < timestamps[0] or ts > timestamps[-1]:
        return None
    upper = bisect.bisect_left(timestamps, ts)
    if timestamps[upper] == ts or upper == 0:
        return points[upper][0], points[upper][1]
    lat0, lon0, ts0 = points[upper - 1]
    lat1, lon1, ts1 = points[upper]
    fraction = (ts - ts0) / (ts1 - ts0)
    return lat0 + fraction * (lat1 - lat0), lon0 + fraction * (lon1 - lon0)


def _pev_cluster_starts(pev_times: list[float]) -> list[float]:
    """PEVs within 30 s of the first of a cluster count as one press at that first time."""
    cluster_starts: list[float] = []
    for value in sorted(pev_times):
        if not cluster_starts or value - cluster_starts[-1] > PEV_CLUSTER_WINDOW_S:
            cluster_starts.append(value)
    return cluster_starts


def _detect_cylinder_start(points, limit: int, start_sector: dict, pev_timestamps: Sequence[float]) -> StartResult:
    radius = float(start_sector.get("radius_m") or 0.0)
    if radius <= 0.0:
        return StartResult(method="cylinder", reason="no_start_zone")

    center = (float(start_sector["lat"]), float(start_sector["lon"]))
    timestamps = [point[2] for point in points]
    cutoff_ts = points[limit][2] if limit < len(points) else float("inf")

    pevs_inside: list[float] = []
    for pev in pev_timestamps:
        if pev >= cutoff_ts:
            continue
        position = _position_at(points, timestamps, float(pev))
        if position is not None and _distance_between_points_m(center[0], center[1], *position) <= radius:
            pevs_inside.append(float(pev))

    pev_starts = _pev_cluster_starts(pevs_inside)
    if pev_starts:
        pev_start = pev_starts[-1]
        lat, lon = _position_at(points, timestamps, pev_start)
        return StartResult(
            method="cylinder",
            source="pev",
            timestamp=pev_start,
            lat=lat,
            lon=lon,
            crossing_count=len(pevs_inside),
            candidates=tuple(pev_starts),
        )

    exit_fix: tuple[float, float, float] | None = None
    previous_distance: float | None = None
    for index in range(limit):
        lat, lon, ts = points[index]
        distance = _distance_between_points_m(center[0], center[1], lat, lon)
        if previous_distance is not None and previous_distance <= radius < distance:
            fraction = (radius - previous_distance) / (distance - previous_distance)
            prev_lat, prev_lon, prev_ts = points[index - 1]
            exit_fix = (
                prev_ts + fraction * (ts - prev_ts),
                prev_lat + fraction * (lat - prev_lat),
                prev_lon + fraction * (lon - prev_lon),
            )
        previous_distance = distance

    if exit_fix is None:
        return StartResult(method="cylinder", reason="no_exit")
    ts, lat, lon = exit_fix
    return StartResult(
        method="cylinder", source="exit", timestamp=_round_to_second(ts), lat=lat, lon=lon, candidates=(_round_to_second(ts),)
    )


def detect_start(
    fixes: Sequence[Any],
    start_sector: dict | None,
    first_turnpoint_sector: dict | None = None,
    pev_timestamps: Sequence[float] = (),
) -> StartResult:
    """Find the race start time; fix and PEV timestamps are UTC epoch seconds."""
    if not start_sector or start_sector.get("lat") is None or start_sector.get("lon") is None:
        return StartResult(reason="no_start_zone")
    points = _fix_points(fixes)
    if len(points) < 2:
        return StartResult(reason="no_fixes")

    limit = _first_turnpoint_index(points, first_turnpoint_sector)
    if classify_start_sector(start_sector) == "cylinder":
        return _detect_cylinder_start(points, limit, start_sector, pev_timestamps)
    return _detect_line_start(points, limit, start_sector, first_turnpoint_sector)


def extract_glider_start_time(
    fixes: Sequence[Any],
    start_sector: dict | None,
    first_turnpoint_sector: dict | None = None,
    pev_timestamps: Sequence[float] = (),
) -> float | None:
    return detect_start(fixes, start_sector, first_turnpoint_sector, pev_timestamps).timestamp


def pev_timestamps_from_igc(path: str, fixes: Sequence[Any]) -> list[float]:
    """Convert E-record PEV times (seconds of day) to epoch seconds using the flight's first fix."""
    seconds_of_day = extract_pev_times_from_igc(path)
    if not seconds_of_day or not fixes:
        return []
    first_ts = fix_timestamp(fixes[0])
    first_raw = getattr(fixes[0], "rawtime", None)
    if first_ts is None or first_raw is None:
        return []
    day_start = first_ts - float(first_raw)
    return [day_start + value for value in seconds_of_day]


def resolve_start(
    official_utc: float | None,
    detected_utc: float | None,
    candidates: Sequence[float] = (),
    shared_official_count: int = 1,
) -> tuple[float | None, str | None, str | None]:
    """Return (start, source, note), preferring the official start unless it is in doubt."""
    if detected_utc is None:
        if official_utc is None:
            return None, None, "no_start"
        return official_utc, "official", "no_detected_start"
    if official_utc is None:
        return detected_utc, "detected", "no_official_start"
    if shared_official_count >= GATE_TIME_MIN_SHARED:
        return detected_utc, "detected", "shared_official_time"
    if not any(abs(official_utc - value) <= OFFICIAL_MATCH_TOLERANCE_S for value in (candidates or (detected_utc,))):
        return detected_utc, "detected", "official_not_in_crossings"
    return official_utc, "official", None
