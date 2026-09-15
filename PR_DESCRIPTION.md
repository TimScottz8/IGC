# PR Summary

## Title
Implement lifecycle gaggle analysis, competition-scale selection fixes, and CPU-first performance optimizations

## Why
This change set shifts the app from single-day/single-flight behavior toward competition-scale analysis, while preserving reproducibility and improving runtime for larger datasets.

## What changed

### 1. Gaggle lifecycle model
- Replaced drift-centric stitching with lifecycle event semantics:
  - join proximity
  - break distance/duration
  - circling grace
- Updated active/render behavior to use event first/last timestamps.

### 2. Analysis setup and reproducibility
- Added analysis parameter model with impact mapping and fingerprinting.
- Added pre-run validation summaries.

### 3. IGC statistics contract scaffolding
- Added contract-aware export module:
  - context/version/fingerprint
  - day summary builder
  - competition summary builder
  - dataset validation checks
  - validation manifest
  - deterministic JSON/CSV output
- Added tests for deterministic output and domain validation failures.

### 4. Selection scope and viewer control
- Enabled selecting one or multiple competitions for load/analysis.
- Added viewer Day/Class filters after bulk load.
- Fixed selection precedence bugs:
  - most specific selected nodes now win
  - day selection no longer expands to entire competition when ancestor is also selected
  - applied for both local contest tree and viewer start-time tree
- Fixed viewer active-scope override bug:
  - bulk load no longer re-renders full loaded set after filters are applied
  - changing day/class filters now updates active map scope immediately
  - reset filters restores full loaded scope

### 5. CPU-first performance improvements
- Load path:
  - parse only cache misses
  - batch parser-service requests
  - parser-side multi-core processing for large batches with safe fallback
- Gaggle compute path:
  - thermal-segment LRU cache
  - precomputed time-window bounds for faster candidate scans

## Validation
- Focused selection/filter tests pass.
- Gaggle lifecycle tests pass.
- Analysis setup and contract tests pass.
- Offscreen import smoke checks pass.

## Notes
- Full Qt-heavy suite can intermittently SIGSEGV in this environment; focused tests are used for reliable iterative verification.
- CPU usage while opening can appear low when most requested flights are cache hits; multi-core parse is primarily exercised on larger uncached selections.

## Follow-up
1. Add status diagnostics for load operations (selected count, cache hits/misses, parse time).
2. Run benchmark script over one full competition and one multi-competition selection.
3. Wire full day/competition summary generation into UI-triggered analysis execution.
