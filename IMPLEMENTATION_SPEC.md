# Implementation Specification

## Purpose

This application exists to generate policy-grade evidence for the International Gliding Commission about whether increasing practical availability of live positional awareness, including OGN-style information, is associated with changes in safety-relevant and fairness-relevant contest behaviour.

The app is not primarily a replay viewer. The viewer exists to validate and illustrate analysis. The product output is a reproducible set of metrics, summaries, and graphs that can support discussion of whether rule changes are needed.

## Core Research Questions

The first implementation phase must support these questions:

1. Has the prevalence of gaggle flying changed over time?
2. Has the scale and persistence of gaggle flying changed over time?
3. Are pilots with materially different start times increasingly ending up in the same gaggles?
4. Are later starters increasingly joining already-established groups?
5. Are these patterns consistent across competitions strongly enough to matter for international rule-making?

The app should avoid hard-coding a single OGN adoption date. The evidence should emerge from time-based and competition-based trends.

## Analysis Hierarchy

The analysis pipeline should use these levels:

1. Flight fix level
One timestamped position sample for one glider.

2. Gaggle event level
A contiguous episode in which a set of gliders satisfies the current gaggle definition.

3. Day summary level
One class-day summary built from all analysed flights on that day.

4. Competition summary level
One class competition summary built by aggregating day summaries.

5. Cross-competition comparison level
Time-based graphs comparing competition summaries across years, classes, and countries.

Day is the atomic analysis unit. Competition is the default comparison unit for trend graphs.

## Canonical Gaggle Model

The code should implement a parameterized gaggle event model with a stable contract.

Baseline event definition:

- a gaggle event exists when at least the minimum number of distinct gliders satisfy horizontal, temporal, and vertical proximity rules
- event membership is evaluated from cached analysis-ready flight samples, not reparsed raw IGC records
- contiguous qualifying samples belong to the same event until the persistence or split rules declare the event ended
- nearby short gaps may be bridged by a persistence rule
- event merge logic may combine drifting or slightly separated clusters when configured to do so

The exact threshold values remain configurable. The important part for implementation is that event construction is a separate layer above cached proximity data.

## First Canonical Metrics

The first implementation phase should produce these competition-level metrics, each derived from day summaries:

1. Gaggle Participation Rate
Proportion of starters who enter at least one gaggle event.

2. Normalized Peak Gaggle Size
Largest gaggle size on a day divided by number of starters.

3. Gaggle Time Exposure
Total pilot-minutes spent in gaggle conditions divided by total airborne pilot-minutes.

4. Median Time To First Gaggle Join
Elapsed time from each pilot's own start to first gaggle membership, summarized robustly.

5. Late-Starter Join Rate
Proportion of later starters who join a gaggle already established by earlier starters.

6. Gaggle Start-Time Mixing
Start-time spread within gaggle events.

7. Established-Gaggle Accretion Rate
Proportion of join events in which a pilot joins a pre-existing gaggle rather than belonging to its initial member set.

8. Day-to-Day Consistency
Spread measure across analysed days for the competition, reported alongside headline competition summaries.

## IGC Statistics Contract v1

This section defines the first code-facing export contract for IGC-oriented outputs.

Contract metadata:

- `contract_name`: `igc_statistics`
- `contract_version`: `1.0.0`
- `analysis_version`: from analysis engine (`v1` initially)
- `parameter_fingerprint`: 16-char hash from current analysis parameters
- `generated_at_utc`: ISO-8601 timestamp in UTC

### Dataset Scope

The contract publishes three tabular datasets per analysis run:

1. Flight-day metrics
One row per analysed flight on a specific class-day.

2. Day summary metrics
One row per analysed class-day.

3. Competition summary metrics
One row per analysed competition-class aggregate.

All metric fields below are required unless the nullability rule says otherwise.

### Key And Identity Fields

Identity fields used across all datasets:

