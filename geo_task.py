import math
import os
import re
from datetime import datetime, timezone


def parse_igc_lat_lon(value: str):
    # IGC latitude/longitude values are encoded in the protocol as DDDMM.mmmmN/S or
    # DDDMM.mmmmE/W, where the hemisphere letter is appended to the numeric value.
    # We convert those decimal-minute strings into normal signed decimal degrees.
    value = str(value).strip()
    if not value:
        return None
    hemisphere = value[-1].upper()
    raw = value[:-1]
    if hemisphere in {"N", "S"}:
        degrees = int(raw[:2])
        minutes = float(raw[2:])
    else:
        degrees = int(raw[:3])
        minutes = float(raw[3:])
    decimal = degrees + (minutes / 60.0)
    if hemisphere in {"S", "W"}:
        decimal *= -1
    return decimal


def _parse_oz_records(path: str):
    """Aggregate SeeYou/IGC observation-zone definitions by index.

    A real task file often splits each OZ into two lines: one line carries the
    sector parameters (Style, R1, A1, R2, A2, A12, etc.) and a second line carries
    the waypoint coordinates for the same index. We normalise those into one dict
    per task index before building either task points or sector overlays.
    """
    records = {}
    if not os.path.exists(path):
        return records

    with open(path, "r", encoding="ISO-8859-1") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            header_match = re.match(r"(?i)([A-Z0-9]+\s*OZ(?:N)?)\s*=\s*(-?\d+)", line)
            if not header_match:
                continue
            idx = int(header_match.group(2))
            rec = records.setdefault(idx, {})

            for key, value in re.findall(r"([A-Za-z0-9]+)\s*=\s*([^,]+)", line):
                key_lower = key.lower()
                if key_lower == "lat":
                    rec["lat"] = parse_igc_lat_lon(value)
                elif key_lower == "lon":
                    rec["lon"] = parse_igc_lat_lon(value)
                elif key_lower == "style":
                    rec["style"] = int(float(value))
                elif key_lower == "a1":
                    rec["a1_deg"] = float(value)
                elif key_lower == "a2":
                    rec["a2_deg"] = float(value)
                elif key_lower == "a12":
                    rec["orientation_deg"] = float(value)
                elif key_lower == "r1":
                    m = re.match(r"([0-9.]+)([a-zA-Z]+)", value)
                    if m:
                        val = float(m.group(1))
                        unit = m.group(2).lower()
                        rec["radius_m"] = val * 1000 if unit == "km" else val
                elif key_lower == "r2":
                    m = re.match(r"([0-9.]+)([a-zA-Z]+)?", value)
                    if m:
                        val = float(m.group(1))
                        unit = (m.group(2) or "m").lower()
                        rec["inner_radius_m"] = val * 1000 if unit == "km" else val
                elif key_lower == "line":
                    rec["line_flag"] = int(float(value))

    return records


def extract_task_points_from_igc(path: str):
    # IGC files can carry task definition records (e.g. LLXVOZ=, LXNAOZN= or
    # LSEEYOU OZ=) with coordinates split across adjacent lines. We aggregate them
    # by index so the task route is drawn from the real task metadata rather than a
    # partial subset of the records.
    task_points = []
    for idx, record in _parse_oz_records(path).items():
        lat = record.get("lat")
        lon = record.get("lon")
        if lat is None or lon is None:
            continue
        task_points.append({"idx": idx, "name": f"Task {idx}", "lat": lat, "lon": lon})
    return sorted(task_points, key=lambda item: item["idx"])


