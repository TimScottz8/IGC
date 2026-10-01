from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from analysis_setup import AnalysisParameters, parameter_fingerprint


CONTRACT_NAME = "igc_statistics"
CONTRACT_VERSION = "1.0.0"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_non_negative_number(value: Any) -> bool:
    return _is_number(value) and float(value) >= 0.0


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and value >= 0


def _in_unit_interval(value: Any) -> bool:
    return _is_number(value) and 0.0 <= float(value) <= 1.0


def _round_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def _round_seconds(value: float | None) -> int | None:
    if value is None:
        return None
    return int(round(float(value)))


def _iqr(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    ordered = sorted(float(v) for v in values)
    q1_index = int(round(0.25 * (len(ordered) - 1)))
    q3_index = int(round(0.75 * (len(ordered) - 1)))
    return max(0.0, ordered[q3_index] - ordered[q1_index])


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0.0:
        return None
    return float(numerator) / float(denominator)


def _csv_write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _json_write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = [dict(sorted(row.items(), key=lambda item: item[0])) for row in rows]
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class ContractContext:
    contract_name: str
    contract_version: str
    analysis_version: str
    parameter_fingerprint: str
    generated_at_utc: str

    def to_dict(self) -> dict[str, str]:
        return dict(asdict(self))


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    passed: bool
    severity: str
    message: str


@dataclass
class ValidationManifest:
    contract_version: str
    analysis_version: str
    parameter_fingerprint: str
    checks_passed: bool
    failed_checks: list[str]
    warning_checks: list[str]
    generated_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_name": CONTRACT_NAME,
            "contract_version": self.contract_version,
            "analysis_version": self.analysis_version,
            "parameter_fingerprint": self.parameter_fingerprint,
            "checks_passed": self.checks_passed,
            "failed_checks": list(self.failed_checks),
            "warning_checks": list(self.warning_checks),
            "generated_at_utc": self.generated_at_utc,
        }


def build_contract_context(
    parameters: AnalysisParameters,
    *,
    analysis_version: str = "v1",
    generated_at_utc: str | None = None,
) -> ContractContext:
    return ContractContext(
        contract_name=CONTRACT_NAME,
        contract_version=CONTRACT_VERSION,
        analysis_version=str(analysis_version),
        parameter_fingerprint=parameter_fingerprint(parameters, analysis_version=analysis_version),
        generated_at_utc=str(generated_at_utc or _utc_now_iso()),
    )


def build_day_summary_row(
    *,
    context: ContractContext,
    competition_id: str,
    competition_name: str,
    class_id: str,
    class_name: str,
    day_id: str,
    starter_count: int,
    valid_flight_count: int,
    excluded_flight_count: int,
    flight_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    quality_notes: list[str] | None = None,
) -> dict[str, Any]:
    flights = list(flight_rows)
    events = list(event_rows)

    participating = [row for row in flights if bool(row.get("entered_any_gaggle"))]
    with_first_join = [float(row["time_to_first_gaggle_join_s"]) for row in flights if row.get("time_to_first_gaggle_join_s") is not None]

    total_exposure_s = sum(float(row.get("gaggle_exposure_s", 0.0) or 0.0) for row in flights)
    total_airborne_s = sum(float(row.get("airborne_duration_s", 0.0) or 0.0) for row in flights)

    peak_size = max([int(event.get("size", 0) or 0) for event in events], default=0)

    late_rows = [
        row
        for row in flights
        if row.get("is_late_starter") is True
    ]
    late_joined_existing = sum(1 for row in late_rows if bool(row.get("joined_established_gaggle")))

    event_spreads = [
        float(event.get("start_time_spread_s"))
        for event in events
        if event.get("start_time_spread_s") is not None
    ]

    join_total = sum(int(row.get("join_event_count", 0) or 0) for row in flights)
    established_join_total = sum(int(row.get("established_join_count", 0) or 0) for row in flights)

    participation_rate = _safe_ratio(len(participating), max(starter_count, 0))
    normalized_peak = _safe_ratio(peak_size, max(starter_count, 0))
    exposure_ratio = _safe_ratio(total_exposure_s, total_airborne_s)
    late_join_rate = _safe_ratio(late_joined_existing, len(late_rows)) if late_rows else None
    accretion_rate = _safe_ratio(established_join_total, join_total) if join_total > 0 else None

    quality_flag = "ok"
    notes = list(quality_notes or [])
    if starter_count <= 0 or valid_flight_count <= 0:
        quality_flag = "insufficient_data"
    elif exposure_ratio is None:
        quality_flag = "partial"
        notes.append("total airborne duration is zero")

    return {
        "competition_id": str(competition_id),
        "competition_name": str(competition_name),
        "class_id": str(class_id),
        "class_name": str(class_name),
        "day_id": str(day_id),
        "starter_count": int(starter_count),
        "valid_flight_count": int(valid_flight_count),
        "excluded_flight_count": int(excluded_flight_count),
        "gaggle_participation_rate": _round_ratio(participation_rate),
        "peak_gaggle_size": int(peak_size),
        "normalized_peak_gaggle_size": _round_ratio(normalized_peak),
        "gaggle_time_exposure_ratio": _round_ratio(exposure_ratio),
        "median_time_to_first_gaggle_join_s": _round_seconds(median(with_first_join) if with_first_join else None),
        "late_starter_join_rate": _round_ratio(late_join_rate),
        "gaggle_start_time_mixing_iqr_s": _round_seconds(_iqr(event_spreads) if event_spreads else None),
        "established_gaggle_accretion_rate": _round_ratio(accretion_rate),
        "event_count": int(len(events)),
        "quality_flag": quality_flag,
        "quality_notes": "; ".join(notes) if notes else None,
        "analysis_version": context.analysis_version,
        "parameter_fingerprint": context.parameter_fingerprint,
    }


