from __future__ import annotations

import os
import multiprocessing as mp
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from math import cos, radians

from sector_geometry import _bearing_between_points, _distance_between_points_m, _normalize_bearing_deg


_MP_CLUSTER_EVENTS: list[dict] = []

THERMAL_MIN_CLIMB_RATE_MPS = 0.3
THERMAL_MIN_TURN_RATE_DPS = 3.0
THERMAL_MIN_STEP_DISTANCE_M = 10.0
EARTH_METERS_PER_DEG_LAT = 111_320.0


def _fix_altitude(fix) -> float | None:
    for attr in ("alt", "gnss_alt", "press_alt"):
        value = getattr(fix, attr, None)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _passes_altitude_delta(
    event_alt: float | None,
    other_alt: float | None,
    max_altitude_delta_m: float | None,
) -> bool:
    if max_altitude_delta_m is None:
        return True
    if event_alt is None or other_alt is None:
        return True
    return abs(float(other_alt) - float(event_alt)) <= max_altitude_delta_m


def _fix_timestamp(fix) -> float | None:
    value = getattr(fix, "timestamp", None)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        if isinstance(value, datetime):
            try:
                return float(value.timestamp())
            except (TypeError, ValueError, OSError):
                return None
        if hasattr(value, "timestamp"):
            try:
                return float(value.timestamp())
            except Exception:
                return None
        return None


def _build_time_offsets(fixes: list) -> list[float]:
    if not fixes:
        return []

    first_timestamp = getattr(fixes[0], "timestamp", None)
    if first_timestamp is None:
        return [float(i) for i in range(len(fixes))]

    offsets: list[float] = []
    previous = 0.0
    for idx, fix in enumerate(fixes):
        timestamp = getattr(fix, "timestamp", None)
        if timestamp is None:
            offsets.append(float(idx))
            previous = offsets[-1]
            continue

        try:
            if isinstance(timestamp, (int, float)) and isinstance(first_timestamp, (int, float)):
                delta = float(timestamp - first_timestamp)
            else:
                delta_obj = timestamp - first_timestamp
                if hasattr(delta_obj, "total_seconds"):
                    delta = float(delta_obj.total_seconds())
                else:
                    delta = float(delta_obj)
        except Exception:
            delta = float(idx)

        if delta < previous:
            delta = previous
        offsets.append(float(delta))
        previous = float(delta)

    if offsets and offsets[-1] <= 0.0:
        return [float(i) for i in range(len(fixes))]
    return offsets


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


def _within_horizontal_distance(
    event_lat: float,
    event_lon: float,
    other_lat: float,
    other_lon: float,
    max_distance_m: float,
) -> bool:
    # Fast rectangular prefilter avoids many expensive geodesic checks.
    lat_threshold_deg = max_distance_m / EARTH_METERS_PER_DEG_LAT
    if abs(other_lat - event_lat) > lat_threshold_deg:
        return False

    cos_lat = max(0.1, abs(cos(radians(event_lat))))
    lon_threshold_deg = max_distance_m / (EARTH_METERS_PER_DEG_LAT * cos_lat)
    if abs(other_lon - event_lon) > lon_threshold_deg:
        return False

    dist_m = _distance_between_points_m(event_lat, event_lon, other_lat, other_lon)
    return dist_m <= max_distance_m


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

        if (
            climb_rate > THERMAL_MIN_CLIMB_RATE_MPS
            and turn_rate > THERMAL_MIN_TURN_RATE_DPS
            and dist_m > THERMAL_MIN_STEP_DISTANCE_M
        ):
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


def _cluster_key_and_payload(members: list[dict]) -> tuple[tuple, dict] | None:
    if len(members) < 2:
        return None
    key_members = tuple(sorted({member["flight_id"] for member in members}))
    if len(key_members) < 2:
        return None
    timestamp = round(sum(member["timestamp"] for member in members) / len(members), 3)
    avg_lat = sum(member["lat"] for member in members) / len(members)
    avg_lon = sum(member["lon"] for member in members) / len(members)
    cluster = {
        "timestamp": timestamp,
        "members": members,
        "size": len(key_members),
        "centroid": {"lat": avg_lat, "lon": avg_lon},
        "radius_m": max(
            _distance_between_points_m(member["lat"], member["lon"], avg_lat, avg_lon)
            for member in members
        ) + 50.0,
    }
    return (timestamp, *key_members), cluster


