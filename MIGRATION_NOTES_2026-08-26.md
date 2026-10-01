# Qt Migration Notes - 2026-08-26

## Goal
Migrate the slow Streamlit animation workflow to a single-process Python desktop app using PySide6 + pyqtgraph, with incremental testable steps.

## Historical Summary

This file records the milestone where the project stopped being primarily a Streamlit animation experiment and became a Qt desktop application.

Key outcomes from the migration:
- introduced the standalone Qt entrypoint in `qt_app.py`
- moved flight loading and playback into a responsive desktop workflow
- added 2D rendering, timeline scrubbing, speed controls, and seek interaction
- overlaid task route plus start, finish, and turnpoint sectors
- corrected map geometry through local projection and equal-axis scaling
- hardened the load/render path against timestamp and UI regressions

## Lasting Impact

The Qt migration established the base that the current app still builds on:
- local desktop startup instead of the older Streamlit loop
- timestamp-driven playback
- task-aware 2D visualisation
- a code path that is easier to refactor safely toward multi-flight analysis

## Current checkpoint
The current work has moved beyond the migration milestone and into the real contest-analysis phase:
- dynamic multi-flight selection is supported
- per-flight markers and recent trails are visible in the same scene
- playback time is preserved while selecting or deselecting gliders
- thermal-only gaggle detection is in place as the current analytical layer

This is the current product checkpoint that should be treated as the baseline for the next phase of development.

## Follow-on Direction

The later project direction expanded beyond this migration milestone:
- downloader integration was added to the desktop workflow
- multi-flight loading and selection became part of the active refactor
- the product goal shifted more clearly toward contest-analysis rather than playback alone
- thermal gaggle detection is now the immediate analysis focus for the next implementation step

For current priorities, see `README.md`, `Pathway.md`, and `Progress.md`.

## Run Command
`/home/tim/Projects/Gaggles/.venv/bin/python /home/tim/Projects/Gaggles/qt_app.py`
