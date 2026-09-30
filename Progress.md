# Progress Summary

Canonical overview:
- `README.md` describes the current project scope
- `Pathway.md` describes the long-term analysis direction
- `resume.md` is the handoff guide for the next working session

## Update 2026-09-15

### Completed today
- implemented lifecycle-based gaggle event semantics in the analysis engine using join, break-distance, break-duration, and circling-grace behavior
- removed drift-stitch dependence from active/static gaggle rendering and aligned overlays with event first/last timestamps
- added and passed lifecycle-focused regression tests for continuity across short gaps and split behavior under sustained separation
- added Analysis setup contract details for IGC statistics in `IMPLEMENTATION_SPEC.md`, including schema fields, nullability rules, acceptance checks, and reproducibility requirements
- implemented `igc_statistics.py` with:
- contract context and parameter fingerprint wiring
- day-summary and competition-summary builders
- dataset validation manifest generation
- deterministic JSON/CSV export scaffolding
- added tests for statistics contract determinism and domain/range validation failures
- enabled bulk multi-competition selection from local downloaded contest tree
- added day/class filters in the Flight viewer start-time panel to control displayed subsets after bulk load
- fixed selection precedence bugs so most-specific selected nodes win:
- selecting day under class no longer pulls whole competition
- mixed ancestor/descendant selection now resolves to requested subset for both local contest tree and viewer start-time tree
- improved flight loading performance:
- parse only cache misses instead of reparsing whole requested set
- batch parser-service payload requests to reduce per-file IPC overhead
- introduced OS-agnostic multi-core parser support for large batches with safe serial fallback
- added CPU-side gaggle compute optimizations:
- LRU thermal-segment cache across reruns
- precomputed time-window bounds for faster neighbor membership scans

### Validation and quality checks completed
- static diagnostics report no errors on edited modules
- focused regression suites passed for:
- gaggle lifecycle logic
- analysis setup and fingerprint behavior
- IGC statistics contract and export determinism
- selection-precedence behavior for local and viewer trees
- import smoke checks passed for `qt_app.py`, `qt_viewer.py`, and `flight_model.py` in offscreen Qt mode

### Current state
- app supports selecting whole competitions or multiple competitions, then narrowing viewer display by day and class
- analysis stack now has a documented, test-covered statistics contract and export scaffolding
- major bottlenecks addressed in both flight loading and gaggle recompute paths using CPU-first optimizations

### Final end-of-day fixes
- fixed a remaining viewer-scope bug where bulk-load rendering could override day/class filters and show full competition tracks again
- filter changes now update active viewer scope immediately, and refresh paths also reapply filters automatically
- reset filters now restores full loaded scope from the retained loaded-flight metadata set
- updated selected-files label to reflect current filtered active scope
- verified with offscreen integration run that:
1. loading two days produces two active flights
2. selecting one day/class reduces active scope to one flight
3. reset returns to full two-flight scope

### Parse/CPU behavior clarification
- parser now supports multi-core parse for large uncached selections with safe fallback to serial
- for small selections or mostly cached selections, lower CPU usage is expected by design due to thresholding and cache-hit reuse
- parser threshold and batching are tuned to avoid multiprocessing overhead on small requests

### Updated next session priorities
1. add explicit load diagnostics in status text: selected count, cache hits, cache misses, parse workers used, parse elapsed time
2. run repeatable benchmark on one full competition and one multi-competition selection with cold vs warm cache
3. wire UI action from Analysis setup to produce day-summary and competition-summary outputs using the contract pipeline

## Current checkpoint
The project is now a working multi-flight desktop viewer and analysis-oriented workflow with a stable contest discovery path, a direct IGC download pipeline, a live per-file queue, and a host-cooldown strategy to reduce SoaringSpot throttling. The app remains analysis-first: the immediate focus is not just file loading but multi-contest interpretation and gaggle behaviour across datasets.

The key technical result from this session is that we have moved beyond the earlier false-candidate bug and can now distinguish genuine IGC flight payloads from generic SoaringSpot download pages and internal route stubs. The remaining live-server issue is not a logic crash but the host’s own request throttling.

## Completed in this session block
- fixed the SoaringSpot false-positive bug that treated `/downloads` and `download-contest-flight/3377-*` URLs as real flight files
- added a live per-file download queue to the Download tab so progress is visible at the file level
- added retry count and elapsed time tracking for each file in the download queue
- reduced the download worker to a conservative single-thread mode for SoaringSpot to avoid triggering burst throttling
- implemented a host cooldown mechanism that pauses requests after 429/5xx throttle responses
- verified live discovery against the real contest URL and confirmed the false URL types are no longer generated
- updated regression tests to cover the false-positive filter and host cooldown behaviour

## Current behaviour
The app can now:
- discover and download contest flights from SoaringSpot without collecting obvious false candidates
- ignore generic contest `/downloads` pages and non-flight route stubs
- display live file-level status in a queue table while downloads are running
- detect host throttling and cool down for a short period instead of continuing aggressive bursts
- maintain a stable Qt import path and pass the relevant contest discovery regression tests

## Important implementation notes
- `download_helpers.py` now contains the main false-positive filtering and host-cooldown logic
- `qt_helpers.py` now records per-request retry and timing info and waits for host cooldown before issuing the next request
- `qt_controllers.py` now runs contest downloads with a conservative single-worker policy for SoaringSpot downloads
- `qt_app.py` shows a per-file queue table so the user can see exactly what is being processed and whether a request is throttled or retried
- `test_contest_dataset.py` is now the regression suite covering the false-candidate issue, real SoaringSpot discovery, and cooldown behaviour

## Current limitations and known issues
- SoaringSpot still appears to impose host-level request throttling on bulk direct-download access; the app now treats that as a first-class host constraint rather than a logic defect
- a single-worker policy is safer than aggressive concurrency, but it can still be slow when many files are queued for one contest
- a proper overnight queue manager is still the next product-level step so the app can keep fetching a backlog without the user needing to babysit the process
- future work should likely keep the queue serialised per contest to respect the host's request budget

## Verified status
Verified commands in the local venv:
- `.venv/bin/python -m pytest -q test_contest_dataset.py`
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -X faulthandler - <<'PY' ... import qt_app ... PY`

Fresh result:
- import succeeded
- 7 regression tests passed

## Best next steps
1. add a queue of contest URLs that downloads sequentially overnight, one contest at a time
2. persist the queue to disk so it survives app restarts
3. add a “run all queued contests” button and a pause/resume status
4. once the queue is in place, add a richer contest-summary view for multi-year and multi-contest comparisons
5. keep the download strategy conservative so we do not upset the host or trigger temporary blocks

## Restart prompt for next time
Resume from `resume.md` and continue with the overnight contest queue and bulk dataset workflow, keeping the SoaringSpot host cooldown and conservative serial download policy as the core safety constraint.