def _collect_members_for_event(
    sorted_events: list[dict],
    index: int,
    max_distance_m: float,
    max_time_delta_s: float,
    max_altitude_delta_m: float | None,
) -> list[dict]:
    event = sorted_events[index]
    total_events = len(sorted_events)
    members = [event]
    event_flight_id = event["flight_id"]
    event_ts = event["timestamp"]
    event_lat = event["lat"]
    event_lon = event["lon"]
    event_alt = event.get("alt")

    backward_index = index - 1
    while backward_index >= 0:
        other = sorted_events[backward_index]
        dt = event_ts - other["timestamp"]
        if dt > max_time_delta_s:
            break
        if other["flight_id"] != event_flight_id:
            if not _passes_altitude_delta(event_alt, other.get("alt"), max_altitude_delta_m):
                backward_index -= 1
                continue
            if _within_horizontal_distance(
                event_lat,
                event_lon,
                other["lat"],
                other["lon"],
                max_distance_m,
            ):
                members.append(other)
        backward_index -= 1

    forward_index = index + 1
    while forward_index < total_events:
        other = sorted_events[forward_index]
        dt = other["timestamp"] - event_ts
        if dt > max_time_delta_s:
            break
        if other["flight_id"] != event_flight_id:
            if not _passes_altitude_delta(event_alt, other.get("alt"), max_altitude_delta_m):
                forward_index += 1
                continue
            if _within_horizontal_distance(
                event_lat,
                event_lon,
                other["lat"],
                other["lon"],
                max_distance_m,
            ):
                members.append(other)
        forward_index += 1

    return members


def _init_cluster_worker(sorted_events: list[dict]) -> None:
    global _MP_CLUSTER_EVENTS
    _MP_CLUSTER_EVENTS = sorted_events


def _cluster_chunk_worker(args: tuple[int, int, float, float, float | None]) -> tuple[list[tuple[tuple, dict]], int]:
    start_index, end_index, max_distance_m, max_time_delta_s, max_altitude_delta_m = args
    local_results: list[tuple[tuple, dict]] = []
    local_seen: set[tuple] = set()
    for index in range(start_index, end_index):
        members = _collect_members_for_event(
            _MP_CLUSTER_EVENTS,
            index,
            max_distance_m,
            max_time_delta_s,
            max_altitude_delta_m,
        )
        payload = _cluster_key_and_payload(members)
        if payload is None:
            continue
        key, cluster = payload
        if key in local_seen:
            continue
        local_seen.add(key)
        local_results.append((key, cluster))
    return local_results, max(0, end_index - start_index)


