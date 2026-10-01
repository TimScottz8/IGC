from __future__ import annotations

import os

from flight_model import FlightRecord, load_flight_record


class FlightCache(dict):
    """Cache parsed IGC flight records keyed by their absolute path."""

    @staticmethod
    def normalize_path(file_path: str) -> str:
        return os.path.abspath(file_path)

    def get_record(self, file_path: str) -> FlightRecord:
        normalized = self.normalize_path(file_path)
        if normalized in self:
            return self[normalized]
        record = load_flight_record(file_path)
        record.file_path = file_path
        self[normalized] = record
        return record

    def get_records(self, file_paths: list[str]) -> list[FlightRecord]:
        results: list[FlightRecord] = []
        seen: set[str] = set()
        for file_path in file_paths:
            normalized = self.normalize_path(file_path)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            record = self.get_record(file_path)
            if record.valid and record.flight is not None:
                results.append(record)
        return results
