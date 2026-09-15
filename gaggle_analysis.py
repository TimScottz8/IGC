from __future__ import annotations

import os
import multiprocessing as mp
from collections.abc import Callable
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor, as_completed
from bisect import bisect_left, bisect_right
from math import cos, radians

from flight_fix_utils import build_time_offsets as _build_time_offsets
from flight_fix_utils import fix_altitude as _fix_altitude
from flight_fix_utils import fix_timestamp as _fix_timestamp
from sector_geometry import _bearing_between_points, _distance_between_points_m, _normalize_bearing_deg


_MP_CLUSTER_EVENTS: list[dict] = []
_MP_WINDOW_BOUNDS: list[tuple[int, int]] = []

_THERMAL_SEGMENT_CACHE: OrderedDict[
    tuple[str, int, float | None, float | None, tuple[float, float] | None, tuple[float, float] | None],
    list[dict],
] = OrderedDict()
_THERMAL_SEGMENT_CACHE_MAX = 512

THERMAL_MIN_CLIMB_RATE_MPS = 0.3
THERMAL_MIN_TURN_RATE_DPS = 3.0
THERMAL_MIN_STEP_DISTANCE_M = 10.0
EARTH_METERS_PER_DEG_LAT = 111_320.0


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
    window_start: int,
    window_end: int,
    max_distance_m: float,
    max_altitude_delta_m: float | None,
) -> list[dict]:
    event = sorted_events[index]
    members = [event]
    event_flight_id = event["flight_id"]
    event_lat = event["lat"]
    event_lon = event["lon"]
    event_alt = event.get("alt")

    for other_index in range(window_start, window_end):
        if other_index == index:
            continue
        other = sorted_events[other_index]
        if other["flight_id"] == event_flight_id:
            continue
        if not _passes_altitude_delta(event_alt, other.get("alt"), max_altitude_delta_m):
            continue
        if _within_horizontal_distance(
            event_lat,
            event_lon,
            other["lat"],
            other["lon"],
            max_distance_m,
        ):
            members.append(other)

    return members


def _build_time_window_bounds(sorted_events: list[dict], max_time_delta_s: float) -> list[tuple[int, int]]:
    if not sorted_events:
        return []
    timestamps = [float(item.get("timestamp", 0.0)) for item in sorted_events]
    bounds: list[tuple[int, int]] = []
    for ts in timestamps:
        start = bisect_left(timestamps, ts - max_time_delta_s)
        end = bisect_right(timestamps, ts + max_time_delta_s)
        bounds.append((start, end))
    return bounds


def _init_cluster_worker(sorted_events: list[dict], window_bounds: list[tuple[int, int]]) -> None:
    global _MP_CLUSTER_EVENTS
    global _MP_WINDOW_BOUNDS
    _MP_CLUSTER_EVENTS = sorted_events
    _MP_WINDOW_BOUNDS = window_bounds