def _group_cluster_members_serial(
    sorted_events: list[dict],
    max_distance_m: float,
    max_time_delta_s: float,
    max_altitude_delta_m: float | None,
    progress_callback: Callable[[str, int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[dict]:
    grouped: list[dict] = []
    seen: set[tuple] = set()
    total_events = len(sorted_events)

    for index in range(total_events):
        if cancel_check is not None and cancel_check():
            return []
        members = _collect_members_for_event(
            sorted_events,
            index,
            max_distance_m,
            max_time_delta_s,
            max_altitude_delta_m,
        )
        payload = _cluster_key_and_payload(members)
        if payload is None:
            continue
        key, cluster = payload
        if key in seen:
            continue
        seen.add(key)
        grouped.append(cluster)

        if progress_callback is not None and (index % 50 == 0 or index + 1 == total_events):
            progress_callback("cluster", index + 1, total_events)
    return grouped


def _group_cluster_members_parallel(
    sorted_events: list[dict],
    max_distance_m: float,
    max_time_delta_s: float,
    max_altitude_delta_m: float | None,
    progress_callback: Callable[[str, int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    max_workers: int | None = None,
) -> list[dict]:
    total_events = len(sorted_events)
    if total_events == 0:
        return []

    workers = max(1, int(max_workers or (os.cpu_count() or 1)))
    chunk_size = max(400, total_events // max(workers * 4, 1))
    chunks: list[tuple[int, int, float, float, float | None]] = []
    for start in range(0, total_events, chunk_size):
        end = min(total_events, start + chunk_size)
        chunks.append((start, end, max_distance_m, max_time_delta_s, max_altitude_delta_m))

    merged: list[tuple[tuple, dict]] = []
    processed = 0
    try:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_cluster_worker,
            initargs=(sorted_events,),
            mp_context=mp.get_context("spawn"),
        ) as executor:
            futures = [executor.submit(_cluster_chunk_worker, chunk) for chunk in chunks]
            for future in as_completed(futures):
                if cancel_check is not None and cancel_check():
                    executor.shutdown(cancel_futures=True)
                    return []
                chunk_results, chunk_processed = future.result()
                merged.extend(chunk_results)
                processed += int(chunk_processed)
                if progress_callback is not None:
                    progress_callback("cluster", min(processed, total_events), total_events)
    except Exception:
        return _group_cluster_members_serial(
            sorted_events,
            max_distance_m,
            max_time_delta_s,
            max_altitude_delta_m,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

    deduped: list[dict] = []
    seen: set[tuple] = set()
    for key, cluster in sorted(merged, key=lambda item: (item[1]["timestamp"], item[1]["size"])):
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cluster)
    return deduped


def _group_cluster_members(
    events: list[dict],
    max_distance_m: float,
    max_time_delta_s: float,
    max_altitude_delta_m: float | None,
    progress_callback: Callable[[str, int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    use_multiprocessing: bool = False,
    max_workers: int | None = None,
) -> list[dict]:
    sorted_events = sorted(events, key=lambda item: float(item.get("timestamp", 0.0)))
    if use_multiprocessing and len(sorted_events) >= 2000:
        return _group_cluster_members_parallel(
            sorted_events,
            max_distance_m,
            max_time_delta_s,
            max_altitude_delta_m,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            max_workers=max_workers,
        )
    return _group_cluster_members_serial(
        sorted_events,
        max_distance_m,
        max_time_delta_s,
        max_altitude_delta_m,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )


def compute_thermal_gaggles(
    flights: list,
    *,
    max_distance_m: float = 500.0,
    max_time_delta_s: float = 30.0,
    max_altitude_delta_m: float | None = None,
    progress_callback: Callable[[str, int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    use_multiprocessing: bool = False,
    max_workers: int | None = None,
) -> list[dict]:
    """Return thermal gaggle clusters for a set of flights."""
    thermal_events: list[dict] = []
    total_flights = len(flights)
    for flight_index, record in enumerate(flights, start=1):
        if cancel_check is not None and cancel_check():
            return []
        fixes = list(getattr(record, "fixes", []) or [])
        offsets = _build_time_offsets(fixes)
        for segment in detect_thermal_segments(record):
            for idx in range(segment["start_idx"], segment["end_idx"] + 1):
                fix = fixes[idx]
                pos = _fix_position(fix)
                if pos is None:
                    continue
                relative_timestamp = offsets[idx] if idx < len(offsets) else float(idx)
                thermal_events.append({
                    "flight_id": str(record.file_path),
                    "timestamp": float(relative_timestamp),
                    "lat": pos[0],
                    "lon": pos[1],
                    "alt": _fix_altitude(fix),
                })
        if progress_callback is not None:
            progress_callback("flight", flight_index, max(total_flights, 1))

    if not thermal_events:
        return []

    clusters = _group_cluster_members(
        thermal_events,
        max_distance_m,
        max_time_delta_s,
        max_altitude_delta_m,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
        use_multiprocessing=use_multiprocessing,
        max_workers=max_workers,
    )
    return sorted(clusters, key=lambda item: (item["timestamp"], item["size"]))


def active_thermal_gaggles(
    flights: list,
    current_time_s: float,
    *,
    max_distance_m: float = 500.0,
    max_time_delta_s: float = 30.0,
    max_altitude_delta_m: float | None = None,
    progress_callback: Callable[[str, int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    use_multiprocessing: bool = False,
    max_workers: int | None = None,
) -> list[dict]:
    clusters = compute_thermal_gaggles(
        flights,
        max_distance_m=max_distance_m,
        max_time_delta_s=max_time_delta_s,
        max_altitude_delta_m=max_altitude_delta_m,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
        use_multiprocessing=use_multiprocessing,
        max_workers=max_workers,
    )
    return [cluster for cluster in clusters if abs(cluster["timestamp"] - current_time_s) <= max_time_delta_s]
