from __future__ import annotations

from dataclasses import dataclass, field

from flight_fix_utils import build_time_offsets, fix_timestamp


@dataclass
class TimelineState:
    time_offsets: list[float] = field(default_factory=list)
    utc_timestamps: list[float] = field(default_factory=list)
    index: int = 0
    total_seconds: float = 0.0

    @classmethod
    def from_flight(cls, flight_record) -> "TimelineState":
        fixes = list(flight_record.fixes)
        offsets = build_time_offsets(fixes)
        utc_timestamps: list[float] = []
        for fix in fixes:
            timestamp = fix_timestamp(fix)
            if timestamp is None:
                utc_timestamps = []
                break
            if utc_timestamps and timestamp < utc_timestamps[-1]:
                timestamp = utc_timestamps[-1]
            utc_timestamps.append(timestamp)
        return cls(
            time_offsets=offsets,
            utc_timestamps=utc_timestamps,
            total_seconds=offsets[-1] if offsets else 0.0,
        )

    def set_index(self, value: int) -> None:
        if not self.time_offsets:
            self.index = 0
            return
        self.index = max(0, min(int(value), len(self.time_offsets) - 1))

    def elapsed_seconds(self) -> float:
        if not self.time_offsets:
            return 0.0
        return self.time_offsets[max(0, min(self.index, len(self.time_offsets) - 1))]

    def progress(self) -> float:
        if not self.time_offsets or self.total_seconds <= 0:
            return 0.0
        return self.elapsed_seconds() / self.total_seconds
