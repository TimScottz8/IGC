# Resume Guide

## Orientation
Start with:
- [README.md](README.md) for the current project scope
- [Pathway.md](Pathway.md) for the long-term product goal
- [Progress.md](Progress.md) for the latest working state and immediate next tasks
- [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md) for the agreed implementation contract for competition-scale gaggle analysis, persistence, and reporting

## Strategic update
The product direction has now been sharpened beyond viewer workflow refinement.

The app's ultimate purpose is to generate policy-grade evidence for the International Gliding Commission about whether increasing practical availability of live positional awareness is associated with safety and fairness changes large enough to justify rule discussion.

The current agreed implementation direction is:
- analyse whole competitions, not isolated flights
- compute day-level summaries first, then aggregate to competition-level summaries
- compare competitions over time rather than relying on a binary OGN adoption date
- persist analysis layers so common gaggle-parameter changes do not require reparsing raw flights
- save graphs and summaries with parameter fingerprints and analysis-version provenance

Before implementing major new behaviour, read [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md) and treat it as the primary contract for the next build stage.

## Current status
The app is now a working multi-flight desktop viewer with a much more advanced thermal gaggle workflow than the previous checkpoint, but the gaggle overlay behaviour is still under active tuning.

The app currently supports the following core Qt workflow:
- contest discovery from SoaringSpot
- grouping contest results by class and day
- local browsing of downloaded contests
- selecting and downloading chosen flight files
- opening one or more flights from local or downloaded sources
- loading flights through a cache-backed record model
- dynamically selecting and deselecting gliders while keeping the same playback time
- rendering full tracks while static and snail trails while animating
- detecting thermal-only gaggles with distance, time, vertical-separation, and minimum-size filters
- showing static whole-flight gaggle reference zones
- showing current-time-focused gaggle overlays during animation
- running gaggle detection off the UI thread with a progress bar and cancel button

This is now a real multi-flight contest-analysis tool in an active gaggle-visualisation phase, not just a stable viewer refactor.

## Verified working baseline
The latest successful verification commands were:

- `.venv/bin/python -m py_compile flight_model.py gaggle_analysis.py qt_app.py qt_viewer.py test_gaggle_analysis.py`

Current constraint:
- `.venv/bin/python -m pytest -q test_gaggle_analysis.py` fails because `pytest` is not installed in the local `.venv`

Important direct validation already done:
- real downloaded flight records now preserve altitude values in the parser-service path
- real-data gaggle clustering returns non-zero clusters once altitude is preserved

## What matters for the next session
The most important files to review are:
- [Pathway.md](Pathway.md) — product purpose and long-term goal
- [Progress.md](Progress.md) — bootstrapping state and next tasks
- [qt_app.py](qt_app.py) — main Qt window and playback shell
- [qt_viewer.py](qt_viewer.py) — render state, selection handling, and multi-flight view logic
- [gaggle_analysis.py](gaggle_analysis.py) — thermal gaggle detection, clustering, multiprocessing, and timing logic
- [timeline_state.py](timeline_state.py) — playback and time indexing state
- [scene_state.py](scene_state.py) — active and selected flight state
- [flight_model.py](flight_model.py) — parser-service record serialization including altitude preservation
- [test_geo_task.py](test_geo_task.py) and [test_gaggle_analysis.py](test_gaggle_analysis.py) — behaviour contract and regression coverage

## Recommended next step
The next working session should stay narrow and focus on making the current gaggle overlay semantics trustworthy before expanding analysis scope:
1. verify that animated current-gaggle circles appear at the expected moments on a known contest day
2. tune persistence, drift merging, or active-window filtering only after confirming what the viewer is actually showing
3. consider surfacing drift-merge parameters in the UI if one drifting thermal still becomes several zones
4. once the overlays are trustworthy, start computing per-flight gaggle summaries tied to start time
5. install `pytest` into the repo-local `.venv` so future changes can be validated executable-first rather than by compile checks and manual observation

## Best way to resume
If I am asked to continue, the most useful prompt is:

“Resume from resume.md and continue the thermal gaggle analysis work, focusing first on animated current-gaggle visibility and drift-merged zone behaviour.”

This will immediately orient the work toward the active product goal without losing the recent selection and playback improvements.
