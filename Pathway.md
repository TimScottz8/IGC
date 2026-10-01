# Pathway: contest trace analysis app

## Purpose

Build a desktop app for analysing historical glider contest traces to test whether online OGN/FLARM guidance has changed gaggle formation and whether this correlates with pilot start time and pilot safety.

The app is intended to answer questions such as:
- Did larger gaggles form more often after OGN data became available?
- Are later starters more likely to join a gaggle already formed by earlier pilots?
- Is there a measurable relationship between start time and the size or timing of a gaggle?
- Are there contest-day or class-specific patterns in this behaviour?

## Primary product direction

This is not just a flight viewer. It is an analysis tool for contest safety and contest behaviour.

The product should help users compare contest traces across eras:
- before OGN online data
- after OGN/online FLARM became common

## Main user goals

1. Load one or more IGC files from a contest or contest dataset.
2. Select a contest/class/day or a set of flights.
3. View the flights in a 2D map and a 3D map.
4. Analyse start times, route geometry, and gaggle behaviour over time.
5. Compare results across eras, classes, or start-time bands.

## Core app questions

The app should support analysis of:
- start-time distribution
- when a gaggle begins to form
- how quickly pilots join a group
- whether later starters join early starter gaggles
- whether outing size correlates with pilot safety risk
- whether the effect changes materially after OGN/FLARM data became available

## Main capabilities

### A. Flight loading
- Open single or multiple IGC files.
- Load by contest directory or selected files.
- Preserve each flight’s metadata:
  - file name
  - pilot identity
  - contest/class/day
  - start time
  - task sectors and waypoints

### B. 2D flight viewer
- Plot the flight track in 2D.
- Show task geometry and sectors.
- Show start/finish/task points.
- Display flight progress over time.
- Keep the 2D view synchronized with the 3D view.

### C. 3D flight viewer
- Display the same flight in a 3D scene.
- Show path and altitude relation.
- Support multiple flights in one scene in the future.
- Keep playback and timeline aligned with the 2D view.

### D. Gaggle analysis
- Detect when multiple flights are close in space and time.
- Measure:
  - gaggle size over time
  - peak group size
  - time of first grouping
  - time to join an existing gaggle
  - whether the pilot started early or late and later joined a group
- Mark important times on the timeline.

### E. Start-time analysis
- Extract start time from each flight.
- Compare:
  - early vs late starters
  - time-to-gaggle join
  - final gaggle size
- Show start time as a key variable in the analysis.

### F. Comparison mode
- Compare:
  - pre-OGN vs post-OGN contest flights
  - different classes
  - different days
  - specific pilot subsets
- Produce summaries and visual comparisons.

## Core design principle

The app should be built around analysing flights as data, not just displaying them.

The core data model should capture:
- flight identity
- contest metadata
- start time
- time-stamped fixes
- position and altitude
- task geometry
- group membership over time
- derived safety metrics

Once that is in place, the visual panes become a way of exploring the data rather than the whole product.

## Proposed interaction model

User workflow:
1. Select contest or flights.
2. Open 2D and 3D views in same window.
3. Choose a flight or set of flights.
4. Review timeline and map views together.
5. Compare start times and gaggle behaviour.
6. Inspect patterns by era or contest.

## Recommended UI layout

Single-window layout with:
- top bar: contest and flight selection
- left pane: 2D map
- right pane: 3D map
- bottom bar: playback and timeline
- optional side panel: start-time list and selected-flight metrics

This matches the requirement for a same-window split view so users can see both representations at once.

## Future multi-flight design

The app should be designed from the start so multiple flights can be rendered together.

That means:
- the scene model accepts a collection of flights
- each flight has colour and metadata
- each flight can be toggled visible/hidden
- selection in one view updates the other view
- later the app can compare groups side by side

The first version can still show one flight, but the architecture should not assume “one flight only”.

## Initial milestone priority

The first useful build should include:
1. Load and select a flight.
2. Show the 2D track.
3. Show the 3D track in the same window.
4. Keep both views synchronized for time/index.
5. Add start-time metadata and flight list.
6. Compute a basic gaggle proximity metric for a small set of flights.

This is the minimum useful version for the stated research objective.

## Non-goals for version 1

Keep the first version focused and avoid:
- full terrain modelling
- complicated 3D camera presets
- heavy analytics dashboards
- networked ingestion
- prediction or inference beyond observable group metrics

This is a grounded analysis tool, not a full simulation platform.

## Recommended file structure

A logical file layout for future work:
- qt_app.py — Qt shell, window layout, app entry
- qt_helpers.py — download helpers
- flight_model.py — flight metadata and fix model
- gaggle_analysis.py — gaggle detection and metrics
- scene_3d.py — 3D rendering and scene state
- viewer_2d.py — 2D map widgets and overlays
- timeline_controls.py — playback and timeline logic

## Decision checkpoint

The key design decision is whether the first version should prioritise:
- single-flight analysis with synchronized 2D+3D split view, or
- multi-flight comparison from the start

Recommended approach:
- start with single-flight synchronized 2D+3D
- design the data model and scene management for multiple flights from day one

That balances usefulness and future-proofing.

## Summary

This project should become a desktop contest-analysis app with a synchronized 2D and 3D viewing workflow, with start-time and gaggle analysis as the core analytical value. The foundation should be built around flight data, not just map display, and the architecture should be kept multi-flight-ready from the beginning.
