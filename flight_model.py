from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import libigc

from geo_task import (
    extract_finish_sector_from_igc,
    extract_glider_start_time,
    extract_start_sector_from_igc,
    extract_task_points_from_igc,
    extract_task_sectors_from_igc,
)


PARSE_PARALLEL_MIN_FILES = 32


@dataclass
class FlightFix:
    lat: float
    lon: float
    timestamp: Any = None
    alt: float | None = None
    gnss_alt: float | None = None
    press_alt: float | None = None


@dataclass
class FlightDataProxy:
    fixes: list[FlightFix] = field(default_factory=list)
    valid: bool = True


@dataclass
class FlightRecord:
    file_path: str
    flight: Any = None
    fixes: list[Any] = field(default_factory=list)
    task_points: list[dict[str, Any]] = field(default_factory=list)
    task_sectors: list[dict[str, Any]] = field(default_factory=list)
    start_sector: dict[str, Any] | None = None
    finish_sector: dict[str, Any] | None = None
    start_time: str | None = None
    valid: bool = False

    @classmethod
    def from_path(cls, file_path: str) -> "FlightRecord":
        flight = libigc.Flight.create_from_file(file_path)
        if not flight.valid:
            return cls(file_path=file_path, flight=flight, valid=False)

        task_points = extract_task_points_from_igc(file_path)
        task_sectors = extract_task_sectors_from_igc(file_path)
        start_sector = extract_start_sector_from_igc(file_path)
        finish_sector = extract_finish_sector_from_igc(file_path)

        turnpoint_sectors = [
            sector
            for sector in task_sectors
            if sector.get("idx") not in {start_sector.get("idx") if start_sector else None, finish_sector.get("idx") if finish_sector else None}
            and sector.get("idx") is not None
        ]
        first_turnpoint_sector = (
            min(turnpoint_sectors, key=lambda sector: int(sector.get("idx", 10**9)))
            if turnpoint_sectors
            else None
        )
        start_time = extract_glider_start_time(flight.fixes, start_sector, first_turnpoint_sector)

        return cls(
            file_path=file_path,
            flight=flight,
            fixes=list(flight.fixes),
            task_points=task_points,
            task_sectors=task_sectors,
            start_sector=start_sector,
            finish_sector=finish_sector,
            start_time=start_time,
            valid=True,
        )

    @property
    def lons(self) -> list[float]:
        return [float(fix.lon) for fix in self.fixes]

    @property
    def lats(self) -> list[float]:
        return [float(fix.lat) for fix in self.fixes]


def load_flight_record(file_path: str) -> FlightRecord:
    return FlightRecord.from_path(file_path)


def _serialize_timestamp(timestamp: Any) -> Any:
    if timestamp is None or isinstance(timestamp, (str, int, float, bool)):
        return timestamp
    if hasattr(timestamp, "isoformat"):
        return {"kind": "datetime", "value": timestamp.isoformat()}
    return str(timestamp)


def _deserialize_timestamp(timestamp: Any) -> Any:
    if isinstance(timestamp, dict) and timestamp.get("kind") == "datetime":
        return datetime.fromisoformat(str(timestamp.get("value") or ""))
    return timestamp


def _serialize_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def serialize_flight_record(file_path: str) -> dict[str, Any]:
    record = load_flight_record(file_path)
    return {
        "file_path": record.file_path,
        "valid": record.valid,
        "fixes": [
            {
                "lat": float(fix.lat),
                "lon": float(fix.lon),
                "timestamp": _serialize_timestamp(getattr(fix, "timestamp", None)),
                "alt": _serialize_optional_float(getattr(fix, "alt", None)),
                "gnss_alt": _serialize_optional_float(getattr(fix, "gnss_alt", None)),
                "press_alt": _serialize_optional_float(getattr(fix, "press_alt", None)),
            }
            for fix in record.fixes
        ],
        "task_points": record.task_points,
        "task_sectors": record.task_sectors,
        "start_sector": record.start_sector,
        "finish_sector": record.finish_sector,
        "start_time": record.start_time,
    }


def _parse_workers_for_count(count: int) -> int:
    cpu_total = max(1, int(os.cpu_count() or 1))
    env_override = os.environ.get("IGC_PARSE_WORKERS", "").strip()
    if env_override:
        try:
            return max(1, min(cpu_total, int(env_override), int(count)))
        except ValueError:
            pass
    return max(1, min(cpu_total, int(count)))


def serialize_flight_records(
    file_paths: list[str],
    *,
    executor: ProcessPoolExecutor | None = None,
) -> list[dict[str, Any]]:
    paths = [str(path) for path in file_paths if path]
    if not paths:
        return []
    if len(paths) < PARSE_PARALLEL_MIN_FILES:
        return [serialize_flight_record(path) for path in paths]

    workers = _parse_workers_for_count(len(paths))
    if workers <= 1:
        return [serialize_flight_record(path) for path in paths]

    try:
        if executor is not None:
            return list(executor.map(serialize_flight_record, paths))
        with ProcessPoolExecutor(max_workers=workers) as ephemeral_executor:
            return list(ephemeral_executor.map(serialize_flight_record, paths))
    except Exception:
        return [serialize_flight_record(path) for path in paths]


def flight_record_from_payload(payload: dict[str, Any]) -> FlightRecord:
    fixes = [
        FlightFix(
            lat=float(item["lat"]),
            lon=float(item["lon"]),
            timestamp=_deserialize_timestamp(item.get("timestamp")),
            alt=_serialize_optional_float(item.get("alt")),
            gnss_alt=_serialize_optional_float(item.get("gnss_alt")),
            press_alt=_serialize_optional_float(item.get("press_alt")),
        )
        for item in payload.get("fixes", [])
    ]
    valid = bool(payload.get("valid"))
    flight = FlightDataProxy(fixes=fixes, valid=valid) if valid else None
    return FlightRecord(
        file_path=str(payload.get("file_path") or ""),
        flight=flight,
        fixes=fixes,
        task_points=list(payload.get("task_points") or []),
        task_sectors=list(payload.get("task_sectors") or []),
        start_sector=payload.get("start_sector"),
        finish_sector=payload.get("finish_sector"),
        start_time=payload.get("start_time"),
        valid=valid,
    )


def serve() -> int:
    executor: ProcessPoolExecutor | None = None
    cpu_total = max(1, int(os.cpu_count() or 1))
    if cpu_total > 1:
        executor = ProcessPoolExecutor(max_workers=cpu_total)
    for line in sys.stdin:
        request_text = line.strip()
        if not request_text:
            continue
        try:
            request = json.loads(request_text)
            paths = [str(path) for path in request.get("paths", []) if path]
            response = {"ok": True, "records": serialize_flight_records(paths, executor=executor)}
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
    if executor is not None:
        executor.shutdown(wait=True, cancel_futures=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--serve":
        return serve()
    payloads = serialize_flight_records([path for path in args if path])
    json.dump(payloads, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
