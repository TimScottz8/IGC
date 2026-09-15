from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math

from flight_model import FlightRecord
from gaggle_analysis import compute_thermal_gaggles


@dataclass
class FakeFix:
    lat: float
    lon: float
    timestamp: float
    alt: float


def _record(name: str, center_lat: float, center_lon: float) -> FlightRecord:
    fixes: list[FakeFix] = []
    for i in range(12):
        angle = i * 30.0
        lat = center_lat + 0.0007 * math.cos(math.radians(angle))
        lon = center_lon + 0.0008 * math.sin(math.radians(angle))
        alt = 500.0 + i * 2.5
        fixes.append(FakeFix(lat=lat, lon=lon, timestamp=float(i * 5), alt=alt))
    return FlightRecord(file_path=name, flight=object(), fixes=fixes, valid=True)


def _record_segments(name: str, segments: list[tuple[float, float, float, int]]) -> FlightRecord:
    fixes: list[FakeFix] = []
    for start_s, center_lat, center_lon, sample_count in segments:
        for i in range(sample_count):
            angle = float((i % 12) * 30.0)
            lat = center_lat + 0.0007 * math.cos(math.radians(angle))
            lon = center_lon + 0.0008 * math.sin(math.radians(angle))
            alt = 500.0 + i * 2.0
            fixes.append(FakeFix(lat=lat, lon=lon, timestamp=float(start_s + (i * 5.0)), alt=alt))
    return FlightRecord(file_path=name, flight=object(), fixes=fixes, valid=True)


def test_compute_thermal_gaggles_finds_cluster_for_two_circling_flights():
    record_a = _record("a.igc", 52.1, -1.0)
    record_b = _record("b.igc", 52.1005, -0.9995)

    clusters = compute_thermal_gaggles([record_a, record_b], max_distance_m=250.0, max_time_delta_s=12.0)

    assert clusters
    assert any(cluster["size"] >= 2 for cluster in clusters)
    assert any("members" in cluster for cluster in clusters)


def test_compute_thermal_gaggles_respects_vertical_separation_filter():
    record_a = _record("a.igc", 52.1, -1.0)
    record_b = _record("b.igc", 52.1005, -0.9995)

    for fix in record_b.fixes:
        fix.alt = float(fix.alt) + 900.0

    clusters = compute_thermal_gaggles(
        [record_a, record_b],
        max_distance_m=250.0,
        max_time_delta_s=12.0,
        max_altitude_delta_m=300.0,
    )

    assert not clusters


def test_compute_thermal_gaggles_handles_datetime_timestamps():
    base = datetime(2026, 8, 8, 11, 0, 0)
    fixes_a: list[FakeFix] = []
    fixes_b: list[FakeFix] = []
    for i in range(12):
        angle = i * 30.0
        lat_a = 52.1 + 0.0007 * math.cos(math.radians(angle))
        lon_a = -1.0 + 0.0008 * math.sin(math.radians(angle))
        lat_b = 52.1005 + 0.0007 * math.cos(math.radians(angle))
        lon_b = -0.9995 + 0.0008 * math.sin(math.radians(angle))
        ts = base + timedelta(seconds=i * 5)
        fixes_a.append(FakeFix(lat=lat_a, lon=lon_a, timestamp=ts, alt=500.0 + i * 2.5))
        fixes_b.append(FakeFix(lat=lat_b, lon=lon_b, timestamp=ts, alt=505.0 + i * 2.5))

    record_a = FlightRecord(file_path="a.igc", flight=object(), fixes=fixes_a, valid=True)
    record_b = FlightRecord(file_path="b.igc", flight=object(), fixes=fixes_b, valid=True)

    clusters = compute_thermal_gaggles(
        [record_a, record_b],
        max_distance_m=250.0,
        max_time_delta_s=12.0,
        max_altitude_delta_m=200.0,
    )

    assert clusters
    assert any(cluster["timestamp"] > 0.0 for cluster in clusters)


def test_lifecycle_keeps_event_across_short_gap_when_still_nearby():
    record_a = _record_segments(
        "a.igc",
        [
            (0.0, 52.1, -1.0, 16),
            (160.0, 52.1001, -1.0001, 16),
        ],
    )
    record_b = _record_segments(
        "b.igc",
        [
            (0.0, 52.1004, -0.9996, 16),
            (160.0, 52.1005, -0.9997, 16),
        ],
    )

    clusters = compute_thermal_gaggles(
        [record_a, record_b],
        max_distance_m=300.0,
        max_time_delta_s=12.0,
        break_distance_m=900.0,
        break_duration_s=120.0,
        circling_grace_s=60.0,
    )

    assert len(clusters) == 1
    assert clusters[0]["last_timestamp"] - clusters[0]["first_timestamp"] >= 200.0


def test_lifecycle_splits_event_after_sustained_separation_distance():
    record_a = _record_segments(
        "a.igc",
        [
            (0.0, 52.1, -1.0, 16),
            (140.0, 52.13, -0.95, 16),
        ],
    )
    record_b = _record_segments(
        "b.igc",
        [
            (0.0, 52.1004, -0.9996, 16),
            (140.0, 52.1304, -0.9496, 16),
        ],
    )

    clusters = compute_thermal_gaggles(
        [record_a, record_b],
        max_distance_m=300.0,
        max_time_delta_s=12.0,
        break_distance_m=800.0,
        break_duration_s=120.0,
        circling_grace_s=60.0,
    )

    assert len(clusters) >= 2
