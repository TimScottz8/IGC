from __future__ import annotations

from dataclasses import dataclass, field
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
