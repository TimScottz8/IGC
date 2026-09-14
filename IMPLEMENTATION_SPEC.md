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