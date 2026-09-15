# IGC

Desktop tooling for analysing historical glider contest traces.

## Aim

This project is intended to become a research and analysis application for studying contest behaviour, especially:
- whether online OGN/FLARM guidance changed gaggle formation
- how pilot start time relates to joining or forming groups
- whether those patterns correlate with contest safety and pilot behaviour

The product direction is analysis-first rather than viewer-first. The goal is to compare flights across contests, classes, days, and eras, then use synchronized visualisation and derived metrics to inspect grouping behaviour.

## Current Scope

The current codebase is a Qt desktop app that provides the working foundation for that analysis workflow.

Implemented and currently working:
- contest discovery and download planning from SoaringSpot
- grouping downloaded flights by contest, class, and day
- opening one or more IGC files from local or downloaded sources
- caching parsed flight records and loading multiple files together
- extracting task geometry, sectors, and glider start times
- rendering a 2D flight view with timeline playback and sector overlays
- selecting multiple flights dynamically and showing each selected glider as a distinct active view
- rendering recent multi-flight trails instead of a single full-route trace
- preserving the current playback timestamp while changing selection state
- thermal-only gaggle detection as the current first-pass analysis layer

This is now a working multi-flight analysis workflow at the first useful product stage, not just a single-flight viewer.

Not yet delivered:
- a polished cluster dashboard and summary table
- stronger gaggles-on-map overlays with clearer human-readable presentation
- full start-time metrics correlation per gaggle event
- a broader 3D comparison workflow beyond the current 2D/thermal-first mode

## Project Shape

Key files:
- `qt_app.py` - main Qt application shell, map view, playback controls, and selected-flight state
- `qt_viewer.py` - render logic, multi-flight selection flow, recent-track display, and viewer updates
- `qt_helpers.py` - contest discovery, grouping, path normalization, and selection handling
- `flight_loader.py` - cache-backed flight loading
- `flight_model.py` - parsed flight record model
- `scene_state.py` - selected and active flight state
- `timeline_state.py` - playback timeline state
- `gaggle_analysis.py` - thermal/gaggle detection logic
- `geo_task.py` and `sector_geometry.py` - task parsing, sectors, and start-time logic
- `test_geo_task.py` and `test_gaggle_analysis.py` - regression coverage for the current behaviour

## Typical Workflow

1. Discover or select contest flights.
2. Download or open IGC files.
3. Load one or more flights into the desktop viewer.
4. Select/deselect gliders dynamically while the animation continues.
5. Inspect route geometry, task sectors, and current gaggle membership.
6. Work toward per-flight start-time and gaggle-size correlation analytics.

## Roadmap

Near term:
- keep the multi-flight viewer flow stable while expanding the analyses
- add clearer gaggle overlays and visible cluster summaries on the map
- correlate thermal gaggle size and timing with each glider's start time
- keep the playback logic centred on the current time slice rather than whole-flight traces

Next product steps:
- add richer per-flight information in the viewer
- extend the gaggle metrics layer beyond the thermal-only prototype
- create a compact start-time versus gaggle-size dashboard
- continue to improve the visual map clarity for group formation

Longer term:
- compare pre-OGN and post-OGN contest traces
- analyse start-time bands against gaggle formation patterns
- derive summaries supporting contest-behaviour and safety research

## Run

```bash
.venv/bin/python qt_app.py
```

## Tests

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q test_geo_task.py
.venv/bin/python -m pytest -q test_gaggle_analysis.py
```

## Project History

- The project began as a slower Streamlit-based viewer workflow.
- On 2026-08-26 it moved onto a Qt desktop path using PySide6 and pyqtgraph.
- That migration established the current foundations: desktop shell, cached file loading, 2D playback, task overlays, and timeline control.
- The current focus is on making the viewer genuinely multi-flight capable and on driving the first useful thermal gaggle analysis layer.

## Notes

The long-term product intent is described in `Pathway.md`.
Recent notes, handoff state, and application milestones are captured in `Progress.md`, `resume.md`, and `MIGRATION_NOTES_2026-08-26.md`.