def build_competition_summary_row(
    *,
    context: ContractContext,
    competition_id: str,
    competition_name: str,
    class_id: str,
    class_name: str,
    year: int,
    day_rows: list[dict[str, Any]],
    skipped_day_count: int,
) -> dict[str, Any]:
    valid_days = [row for row in day_rows if row.get("quality_flag") != "insufficient_data"]

    def metric_values(name: str) -> list[float]:
        values: list[float] = []
        for row in valid_days:
            value = row.get(name)
            if value is None:
                continue
            values.append(float(value))
        return values

    def metric_median(name: str) -> float | int | None:
        values = metric_values(name)
        if not values:
            return None
        result = median(values)
        return _round_seconds(result) if name.endswith("_s") else _round_ratio(result)

    def metric_iqr(name: str) -> float | int | None:
        values = metric_values(name)
        spread = _iqr(values)
        if spread is None:
            return None
        return _round_seconds(spread) if name.endswith("_s") else _round_ratio(spread)

    primary_spreads = [
        metric_iqr("gaggle_participation_rate"),
        metric_iqr("normalized_peak_gaggle_size"),
        metric_iqr("gaggle_time_exposure_ratio"),
    ]
    spread_values = [float(item) for item in primary_spreads if item is not None]
    consistency = None
    if spread_values:
        consistency = max(0.0, min(1.0, 1.0 - (sum(spread_values) / len(spread_values))))

    completeness_flag = "ok"
    completeness_notes: list[str] = []
    if len(valid_days) == 0:
        completeness_flag = "insufficient_data"
        completeness_notes.append("no valid days")
    elif len(valid_days) == 1:
        completeness_flag = "partial"
        completeness_notes.append("single analysed day")

    return {
        "competition_id": str(competition_id),
        "competition_name": str(competition_name),
        "class_id": str(class_id),
        "class_name": str(class_name),
        "year": int(year),
        "analysed_day_count": int(len(valid_days)),
        "skipped_day_count": int(skipped_day_count),
        "median_gaggle_participation_rate": metric_median("gaggle_participation_rate"),
        "iqr_gaggle_participation_rate": metric_iqr("gaggle_participation_rate"),
        "median_normalized_peak_gaggle_size": metric_median("normalized_peak_gaggle_size"),
        "iqr_normalized_peak_gaggle_size": metric_iqr("normalized_peak_gaggle_size"),
        "median_gaggle_time_exposure_ratio": metric_median("gaggle_time_exposure_ratio"),
        "iqr_gaggle_time_exposure_ratio": metric_iqr("gaggle_time_exposure_ratio"),
        "median_time_to_first_gaggle_join_s": metric_median("median_time_to_first_gaggle_join_s"),
        "iqr_time_to_first_gaggle_join_s": metric_iqr("median_time_to_first_gaggle_join_s"),
        "median_late_starter_join_rate": metric_median("late_starter_join_rate"),
        "iqr_late_starter_join_rate": metric_iqr("late_starter_join_rate"),
        "median_gaggle_start_time_mixing_iqr_s": metric_median("gaggle_start_time_mixing_iqr_s"),
        "iqr_gaggle_start_time_mixing_iqr_s": metric_iqr("gaggle_start_time_mixing_iqr_s"),
        "median_established_gaggle_accretion_rate": metric_median("established_gaggle_accretion_rate"),
        "iqr_established_gaggle_accretion_rate": metric_iqr("established_gaggle_accretion_rate"),
        "day_to_day_consistency_score": _round_ratio(consistency),
        "completeness_flag": completeness_flag,
        "completeness_notes": "; ".join(completeness_notes) if completeness_notes else None,
        "analysis_version": context.analysis_version,
        "parameter_fingerprint": context.parameter_fingerprint,
    }


