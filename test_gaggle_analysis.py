from __future__ import annotations

from dataclasses import dataclass

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
        lat = center_lat + 0.0007 * __import__("math").cos(__import__("math").radians(angle))
        lon = center_lon + 0.0008 * __import__("math").sin(__import__("math").radians(angle))
        alt = 500.0 + i * 2.5
        fixes.append(FakeFix(lat=lat, lon=lon, timestamp=float(i * 5), alt=alt))
    return FlightRecord(file_path=name, flight=object(), fixes=fixes, valid=True)


def test_compute_thermal_gaggles_finds_cluster_for_two_circling_flights():
    record_a = _record("a.igc", 52.1, -1.0)
    record_b = _record("b.igc", 52.1005, -0.9995)

    clusters = compute_thermal_gaggles([record_a, record_b], max_distance_m=250.0, max_time_delta_s=12.0)

    assert clusters
    assert any(cluster["size"] >= 2 for cluster in clusters)
    assert any("members" in cluster for cluster in clusters)
