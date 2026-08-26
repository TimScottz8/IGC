# Qt Migration Notes - 2026-08-26

## Goal
Migrate the slow Streamlit animation workflow to a single-process Python desktop app using PySide6 + pyqtgraph, with incremental testable steps.

## Environment and Dependencies
Installed in project virtual environment:
- PySide6
- pyqtgraph
- pyproj

## What Was Implemented Today

### 1) Desktop shell bootstrap
- Added a standalone desktop entrypoint in `qt_app.py`.
- Confirmed instant startup.

### 2) File open workflow
- Added File -> Open IGC action.
- Displays selected file path in the UI.

### 3) Static track rendering
- Added libigc parsing on file open.
- Renders static flight track.

### 4) High performance animation loop
- Added Play/Pause/Reset controls.
- Kept full track static.
- Per-frame updates only:
  - flown track segment
  - glider marker

### 5) Speed controls
- Added multipliers:
  - 1x
  - 5x
  - 10x
  - 30x
  - 60x
  - 120x

### 6) Timestamp-based playback
- Switched from frame-step playback to fix timestamp playback.
- 1x now means real elapsed fix timing.
- Multipliers scale simulated clock from that baseline.

### 7) Click/seek interaction
- Added double-click on plot to jump marker to nearest fix.
- Works while paused.

### 8) Static task and sector overlays
- Added task route overlay.
- Added start/finish/turnpoint sector overlays.
- Overlays are static and do not update per frame.

### 9) Projection/scaling correction
- Replaced raw lon/lat plotting with local projected coordinates.
- Uses local azimuthal equidistant projection centered on flight.
- Plot uses equal axis scaling (1:1) to avoid visual distortion.

### 10) Timeline scrubber
- Added slider for time/index scrubbing.
- Added elapsed/total time label.
- Slider updates during playback and supports drag-to-seek.

## Bugs Found and Fixed During Migration
- Fixed timestamp type mismatch from libigc (float timestamps vs datetime assumption).
- Added safer error/status reporting in load/render path.
- Fixed indentation regression causing `NameError: name 'self' is not defined` in jump_to_index.

## Current Behavior Summary
- Loads IGC file and renders track quickly.
- Playback is smooth and timestamp-driven.
- Speed, slider scrub, and double-click seek all work.
- Task and sector overlays are visible and static.

## Recommended Next Steps
1. Add info panel:
   - current fix timestamp
   - flight start time
   - estimated groundspeed
   - current task leg
2. Add jump buttons:
   - jump to start
   - jump to first sector entry
   - jump to finish
3. Add parse/overlay cache keyed by file path + modified time for instant reopen.
4. Add a second desktop tab/panel for downloader integration.

## Run Command
`/home/tim/Projects/Gaggles/.venv/bin/python /home/tim/Projects/Gaggles/qt_app.py`