def validate_contract_datasets(
    *,
    context: ContractContext,
    flight_rows: list[dict[str, Any]],
    day_rows: list[dict[str, Any]],
    competition_rows: list[dict[str, Any]],
    day_min_valid_flights: int,
) -> tuple[ValidationManifest, list[CheckResult]]:
    checks: list[CheckResult] = []

    def check(check_id: str, passed: bool, severity: str, message: str) -> None:
        checks.append(CheckResult(check_id=check_id, passed=bool(passed), severity=severity, message=message))

    key_flight = {
        (str(r.get("competition_id")), str(r.get("class_id")), str(r.get("day_id")), str(r.get("flight_id")))
        for r in flight_rows
    }
    key_day = {(str(r.get("competition_id")), str(r.get("class_id")), str(r.get("day_id"))) for r in day_rows}
    key_comp = {(str(r.get("competition_id")), str(r.get("class_id"))) for r in competition_rows}

    check(
        "key_uniqueness",
        len(key_flight) == len(flight_rows) and len(key_day) == len(day_rows) and len(key_comp) == len(competition_rows),
        "error",
        "Primary key uniqueness across all datasets",
    )

    rate_fields = [
        "gaggle_participation_rate",
        "normalized_peak_gaggle_size",
        "gaggle_time_exposure_ratio",
        "late_starter_join_rate",
        "established_gaggle_accretion_rate",
    ]
    day_rate_ok = True
    for row in day_rows:
        for field in rate_fields:
            value = row.get(field)
            if value is None:
                continue
            if not _in_unit_interval(value):
                day_rate_ok = False
                break
    check("day_rate_domain", day_rate_ok, "error", "Day-level rates are null or in [0,1]")

    day_counts_ok = True
    for row in day_rows:
        if not _is_non_negative_int(row.get("starter_count")):
            day_counts_ok = False
            break
        if not _is_non_negative_int(row.get("valid_flight_count")):
            day_counts_ok = False
            break
        if not _is_non_negative_int(row.get("excluded_flight_count")):
            day_counts_ok = False
            break
        if not _is_non_negative_int(row.get("event_count")):
            day_counts_ok = False
            break
    check("day_count_domain", day_counts_ok, "error", "Day-level count fields are non-negative integers")

    duration_fields = ["median_time_to_first_gaggle_join_s", "gaggle_start_time_mixing_iqr_s"]
    day_duration_ok = True
    for row in day_rows:
        for field in duration_fields:
            value = row.get(field)
            if value is None:
                continue
            if not _is_non_negative_number(value):
                day_duration_ok = False
                break
    check("day_duration_domain", day_duration_ok, "error", "Day-level duration fields are null or non-negative")

    day_relations_ok = True
    for row in day_rows:
        starter_count = int(row.get("starter_count", 0) or 0)
        valid_count = int(row.get("valid_flight_count", 0) or 0)
        peak_size = int(row.get("peak_gaggle_size", 0) or 0)
        if valid_count > starter_count:
            day_relations_ok = False
            break
        if starter_count > 0 and peak_size > starter_count:
            day_relations_ok = False
            break
    check("day_relations", day_relations_ok, "error", "Day-level relational constraints hold")

    day_event_consistency_ok = True
    for row in day_rows:
        event_count = int(row.get("event_count", 0) or 0)
        participation_rate = row.get("gaggle_participation_rate")
        median_join = row.get("median_time_to_first_gaggle_join_s")
        if event_count == 0 and participation_rate not in (None, 0, 0.0):
            day_event_consistency_ok = False
            break
        if participation_rate in (0, 0.0) and median_join is not None:
            day_event_consistency_ok = False
            break
    check("day_event_consistency", day_event_consistency_ok, "error", "Day event and join-time consistency checks")

    min_day_quality_ok = True
    for row in day_rows:
        valid_count = int(row.get("valid_flight_count", 0) or 0)
        quality = str(row.get("quality_flag", ""))
        if valid_count < int(day_min_valid_flights) and quality == "ok":
            min_day_quality_ok = False
            break
    check(
        "day_quality_threshold",
        min_day_quality_ok,
        "warning",
        "Days below minimum valid flight threshold are not marked as fully publishable",
    )

    fingerprint_ok = True
    version_ok = True
    for row in [*flight_rows, *day_rows, *competition_rows]:
        if str(row.get("parameter_fingerprint")) != context.parameter_fingerprint:
            fingerprint_ok = False
        if str(row.get("analysis_version")) != context.analysis_version:
            version_ok = False
    check("fingerprint_consistency", fingerprint_ok, "error", "Rows carry the current parameter fingerprint")
    check("analysis_version_consistency", version_ok, "error", "Rows carry the current analysis version")

    failed = [result.check_id for result in checks if (not result.passed and result.severity == "error")]
    warnings = [result.check_id for result in checks if (not result.passed and result.severity == "warning")]

    manifest = ValidationManifest(
        contract_version=context.contract_version,
        analysis_version=context.analysis_version,
        parameter_fingerprint=context.parameter_fingerprint,
        checks_passed=not failed,
        failed_checks=failed,
        warning_checks=warnings,
        generated_at_utc=context.generated_at_utc,
    )
    return manifest, checks


