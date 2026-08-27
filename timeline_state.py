from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TimelineState:
    time_offsets: list[float] = field(default_factory=list)
    index: int = 0
    total_seconds: float = 0.0

    @classmethod
    def from_flight(cls, flight_record) -> "TimelineState":
        offsets = cls._build_time_offsets(flight_record.fixes)
        return cls(time_offsets=offsets, total_seconds=offsets[-1] if offsets else 0.0)

    @staticmethod
    def _build_time_offsets(fixes: list) -> list[float]:
        if not fixes:
            return []

        first_timestamp = getattr(fixes[0], "timestamp", None)
        if first_timestamp is None:
            return [float(i) for i in range(len(fixes))]

        offsets: list[float] = []
        previous = 0.0
        for idx, fix in enumerate(fixes):
            timestamp = getattr(fix, "timestamp", None)
            if timestamp is None:
                offsets.append(float(idx))
                previous = offsets[-1]
                continue

            if isinstance(timestamp, (int, float)) and isinstance(first_timestamp, (int, float)):
                delta = float(timestamp - first_timestamp)
            else:
                delta_obj = timestamp - first_timestamp
                if hasattr(delta_obj, "total_seconds"):
                    delta = float(delta_obj.total_seconds())
                else:
                    delta = float(delta_obj)

            if delta < previous:
                delta = previous
            offsets.append(float(delta))
            previous = float(delta)

        if offsets[-1] <= 0.0:
            return [float(i) for i in range(len(fixes))]
        return offsets

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
