from __future__ import annotations

from dataclasses import replace

from analysis_setup import (
    AnalysisParameters,
    RecomputeImpact,
    changed_fields,
    highest_change_impact,
    parameter_fingerprint,
    validate_flights,
)


class _Fix:
    def __init__(self, *, alt=None, gnss_alt=None, press_alt=None):
        self.alt = alt
        self.gnss_alt = gnss_alt
        self.press_alt = press_alt


class _Record:
    def __init__(self, *, valid=True, start_time="2026-08-08T11:00:00Z", fixes=None):
        self.valid = valid
        self.start_time = start_time
        self.fixes = list(fixes or [])


def test_changed_fields_reports_only_modified_parameters():
    baseline = AnalysisParameters()
    current = replace(baseline, max_distance_m=750, normalization_mode="starters")

    changed = changed_fields(current, baseline)

    assert "max_distance_m" in changed
    assert "normalization_mode" in changed
    assert "max_time_delta_s" not in changed


def test_highest_change_impact_uses_changed_fields_only():
    baseline = AnalysisParameters()

    quick_only = replace(baseline, min_cluster_size=3)
    rebuild_change = replace(baseline, max_time_delta_s=45)
    deep_change = replace(baseline, resample_interval_s=10)

    assert highest_change_impact(quick_only, baseline) == RecomputeImpact.QUICK
    assert highest_change_impact(rebuild_change, baseline) == RecomputeImpact.REBUILD
    assert highest_change_impact(deep_change, baseline) == RecomputeImpact.DEEP


def test_parameter_fingerprint_is_stable_and_sensitive_to_changes():
    baseline = AnalysisParameters()
    same = AnalysisParameters()
    changed = replace(baseline, max_altitude_delta_m=900)

    fp_a = parameter_fingerprint(baseline, analysis_version="v1")
    fp_b = parameter_fingerprint(same, analysis_version="v1")
    fp_c = parameter_fingerprint(changed, analysis_version="v1")

    assert fp_a == fp_b
    assert fp_a != fp_c


def test_validate_flights_reports_missing_start_time_altitude_and_invalid_records():
    valid_with_alt = _Record(fixes=[_Fix(alt=500.0)])
    valid_missing_start = _Record(start_time=None, fixes=[_Fix(gnss_alt=530.0)])
    valid_missing_alt = _Record(fixes=[_Fix()])
    invalid = _Record(valid=False, fixes=[])

    summary = validate_flights(
        [valid_with_alt, valid_missing_start, valid_missing_alt, invalid],
        day_min_valid_flights=4,
    )

    assert summary.total_flights == 4
    assert summary.valid_flights == 3
    assert summary.invalid_records == 1
    assert summary.missing_start_time == 1
    assert summary.missing_altitude == 1
    assert any("Only 3 valid flights" in warning for warning in summary.warnings)
    assert any("missing start time" in warning for warning in summary.warnings)
    assert any("missing altitude" in warning for warning in summary.warnings)
    assert any("invalid" in warning for warning in summary.warnings)
