# Progress Summary

Canonical overview:
- `README.md` describes the current project scope
- `Pathway.md` describes the long-term analysis direction

## Update 2026-09-15

### Completed today
- implemented lifecycle-based gaggle event semantics in the analysis engine using join, break-distance, break-duration, and circling-grace behavior
- removed drift-stitch dependence from active/static gaggle rendering and aligned overlays with event first/last timestamps
- added and passed lifecycle-focused regression tests for continuity across short gaps and split behavior under sustained separation
- added Analysis setup contract details for IGC statistics in `IMPLEMENTATION_SPEC.md`, including schema fields, nullability rules, acceptance checks, and reproducibility requirements
- implemented `igc_statistics.py` with:
- contract context and parameter fingerprint wiring
- day-summary and competition-summary builders
- dataset validation manifest generation
- deterministic JSON/CSV export scaffolding
- added tests for statistics contract determinism and domain/range validation failures
- enabled bulk multi-competition selection from local downloaded contest tree
- added day/class filters in the Flight viewer start-time panel to control displayed subsets after bulk load
- fixed selection precedence bugs so most-specific selected nodes win:
- selecting day under class no longer pulls whole competition
- mixed ancestor/descendant selection now resolves to requested subset for both local contest tree and viewer start-time tree
- improved flight loading performance:
- parse only cache misses instead of reparsing whole requested set
- batch parser-service payload requests to reduce per-file IPC overhead
- introduced OS-agnostic multi-core parser support for large batches with safe serial fallback
- added CPU-side gaggle compute optimizations:
- LRU thermal-segment cache across reruns
- precomputed time-window bounds for faster neighbor membership scans

### Validation and quality checks completed
- static diagnostics report no errors on edited modules
- focused regression suites passed for:
- gaggle lifecycle logic
- analysis setup and fingerprint behavior
- IGC statistics contract and export determinism
- selection-precedence behavior for local and viewer trees
- import smoke checks passed for `qt_app.py`, `qt_viewer.py`, and `flight_model.py` in offscreen Qt mode

### Current state
- app supports selecting whole competitions or multiple competitions, then narrowing viewer display by day and class
- analysis stack now has a documented, test-covered statistics contract and export scaffolding
- major bottlenecks addressed in both flight loading and gaggle recompute paths using CPU-first optimizations

## Current checkpoint
The viewer is now beyond the initial multi-flight baseline and has an actively evolving thermal gaggle analysis workflow.

The core product direction is unchanged: this is an analysis-first Qt desktop application for studying contest behaviour, gaggle formation, and start-time relationships. The recent work concentrated on making gaggle detection visible enough to iterate on in the viewer, while keeping the playback workflow stable.

## Completed in this session block
- preserved full flight-path display while static, with snail-trail rendering only during active animation
- added inline gaggle settings in the Flight viewer for distance, time window, minimum cluster size, and vertical separation
- added persistent gaggle reference zones for static inspection and current-time-only gaggle overlays during animation
- moved gaggle detection off the UI thread and added visible progress/cancel controls for heavy day-level processing
- enabled a multiprocessing clustering path to use multiple CPU cores, with serial fallback when process-pool startup is unsuitable
- fixed a critical data issue where altitude fields were lost during parser-service serialization, which previously caused zero detected gaggle zones
- aligned gaggle event timestamps to the same relative-seconds timeline used by playback, which is necessary for animated detection to line up with the map
- introduced drift-aware gaggle-zone merging so one drifting thermal does not explode into many separate reference zones
- limited overlay draw load to avoid UI hangs after detection completes
- corrected gaggle visual size to use unique-flight count instead of raw event count

## Current behaviour
The app can now:
- discover and download contest flights
- open multiple gliders together
- dynamically select and deselect gliders without resetting time
- show full routes when paused or static, and snail trails while animating
- compute thermal gaggle candidates with horizontal, temporal, and vertical separation filters
- show whole-flight reference zones while static
- show only current or recent gaggle overlays while animating, instead of the entire flight's zones
- keep gaggle circles visible for a persistence window after departure so formation can be followed in playback

## Important implementation notes
- `flight_model.py` now preserves `alt`, `gnss_alt`, and `press_alt` when records move through the parser-service path
- `gaggle_analysis.py` is currently the main performance-sensitive module; it now contains:
- clearer thermal threshold constants
- relative-time event generation
- fast horizontal prefiltering before geodesic distance checks
- multiprocessing chunk execution with a safe fallback path
- `qt_app.py` now owns substantial gaggle UI state, including settings, progress UI, static reference rendering, active animation overlays, and drift-zone merging

## Current limitations and known issues
- animated gaggle visualization is improved but still needs more field validation; the latest issue under active refinement has been making active circles appear consistently and with sensible persistence
- drift merging is heuristic and likely needs exposure of its parameters in the UI once the baseline behaviour feels trustworthy
- there is now a lot of gaggle-specific logic in `qt_app.py`; a future cleanup should move this into a dedicated controller/service layer once behaviour stabilizes
- `pytest` is not currently available in the repo venv on this machine, so test verification has been limited to compile checks and live application validation

## Verified status
Verified commands in the local venv:
- `.venv/bin/python -m py_compile flight_model.py gaggle_analysis.py qt_app.py qt_viewer.py test_gaggle_analysis.py`

Observed constraints:
- `.venv/bin/python -m pytest -q test_gaggle_analysis.py` currently fails because `pytest` is not installed in the local `.venv`

Additional direct checks already performed during this session:
- real downloaded IGC files now load with altitude present in the parsed fixes
- real-data gaggle clustering returns non-zero clusters with practical thresholds once altitude serialization is preserved

## Best next steps
1. verify animated current-gaggle circles visually on a known day dataset and tune persistence or active-window logic only after that behaviour is confirmed
2. expose drift-merge parameters in the UI if one thermal still becomes several zones under contest-day conditions
3. move gaggle rendering/detection orchestration out of `qt_app.py` into a dedicated controller once the interaction model stops changing every session
4. install `pytest` in the repo-local `.venv` and restore executable regression validation for the gaggle pipeline
5. start computing per-flight gaggle summaries once the overlay semantics are visually trustworthy

## Restart prompt for next time
Resume from `resume.md` and continue tightening the thermal gaggle animation workflow, especially current-time overlay behaviour, drift merging, and the transition from map-only cues to per-flight metrics.
