from __future__ import annotations

import json
import sys
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


@dataclass
class FlightFix:
    lat: float
    lon: float
    timestamp: Any = None


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
            }
            for fix in record.fixes
        ],
        "task_points": record.task_points,
        "task_sectors": record.task_sectors,
        "start_sector": record.start_sector,
        "finish_sector": record.finish_sector,
        "start_time": record.start_time,
    }


def flight_record_from_payload(payload: dict[str, Any]) -> FlightRecord:
    fixes = [
        FlightFix(
            lat=float(item["lat"]),
            lon=float(item["lon"]),
            timestamp=_deserialize_timestamp(item.get("timestamp")),
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
    for line in sys.stdin:
        request_text = line.strip()
        if not request_text:
            continue
        try:
            request = json.loads(request_text)
            paths = [str(path) for path in request.get("paths", []) if path]
            response = {"ok": True, "records": [serialize_flight_record(path) for path in paths]}
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--serve":
        return serve()
    payloads = [serialize_flight_record(path) for path in args if path]
    json.dump(payloads, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
