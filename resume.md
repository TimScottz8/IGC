# Resume Guide

## Mission and Product Goal
This project is an analysis-first desktop app for producing policy-grade evidence for the IGC.

Primary objective:
- quantify how gaggle behavior and start-time mixing change across days, competitions, and years
- produce reproducible, versioned outputs suitable for rule-discussion evidence

Core contract source:
- [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md) (includes IGC Statistics Contract v1 and acceptance checks)

## Current Working State
The app now supports whole-competition and multi-competition workflows, not just individual flights.

The current working state includes both the earlier multi-competition analysis work and the latest SoaringSpot throttling-safe acquisition work:
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
- final viewer-scope fix:
  1. day/class filters now control active map scope immediately
  2. bulk-load no longer overrides filtered scope with full loaded set
  3. reset filters restores full loaded scope from retained loaded metadata
- SoaringSpot download safety fixes:
  - filtered real IGC links only, excluding generic `/downloads` pages and false route stubs
  - live file-level queue with status, retry counts, and elapsed times
  - host cooldown logic after 429/5xx throttling responses
  - serialised contest download strategy to reduce the risk of blocks

## Architecture Pointers
Read these first when resuming:
- [README.md](README.md)
- [Pathway.md](Pathway.md)
- [Progress.md](Progress.md)
- [download_diagnostics.md](download_diagnostics.md)
- [qt_app.py](qt_app.py)
- [qt_viewer.py](qt_viewer.py)
- [qt_helpers.py](qt_helpers.py)
- [download_helpers.py](download_helpers.py)
- [gaggle_analysis.py](gaggle_analysis.py)
- [flight_model.py](flight_model.py)
- [analysis_setup.py](analysis_setup.py)
- [igc_statistics.py](igc_statistics.py)

## Verification Baseline
Recent validated test sets:
- `.venv/bin/python -m pytest -q test_contest_dataset.py`
- `.venv/bin/python -m pytest -q test_geo_task.py -k "infer_contest_class_day_from_path or start_time_filters_by_day_and_class"`
- `.venv/bin/python -m pytest -q test_gaggle_analysis.py test_analysis_setup.py test_igc_statistics.py`

Recent smoke checks:
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -X faulthandler - <<'PY' ... import qt_app ... PY`
- offscreen integration check confirms filter scope behavior:
  1. two-day load -> 2 active flights
  2. day/class filter -> 1 active flight
  3. reset filters -> back to 2 active flights

## Known Risks / Notes
- full Qt-heavy suite can intermittently crash in this environment with SIGSEGV; rely on focused tests plus smoke checks for iterative changes
- parser multi-core mode currently has thresholding to avoid overhead on small batches
- lifecycle event semantics are implemented and tested, but large multi-day tuning remains open
- low CPU utilization can still be normal when most selected flights are cache hits
- SoaringSpot remains a rate-limited host; the implemented policy is to keep requests conservative and serial

## Next Session Priority
1. add a persistent queue of contest URLs and resume support
2. process one contest at a time to respect host limits and avoid bans
3. add a queue summary UI with pause/resume and per-contest status
4. benchmark end-to-end timings on one full competition and one multi-competition selection
5. begin wiring actual day-summary/competition-summary generation from loaded events into export pipeline
6. add “Analyze selected competitions” action from the Analysis tab using current filters and active selection scope

## Resume Prompt
Use this to restart quickly:

“Resume from [resume.md](resume.md), continue with the overnight contest queue and multi-contest dataset workflow, and keep the SoaringSpot cooldown logic and serial contest processing as the safety constraints.”
