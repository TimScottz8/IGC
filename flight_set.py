from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from flight_model import FlightRecord, load_flight_record


@dataclass
class FlightSet:
    flights: list[FlightRecord] = field(default_factory=list)

    @classmethod
    def from_paths(cls, paths: Iterable[str]) -> "FlightSet":
        dataset = cls()
        dataset.flights = [load_flight_record(path) for path in paths if path]
        return dataset

    def add(self, flight: FlightRecord) -> None:
        self.flights.append(flight)

    def count(self) -> int:
        return len(self.flights)

    def by_start_time(self) -> list[FlightRecord]:
        return sorted(
            self.flights,
            key=lambda flight: (flight.start_time or "", flight.file_path),
        )

    def filter_by_day(self, day: str) -> list[FlightRecord]:
        return [flight for flight in self.flights if day in (flight.file_path or "")]

    def filter_by_class(self, class_name: str) -> list[FlightRecord]:
        return [flight for flight in self.flights if class_name.lower() in (flight.file_path or "").lower()]

    def summary(self) -> dict[str, object]:
        return {
            "count": len(self.flights),
            "with_start_time": sum(1 for flight in self.flights if flight.start_time),
            "start_times": [flight.start_time for flight in self.by_start_time() if flight.start_time],
        }
