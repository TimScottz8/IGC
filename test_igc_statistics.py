from __future__ import annotations

import json
from pathlib import Path

from analysis_setup import AnalysisParameters
from igc_statistics import (
    build_competition_summary_row,
    build_contract_context,
    build_day_summary_row,
    export_contract_result_set,
    validate_contract_datasets,
)


def _flight_row(
    *,
    context,
    competition_id: str,
    class_id: str,
    day_id: str,
    flight_id: str,
    airborne_duration_s: int,
    entered_any_gaggle: bool,
    time_to_first_join_s: int | None,
    gaggle_exposure_s: int,
    is_late_starter: bool,
    joined_established_gaggle: bool,
    join_event_count: int,
    established_join_count: int,
) -> dict:
    return {
        "competition_id": competition_id,
        "competition_name": "Open Nationals",
        "class_id": class_id,
        "class_name": "15m",
        "day_id": day_id,
        "flight_id": flight_id,
        "pilot_code": flight_id.upper(),
        "start_time_utc_s": 100,
        "start_rank": 1,
        "airborne_duration_s": airborne_duration_s,
        "entered_any_gaggle": entered_any_gaggle,
        "first_gaggle_join_utc_s": 250 if entered_any_gaggle else None,
        "time_to_first_gaggle_join_s": time_to_first_join_s,
        "gaggle_exposure_s": gaggle_exposure_s,
        "gaggle_exposure_ratio": round(gaggle_exposure_s / max(airborne_duration_s, 1), 4),
        "is_late_starter": is_late_starter,
        "joined_established_gaggle": joined_established_gaggle,
        "join_event_count": join_event_count,
        "established_join_count": established_join_count,
        "analysis_version": context.analysis_version,
        "parameter_fingerprint": context.parameter_fingerprint,
    }


def test_contract_validation_and_export_are_deterministic(tmp_path: Path):
    context = build_contract_context(AnalysisParameters(), analysis_version="v1", generated_at_utc="2026-09-15T12:00:00Z")

    flights_day_1 = [
        _flight_row(
            context=context,
            competition_id="comp-1",
            class_id="15m",
            day_id="2026-08-08",
            flight_id="a",
            airborne_duration_s=1000,
            entered_any_gaggle=True,
            time_to_first_join_s=200,
            gaggle_exposure_s=450,
            is_late_starter=False,
            joined_established_gaggle=False,
            join_event_count=2,
            established_join_count=1,
        ),
        _flight_row(
            context=context,
            competition_id="comp-1",
            class_id="15m",
            day_id="2026-08-08",
            flight_id="b",
            airborne_duration_s=980,
            entered_any_gaggle=True,
            time_to_first_join_s=250,
            gaggle_exposure_s=400,
            is_late_starter=True,
            joined_established_gaggle=True,
            join_event_count=2,
            established_join_count=2,
        ),
        _flight_row(
            context=context,
            competition_id="comp-1",
            class_id="15m",
            day_id="2026-08-08",
            flight_id="c",
            airborne_duration_s=1020,
            entered_any_gaggle=False,
            time_to_first_join_s=None,
            gaggle_exposure_s=0,
            is_late_starter=True,
            joined_established_gaggle=False,
            join_event_count=0,
            established_join_count=0,
        ),
    ]

    day_1 = build_day_summary_row(
        context=context,
        competition_id="comp-1",
        competition_name="Open Nationals",
        class_id="15m",
        class_name="15m",
        day_id="2026-08-08",
        starter_count=3,
        valid_flight_count=3,
        excluded_flight_count=0,
        flight_rows=flights_day_1,
        event_rows=[
            {"size": 2, "start_time_spread_s": 120},
            {"size": 3, "start_time_spread_s": 180},
        ],
    )

    day_2 = {
        **day_1,
        "day_id": "2026-08-09",
        "gaggle_participation_rate": 0.3333,
        "normalized_peak_gaggle_size": 0.6667,
        "gaggle_time_exposure_ratio": 0.2500,
        "median_time_to_first_gaggle_join_s": 310,
        "late_starter_join_rate": 0.5000,
        "gaggle_start_time_mixing_iqr_s": 90,
        "established_gaggle_accretion_rate": 0.2500,
        "event_count": 1,
    }

    competition = build_competition_summary_row(
        context=context,
        competition_id="comp-1",
        competition_name="Open Nationals",
        class_id="15m",
        class_name="15m",
        year=2026,
        day_rows=[day_1, day_2],
        skipped_day_count=0,
    )

    manifest, checks = validate_contract_datasets(
        context=context,
        flight_rows=flights_day_1,
        day_rows=[day_1, day_2],
        competition_rows=[competition],
        day_min_valid_flights=2,
    )

    assert manifest.checks_passed is True
    assert not manifest.failed_checks
    assert checks

    output_1 = export_contract_result_set(
        output_dir=tmp_path / "run_1",
        context=context,
        flight_rows=flights_day_1,
        day_rows=[day_1, day_2],
        competition_rows=[competition],
        validation_manifest=manifest,
    )
    output_2 = export_contract_result_set(
        output_dir=tmp_path / "run_2",
        context=context,
        flight_rows=flights_day_1,
        day_rows=[day_1, day_2],
        competition_rows=[competition],
        validation_manifest=manifest,
    )

    day_json_1 = Path(output_1["day_summary_metrics_json"]).read_text(encoding="utf-8")
    day_json_2 = Path(output_2["day_summary_metrics_json"]).read_text(encoding="utf-8")
    manifest_json_1 = Path(output_1["validation_manifest_json"]).read_text(encoding="utf-8")
    manifest_json_2 = Path(output_2["validation_manifest_json"]).read_text(encoding="utf-8")

    assert day_json_1 == day_json_2
    assert manifest_json_1 == manifest_json_2

    parsed_manifest = json.loads(manifest_json_1)
    assert parsed_manifest["contract_version"] == "1.0.0"
    assert parsed_manifest["checks_passed"] is True


def test_validation_catches_out_of_range_metrics():
    context = build_contract_context(AnalysisParameters(), analysis_version="v1", generated_at_utc="2026-09-15T12:00:00Z")

    bad_day = {
        "competition_id": "comp-1",
        "class_id": "15m",
        "day_id": "2026-08-08",
        "starter_count": 2,
        "valid_flight_count": 2,
        "excluded_flight_count": 0,
        "gaggle_participation_rate": 1.5,
        "peak_gaggle_size": 3,
        "normalized_peak_gaggle_size": 1.5,
        "gaggle_time_exposure_ratio": 0.3,
        "median_time_to_first_gaggle_join_s": 120,
        "late_starter_join_rate": None,
        "gaggle_start_time_mixing_iqr_s": 50,
        "established_gaggle_accretion_rate": 0.2,
        "event_count": 1,
        "quality_flag": "ok",
        "quality_notes": None,
        "analysis_version": context.analysis_version,
        "parameter_fingerprint": context.parameter_fingerprint,
    }

    competition_row = {
        "competition_id": "comp-1",
        "class_id": "15m",
        "analysis_version": context.analysis_version,
        "parameter_fingerprint": context.parameter_fingerprint,
    }

    manifest, checks = validate_contract_datasets(
        context=context,
        flight_rows=[],
        day_rows=[bad_day],
        competition_rows=[competition_row],
        day_min_valid_flights=2,
    )

    assert manifest.checks_passed is False
    assert "day_rate_domain" in manifest.failed_checks or "day_relations" in manifest.failed_checks
    assert any(not result.passed for result in checks)
