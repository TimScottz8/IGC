# UI Requirements for IGC Statistics Workflow

## Purpose
Define the user interface requirements for producing policy-grade competition statistics for IGC from contest flight traces.

This document focuses on analyst workflows first, then supporting viewer interactions.

## Scope
In scope:
- Competition and dataset selection
- Parameter configuration and recompute behavior
- Analysis execution feedback
- Day and competition statistics presentation
- Provenance and reproducibility visibility
- Drill-down from summaries to events and flights

Out of scope for initial UI release:
- Advanced 3D workflows
- Rich publication dashboard styling
- Multi-user collaboration features

## Primary Users
- Analyst: Runs analysis and interprets outputs.
- Reviewer: Verifies assumptions, parameters, and reproducibility.
- Maintainer: Diagnoses data quality and recomputation issues.

## Core UI Principles
- Analysis-first: viewing tracks supports validation, not the main output.
- Reproducible by design: every metric view shows parameter fingerprint and analysis version.
- Progressive disclosure: show summaries first, with clear drill-down paths.
- Safe recomputation: clearly distinguish quick recompute from rebuild-required changes.

## Information Architecture
Top-level app tabs/panels:
1. Data
2. Analysis Setup
3. Results
4. Validation

Supporting panes:
- Right-side details panel for selected item context.
- Bottom status/progress strip for long-running tasks.

## Screen and Feature Requirements

### 1. Data Screen
Purpose: Choose competition/class/day scope and verify data readiness.

Required UI elements:
- Contest tree: competition > class > day > flights.
- Selection summary: selected competitions, classes, days, flights.
- Data quality indicators:
  - Parsed flight count
  - Flights missing start time
  - Flights missing altitude fields
  - Duplicate or invalid records
- Action buttons:
  - Refresh local data index
  - Open selected flights in viewer
  - Continue to analysis setup

Acceptance criteria:
- User can select one or more competition-class groups for analysis.
- User sees data completeness warnings before running analysis.

### 2. Analysis Setup Screen
Purpose: Configure gaggle and aggregation parameters with explicit recompute impact.

Required UI elements:
- Parameter groups:
  - Gaggle proximity (distance, time window, vertical separation)
  - Event construction (min cluster size, persistence, merge tolerance)
  - Aggregation (day validity thresholds, normalization options)
- Parameter impact badges per field:
  - Quick recompute
  - Rebuild from analysis-ready layer
  - Deep recompute
- Analysis run metadata:
  - Analysis version
  - Parameter fingerprint preview
  - Output location
- Saved parameter presets:
  - Load preset
  - Save current preset

Acceptance criteria:
- Any parameter change immediately indicates recompute class.
- User can launch analysis only when required inputs are valid.

### 3. Execution and Progress UX
Purpose: Make long runs observable, cancellable, and resumable.

Required UI elements:
- Stage progress timeline:
  1. Flight preparation
  2. Proximity candidate build
  3. Event construction
  4. Day summaries
  5. Competition summaries
  6. Artifact export
- Current stage counters and ETA estimate.
- Cancel button with clear stop semantics.
- Resume-from-last-valid-layer option when applicable.
- Error panel with per-day/per-flight failure details.

Acceptance criteria:
- User can identify current stage and failure location.
- Cancel does not corrupt existing persisted outputs.

### 4. Results Screen
Purpose: Present policy-facing metrics with drill-down paths.

Required UI elements:
- Competition summary cards for canonical metrics:
  - Gaggle Participation Rate
  - Normalized Peak Gaggle Size
  - Gaggle Time Exposure
  - Median Time To First Gaggle Join
  - Late-Starter Join Rate
  - Gaggle Start-Time Mixing
  - Established-Gaggle Accretion Rate
  - Day-to-Day Consistency
- Spread indicators (IQR or equivalent) adjacent to headline values.
- Day summary table with sorting/filtering by metric and quality flag.
- Trend charts across competitions/years/classes.
- Provenance footer on every view:
  - Analysis version
  - Parameter fingerprint
  - Source dataset stamp

Acceptance criteria:
- Every displayed summary is traceable to versioned run metadata.
- User can filter by competition/class/day and see updates consistently.

### 5. Drill-Down and Evidence Screen
Purpose: Connect aggregate statistics to flight-level evidence.

Required UI elements:
- Click-through from competition metric to day-level contributors.
- Click-through from day metric to gaggle events.
- Event details panel:
  - Start/end time
  - Duration
  - Peak size
  - Membership changes
  - Start-time spread
- Open-in-viewer action at event timestamp for visual verification.

Acceptance criteria:
- User can navigate from a metric card to concrete event evidence in <= 3 interactions.

### 6. Validation Screen
Purpose: Provide trust signals before external use.

Required UI elements:
- Data completeness summary by day.
- Sensitivity summary for key threshold sweeps.
- Outlier warning panel (dominant-day effect).
- Run comparison panel (current run vs prior parameter set).

Acceptance criteria:
- User can quickly determine whether outputs are stable enough for policy discussion.

## Interaction Requirements
- Persist selections when switching between tabs.
- Do not reset playback time when opening event evidence from results.
- Provide consistent loading states for all heavy operations.
- Avoid blocking the UI thread during analysis execution.

## UX Copy Requirements
Status and warning copy should explicitly state impact and next action.
Examples:
- "Parameter change requires rebuilding proximity candidates."
- "3 of 6 days excluded due to insufficient valid flights."
- "Results updated from cached candidates; no raw reparse required."

## Initial Release Acceptance Checklist
1. Analyst can run one full competition-class analysis end to end.
2. Results include all canonical metrics and spread indicators.
3. Every result view includes analysis version and parameter fingerprint.
4. Drill-down to event evidence works from summary metrics.
5. Cancel and resume behavior is reliable and non-destructive.
6. Data-quality exclusions are visible and auditable.

## Mapping to Current Codebase
Current foundations:
- Qt shell and tabbed layout: [qt_app.py](qt_app.py)
- Data and contest selection helpers: [qt_helpers.py](qt_helpers.py)
- Download and discovery controller flow: [qt_controllers.py](qt_controllers.py)
- Thermal event detection foundation: [gaggle_analysis.py](gaggle_analysis.py)
- Flight loading and caching: [qt_viewer.py](qt_viewer.py), [flight_model.py](flight_model.py), [flight_loader.py](flight_loader.py)

Expected near-term UI refactor needs:
- Move analysis orchestration out of the main window into a dedicated controller/service.
- Add results-state model for day and competition summaries.
- Add reusable provenance banner component used in all results views.
