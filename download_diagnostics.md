# Download diagnostics

## Purpose

This file records the live-tuning notes for SoaringSpot download performance so the app can be adjusted against real site behavior.

## Symptom

The app was downloading contest files far more slowly than a normal browser for the same contest URL, especially when the selected contest contained many IGC files.

## Likely cause

The main bottlenecks were:
- serial per-file downloads instead of a small concurrent pool
- no retry/backoff handling for rate-limited or transient server responses
- minimal browser-like headers rather than a fuller browser session profile
- multiple HTML crawl steps before the actual payload download

## What has been changed

The following improvements were implemented:
- browser-like headers added in `download_helpers.browser_headers()`
- retry/backoff added in `download_single_candidate()` for 429 / 5xx responses
- small thread pool used in `ContestDownloadWorker.run()` for concurrent file downloads
- session-level keep-alive and browser-like defaults added in `create_session()`

## Recommended live checks

When testing again against SoaringSpot, compare:
1. number of files downloaded per minute
2. how often the app hits 429/5xx responses
3. whether retry delays are occurring
4. whether the app now behaves much closer to browser download speed for a contest of similar size

## Observations to capture

For each contest test, write down:
- contest URL
- number of selected files
- total elapsed runtime
- whether any retry happened
- whether any file failed with `429`, `502`, `503`, or `504`
- whether the browser still outperforms the app after the changes

## Next tuning steps if still slow

If live tests still show poor performance, the next likely improvements are:
- reduce HTML crawl depth before download starts
- pre-resolve direct file URLs more aggressively
- use a stronger browser/session profile and explicit cookie persistence
- throttle concurrency to a level that avoids SoaringSpot rate-limiting
- add timing logs for each file and per-attempt retry count

## Current status

The code has been improved for the most likely cause and validated with regression tests, but live SoaringSpot timing should still be checked in the browser environment against the same contest URL.