def _cluster_chunk_worker(args: tuple[int, int, float, float | None]) -> tuple[list[tuple[tuple, dict]], int]:
    start_index, end_index, max_distance_m, max_altitude_delta_m = args
    local_results: list[tuple[tuple, dict]] = []
    local_seen: set[tuple] = set()
    for index in range(start_index, end_index):
        window_start, window_end = _MP_WINDOW_BOUNDS[index]
        members = _collect_members_for_event(
            _MP_CLUSTER_EVENTS,
            index,
            window_start,
            window_end,
            max_distance_m,
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
    window_bounds = _build_time_window_bounds(sorted_events, max_time_delta_s)

    for index in range(total_events):
        if cancel_check is not None and cancel_check():
            return []
        window_start, window_end = window_bounds[index]
        members = _collect_members_for_event(
            sorted_events,
            index,
            window_start,
            window_end,
            max_distance_m,
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

    window_bounds = _build_time_window_bounds(sorted_events, max_time_delta_s)

    workers = max(1, int(max_workers or (os.cpu_count() or 1)))
    chunk_size = max(400, total_events // max(workers * 4, 1))
    chunks: list[tuple[int, int, float, float | None]] = []
    for start in range(0, total_events, chunk_size):
        end = min(total_events, start + chunk_size)
        chunks.append((start, end, max_distance_m, max_altitude_delta_m))

    merged: list[tuple[tuple, dict]] = []
    processed = 0
    try:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_cluster_worker,
            initargs=(sorted_events, window_bounds),
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


def _record_thermal_cache_key(
    record,
    fixes: list,
) -> tuple[str, int, float | None, float | None, tuple[float, float] | None, tuple[float, float] | None]:
    first_ts = _fix_timestamp(fixes[0]) if fixes else None
    last_ts = _fix_timestamp(fixes[-1]) if fixes else None
    first_pos = _fix_position(fixes[0]) if fixes else None
    last_pos = _fix_position(fixes[-1]) if fixes else None
    return (str(getattr(record, "file_path", "")), len(fixes), first_ts, last_ts, first_pos, last_pos)


def _cached_detect_thermal_segments(record, fixes: list) -> list[dict]:
    key = _record_thermal_cache_key(record, fixes)
    cached = _THERMAL_SEGMENT_CACHE.get(key)
    if cached is not None:
        _THERMAL_SEGMENT_CACHE.move_to_end(key)
        return [dict(item) for item in cached]

    segments = detect_thermal_segments(record)
    _THERMAL_SEGMENT_CACHE[key] = [dict(item) for item in segments]
    _THERMAL_SEGMENT_CACHE.move_to_end(key)
    while len(_THERMAL_SEGMENT_CACHE) > _THERMAL_SEGMENT_CACHE_MAX:
        _THERMAL_SEGMENT_CACHE.popitem(last=False)
    return segments


def _cluster_flight_ids(cluster: dict) -> set[str]:
    return {
        str(member.get("flight_id"))
        for member in list(cluster.get("members") or [])
        if member.get("flight_id") is not None
    }


def _build_lifecycle_events(
    snapshot_clusters: list[dict],
    *,
    break_distance_m: float,
    break_duration_s: float,
    circling_grace_s: float,
) -> list[dict]:
    if not snapshot_clusters:
        return []

    active_events: list[dict] = []
    completed_events: list[dict] = []
    next_event_id = 1

    for cluster in sorted(snapshot_clusters, key=lambda item: float(item.get("timestamp", 0.0))):
        centroid = cluster.get("centroid") or {}
        lat = centroid.get("lat")
        lon = centroid.get("lon")
        if lat is None or lon is None:
            continue
        ts = float(cluster.get("timestamp", 0.0))
        member_ids = _cluster_flight_ids(cluster)
        if not member_ids:
            continue

        still_active: list[dict] = []
        for event in active_events:
            stale_after = float(event["last_timestamp"]) + float(break_duration_s) + float(circling_grace_s)
            if ts > stale_after:
                completed_events.append(event)
            else:
                still_active.append(event)
        active_events = still_active

        best_event: dict | None = None
        best_score: float | None = None
        for event in active_events:
            dt = ts - float(event["last_timestamp"])
            if dt < 0.0 or dt > float(break_duration_s) + float(circling_grace_s):
                continue
            overlap = len(member_ids & event["flight_ids"])
            if overlap <= 0:
                continue
            dist_m = _distance_between_points_m(
                float(lat),
                float(lon),
                float(event["centroid"]["lat"]),
                float(event["centroid"]["lon"]),
            )
            if dist_m > float(break_distance_m):
                continue
            score = dist_m - (50.0 * min(overlap, 4))
            if best_score is None or score < best_score:
                best_score = score
                best_event = event

        if best_event is None:
            active_events.append({
                "event_id": next_event_id,
                "first_timestamp": ts,
                "last_timestamp": ts,
                "centroid": {"lat": float(lat), "lon": float(lon)},
                "sample_count": 1,
                "flight_ids": set(member_ids),
                "peak_size": int(cluster.get("size", 0)),
                "max_radius_m": float(cluster.get("radius_m", 0.0)),
                "representative": cluster,
            })
            next_event_id += 1
            continue

        count = int(best_event["sample_count"])
        weight = max(1, int(cluster.get("size", 1)))
        total_weight = count + weight
        best_event["centroid"]["lat"] = ((float(best_event["centroid"]["lat"]) * count) + (float(lat) * weight)) / total_weight
        best_event["centroid"]["lon"] = ((float(best_event["centroid"]["lon"]) * count) + (float(lon) * weight)) / total_weight
        best_event["sample_count"] = count + 1
        best_event["last_timestamp"] = ts
        best_event["flight_ids"].update(member_ids)
        best_event["peak_size"] = max(int(best_event["peak_size"]), int(cluster.get("size", 0)))
        best_event["max_radius_m"] = max(float(best_event["max_radius_m"]), float(cluster.get("radius_m", 0.0)))
        if int(cluster.get("size", 0)) >= int(best_event["representative"].get("size", 0)):
            best_event["representative"] = cluster

    completed_events.extend(active_events)

    events: list[dict] = []
    for event in completed_events:
        representative = event.get("representative") or {}
        first_ts = float(event["first_timestamp"])
        last_ts = float(event["last_timestamp"])
        payload = dict(representative)
        payload["event_id"] = int(event["event_id"])
        payload["timestamp"] = float(last_ts)
        payload["first_timestamp"] = first_ts
        payload["last_timestamp"] = last_ts
        payload["duration_s"] = max(0.0, last_ts - first_ts)
        payload["size"] = int(event["peak_size"])
        payload["radius_m"] = float(event["max_radius_m"])
        payload["centroid"] = {
            "lat": float(event["centroid"]["lat"]),
            "lon": float(event["centroid"]["lon"]),
        }
        payload["zone_flight_ids"] = sorted(event["flight_ids"])
        events.append(payload)

    return sorted(events, key=lambda item: (float(item.get("first_timestamp", 0.0)), int(item.get("size", 0))))


def compute_thermal_gaggles(
    flights: list,
    *,
    max_distance_m: float = 500.0,
    max_time_delta_s: float = 30.0,
    join_distance_m: float | None = None,
    join_time_delta_s: float | None = None,
    break_distance_m: float | None = None,
    break_duration_s: float = 120.0,
    circling_grace_s: float = 60.0,
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
        for segment in _cached_detect_thermal_segments(record, fixes):
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

    join_distance = float(join_distance_m if join_distance_m is not None else max_distance_m)
    join_time = float(join_time_delta_s if join_time_delta_s is not None else max_time_delta_s)
    break_distance = float(break_distance_m if break_distance_m is not None else join_distance * 1.6)

    clusters = _group_cluster_members(
        thermal_events,
        join_distance,
        join_time,
        max_altitude_delta_m,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
        use_multiprocessing=use_multiprocessing,
        max_workers=max_workers,
    )
    return _build_lifecycle_events(
        clusters,
        break_distance_m=break_distance,
        break_duration_s=float(break_duration_s),
        circling_grace_s=float(circling_grace_s),
    )


def active_thermal_gaggles(
    flights: list,
    current_time_s: float,
    *,
    max_distance_m: float = 500.0,
    max_time_delta_s: float = 30.0,
    join_distance_m: float | None = None,
    join_time_delta_s: float | None = None,
    break_distance_m: float | None = None,
    break_duration_s: float = 120.0,
    circling_grace_s: float = 60.0,
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
        join_distance_m=join_distance_m,
        join_time_delta_s=join_time_delta_s,
        break_distance_m=break_distance_m,
        break_duration_s=break_duration_s,
        circling_grace_s=circling_grace_s,
        max_altitude_delta_m=max_altitude_delta_m,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
        use_multiprocessing=use_multiprocessing,
        max_workers=max_workers,
    )
    return [
        cluster
        for cluster in clusters
        if float(cluster.get("first_timestamp", cluster.get("timestamp", 0.0)))
        <= float(current_time_s)
        <= float(cluster.get("last_timestamp", cluster.get("timestamp", 0.0))) + float(circling_grace_s)
    ]