def export_contract_result_set(
    *,
    output_dir: str | Path,
    context: ContractContext,
    flight_rows: list[dict[str, Any]],
    day_rows: list[dict[str, Any]],
    competition_rows: list[dict[str, Any]],
    validation_manifest: ValidationManifest,
) -> dict[str, str]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    flight_rows_sorted = sorted(
        flight_rows,
        key=lambda row: (
            str(row.get("competition_id", "")),
            str(row.get("class_id", "")),
            str(row.get("day_id", "")),
            str(row.get("flight_id", "")),
        ),
    )
    day_rows_sorted = sorted(
        day_rows,
        key=lambda row: (
            str(row.get("competition_id", "")),
            str(row.get("class_id", "")),
            str(row.get("day_id", "")),
        ),
    )
    competition_rows_sorted = sorted(
        competition_rows,
        key=lambda row: (str(row.get("competition_id", "")), str(row.get("class_id", ""))),
    )

    contract_metadata_path = destination / "contract_metadata.json"
    flight_json_path = destination / "flight_day_metrics.json"
    day_json_path = destination / "day_summary_metrics.json"
    competition_json_path = destination / "competition_summary_metrics.json"
    flight_csv_path = destination / "flight_day_metrics.csv"
    day_csv_path = destination / "day_summary_metrics.csv"
    competition_csv_path = destination / "competition_summary_metrics.csv"
    manifest_path = destination / "validation_manifest.json"

    contract_metadata_path.write_text(json.dumps(context.to_dict(), sort_keys=True, indent=2) + "\n", encoding="utf-8")
    _json_write_rows(flight_json_path, flight_rows_sorted)
    _json_write_rows(day_json_path, day_rows_sorted)
    _json_write_rows(competition_json_path, competition_rows_sorted)
    _csv_write_rows(flight_csv_path, flight_rows_sorted)
    _csv_write_rows(day_csv_path, day_rows_sorted)
    _csv_write_rows(competition_csv_path, competition_rows_sorted)
    manifest_path.write_text(json.dumps(validation_manifest.to_dict(), sort_keys=True, indent=2) + "\n", encoding="utf-8")

    return {
        "contract_metadata_json": str(contract_metadata_path),
        "flight_day_metrics_json": str(flight_json_path),
        "day_summary_metrics_json": str(day_json_path),
        "competition_summary_metrics_json": str(competition_json_path),
        "flight_day_metrics_csv": str(flight_csv_path),
        "day_summary_metrics_csv": str(day_csv_path),
        "competition_summary_metrics_csv": str(competition_csv_path),
        "validation_manifest_json": str(manifest_path),
    }