- `competition_id`: stable slug-like id for contest
- `competition_name`: human-readable contest name
- `class_id`: stable class slug
- `class_name`: human-readable class name
- `day_id`: `YYYY-MM-DD` (day-scoped datasets only)
- `flight_id`: stable file- or CN-based id (flight-day only)
- `analysis_version`
- `parameter_fingerprint`

## Flight-Day Metrics Schema (v1)

One row per valid analysed flight on one day.

Required fields:

- `competition_id` (string)
- `class_id` (string)
- `day_id` (date string, `YYYY-MM-DD`)
- `flight_id` (string)
- `pilot_code` (string, nullable)
- `start_time_utc_s` (number, nullable)
- `start_rank` (integer, nullable)
- `airborne_duration_s` (number)
- `entered_any_gaggle` (boolean)
- `first_gaggle_join_utc_s` (number, nullable)
- `time_to_first_gaggle_join_s` (number, nullable)
- `gaggle_exposure_s` (number)
- `gaggle_exposure_ratio` (number in `[0,1]`)
- `joined_established_gaggle` (boolean)
- `established_join_count` (integer, default `0`)
- `analysis_version` (string)
- `parameter_fingerprint` (string)

Nullability and rules:

- `start_time_utc_s` and `start_rank` may be null when start cannot be derived.
- `first_gaggle_join_utc_s` and `time_to_first_gaggle_join_s` are null when `entered_any_gaggle=false`.
- `joined_established_gaggle=false` when no join events are detected.

## Day Summary Metrics Schema (v1)

One row per analysed class-day.

Required fields:

- identity fields for competition/class/day
- `starter_count` (integer)
- `valid_flight_count` (integer)
- `excluded_flight_count` (integer)
- `gaggle_participation_rate` (number in `[0,1]`)
- `peak_gaggle_size` (integer)
- `normalized_peak_gaggle_size` (number in `[0,1]`)
- `gaggle_time_exposure_ratio` (number in `[0,1]`)
- `median_time_to_first_gaggle_join_s` (number, nullable)
- `late_starter_join_rate` (number in `[0,1]`, nullable)
- `gaggle_start_time_mixing_iqr_s` (number, nullable)
- `established_gaggle_accretion_rate` (number in `[0,1]`, nullable)
- `event_count` (integer)
- `quality_flag` (enum: `ok`, `partial`, `insufficient_data`)
- `quality_notes` (string, nullable)
- `analysis_version` (string)
- `parameter_fingerprint` (string)

Nullability and rules:

- `median_time_to_first_gaggle_join_s` is null when no flight joins any gaggle.
- `late_starter_join_rate` is null when late-starter denominator is zero.
- `gaggle_start_time_mixing_iqr_s` is null when fewer than two distinct start times exist in event participation.
- `established_gaggle_accretion_rate` is null when no join events exist.

## Competition Summary Metrics Schema (v1)

One row per competition-class aggregate.

Required fields:

- identity fields for competition/class
- `year` (integer)
- `analysed_day_count` (integer)
- `skipped_day_count` (integer)
- `median_gaggle_participation_rate` (number in `[0,1]`, nullable)
- `iqr_gaggle_participation_rate` (number, nullable)
- `median_normalized_peak_gaggle_size` (number in `[0,1]`, nullable)
- `iqr_normalized_peak_gaggle_size` (number, nullable)
- `median_gaggle_time_exposure_ratio` (number in `[0,1]`, nullable)
- `iqr_gaggle_time_exposure_ratio` (number, nullable)
- `median_time_to_first_gaggle_join_s` (number, nullable)
- `iqr_time_to_first_gaggle_join_s` (number, nullable)
- `median_late_starter_join_rate` (number in `[0,1]`, nullable)
- `iqr_late_starter_join_rate` (number, nullable)
- `median_gaggle_start_time_mixing_iqr_s` (number, nullable)
- `iqr_gaggle_start_time_mixing_iqr_s` (number, nullable)
- `median_established_gaggle_accretion_rate` (number in `[0,1]`, nullable)
- `iqr_established_gaggle_accretion_rate` (number, nullable)
- `day_to_day_consistency_score` (number in `[0,1]`, nullable)
- `completeness_flag` (enum: `ok`, `partial`, `insufficient_data`)
- `completeness_notes` (string, nullable)
- `analysis_version` (string)
- `parameter_fingerprint` (string)

