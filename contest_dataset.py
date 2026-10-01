from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text or "contest"


def _extract_year(value: str | None) -> int | None:
    if not value:
        return None
    matches = re.findall(r"(19\d{2}|20\d{2})", value)
    if not matches:
        return None
    return int(matches[-1])


@dataclass
class ContestMetadata:
    contest_id: str
    name: str
    year: int | None
    era: str | None = None
    source_path: str = ""
    class_names: list[str] = field(default_factory=list)
    day_labels: list[str] = field(default_factory=list)


@dataclass
class NormalizedFlightRecord:
    flight_id: str
    file_path: str
    contest_id: str
    contest_name: str
    year: int | None
    class_name: str
    day: str
    pilot_name: str | None = None
    start_time: str | None = None
    source_path: str = ""


@dataclass
class FlightGaggleSummary:
    flight_id: str
    first_gaggle_time: float | None = None
    peak_gaggle_size: int = 0
    time_to_join_gaggle: float | None = None
    total_time_in_gaggle: float = 0.0
    start_time_band: str = "unknown"
    formed_gaggle: bool = False
    joined_existing_gaggle: bool = False


class ContestDataset:
    """Minimal multi-contest dataset abstraction for the analysis layer."""

    def __init__(self, records: Iterable[NormalizedFlightRecord] | None = None) -> None:
        self.records = list(records or [])

    @classmethod
    def from_contest_paths(cls, contest_paths: list[str]) -> "ContestDataset":
        all_records: list[NormalizedFlightRecord] = []
        for contest_path in contest_paths:
            if not contest_path:
                continue
            contest_root = Path(contest_path)
            if not contest_root.exists():
                continue
            all_records.extend(cls._load_contest_records(contest_root))
        return cls(all_records)

    @classmethod
    def _load_contest_records(cls, contest_root: Path) -> list[NormalizedFlightRecord]:
        contest_name = contest_root.name
        contest_year = _extract_year(contest_name)
        records: list[NormalizedFlightRecord] = []

        for igc_file in sorted(contest_root.rglob("*.igc")):
            relative = igc_file.relative_to(contest_root)
            parts = relative.parts
            if len(parts) < 3:
                class_name = "unknown"
                day_value = "unknown"
            else:
                class_name = parts[0]
                day_value = parts[1]

            contest_id = _slugify(contest_name)
            flight_id = igc_file.stem
            records.append(
                NormalizedFlightRecord(
                    flight_id=flight_id,
                    file_path=str(igc_file),
                    contest_id=contest_id,
                    contest_name=contest_name,
                    year=contest_year,
                    class_name=class_name,
                    day=day_value,
                    pilot_name=None,
                    start_time=None,
                    source_path=str(contest_root),
                )
            )

        return records

    def filter_by_year(self, year: int | str) -> "ContestDataset":
        target = int(year)
        return ContestDataset([record for record in self.records if record.year == target])

    def filter_by_class(self, class_name: str) -> "ContestDataset":
        return ContestDataset([record for record in self.records if record.class_name == class_name])

    def filter_by_day(self, day: str) -> "ContestDataset":
        return ContestDataset([record for record in self.records if record.day == day])

    def filter_by_era(self, era: str) -> "ContestDataset":
        if era == "all":
            return ContestDataset(list(self.records))
        return ContestDataset([record for record in self.records if record.contest_name.lower().find(era.lower()) >= 0])

    def summary_rows(self) -> list[dict]:
        return [
            {
                "flight_id": record.flight_id,
                "contest_name": record.contest_name,
                "year": record.year,
                "class_name": record.class_name,
                "day": record.day,
                "file_path": record.file_path,
            }
            for record in self.records
        ]

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self):
        return iter(self.records)
