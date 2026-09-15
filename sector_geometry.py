import math
from datetime import datetime, timezone

from task_parsing import extract_task_points_from_igc, extract_task_sectors_from_igc


def _bearing_between_points(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the compass bearing in degrees from one point to another."""
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    d_lon = lon2_rad - lon1_rad
    y = math.sin(d_lon) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(d_lon)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360.0) % 360.0


def _normalize_bearing_deg(value: float) -> float:
    """Wrap any bearing into the standard 0-360 degree range."""
    return value % 360.0


def _shortest_angular_distance_deg(a_deg: float, b_deg: float) -> float:
    """Measure the smallest angular separation between two bearings, handling wrap-around."""
    delta = abs(_normalize_bearing_deg(a_deg - b_deg))
    return min(delta, 360.0 - delta)


def _heading_to_unit_vector(bearing_deg: float):
    """Convert a compass bearing to a unit vector used in bisector math."""
    bearing_rad = math.radians(bearing_deg)
    return (math.sin(bearing_rad), math.cos(bearing_rad))


def _unit_vector_bearing(unit_vector):
    """Invert the unit-vector conversion and return a compass bearing."""
    x, y = unit_vector
    return _normalize_bearing_deg(math.degrees(math.atan2(x, y)))


def _internal_bisector_from_legs(inbound_bearing_deg: float, outbound_bearing_deg: float) -> float:
    """Compute the internal bisector between the inbound and outbound leg bearings."""
    inbound_away = (-_heading_to_unit_vector(inbound_bearing_deg)[0], -_heading_to_unit_vector(inbound_bearing_deg)[1])
    outbound_away = _heading_to_unit_vector(outbound_bearing_deg)

    vx = inbound_away[0] + outbound_away[0]
    vy = inbound_away[1] + outbound_away[1]
    norm = math.hypot(vx, vy)
    if norm == 0:
        return _normalize_bearing_deg(outbound_bearing_deg)
    return _unit_vector_bearing((vx / norm, vy / norm))


def _outward_bisector_from_legs(inbound_bearing_deg: float, outbound_bearing_deg: float) -> float:
    """Return the outward-facing bisector used for the visible turnpoint sector axis."""
    task_side_bisector = _internal_bisector_from_legs(inbound_bearing_deg, outbound_bearing_deg)
    return _normalize_bearing_deg(task_side_bisector + 180.0)


def project_point_from_bearing(center_lat: float, center_lon: float, bearing_deg: float, distance_m: float):
    """Project a point along a bearing at a given distance from a reference coordinate."""
    if distance_m <= 0:
        return center_lat, center_lon
    earth_radius_m = 6371000.0
    bearing_rad = math.radians(bearing_deg)
    lat1 = math.radians(center_lat)
    lon1 = math.radians(center_lon)
    angular_distance = distance_m / earth_radius_m

    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_distance)
        + math.cos(lat1) * math.sin(angular_distance) * math.cos(bearing_rad)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing_rad) * math.sin(angular_distance) * math.cos(lat1),
        math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def _distance_between_points_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance between two lat/lon points in metres."""
    earth_radius_m = 6371000.0
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad
    a = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2.0) ** 2
    )
    return 2.0 * earth_radius_m * math.asin(math.sqrt(a))


def is_point_in_sector(point_lat: float, point_lon: float, sector: dict) -> bool:
    """Check whether a fix lies inside a SeeYou OZ.

    A SeeYou OZ is the union of two component shapes: the primary component is defined by
    the larger radius/half-angle pair and the secondary component by the smaller pair.
    The fix is inside the zone when it falls inside either component.
    """
    if not sector:
        return False

    center_lat = sector.get("lat")
    center_lon = sector.get("lon")
    if center_lat is None or center_lon is None:
        return False

    if math.isclose(point_lat, center_lat, abs_tol=1e-12) and math.isclose(point_lon, center_lon, abs_tol=1e-12):
        return True

    distance_m = _distance_between_points_m(center_lat, center_lon, point_lat, point_lon)
    axis_deg = float(sector.get("orientation_deg") or 0.0)
    bearing_deg = _bearing_between_points(center_lat, center_lon, point_lat, point_lon)
    angular_delta = _shortest_angular_distance_deg(bearing_deg, axis_deg)

    primary_radius_m = float(sector.get("radius_m") or 0.0)
    primary_half_angle_deg = float(sector.get("a1_deg") or 0.0)
    primary_match = primary_radius_m > 0 and distance_m <= primary_radius_m
    if primary_half_angle_deg > 0:
        primary_match = primary_match and angular_delta <= primary_half_angle_deg

    secondary_radius_m = float(sector.get("inner_radius_m") or 0.0)
    secondary_half_angle_deg = float(sector.get("a2_deg") or 0.0)
    secondary_match = secondary_radius_m > 0 and distance_m <= secondary_radius_m
    if secondary_half_angle_deg > 0:
        secondary_match = secondary_match and angular_delta <= secondary_half_angle_deg

    return primary_match or secondary_match