Nullability and rules:

- Aggregated metrics are null when fewer than one valid day contributes to that metric.
- IQR fields are null when fewer than two valid day values exist.

## Canonical Metric Definitions (v1)

All rates are computed in real-valued form before rounding.

1. Gaggle Participation Rate (day)

`gaggle_participation_rate = flights_with_entered_any_gaggle / starter_count`

2. Normalized Peak Gaggle Size (day)

`normalized_peak_gaggle_size = peak_gaggle_size / starter_count`

3. Gaggle Time Exposure (day)

`gaggle_time_exposure_ratio = total_gaggle_exposure_s / total_airborne_duration_s`

4. Median Time To First Gaggle Join (day)

Median of `time_to_first_gaggle_join_s` for flights where value is not null.

5. Late-Starter Join Rate (day)

`late_starter_join_rate = late_starters_joined_existing / late_starter_count`

6. Gaggle Start-Time Mixing (day)

For each event, compute start-time spread in seconds across participating flights with known starts; report day median IQR-style spread as `gaggle_start_time_mixing_iqr_s`.

7. Established-Gaggle Accretion Rate (day)

`established_gaggle_accretion_rate = established_join_events / total_join_events`

8. Day-To-Day Consistency (competition)

Derived monotonic score in `[0,1]` using normalized dispersion across primary day-level metrics; exact transform is versioned under `analysis_version` and must be documented in code.

## Units, Rounding, And Serialization

Unit policy:

- durations: seconds (`_s` suffix)
- rates/ratios: unitless real numbers in `[0,1]`
- counts: integers
- date: `YYYY-MM-DD`

Rounding policy for exports:

- rates/ratios: round to 4 decimal places
- duration metrics in seconds: round to nearest integer second
- consistency score: round to 4 decimal places
- do not round internal computation values before final export fields

Serialization policy:

- JSON: numbers must remain numeric (no stringified numbers)
- CSV: empty field represents null
- booleans in CSV: `true` / `false`

## Edge-Case Rules

1. Zero starters on a day

- mark `quality_flag=insufficient_data`
- set rate metrics null
- keep row with explicit notes

2. No valid analysed flights

- mark `quality_flag=insufficient_data`
- all derived day metrics null except counts

3. No gaggle events detected

- set participation/exposure/accretion metrics to `0` where denominator is valid
- set first-join timing metrics null

4. Missing start times for subset of flights

- exclude unknown starts from start-rank and start-mixing denominators
- keep day valid if minimum valid-flight threshold is met
- append quality note with missing-start count

5. Late-starter denominator equals zero

- set `late_starter_join_rate=null`
- add quality note `no late starters under current rule`

6. Total airborne duration is zero

- set `gaggle_time_exposure_ratio=null`
- set day `quality_flag=partial`

7. Single analysed day in competition summary

- median metrics populated from the single day
- all IQR fields null
- completeness flag remains `partial` unless policy explicitly allows `ok`

## Acceptance Checks (Release Gate For v1)

Every generated result set must pass all checks below.

### Structural Checks

- output includes all required datasets and fields for contract v1
- `contract_version`, `analysis_version`, and `parameter_fingerprint` are present in each row set
- primary key uniqueness holds:
	- flight-day: (`competition_id`, `class_id`, `day_id`, `flight_id`)
	- day summary: (`competition_id`, `class_id`, `day_id`)
	- competition summary: (`competition_id`, `class_id`)

### Domain Checks

