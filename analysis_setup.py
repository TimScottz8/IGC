from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from flight_fix_utils import has_any_altitude


class RecomputeImpact(str, Enum):
    QUICK = "Quick recompute"
    REBUILD = "Rebuild required"
    DEEP = "Deep recompute"


@dataclass(frozen=True)
class AnalysisParameters:
    max_distance_m: int = 500
    max_time_delta_s: int = 30
    max_altitude_delta_m: int = 800
    min_cluster_size: int = 2
    persistence_s: int = 300
    break_distance_m: int = 900
    break_duration_s: int = 120
    circling_grace_s: int = 60
    day_min_valid_flights: int = 2
    normalization_mode: str = "both"
    late_starter_rule: str = "median_split"
    aggregation_method: str = "median_iqr"
    resample_interval_s: int = 5
    distance_method: str = "geodesic"
    altitude_source: str = "any"

    def to_dict(self) -> dict[str, Any]:
        return dict(asdict(self))


IMPACT_MAP: dict[str, RecomputeImpact] = {
    "max_distance_m": RecomputeImpact.REBUILD,
    "max_time_delta_s": RecomputeImpact.REBUILD,
    "max_altitude_delta_m": RecomputeImpact.REBUILD,
    "min_cluster_size": RecomputeImpact.QUICK,
    "persistence_s": RecomputeImpact.QUICK,
    "break_distance_m": RecomputeImpact.QUICK,
    "break_duration_s": RecomputeImpact.QUICK,
    "circling_grace_s": RecomputeImpact.QUICK,
    "day_min_valid_flights": RecomputeImpact.QUICK,
    "normalization_mode": RecomputeImpact.QUICK,
    "late_starter_rule": RecomputeImpact.QUICK,
    "aggregation_method": RecomputeImpact.QUICK,
    "resample_interval_s": RecomputeImpact.DEEP,
    "distance_method": RecomputeImpact.DEEP,
    "altitude_source": RecomputeImpact.DEEP,
}


@dataclass
class ValidationSummary:
    total_flights: int = 0
    valid_flights: int = 0
    missing_start_time: int = 0
    missing_altitude: int = 0
    invalid_records: int = 0
    warnings: list[str] = field(default_factory=list)


def parameter_impact(field_name: str) -> RecomputeImpact:
    return IMPACT_MAP.get(field_name, RecomputeImpact.QUICK)


def changed_fields(current: AnalysisParameters, baseline: AnalysisParameters) -> list[str]:
    current_values = current.to_dict()
    baseline_values = baseline.to_dict()
    return [
        field_name
        for field_name, current_value in current_values.items()
        if current_value != baseline_values.get(field_name)
    ]


def highest_change_impact(current: AnalysisParameters, baseline: AnalysisParameters) -> RecomputeImpact:
    priorities = {
        RecomputeImpact.QUICK: 0,
        RecomputeImpact.REBUILD: 1,
        RecomputeImpact.DEEP: 2,
    }
    top = RecomputeImpact.QUICK
    for field_name in changed_fields(current, baseline):
        impact = parameter_impact(field_name)
        if priorities[impact] > priorities[top]:
            top = impact
    return top


def parameter_fingerprint(parameters: AnalysisParameters, analysis_version: str = "v1") -> str:
    payload = {
        "analysis_version": analysis_version,
        "parameters": parameters.to_dict(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return digest[:16]


def validate_flights(flights: list[Any], *, day_min_valid_flights: int) -> ValidationSummary:
    summary = ValidationSummary(total_flights=len(flights))

    for record in flights:
        is_valid = bool(getattr(record, "valid", False)) and bool(getattr(record, "fixes", None))
        if not is_valid:
            summary.invalid_records += 1
            continue

        summary.valid_flights += 1

        if not getattr(record, "start_time", None):
            summary.missing_start_time += 1

        fixes = list(getattr(record, "fixes", []) or [])
        if not has_any_altitude(fixes):
            summary.missing_altitude += 1

    if summary.valid_flights < int(day_min_valid_flights):
        summary.warnings.append(
            f"Only {summary.valid_flights} valid flights; day minimum is {int(day_min_valid_flights)}."
        )
    if summary.missing_start_time > 0:
        summary.warnings.append(f"{summary.missing_start_time} valid flights are missing start time.")
    if summary.missing_altitude > 0:
        summary.warnings.append(f"{summary.missing_altitude} valid flights are missing altitude data.")
    if summary.invalid_records > 0:
        summary.warnings.append(f"{summary.invalid_records} selected records are invalid and will be excluded.")

    return summary