def segment_crosses_sector(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    sector: dict,
) -> bool:
    """Return True when the track segment crosses the task sector envelope.

    We must match the OZ rule: a valid turnpoint is reached when either a fix is inside
    the sector or the interpolated track between two consecutive fixes passes through it.
    We do this by sampling the line segment and checking the actual sector predicate along
    the segment, instead of using a broad angular-only shortcut that over-matches.
    """
    if not sector:
        return False

    if is_point_in_sector(start_lat, start_lon, sector):
        return True
    if is_point_in_sector(end_lat, end_lon, sector):
        return True

    samples = 9
    for index in range(1, samples):
        fraction = index / samples
        sample_lat = start_lat + (end_lat - start_lat) * fraction
        sample_lon = start_lon + (end_lon - start_lon) * fraction
        if is_point_in_sector(sample_lat, sample_lon, sector):
            return True

    return False


def format_human_readable_datetime(value):
    """Convert timestamps into a readable UTC date/time string for the UI."""
    if value is None:
        return "Not detected"

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except (OverflowError, OSError, ValueError):
            return str(value)

    if hasattr(value, "strftime"):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return "Not detected"
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            return candidate
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return str(value)


def extract_glider_start_time(fixes, start_sector: dict | None, first_turnpoint_sector: dict | None = None):
    """Track the last fix inside the start sector before the first turnpoint is reached."""
    if not fixes or not start_sector:
        return None

    last_start_time = None
    seen_turnpoint_1 = False

    for fix in fixes:
        lat = getattr(fix, "lat", None)
        lon = getattr(fix, "lon", None)
        timestamp = getattr(fix, "timestamp", None)
        if isinstance(fix, dict):
            lat = fix.get("lat", lat)
            lon = fix.get("lon", lon)
            timestamp = fix.get("timestamp", timestamp)
        if lat is None or lon is None:
            continue

        if first_turnpoint_sector and is_point_in_sector(float(lat), float(lon), first_turnpoint_sector):
            seen_turnpoint_1 = True

        if not seen_turnpoint_1 and is_point_in_sector(float(lat), float(lon), start_sector):
            last_start_time = timestamp

    return last_start_time


def build_sector_points(center_lat: float, center_lon: float, radius_m: float, start_angle_deg: float, end_angle_deg: float, points: int = 48, center_bearing_deg: float | None = None):
    """Build a polygon outline for a circular sector wedge used in the task overlay."""
    if radius_m <= 0:
        return []

    if center_bearing_deg is not None and float(start_angle_deg) >= 0:
        half_angle_deg = float(start_angle_deg)
        start_angle_deg = _normalize_bearing_deg(center_bearing_deg - half_angle_deg)
        end_angle_deg = _normalize_bearing_deg(center_bearing_deg + half_angle_deg)

    full_circle = (
        math.isclose(start_angle_deg, 0.0, abs_tol=1e-6)
        and math.isclose(end_angle_deg, 360.0, abs_tol=1e-6)
    )
    if full_circle:
        start_angle_deg = 0.0
        end_angle_deg = 360.0
    elif end_angle_deg < start_angle_deg:
        end_angle_deg += 360.0

    polygon = [(center_lat, center_lon)]
    for i in range(points + 1):
        fraction = i / points
        bearing = start_angle_deg + (end_angle_deg - start_angle_deg) * fraction
        lat, lon = project_point_from_bearing(center_lat, center_lon, _normalize_bearing_deg(bearing), radius_m)
        polygon.append((lat, lon))
    polygon.append((center_lat, center_lon))
    return polygon


def build_sector_split_points(
    center_lat: float,
    center_lon: float,
    radius_m: float,
    center_bearing_deg: float,
    half_angle_deg: float,
    inner_radius_m: float = 0.0,
    inner_half_angle_deg: float = 0.0,
    points: int = 48,
):
    """Return the two arc halves of a sector without any radial centerline."""
    if radius_m <= 0:
        return [], []

    def points_for_radius(target_radius, target_half_angle_deg):
        arc_points = []
        for i in range(points + 1):
            fraction = i / points
            clockwise_bearing = _normalize_bearing_deg(center_bearing_deg + target_half_angle_deg * fraction)
            anticlockwise_bearing = _normalize_bearing_deg(center_bearing_deg - target_half_angle_deg * fraction)

            cw_lat, cw_lon = project_point_from_bearing(center_lat, center_lon, clockwise_bearing, target_radius)
            acw_lat, acw_lon = project_point_from_bearing(center_lat, center_lon, anticlockwise_bearing, target_radius)

            arc_points.append((cw_lat, cw_lon, acw_lat, acw_lon))
        return arc_points

    outer_points = points_for_radius(radius_m, half_angle_deg)
    clockwise_points = [(cw_lat, cw_lon) for cw_lat, cw_lon, _, _ in outer_points]
    anticlockwise_points = [(acw_lat, acw_lon) for _, _, acw_lat, acw_lon in outer_points]

    if inner_radius_m > 0:
        inner_half = inner_half_angle_deg if inner_half_angle_deg > 0 else half_angle_deg
        inner_points = points_for_radius(inner_radius_m, inner_half)
        inner_clockwise_points = [(cw_lat, cw_lon) for cw_lat, cw_lon, _, _ in inner_points]
        inner_anticlockwise_points = [(acw_lat, acw_lon) for _, _, acw_lat, acw_lon in inner_points]
        return clockwise_points, anticlockwise_points, inner_clockwise_points, inner_anticlockwise_points

    return clockwise_points, anticlockwise_points


