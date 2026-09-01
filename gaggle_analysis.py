from __future__ import annotations

from collections import defaultdict
from math import cos, radians, sin

from sector_geometry import _bearing_between_points, _distance_between_points_m, _normalize_bearing_deg


def _fix_altitude(fix) -> float | None:
    for attr in ("alt", "gnss_alt", "press_alt"):
        value = getattr(fix, attr, None)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _fix_timestamp(fix) -> float | None:
    value = getattr(fix, "timestamp", None)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fix_position(fix) -> tuple[float, float] | None:
    lat = getattr(fix, "lat", None)
    lon = getattr(fix, "lon", None)
    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def _turn_rate_deg_per_second(prev_fix, curr_fix, next_fix) -> float:
    if prev_fix is None or curr_fix is None or next_fix is None:
        return 0.0
    prev_pos = _fix_position(prev_fix)
    curr_pos = _fix_position(curr_fix)
    next_pos = _fix_position(next_fix)
    if prev_pos is None or curr_pos is None or next_pos is None:
        return 0.0
    prev_ts = _fix_timestamp(prev_fix)
    curr_ts = _fix_timestamp(curr_fix)
    next_ts = _fix_timestamp(next_fix)
    if prev_ts is None or curr_ts is None or next_ts is None:
        return 0.0
    dt = max((curr_ts - prev_ts), 1.0)
    ref = _bearing_between_points(prev_pos[0], prev_pos[1], curr_pos[0], curr_pos[1])
    next_bearing = _bearing_between_points(curr_pos[0], curr_pos[1], next_pos[0], next_pos[1])
    delta = abs(_normalize_bearing_deg(next_bearing - ref))
    turn_rate = min(delta, 360.0 - delta) / dt
    return float(turn_rate)


def detect_thermal_segments(record) -> list[dict]:
    """Return contiguous circling/climbing segments for a single flight."""
    fixes = list(getattr(record, "fixes", []) or [])
    if len(fixes) < 3:
        return []

    flags: list[bool] = [False] * len(fixes)
    for idx in range(1, len(fixes) - 1):
        prev_fix = fixes[idx - 1]
        curr_fix = fixes[idx]
        next_fix = fixes[idx + 1]

        alt_prev = _fix_altitude(prev_fix)
        alt_curr = _fix_altitude(curr_fix)
        alt_next = _fix_altitude(next_fix)
        if alt_prev is None or alt_curr is None or alt_next is None:
            continue

        prev_ts = _fix_timestamp(prev_fix)
        curr_ts = _fix_timestamp(curr_fix)
        next_ts = _fix_timestamp(next_fix)
        if prev_ts is None or curr_ts is None or next_ts is None:
            continue

        dt = max((curr_ts - prev_ts), 1.0)
        climb_rate = (alt_next - alt_prev) / (2.0 * dt)
        turn_rate = _turn_rate_deg_per_second(prev_fix, curr_fix, next_fix)
        dist_m = _distance_between_points_m(
            prev_fix.lat,
            prev_fix.lon,
            curr_fix.lat,
            curr_fix.lon,
        )

        if climb_rate > 0.3 and turn_rate > 3.0 and dist_m > 10.0:
            flags[idx] = True

    segments: list[dict] = []
    start_idx: int | None = None
    for idx, is_thermal in enumerate(flags):
        if is_thermal and start_idx is None:
            start_idx = idx
        elif (not is_thermal or idx == len(flags) - 1) and start_idx is not None:
            end_idx = idx if not is_thermal else idx
            if end_idx - start_idx >= 3:
                segments.append({
                    "start_idx": start_idx,
                    "end_idx": end_idx,
                    "start_time": _fix_timestamp(fixes[start_idx]),
                    "end_time": _fix_timestamp(fixes[end_idx]),
                })
            start_idx = None

    return segments


def _group_cluster_members(events: list[dict], max_distance_m: float, max_time_delta_s: float) -> list[dict]:
    grouped: list[dict] = []
    seen: set[tuple[str, ...]] = set()
    for event in events:
        members = [event]
        for other in events:
            if other is event:
                continue
            if other["flight_id"] == event["flight_id"]:
                continue
            if abs(other["timestamp"] - event["timestamp"]) > max_time_delta_s:
                continue
            dist_m = _distance_between_points_m(
                event["lat"], event["lon"], other["lat"], other["lon"]
            )
            if dist_m <= max_distance_m:
                members.append(other)

        key_members = tuple(sorted({member["flight_id"] for member in members}))
        timestamp = round(sum(member["timestamp"] for member in members) / len(members), 3)
        key = (timestamp, *key_members)
        if len(members) < 2:
            continue
        if key in seen:
            continue
        seen.add(key)

        avg_lat = sum(member["lat"] for member in members) / len(members)
        avg_lon = sum(member["lon"] for member in members) / len(members)
        grouped.append({
            "timestamp": timestamp,
            "members": members,
            "size": len(members),
            "centroid": {"lat": avg_lat, "lon": avg_lon},
            "radius_m": max(
                _distance_between_points_m(member["lat"], member["lon"], avg_lat, avg_lon)
                for member in members
            ) + 50.0,
        })
    return grouped


def compute_thermal_gaggles(
    flights: list,
    *,
    max_distance_m: float = 500.0,
    max_time_delta_s: float = 30.0,
) -> list[dict]:
    """Return thermal gaggle clusters for a set of flights."""
    thermal_events: list[dict] = []
    for record in flights:
        for segment in detect_thermal_segments(record):
            fixes = list(getattr(record, "fixes", []) or [])
            for idx in range(segment["start_idx"], segment["end_idx"] + 1):
                fix = fixes[idx]
                pos = _fix_position(fix)
                if pos is None:
                    continue
                thermal_events.append({
                    "flight_id": str(record.file_path),
                    "timestamp": _fix_timestamp(fix) or 0.0,
                    "lat": pos[0],
                    "lon": pos[1],
                })

    if not thermal_events:
        return []

    clusters = _group_cluster_members(thermal_events, max_distance_m, max_time_delta_s)
    return sorted(clusters, key=lambda item: (item["timestamp"], item["size"]))


def active_thermal_gaggles(
    flights: list,
    current_time_s: float,
    *,
    max_distance_m: float = 500.0,
    max_time_delta_s: float = 30.0,
) -> list[dict]:
    clusters = compute_thermal_gaggles(
        flights,
        max_distance_m=max_distance_m,
        max_time_delta_s=max_time_delta_s,
    )
    return [cluster for cluster in clusters if abs(cluster["timestamp"] - current_time_s) <= max_time_delta_s]
