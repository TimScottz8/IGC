from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SceneState:
    selected_flight: Any | None = None
    selected_index: int = 0
    active_flights: list[Any] = field(default_factory=list)

    def set_selected_flight(self, flight: Any | None) -> None:
        self.selected_flight = flight
        self.selected_index = 0

    def set_selected_index(self, index: int) -> None:
        self.selected_index = max(0, int(index))

    def set_active_flights(self, flights: list[Any]) -> None:
        self.active_flights = list(flights)
        if self.selected_flight not in self.active_flights:
            self.selected_flight = self.active_flights[0] if self.active_flights else None
            self.selected_index = 0