def project_geometry_table(path: str):
    """Return a row-wise task geometry table for the app viewer and audit tooling."""
    pts = extract_task_points_from_igc(path)
    if not pts:
        return []

    by_idx = {p["idx"]: p for p in pts}
    sectors = {s["idx"]: s for s in extract_task_sectors_from_igc(path)}
    rows = []

    start_idx = -1
    if start_idx in by_idx:
        start_pt = by_idx[start_idx]
        next_idx = min(j for j in by_idx if j > start_idx)
        next_pt = by_idx[next_idx]
        first_leg_deg = _bearing_between_points(start_pt["lat"], start_pt["lon"], next_pt["lat"], next_pt["lon"])
        start_sector = sectors.get(start_idx, {})
        rows.append({
            "point": "Start",
            "idx": start_idx,
            "first_leg_deg": round(first_leg_deg, 6),
            "inbound_deg": None,
            "outbound_deg": round(first_leg_deg, 6),
            "internal_bisector_deg": None,
            "external_bisector_deg": None,
            "style": start_sector.get("style"),
            "radius_m": start_sector.get("radius_m"),
            "inner_radius_m": start_sector.get("inner_radius_m"),
            "a1_deg": start_sector.get("a1_deg"),
            "a2_deg": start_sector.get("a2_deg"),
            "a12_deg": start_sector.get("orientation_deg"),
        })

    for idx in sorted(j for j in by_idx if j >= 0):
        tp = by_idx[idx]
        prev_idx = max(j for j in by_idx if j < idx)
        prev_pt = by_idx[prev_idx]
        inbound_deg = _bearing_between_points(prev_pt["lat"], prev_pt["lon"], tp["lat"], tp["lon"])

        row = {
            "point": f"TP{idx}",
            "idx": idx,
            "first_leg_deg": None,
            "inbound_deg": round(inbound_deg, 6),
            "outbound_deg": None,
            "internal_bisector_deg": None,
            "external_bisector_deg": None,
            "style": None,
            "radius_m": None,
            "inner_radius_m": None,
            "a1_deg": None,
            "a2_deg": None,
            "a12_deg": None,
        }

        next_candidates = [j for j in by_idx if j > idx]
        if next_candidates:
            next_idx = min(next_candidates)
            next_pt = by_idx[next_idx]
            outbound_deg = _bearing_between_points(tp["lat"], tp["lon"], next_pt["lat"], next_pt["lon"])
            internal_bisector_deg = _internal_bisector_from_legs(inbound_deg, outbound_deg)
            external_bisector_deg = _outward_bisector_from_legs(inbound_deg, outbound_deg)
            row["outbound_deg"] = round(outbound_deg, 6)
            row["internal_bisector_deg"] = round(internal_bisector_deg, 6)
            row["external_bisector_deg"] = round(external_bisector_deg, 6)

        sector = sectors.get(idx, {})
        row["style"] = sector.get("style")
        row["radius_m"] = sector.get("radius_m")
        row["inner_radius_m"] = sector.get("inner_radius_m")
        row["a1_deg"] = sector.get("a1_deg")
        row["a2_deg"] = sector.get("a2_deg")
        row["a12_deg"] = sector.get("orientation_deg")
        rows.append(row)

    finish_idx = max(by_idx)
    finish_pt = by_idx[finish_idx]
    prev_idx = max(j for j in by_idx if j < finish_idx)
    prev_pt = by_idx[prev_idx]
    inbound_deg = _bearing_between_points(prev_pt["lat"], prev_pt["lon"], finish_pt["lat"], finish_pt["lon"])
    finish_sector = sectors.get(finish_idx, {})
    rows.append({
        "point": "Finish",
        "idx": finish_idx,
        "first_leg_deg": None,
        "inbound_deg": round(inbound_deg, 6),
        "outbound_deg": None,
        "internal_bisector_deg": None,
        "external_bisector_deg": None,
        "style": finish_sector.get("style"),
        "radius_m": finish_sector.get("radius_m"),
        "inner_radius_m": finish_sector.get("inner_radius_m"),
        "a1_deg": finish_sector.get("a1_deg"),
        "a2_deg": finish_sector.get("a2_deg"),
        "a12_deg": finish_sector.get("orientation_deg"),
    })

    return rows
