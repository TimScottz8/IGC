# Resume Guide

## Mission and Product Goal
This project is an analysis-first desktop app for producing policy-grade evidence for the IGC.

Primary objective:
- quantify how gaggle behavior and start-time mixing change across days, competitions, and years
- produce reproducible, versioned outputs suitable for rule-discussion evidence

Core contract source:
- [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md) (includes IGC Statistics Contract v1 and acceptance checks)

## Current Working State (2026-09-15)
The app now supports whole-competition and multi-competition workflows, not just individual flights.

Delivered this session:
- lifecycle-based gaggle events (join + break distance/duration + circling grace)
- analysis setup model and fingerprinting in [analysis_setup.py](analysis_setup.py)
- deterministic statistics export scaffold and validation manifest in [igc_statistics.py](igc_statistics.py)
- local contest multi-select loading in the Download tab
- viewer day/class filters to narrow displayed flights after bulk load
- selection precedence fix (most-specific nodes win) for both local tree and viewer tree
- CPU-first performance improvements:
1. parse only cache misses when opening selections
2. batched parser-service requests
3. multi-core parsing for large batches in parser service
4. gaggle compute: thermal-segment LRU cache + precomputed time-window bounds

## Architecture Pointers
Read these first when resuming:
- [README.md](README.md)
- [Pathway.md](Pathway.md)
- [Progress.md](Progress.md)
- [qt_app.py](qt_app.py)
- [qt_viewer.py](qt_viewer.py)
- [qt_helpers.py](qt_helpers.py)
- [gaggle_analysis.py](gaggle_analysis.py)
- [flight_model.py](flight_model.py)
- [analysis_setup.py](analysis_setup.py)
- [igc_statistics.py](igc_statistics.py)

## Verification Baseline
Recent validated test sets:
- `.venv/bin/python -m pytest -q test_qt_helpers_selection.py`
- `.venv/bin/python -m pytest -q test_geo_task.py -k "infer_contest_class_day_from_path or start_time_filters_by_day_and_class"`
- `.venv/bin/python -m pytest -q test_gaggle_analysis.py test_analysis_setup.py test_igc_statistics.py`

Recent smoke checks:
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -c "import qt_app, qt_viewer, flight_model; print('imports_ok')"`

## Known Risks / Notes
- full Qt-heavy suite can intermittently crash in this environment with SIGSEGV; rely on focused tests + smoke checks for iterative changes
- parser multi-core mode currently has thresholding to avoid overhead on small batches
- lifecycle event semantics are implemented and tested, but large multi-day tuning remains open

## Next Session Priority
1. add visible load diagnostics in UI status: selected count, cache hits/misses, parse time
2. benchmark end-to-end timings on one full competition and one multi-competition selection
3. begin wiring actual day-summary/competition-summary generation from loaded events into export pipeline
4. add “Analyze selected competitions” action from Analysis tab using current filters and active selection scope

## Resume Prompt
Use this to restart quickly:

"Resume from [resume.md](resume.md), continue with load diagnostics and competition-scale analysis export wiring, and keep behavior aligned with [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md)."