- all rate/ratio fields are either null or in `[0,1]`
- all count fields are integers `>=0`
- all duration fields are either null or `>=0`
- `valid_flight_count <= starter_count` for each day
- `peak_gaggle_size <= starter_count` when `starter_count > 0`

### Consistency Checks

- for each day row:
	- if `event_count == 0`, then `gaggle_participation_rate == 0` (unless null due to insufficient data)
	- if `gaggle_participation_rate == 0`, then `median_time_to_first_gaggle_join_s` must be null
- competition medians must be computed only from non-null day values of the same metric
- competition IQR fields must be null when contributing day count for that metric is `<2`

### Reproducibility Checks

- re-running unchanged input with identical parameters must produce identical summary rows (except `generated_at_utc`)
- changed `parameter_fingerprint` must invalidate previous result set comparisons unless explicitly grouped by fingerprint

### Data-Quality Checks

- any day below `day_min_valid_flights` must be flagged and excluded from competition headline aggregation
- missing-start and missing-altitude counts must be surfaced in quality notes or side diagnostics

## Acceptance Check Outcome Contract

Each analysis run should emit a validation manifest with:

- `contract_version`
- `analysis_version`
- `parameter_fingerprint`
- `checks_passed` (boolean)
- `failed_checks` (list of check ids)
- `warning_checks` (list of check ids)
- `generated_at_utc`

If `checks_passed=false`, headline competition outputs must be marked non-publishable in the UI.

## Required Normalization Rules

To keep cross-competition comparisons defensible:

- compare competition summaries, not raw pooled events across many days
- normalize size-related metrics by starter count or airborne pilot-time where appropriate
- prefer competition-level medians as headline values
- also store spread across days so a competition cannot appear stable when one day dominated the result

## Competition-Level Aggregation Rules

Each competition-class summary should be built from valid day summaries only.

Headline aggregation defaults:

- median across days for primary metrics
- interquartile range or similar spread measure across days
- count of analysed days
- count of skipped or invalid days
- data completeness flags

Means may also be stored, but medians should be the default public-facing summary unless there is a strong reason otherwise.

## Storage Model

The app should persist analysis in layers so threshold changes do not always require re-analysis from raw flights.

### Layer A: Raw Source Layer

Persist or reference:

- downloaded IGC files
- source contest, class, and day metadata

### Layer B: Parsed Flight Layer

Persist per flight:

- timestamped fixes
- latitude and longitude
- altitude fields needed by analysis
- flight metadata
- derived start time
- task metadata when available

This layer avoids reparsing IGC files.

### Layer C: Analysis-Ready Flight Layer

Persist per analysed day:

- resampled or synchronized flight samples
- projected coordinates suitable for fast distance checks
- valid and airborne masks
- altitude values prepared for vertical-separation tests
- per-flight start-time rank and other derived metadata needed by summary metrics

### Layer D: Proximity Candidate Layer

Persist a superset of plausible neighborhood relationships so the most common threshold changes are cheap:

- candidate nearby gliders by time slice
- horizontal separation candidates within a generous outer radius
- vertical separation candidates or enough altitude data to filter quickly
- sparse adjacency-style data rather than dense all-pairs matrices where possible

### Layer E: Result Sets

Persist one or more result sets for each parameter configuration:

- event-level gaggle summaries
- flight participation summaries
- day summaries
- competition summaries
- generated graphs
- analysis version
- parameter fingerprint

## Parameter Classes And Recompute Rules

The UI and backend should distinguish between fast and deep changes.

### Quick Recompute

These should rerun from cached proximity or event-ready data where possible:

- minimum participant count
- event persistence window
- event merge distance or drift merge tolerance
- late-starter classification when based on cached start rankings
- summary presentation options

### Derived Rebuild Required

These may invalidate proximity candidates and should trigger a warning plus rebuild from the analysis-ready layer:

- horizontal separation threshold when it exceeds the cached candidate envelope
- vertical separation threshold when cached derived data is insufficient
- temporal association window when it changes how candidate proximity is constructed