def _bearing_between_points(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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
    return value % 360.0


def _heading_to_unit_vector(bearing_deg: float):
    bearing_rad = math.radians(bearing_deg)
    return (math.sin(bearing_rad), math.cos(bearing_rad))


def _unit_vector_bearing(unit_vector):
    x, y = unit_vector
    return _normalize_bearing_deg(math.degrees(math.atan2(x, y)))


def _internal_bisector_from_legs(inbound_bearing_deg: float, outbound_bearing_deg: float) -> float:
    # The angle bisector is computed from the rays leaving the turning point.
    # The incoming leg direction points toward the point, so the ray used for the
    # angle at the point is the opposite of that heading. The outgoing leg already
    # points away from the point. We normalize both rays and add them.
    inbound_away = (-_heading_to_unit_vector(inbound_bearing_deg)[0], -_heading_to_unit_vector(inbound_bearing_deg)[1])
    outbound_away = _heading_to_unit_vector(outbound_bearing_deg)

    vx = inbound_away[0] + outbound_away[0]
    vy = inbound_away[1] + outbound_away[1]
    norm = math.hypot(vx, vy)
    if norm == 0:
        return _normalize_bearing_deg(outbound_bearing_deg)
    return _unit_vector_bearing((vx / norm, vy / norm))


def _outward_bisector_from_legs(inbound_bearing_deg: float, outbound_bearing_deg: float) -> float:
    # The visible turnpoint sector opens on the opposite side of the turning point,
    # so the actual sector axis is the opposite ray of the task-side bisector.
    task_side_bisector = _internal_bisector_from_legs(inbound_bearing_deg, outbound_bearing_deg)
    return _normalize_bearing_deg(task_side_bisector + 180.0)


def _infer_sector_orientation(path: str, idx: int, lat: float, lon: float, style: int | None = None, fixed_axis_deg: float | None = None):
    task_points = extract_task_points_from_igc(path)
    if not task_points:
        return None
    by_idx = {p["idx"]: p for p in task_points}
    prev_idx = None
    next_idx = None
    for candidate in sorted(by_idx):
        if candidate < idx:
            prev_idx = candidate
        elif candidate > idx:
            next_idx = candidate
            break

    if style == 0 and fixed_axis_deg is not None:
        return _normalize_bearing_deg(fixed_axis_deg)

    if idx == -1 and next_idx is not None:
        next_pt = by_idx[next_idx]
        outbound = _bearing_between_points(lat, lon, next_pt["lat"], next_pt["lon"])
        if style in (2, 3):
            # SeeYou starts are defined around the external axis, so the sector axis is
            # the reciprocal of the outbound leg direction when the file says "to next point".
            return _normalize_bearing_deg(outbound + 180.0)
        return _normalize_bearing_deg(outbound + 180.0)

    if prev_idx is not None and next_idx is not None:
        prev_pt = by_idx[prev_idx]
        next_pt = by_idx[next_idx]
        inbound = _bearing_between_points(prev_pt["lat"], prev_pt["lon"], lat, lon)
        outbound = _bearing_between_points(lat, lon, next_pt["lat"], next_pt["lon"])
        if style == 1:
            # SeeYou defines the turnpoint sector as centered on the external bisector of the
            # angle between the inbound and outbound legs, so the relevant axis is the opposite
            # ray of the interior bisector, not the interior bisector itself.
            return _outward_bisector_from_legs(inbound, outbound)
        if style == 2:
            return _normalize_bearing_deg(outbound)
        if style == 3:
            return _normalize_bearing_deg(inbound)
        return _outward_bisector_from_legs(inbound, outbound)

    if prev_idx is not None and next_idx is None:
        prev_pt = by_idx[prev_idx]
        inbound = _bearing_between_points(prev_pt["lat"], prev_pt["lon"], lat, lon)
        if style in (2, 3):
            return _normalize_bearing_deg(inbound + 180.0)
        return _normalize_bearing_deg(inbound + 180.0)

    if prev_idx is not None:
        prev_pt = by_idx[prev_idx]
        return _bearing_between_points(prev_pt["lat"], prev_pt["lon"], lat, lon)

    if next_idx is not None:
        next_pt = by_idx[next_idx]
        return _bearing_between_points(lat, lon, next_pt["lat"], next_pt["lon"]) 

    return None


def extract_task_sectors_from_igc(path: str):
    """Return all SeeYou/IGC observation-zone sector definitions from a task file.

    This includes the start, turning points, and finish records. For a normal
    racing task the turning-point records are the cylinder-style sectors that
    define the valid radius around each waypoint. Start and finish zones can also
    be represented as line-like or multi-tier sectors depending on the task data.
    """
    sectors = []
    for idx, record in _parse_oz_records(path).items():
        if "radius_m" not in record or "a1_deg" not in record:
            continue
        lat = record.get("lat")
        lon = record.get("lon")

        # SeeYou tactics follow the task style semantics: Style 1 is the bisector of the
        # incoming/outgoing legs, Style 2 points to the next waypoint, Style 3 points to
        # the previous waypoint, and Style 0 uses the explicit A12 heading. Where we have
        # the adjacent task points we recalculate the axis to match the format rather than
        # trusting the raw line values alone.
        orientation = None
        if lat is not None and lon is not None:
            orientation = _infer_sector_orientation(
                path,
                idx,
                lat,
                lon,
                style=record.get("style"),
                fixed_axis_deg=record.get("orientation_deg"),
            )
        if orientation is None:
            orientation = record.get("orientation_deg")

        sectors.append({
            "idx": idx,
            "lat": lat,
            "lon": lon,
            "radius_m": record.get("radius_m"),
            "inner_radius_m": record.get("inner_radius_m", 0.0),
            "style": record.get("style"),
            "a1_deg": record.get("a1_deg"),
            "a2_deg": record.get("a2_deg", 0.0),
            "orientation_deg": orientation,
            "line_flag": record.get("line_flag", 0),
        })
    return sorted(sectors, key=lambda item: item["idx"])


def extract_start_sector_from_igc(path: str):
    candidates = extract_task_sectors_from_igc(path)
    if not candidates:
        return None
    for preferred in (-1, 0):
        for candidate in candidates:
            if candidate["idx"] == preferred:
                return candidate
    return candidates[0]


def extract_finish_sector_from_igc(path: str):
    candidates = extract_task_sectors_from_igc(path)
    if not candidates:
        return None
    max_idx = max(candidate["idx"] for candidate in candidates)
    for candidate in candidates:
        if candidate["idx"] == max_idx:
            return candidate
    return candidates[-1]


def project_point_from_bearing(center_lat: float, center_lon: float, bearing_deg: float, distance_m: float):
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
    if not sector:
        return False
    center_lat = sector.get("lat")
    center_lon = sector.get("lon")
    radius_m = float(sector.get("radius_m") or 0.0)
    if center_lat is None or center_lon is None or radius_m <= 0:
        return False

    if math.isclose(point_lat, center_lat, abs_tol=1e-12) and math.isclose(point_lon, center_lon, abs_tol=1e-12):
        return True

    distance_m = _distance_between_points_m(center_lat, center_lon, point_lat, point_lon)
    if distance_m > radius_m:
        return False

    inner_radius_m = float(sector.get("inner_radius_m") or 0.0)
    if inner_radius_m > 0 and distance_m < inner_radius_m:
        return False

    axis_deg = float(sector.get("orientation_deg") or 0.0)
    half_angle_deg = float(sector.get("a1_deg") or 0.0)
    if half_angle_deg <= 0:
        return True

    bearing_deg = _bearing_between_points(center_lat, center_lon, point_lat, point_lon)
    angular_distance = abs(((bearing_deg - axis_deg) + 540.0) % 360.0 - 180.0)
    return angular_distance <= half_angle_deg


def format_human_readable_datetime(value):
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
    if radius_m <= 0:
        return []

    # A1 is the half-angle either side of the sector axis. For a normal racing
    # turnpoint sector, the axis is the outward-facing bisector, not the task-side
    # bisector used to compute the turn geometry.
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
        # The sweep crosses 0/360 degrees, so keep the orientation explicit and
        # preserve the outward-facing wedge instead of flipping it to the inside.
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
    """Return the two arc halves of a sector without any radial centerline.

    The outer arc is defined by R1 and the optional inner arc by R2. SeeYou
    sectors are annular or single-radius depending on whether R2 is present, and
    the inner ring must use its own A2 angular opening rather than reusing A1.
    """
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
    """Return a row-wise task geometry table for the app viewer.

    Each row includes the task point name, leg bearings, bisectors, and the OZ
    parameters stored in the IGC file for direct audit against the source task.
    """
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
