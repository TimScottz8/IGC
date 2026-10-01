# Resume Guide

## Mission and Product Goal
This project is an analysis-first desktop app for producing policy-grade evidence for the IGC.

Primary objective:
- quantify how gaggle behavior and start-time mixing change across days, competitions, and years
- produce reproducible, versioned outputs suitable for rule-discussion evidence

Core contract source:
- [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md) (includes IGC Statistics Contract v1, acceptance checks, and IGC time/start-event semantics)

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
- persistent multi-contest acquisition queue:
  - queue contest URLs from the Download tab and process them one at a time
  - persist contest status under `igc_downloads/.contest_acquisition_queue.json`
  - recover interrupted `running` entries as pending after restart
  - pause after the current contest, or cancel and resume remaining work later
- per-file download progress is emitted as each file completes, rather than waiting for a whole contest batch
- escaped SoaringSpot result-page anchors labeled `Download IGC` are accepted contextually while bare numeric download stubs remain rejected
- multi-flight renderer caches projected tracks and timelines and reuses active flight/gaggle graphics items; 50-flight rendering has a regression and benchmark
- gaggle event times and multi-flight playback use absolute UTC from IGC fixes; playback spans the selected cohort's earliest to latest fix
- gaggle detection is completed before multi-flight playback starts; animation filters cached events by UTC event bounds

## IGC Time Rules
- IGC B-record time is UTC `HHMMSS`; HFDTE gives the UTC date of the first valid B-record fix. Do not adjust or per-flight-normalize these timestamps for cross-flight comparison.
- Reference: [IGC 2008 format guide](https://xp-soaring.github.io/igc_file_format/igc_format_2008.html), sections 2.4, 2.5.4, and 4.1; [FAI/IGC 2023 specification](https://xp-soaring.github.io/igc_file_format/igc_fr_specification_with_al8_2023-2-1_0.pdf).
- Keep **launch onset** and **race start** distinct. Launch onset is the first valid ground-speed sample above 30 kt. Race start is the last exit from the start zone before proceeding to the first turning point.
- Preserve all fix times on the UTC axis, including ground/pre-launch fixes. Derived event times use the same UTC basis.
- `gaggle_analysis.compute_thermal_gaggles()` emits absolute UTC event times. `TimelineState.utc_timestamps` retains per-fix absolute timestamps alongside relative duration offsets. The Qt cohort clock uses the minimum/maximum UTC bounds across selected flights.

## Current Evidence
- On two real `58 Hww` 15m traces, first fixes were 14:12:27 and 14:27:29 UTC; the viewer used the cohort interval 14:12:27–14:41:16 UTC and playback remained active.
- Current synthetic 50-flight render benchmark: 200 frames, 3.20 ms mean / 3.91 ms p95 / 4.91 ms max with gaggle overlays.
- Current real 22-flight `58 Hww` playback benchmark: 8 seconds, 493 ticks, 0.84 ms mean / 1.19 ms p95 / 1.48 ms max. Gaggle compute was excluded from tick timing; it is precomputed before multi-flight play.
- `57-hww` public HTML discovery returned 377 IGC candidates. A candidate returned HTTP 200 with IGC content. API access is not used because it requires competition-specific credentials.

## Architecture Pointers
Read these first when resuming:
- [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md)
- [README.md](README.md)
- [Pathway.md](Pathway.md)
- [Progress.md](Progress.md)
- [download_diagnostics.md](download_diagnostics.md)
- [qt_app.py](qt_app.py)
- [qt_viewer.py](qt_viewer.py)
- [qt_helpers.py](qt_helpers.py)
- [download_helpers.py](download_helpers.py)
- [gaggle_analysis.py](gaggle_analysis.py)
- [timeline_state.py](timeline_state.py)
- [flight_fix_utils.py](flight_fix_utils.py)
- [flight_model.py](flight_model.py)
- [analysis_setup.py](analysis_setup.py)
- [igc_statistics.py](igc_statistics.py)

## Verification Baseline
Most recent focused validation:
- `.venv/bin/python -m pytest -q test_gaggle_analysis.py` (6 passed)
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q test_geo_task.py -k 'multi_flight_playback_uses_shared_utc_range_and_staggered_fixes or reuses_render_state_for_fifty_active_flights or animation_waits_until_gaggle_events_are_precomputed or gaggle_circles_follow_cached_event_timestamps_without_recomputing'` (4 passed)
- `.venv/bin/python -m pytest -q test_contest_dataset.py -k reports_each_completed_file_before_returning` (1 passed)
- Python editor diagnostics on the changed modules: no errors

Recent smoke checks:
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -X faulthandler - <<'PY' ... import qt_app ... PY`
- offscreen integration check confirms filter scope behavior:
  1. two-day load -> 2 active flights
  2. day/class filter -> 1 active flight
  3. reset filters -> back to 2 active flights

## Known Risks / Notes
- full Qt-heavy suite can intermittently crash in this environment with SIGSEGV; rely on focused tests plus smoke checks for iterative changes
- parser multi-core mode currently has thresholding to avoid overhead on small batches
- derived launch-onset and race-start event calculation are not implemented yet; use the definitions in `IMPLEMENTATION_SPEC.md`
- the current race-start rule is the final exit from the start zone before the track proceeds to the first turning point; this is not the first fix or the >30 kt launch event
- multi-flight timing must remain on absolute UTC; per-flight `time_offsets` are only for individual-flight durations, never cross-flight alignment
- low CPU utilization can still be normal when most selected flights are cache hits
- SoaringSpot remains a rate-limited host; the implemented policy is to keep requests conservative and serial

## Next Session Priority
1. Inspect `geo_task.py` start-zone/first-turnpoint geometry and existing `extract_glider_start_time()` behavior.
2. Derive launch onset as the first valid >30 kt ground-speed sample; do not alter IGC UTC timestamps.
3. Derive race start as the final start-zone exit followed by progress to the first turning point; add tests for repeated zone exits, missing task geometry, and no valid start.
4. Carry both derived event timestamps in absolute UTC into per-flight metrics, then wire day/competition summaries into the export pipeline.
5. Benchmark multi-contest acquisition after these analysis changes; defer 3D renderer choice until the shared UTC scene contract is stable.

## Resume Prompt
Use this to restart quickly:

“Resume from [resume.md](resume.md) and [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md). First implement and test UTC launch-onset (>30 kt) and race-start (last start-zone exit followed by progress to TP1) derivation. Never rebase IGC UTC fix times per flight; playback and gaggle events share the cohort UTC axis.”