### Deep Recompute Required

These should warn that a deeper rebuild is needed from a lower analysis layer or from raw parsed traces:

- resampling interval
- coordinate projection or distance method
- altitude source selection when it changes the core separation logic
- thermal-state detection model if gaggle logic depends on it
- raw cleaning or interpolation rules
- any structural change to how events are formed from candidate relationships

## Required Warning Behaviour

When a parameter change invalidates the currently cached layer, the app should say so explicitly.

Required behaviour:

- quick parameters recompute immediately or on demand with no major warning
- derived rebuild parameters show that cached proximity data is invalidated and a rebuild from analysis-ready data is required
- deep parameters show that lower-layer recomputation is required before fresh summaries or graphs can be trusted

Graphs and summaries must always record the parameter fingerprint and analysis version used to create them.

## Persisted Data Entities

The implementation should support at least these persisted logical entities:

### Flight Summary Record

- competition id
- class id
- day id
- flight id
- pilot or competition number
- derived start time
- airborne duration
- any metadata needed for grouping and filtering

### Gaggle Event Record

- event id
- day id
- start time
- end time
- duration
- peak size
- mean size
- unique glider count
- start-time spread
- normalized size fields
- location or task-context fields where available

### Gaggle Participation Record

- event id
- flight id
- entry time
- exit time
- duration in event
- start-time rank
- whether the glider joined an already-established event

### Day Summary Record

- competition id
- class id
- date
- starter count
- valid analysed flight count
- canonical day metrics
- quality flags
- graph references

### Competition Summary Record

- competition id
- class id
- year
- analysed day count
- skipped day count
- canonical aggregated metrics
- day-to-day spread metrics
- completeness flags
- graph references

### Graph Manifest Record

- graph id
- graph type
- scope
- owning competition and class
- optional owning day
- file path
- analysis version
- parameter fingerprint
- generation timestamp

## Human-Readable Outputs

The first reporting system should generate:

### Day-Level Validation Outputs

- gaggle activity through the day
- gaggle size distribution for the day
- start-time versus first-join scatter for pilots on the day

### Competition-Level Summary Outputs

- box or spread plot of day-level normalized peak gaggle size
- box or spread plot of day-level gaggle participation rate
- summary of start-time mixing across days
- compact headline summary panel with the canonical competition metrics

### Cross-Competition Trend Outputs

- time-based trend of competition-level gaggle participation
- time-based trend of competition-level normalized peak gaggle size
- time-based trend of median time to first gaggle join
- time-based trend of gaggle start-time mixing
- time-based trend of late-starter join rate

Competition should be the default point shown in long-term graphs. Day-level plots should exist mainly for drill-down and validation.

## First Implementation Sequence

Implementation should proceed in this order:

1. Finalize the event model contract in code-facing terms.
2. Define persisted schemas for flight, event, participation, day summary, competition summary, and graph manifest data.
3. Build competition download and day-analysis orchestration.
4. Persist parsed and analysis-ready layers so repeated runs avoid raw reparsing.
5. Add parameter fingerprinting and cache invalidation rules.
6. Generate canonical day summaries.
7. Aggregate competition summaries from day summaries.
8. Generate saved graphs and narrative summary outputs.
9. Expose parameter classes in the UI with correct warnings for deeper rebuilds.

## Non-Goals For This Phase

The first implementation phase should not drift into:

- making the live viewer the primary product
- relying on a single pre-OGN versus post-OGN cutoff date
- inventing one composite gaggle score too early
- overbuilding 3D or presentation polish before the metric pipeline is stable
- hiding analysis-version or parameter-version provenance

## Handoff Note For Next Session

The next implementation session should treat this document as the contract for the first analysis pipeline phase.

The immediate coding priority is not more discussion. It is to translate this specification into:

1. explicit data structures
2. cache-layer boundaries
3. parameter invalidation rules
4. day and competition summary generation
5. saved graph outputs tied to parameter fingerprints