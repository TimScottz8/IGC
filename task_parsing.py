import os
import re


def parse_igc_lat_lon(value: str):
    """Convert IGC DDDMM.mmmmN/S or DDDMM.mmmmE/W values into signed decimal degrees."""
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


def _parse_oz_numeric(value: str, *, default_unit: str = "m"):
    """Parse OZ numeric values like "5km" or "250m" into metres for geometry math."""
    match = re.match(r"([0-9.]+)([a-zA-Z]+)?", str(value).strip())
    if not match:
        return None
    val = float(match.group(1))
    unit = (match.group(2) or default_unit).lower()
    return val * 1000 if unit == "km" else val


def _parse_oz_records(path: str):
    """Aggregate SeeYou/IGC observation-zone definitions by index."""
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
            record = records.setdefault(idx, {})
            for key, value in re.findall(r"([A-Za-z0-9]+)\s*=\s*([^,]+)", line):
                key_lower = key.lower()
                if key_lower == "lat":
                    record["lat"] = parse_igc_lat_lon(value)
                elif key_lower == "lon":
                    record["lon"] = parse_igc_lat_lon(value)
                elif key_lower == "style":
                    record["style"] = int(float(value))
                elif key_lower == "a1":
                    record["a1_deg"] = float(value)
                elif key_lower == "a2":
                    record["a2_deg"] = float(value)
                elif key_lower == "a12":
                    record["orientation_deg"] = float(value)
                elif key_lower == "r1":
                    record["radius_m"] = _parse_oz_numeric(value)
                elif key_lower == "r2":
                    record["inner_radius_m"] = _parse_oz_numeric(value)
                elif key_lower == "line":
                    record["line_flag"] = int(float(value))

    return records


def _task_point_from_oz_record(idx: int, record: dict):
    """Build the waypoint dictionary for one OZ task point record."""
    lat = record.get("lat")
    lon = record.get("lon")
    if lat is None or lon is None:
        return None
    return {"idx": idx, "name": f"Task {idx}", "lat": lat, "lon": lon}


def _infer_sector_orientation(path: str, idx: int, lat: float, lon: float, style: int | None = None, fixed_axis_deg: float | None = None):
    """Infer the sector's axis from the task legs and the OZ style when the file is ambiguous."""
    from sector_geometry import _bearing_between_points, _normalize_bearing_deg, _outward_bisector_from_legs

    task_points = extract_task_points_from_igc(path)
    if not task_points:
        return None

    by_idx = {point["idx"]: point for point in task_points}
    prev_idx = max((candidate for candidate in by_idx if candidate < idx), default=None)
    next_idx = min((candidate for candidate in by_idx if candidate > idx), default=None)

    if style == 0 and fixed_axis_deg is not None:
        return _normalize_bearing_deg(fixed_axis_deg)

    if idx == -1 and next_idx is not None:
        next_pt = by_idx[next_idx]
        outbound = _bearing_between_points(lat, lon, next_pt["lat"], next_pt["lon"])
        return _normalize_bearing_deg(outbound + 180.0)

    if prev_idx is not None and next_idx is not None:
        prev_pt = by_idx[prev_idx]
        next_pt = by_idx[next_idx]
        inbound = _bearing_between_points(prev_pt["lat"], prev_pt["lon"], lat, lon)
        outbound = _bearing_between_points(lat, lon, next_pt["lat"], next_pt["lon"])

        if style == 2:
            return _normalize_bearing_deg(outbound)
        if style == 3:
            return _normalize_bearing_deg(inbound)
        return _outward_bisector_from_legs(inbound, outbound)

    if prev_idx is not None:
        prev_pt = by_idx[prev_idx]
        inbound = _bearing_between_points(prev_pt["lat"], prev_pt["lon"], lat, lon)
        return _normalize_bearing_deg(inbound + 180.0 if style in (2, 3) else inbound)

    if next_idx is not None:
        next_pt = by_idx[next_idx]
        outbound = _bearing_between_points(lat, lon, next_pt["lat"], next_pt["lon"])
        return _normalize_bearing_deg(outbound + 180.0 if style in (2, 3) else outbound)

    return None


def _sector_from_oz_record(path: str, idx: int, record: dict):
    """Turn a raw OZ definition into the sector metadata used for rendering and checks."""
    lat = record.get("lat")
    lon = record.get("lon")
    if lat is None or lon is None:
        return None

    style = record.get("style")
    orientation = None
    if lat is not None and lon is not None:
        orientation = _infer_sector_orientation(
            path,
            idx,
            lat,
            lon,
            style=style,
            fixed_axis_deg=record.get("orientation_deg"),
        )
    if orientation is None:
        orientation = record.get("orientation_deg")

    return {
        "idx": idx,
        "lat": lat,
        "lon": lon,
        "radius_m": record.get("radius_m"),
        "inner_radius_m": record.get("inner_radius_m", 0.0),
        "style": style,
        "a1_deg": record.get("a1_deg"),
        "a2_deg": record.get("a2_deg", 0.0),
        "orientation_deg": orientation,
        "line_flag": record.get("line_flag", 0),
    }


def extract_task_points_from_igc(path: str):
    """Read the IGC task waypoint list and return the ordered task points as lat/lon records."""
    task_points = []
    for idx, record in _parse_oz_records(path).items():
        point = _task_point_from_oz_record(idx, record)
        if point is not None:
            task_points.append(point)
    return sorted(task_points, key=lambda item: item["idx"])


def extract_task_sectors_from_igc(path: str):
    """Return all SeeYou/IGC observation-zone sector definitions from a task file."""
    sectors = []
    for idx, record in _parse_oz_records(path).items():
        if "radius_m" not in record or "a1_deg" not in record:
            continue
        sector = _sector_from_oz_record(path, idx, record)
        if sector is not None:
            sectors.append(sector)
    return sorted(sectors, key=lambda item: item["idx"])


def _find_sector_by_idx(sectors: list[dict], target_idx: int):
    """Look up a sector by its OZ index."""
    for sector in sectors:
        if sector["idx"] == target_idx:
            return sector
    return None


def extract_start_sector_from_igc(path: str):
    """Return the start sector, preferring the explicit -1 start OZ when present."""
    sectors = extract_task_sectors_from_igc(path)
    if not sectors:
        return None
    for preferred in (-1, 0):
        sector = _find_sector_by_idx(sectors, preferred)
        if sector is not None:
            return sector
    return sectors[0]


def extract_finish_sector_from_igc(path: str):
    """Return the finish sector defined by the largest OZ index in the task."""
    sectors = extract_task_sectors_from_igc(path)
    if not sectors:
        return None
    max_idx = max(sector["idx"] for sector in sectors)
    return _find_sector_by_idx(sectors, max_idx) or sectors[-1]
