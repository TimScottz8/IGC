# Implementation Checklist for Multi-Contest Analysis

## Objective

Implement the first dataset-level analysis slice so the app can load multiple contests, normalize flight metadata, compute per-flight gaggle summaries, and present a comparison table across contests and years.

This is the next milestone after the current viewer and thermal gaggle workflow described in [Progress.md](Progress.md).

## Milestone

A user can:
- load multiple contest folders
- normalize the flight metadata consistently
- compute per-flight gaggle summary metrics
- compare summary rows across contest/year/class filters
- select a flight from the summary and inspect it in the current viewer context

## Implementation order

### 1. Data model classes

#### A. ContestMetadata
Add a small dataclass to represent a contest-level record.

Fields:
- contest_id: str
- name: str
- year: int | str
- location: str | None
- era: str | None
- class_names: list[str]
- source_path: str
- day_labels: list[str]

#### B. NormalizedFlightRecord
Add a normalized flight model that sits above the raw parsed IGC flight record.

Fields:
- flight_id: str
- file_path: str
- contest_id: str
- contest_name: str
- year: int | str
- class_name: str
- day: str
- pilot_name: str | None
- start_time: str | None
- source_path: str
- task_points: list[dict]
- task_sectors: list[dict]
- fixes: list
- summary: FlightGaggleSummary | None

#### C. FlightGaggleSummary
Add a dataclass for per-flight gaggle metrics.

Fields:
- flight_id: str
- first_gaggle_time: float | None
- peak_gaggle_size: int
- time_to_join_gaggle: float | None
- total_time_in_gaggle: float
- start_time_band: str
- formed_gaggle: bool
- joined_existing_gaggle: bool

#### D. ContestDataset
Add a collection object that manages a corpus of contest flights.

Methods:
- add_contest(contest_path: str) -> ContestMetadata
- load_contest(contest_path: str) -> list[NormalizedFlightRecord]
- load_contests(contest_paths: list[str]) -> list[NormalizedFlightRecord]
- filter_by_year(year)
- filter_by_class(class_name)
- filter_by_day(day)
- filter_by_era(era)
- get_summary_rows()

---

### 2. Normalization layer

#### Requirements
Normalize the current flight metadata so all contests share the same schema.

#### Tasks
- detect contest name and year from contest path or source metadata
- parse class name from path layout or flight tags where available
- parse day label from folder structure
- map each flight to its contest and class
- standardize start time and task metadata

#### Validation
- A contest folder with multiple days should produce multiple day values.
- A contest folder with multiple classes should produce a distinct class label per flight.
- Summary rows should not depend on ad hoc parsing logic in each UI call.

---

### 3. Per-flight gaggle summary generation

#### Requirements
Once a valid flight record exists, compute simple summary metrics for gaggle behaviour.

#### Tasks
- reuse current gaggle detection output from [gaggle_analysis.py](gaggle_analysis.py)
- aggregate event membership to derive flight-level metrics
- summarize the pilot’s grouping pattern over time
- record first gaggle start, peak group size, and total time in group

#### Suggested logic
- `first_gaggle_time`: earliest detected thermal cluster event time for that flight
- `peak_gaggle_size`: maximum observed cluster size for that flight
- `time_to_join_gaggle`: elapsed time from start to first valid gaggle membership
- `total_time_in_gaggle`: cumulative time spent inside detected cluster events
- `start_time_band`: classify start as early / mid / late using contest-specific quantiles or fixed windowing

#### Validation
- For a flight with no gaggle events, summary values should be empty / zero / None, not crash.
- For a flight with clear cluster events, summary values should match a direct manual inspection of event data.

---

### 4. Dataset summary table UI

#### Requirements
Add a UI block that lists the current cohort of flights in a normalized, compareable view.

#### Columns
- Pilot
- Contest
- Year
- Class
- Day
- Start time
- First gaggle
- Peak gaggle size
- Total gaggle time
- Start-time band

#### UI placement
Best placement for this first pass:
- left or top data panel beneath the contest selector in the main window
- compact table with row selection
- selection should update the current flight viewer while preserving current playback time

#### Interaction behavior
- clicking a row selects that flight for viewer inspection
- selecting multiple rows should still be possible for a subset comparison in the future
- filtering should update the table immediately without reloading the whole app

---

### 5. Dataset filter controls

#### Requirements
Support comparisons across contests and years with simple filters.

#### Controls
- contest selector
- year dropdown
- class dropdown
- day dropdown
- era dropdown
- maybe “selected contests only” toggle

#### Logic
- filter dataset at the contest collection level
- update summary table and selected flights from the filtered result set
- keep the viewer and summary table synchronized

#### Validation
- Filtering by year or class updates the summary table without breaking selection state.
- Empty selections should show a clean empty state instead of errors.

---

### 6. Test plan

## Unit tests to add first

### A. test_contest_dataset_loads_multiple_contests
- create a synthetic folder layout with multiple contest directories
- assert dataset loads all normalized records

### B. test_dataset_filters_by_year_class_and_era
- assert `filter_by_year`, `filter_by_class`, and `filter_by_era` return only matching records

### C. test_flight_summary_metrics_are_computed
- create a minimal fake flight with cluster events
- assert summary fields match expected values

### D. test_empty_summary_handles_no_gaggle_events
- assert no-gaggle flight produces zero/None values without crashing

### E. test_start_time_band_classification
- assert early/mid/late classification behaves properly

## Integration tests

### A. load_real_dataset_subset
- load a few real downloaded contest folders from the workspace
- assert the dataset summary table has rows and non-zero gaggle summaries when expected

### B. filter_round_trip
- change class/year/era filters in the UI state model
- assert summary rows update correctly

### C. selection_sync
- click a summary row and ensure the current flight selection and viewer state update without resetting time

## Validation commands

Use the project-local venv and selected interpreter as required by repo instructions.

### Linux/macOS
```bash
source .venv/bin/activate
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

### Focused compile check
```bash
source .venv/bin/activate
.venv/bin/python -m py_compile flight_model.py flight_loader.py gaggle_analysis.py qt_app.py
```

## Definition of done

This slice is complete when:
- the app can load multiple contest folders
- the dataset is normalized and queryable
- per-flight gaggle summaries are produced
- a summary table can be filtered by contest/year/class/era
- selecting a row updates the current viewer context
- tests cover the normalization/filtering/summary logic

## Next milestone after this slice

Once this is complete, the next step is to add a lightweight comparison dashboard with charts and aggregated contest-era summaries, rather than adding more map features.
