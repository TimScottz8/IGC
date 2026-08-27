# Resume Guide

## Project goal
This project is intended to become a desktop Qt application for analysing historical glider contest traces, with a focus on comparing gaggle formation, start-time effects, and contest safety behaviour over time.

The deeper product direction is described in [Pathway.md](Pathway.md):
- discover contests and flight data
- load one or more IGC files
- compare flights across classes, days, and eras
- view flight data in 2D and 3D
- analyse gaggle formation and start-time patterns
- use the derived analytics to study whether online OGN/FLARM guidance changed contest behaviour

This is not just a flight viewer. It is a research and analysis workflow built around contest flight data.

## Current status
The project is in a stable refactor state.

The app currently supports the following core Qt workflow:
- contest discovery from SoaringSpot
- grouping contest results by class and day
- local browsing of downloaded contests
- selecting and downloading chosen flight files
- opening one or more flights from local or downloaded sources
- loading flights through a cache-backed record model
- showing the active flight set in the viewer state
- keeping the UI flow and selection logic stable while refactoring

The app is no longer in the earlier Streamlit-era state; it is now a desktop Qt workflow centred on the contest-analysis use case.

## Verified working baseline
The last verified validation command was:

`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q test_geo_task.py`

Result:
- 33 passed in 26.11s

## What has been deferred intentionally
The project deliberately does not try to do all advanced analysis work in one move. We have deferred:
- full OZ drawing work
- deeper 3D feature completion
- broader gaggle metrics and comparison analysis
- large-scale feature churn while the selection and viewer flow are still being stabilized

This is intentional, because the team has chosen a safe, incremental path rather than trying to build the full long-term system in one pass.

## Files that matter for the next session
If you want a fast resume, the most important files to review are:
- [Pathway.md](Pathway.md) — product purpose and long-term goal
- [Progress.md](Progress.md) — current session summary and handoff state
- [qt_app.py](qt_app.py) — main Qt window and UI flow
- [qt_helpers.py](qt_helpers.py) — extracted logic for selection, contests, downloads, groupings, and path handling
- [flight_loader.py](flight_loader.py) — parsing cache and flight loading
- [flight_model.py](flight_model.py) — flight data model
- [scene_state.py](scene_state.py) — selected/active flight state
- [timeline_state.py](timeline_state.py) — playback and time state
- [test_geo_task.py](test_geo_task.py) — the current behaviour contract and validation suite

## Recommended next step
The next working session should continue with the same pattern as before:
1. keep refactoring only the remaining duplicated or UI-heavy logic
2. preserve correctness before optimising for elegance
3. keep the architecture multi-flight-ready for the analysis use case
4. avoid broad feature changes unless they are directly tied to the product goal

## Best way to resume
If I am asked to continue, the most useful prompt is:

“Please resume from resume.md, then review the current project state and recommend the next safe step toward the contest-analysis goal.”

This will let me immediately understand the goal, the current baseline, and the intended next move without re-deriving the project context.
