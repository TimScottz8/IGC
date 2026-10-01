# Multi-Contest Analysis Plan

## Goal

Extend the current Qt-based glider contest analysis workflow from single-contest / multi-flight inspection toward a true multi-contest, multi-year analysis system for studying thermal gaggle behaviour, pilot start-time effects, and era-based comparison.

This plan is the implementation roadmap for the next phase of the project and should be used alongside:
- [README.md](README.md)
- [Pathway.md](Pathway.md)
- [Progress.md](Progress.md)
- [resume.md](resume.md)

## Product intent

The app should support analysis of:
- contest-to-contest comparison
- multi-year comparison
- class-specific patterns
- era-based comparison, especially pre-OGN vs post-OGN
- pilot start-time and gaggle-formation relationships
- thermal gaggle behaviour over time and across datasets

The core product question remains: did online guidance change the way glider pilots form and join gaggles, and does that correlate with start time and contest behaviour?

## Current project status

The project already has a working desktop viewer and a thermal gaggle detection workflow, including:
- contest discovery and local flight selection
- multi-flight loading and dynamic selection
- task and sector overlays
- live/time-synced playback
- thermal gaggle detection and current-time overlays
- a working foundation for analysis-first inspection

The next phase is not about making the viewer prettier; it is about making the app capable of corpus-scale comparison across contests and years.

## Architectural direction

The app should evolve from a “loaded flight set” workflow to a “dataset query” workflow.

### Core design idea

Treat contests and flights as structured data rather than just a set of visible traces in a map.

The analysis stack should support:
- contest identity and metadata
- year, era, class, and day dimensions
- flight-level metrics
- gaggle event summaries
- aggregated comparisons over multiple contests

## Implementation phases

### Phase 1: Contest dataset model

#### Objective
Allow the app to ingest, group, and compare multiple contests and years as a coherent dataset.

#### Deliverables
- Contest model
  - id
  - name
  - year
  - location
  - class set
  - date range
  - era tag
  - source dataset
- Flight metadata normalization
  - contest id
  - class
  - day
  - pilot identity
  - start time
  - task metadata
  - time series and altitude data
- Dataset loading API
  - load one contest
  - load many contests
  - filter by year/class/day/era

#### Key tasks
1. Add a contest registry abstraction.
2. Normalize all flight metadata under a shared schema.
3. Add multi-contest and multi-year dataset loaders.
4. Persist contest metadata and flight record references.

#### Acceptance criteria
- The app can load multiple contest directories in the same session.
- A contest is treated as a first-class object rather than an ad hoc folder.
- Data can be filtered across year, class, and era reliably.

---

### Phase 2: Per-flight gaggle summary pipeline

#### Objective
Convert the current thermal gaggle detection into quantitative flight-level metrics that can be compared across the dataset.

#### Metrics to compute per flight
- first gaggle time
- peak gaggle size
- time to join a gaggle
- total time in a gaggle
- thermal cluster duration
- start-time band
- whether the pilot formed a gaggle or joined one

#### Key tasks
1. Extend current gaggle detection output into structured event summaries.
2. Aggregate event membership over the flight timeline.
3. Extract start-time relationships to gaggle formation.
4. Attach those summaries to each flight record.

#### Acceptance criteria
- Each flight has a summary of its gaggle behaviour.
- The app can answer questions like “when did this pilot first join a group?”
- Summary metrics are stable and reusable for cross-contest comparison.

---

### Phase 3: Cross-contest comparison view

#### Objective
Build the first comparison dashboard for multi-contest analysis.

#### UI features
- contest selector
- year selector
- class selector
- era selector
- day selector
- start-time band filter
- summary table of flights
- charts for gaggle metrics

#### Initial comparison charts
- gaggle size by year
- gaggle size by start-time band
- first gaggle time vs start time
- contest-to-contest distribution comparison

#### Key tasks
1. Add dataset-level selection controls.
2. Implement summary table for flight-level analytics.
3. Add a chart layer for comparison across contests and years.
4. Preserve selection and map inspection for specific flights within a filtered dataset.

#### Acceptance criteria
- Users can compare multiple contests in one session.
- Filters can be changed without reworking the entire app state.
- The app can highlight data trends across contest years and classes.

---

### Phase 4: Research-grade analytics

#### Objective
Support the long-term project question around whether guidance technology altered group behaviour.

#### Target analyses
- pre-OGN vs post-OGN comparisons
- class-by-class gaggles and start-time trends
- day-level contest behaviour
- pilot grouping patterns across years
- correlation between start time and gaggle size

#### Key tasks
1. Add era tagging to contests and datasets.
2. Standardize comparison queries by contest, class, era, and start-time band.
3. Generate summary outputs for research and export.
4. Add lightweight persistence for derived metrics to avoid repeated expensive recomputation.

#### Acceptance criteria
- The app can answer the core contest-behaviour research questions.
- Data interpretation is driven by repeated metrics, not only by map inspection.

---

## Recommended order of work

### Sprint 1: dataset foundation
- contest model
- contest directory ingestion
- metadata normalization
- dataset selection and persistence

### Sprint 2: gaggle metrics
- per-flight summary generation
- start-time correlation logic
- first-handoff of comparison metrics

### Sprint 3: comparison dashboard
- summary tables
- charts
- multi-contest filters
- selected-flight drill-down

### Sprint 4: era and research analysis
- pre/post comparison
- contest trends
- export and reporting support

## Key engineering principles

1. Normalize before comparing.
2. Build around data queries, not just visual inspection.
3. Make contest metadata explicit and persistent.
4. Treat gaggle metrics as first-class outputs, not incidental map overlays.
5. Persist analysis results once derived so repeated comparisons are fast.

## Most important immediate next step

The single highest-value next implementation is:

Build the contest dataset + normalized flight metadata + per-flight gaggle summary model first, and only then add broader comparison UI.

This unlocks the true project goal: ingesting multiple contests, comparing years, and analysing gaggle behaviour across the full contest history.

## Next milestone target

The next milestone should be:

A user can load multiple contest folders, normalize the flights, compute per-flight gaggle summaries, and compare those summaries across contests and years in a single analysis view.

That is the point where the app becomes genuinely capable of the long-term research work described in [Pathway.md](Pathway.md).
