"""SQLite store for contest flights, official results and detected start times."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from download_helpers import DOWNLOAD_DIR, sanitize
from official_results import contest_id_from_igc_path, fetch_contest_results, seconds_of_day
from start_detection import resolve_start

DEFAULT_DB_PATH = Path(DOWNLOAD_DIR) / "igc_analysis.sqlite"
DETECTOR_VERSION = "start-v1"
MIN_OFFSET_SAMPLES = 3
OFFSET_TOLERANCE_S = 900

# All timestamps are UTC epoch seconds except the *_local columns, which hold the page's clock text.
SCHEMA = """
CREATE TABLE IF NOT EXISTS contest (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    url TEXT
);
CREATE TABLE IF NOT EXISTS class_day (
    id INTEGER PRIMARY KEY,
    contest_id INTEGER NOT NULL REFERENCES contest(id),
    class_name TEXT NOT NULL,
    day TEXT NOT NULL,
    results_url TEXT,
    tz_offset_h REAL,
    tz_source TEXT,
    UNIQUE (contest_id, class_name, day)
);
CREATE TABLE IF NOT EXISTS flight (
    id INTEGER PRIMARY KEY,
    class_day_id INTEGER NOT NULL REFERENCES class_day(id),
    contest_code TEXT NOT NULL,
    file_path TEXT NOT NULL UNIQUE,
    file_sha256 TEXT NOT NULL,
    valid INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS start_official (
    class_day_id INTEGER NOT NULL REFERENCES class_day(id),
    contest_code TEXT NOT NULL,
    start_local TEXT,
    finish_local TEXT,
    start_utc REAL,
    finish_utc REAL,
    PRIMARY KEY (class_day_id, contest_code)
);
CREATE TABLE IF NOT EXISTS start_detected (
    flight_id INTEGER PRIMARY KEY REFERENCES flight(id) ON DELETE CASCADE,
    detector_version TEXT NOT NULL,
    method TEXT,
    source TEXT,
    timestamp_utc REAL,
    lat REAL,
    lon REAL,
    crossing_count INTEGER NOT NULL,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS start_crossing (
    flight_id INTEGER NOT NULL REFERENCES flight(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    timestamp_utc REAL NOT NULL,
    PRIMARY KEY (flight_id, seq)
);
CREATE TABLE IF NOT EXISTS start_resolved (
    flight_id INTEGER PRIMARY KEY REFERENCES flight(id) ON DELETE CASCADE,
    start_utc REAL,
    source TEXT,
    note TEXT
);
"""


def connect(path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def upsert_contest(conn: sqlite3.Connection, name: str, url: str | None = None) -> int:
    conn.execute(
        "INSERT INTO contest (name, url) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET url = COALESCE(excluded.url, contest.url)",
        (name, url),
    )
    return conn.execute("SELECT id FROM contest WHERE name = ?", (name,)).fetchone()[0]


def upsert_class_day(
    conn: sqlite3.Connection, contest_id: int, class_name: str, day: str, results_url: str | None = None
) -> int:
    conn.execute(
        "INSERT INTO class_day (contest_id, class_name, day, results_url) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(contest_id, class_name, day) DO UPDATE SET "
        "results_url = COALESCE(excluded.results_url, class_day.results_url)",
        (contest_id, class_name, day, results_url),
    )
    return conn.execute(
        "SELECT id FROM class_day WHERE contest_id = ? AND class_name = ? AND day = ?",
        (contest_id, class_name, day),
    ).fetchone()[0]


def upsert_flight(
    conn: sqlite3.Connection, class_day_id: int, contest_code: str, file_path: str, file_sha256: str, valid: bool
) -> int:
    conn.execute(
        "INSERT INTO flight (class_day_id, contest_code, file_path, file_sha256, valid) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(file_path) DO UPDATE SET class_day_id = excluded.class_day_id, "
        "contest_code = excluded.contest_code, file_sha256 = excluded.file_sha256, valid = excluded.valid",
        (class_day_id, contest_code, file_path, file_sha256, int(valid)),
    )
    return conn.execute("SELECT id FROM flight WHERE file_path = ?", (file_path,)).fetchone()[0]


def save_detected_start(conn: sqlite3.Connection, flight_id: int, detail: dict[str, Any]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO start_detected "
        "(flight_id, detector_version, method, source, timestamp_utc, lat, lon, crossing_count, reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            flight_id,
            DETECTOR_VERSION,
            detail.get("method"),
            detail.get("source"),
            detail.get("timestamp"),
            detail.get("lat"),
            detail.get("lon"),
            int(detail.get("crossing_count") or 0),
            detail.get("reason"),
        ),
    )
    conn.execute("DELETE FROM start_crossing WHERE flight_id = ?", (flight_id,))
    conn.executemany(
        "INSERT INTO start_crossing (flight_id, seq, timestamp_utc) VALUES (?, ?, ?)",
        [(flight_id, seq, ts) for seq, ts in enumerate(detail.get("candidates") or [])],
    )


def import_official(
    conn: sqlite3.Connection,
    contest_name: str,
    class_name: str,
    day: str,
    pilots: dict[str, dict[str, str | None]],
    results_url: str | None = None,
) -> int:
    """Store a day's official local times; UTC values are filled in by resolve_all."""
    class_day_id = upsert_class_day(conn, upsert_contest(conn, contest_name), class_name, day, results_url)
    conn.execute("DELETE FROM start_official WHERE class_day_id = ?", (class_day_id,))
    conn.executemany(
        "INSERT INTO start_official (class_day_id, contest_code, start_local, finish_local) VALUES (?, ?, ?, ?)",
        [(class_day_id, code, times.get("start"), times.get("finish")) for code, times in pilots.items()],
    )
    return class_day_id


def _local_to_epoch(day: str, local_time: str | None, offset_h: float | None) -> float | None:
    sod = seconds_of_day(local_time)
    if sod is None or offset_h is None:
        return None
    try:
        midnight = datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None
    return midnight + sod - offset_h * 3600.0


def infer_tz_offsets(conn: sqlite3.Connection) -> int:
    """Infer each contest day's whole-hour UTC offset from official local vs detected UTC starts.

    The IGC timezone header is unreliable, so the median difference is used instead. Days without
    enough comparable flights take the contest's most common offset.
    """
    rows = conn.execute(
        "SELECT cd.contest_id, cd.day, o.start_local, d.timestamp_utc "
        "FROM start_official o "
        "JOIN class_day cd ON cd.id = o.class_day_id "
        "JOIN flight f ON f.class_day_id = o.class_day_id AND f.contest_code = o.contest_code "
        "JOIN start_detected d ON d.flight_id = f.id "
        "WHERE o.start_local IS NOT NULL AND d.timestamp_utc IS NOT NULL"
    ).fetchall()
    deltas: dict[tuple[int, str], list[int]] = defaultdict(list)
    for row in rows:
        deltas[(row["contest_id"], row["day"])].append(
            seconds_of_day(row["start_local"]) - int(row["timestamp_utc"]) % 86400
        )

    inferred: dict[tuple[int, str], float] = {}
    for key, values in deltas.items():
        if len(values) < MIN_OFFSET_SAMPLES:
            continue
        median = statistics.median(values)
        hours = round(median / 3600.0)
        if abs(median - hours * 3600) <= OFFSET_TOLERANCE_S:
            inferred[key] = float(hours)

    by_contest: dict[int, list[float]] = defaultdict(list)
    for (contest_id, _), hours in inferred.items():
        by_contest[contest_id].append(hours)
    contest_mode = {cid: Counter(values).most_common(1)[0][0] for cid, values in by_contest.items()}

    updated = 0
    for row in conn.execute("SELECT id, contest_id, day FROM class_day").fetchall():
        key = (row["contest_id"], row["day"])
        if key in inferred:
            offset, source = inferred[key], "inferred"
        elif row["contest_id"] in contest_mode:
            offset, source = contest_mode[row["contest_id"]], "contest_mode"
        else:
            offset, source = None, None
        conn.execute("UPDATE class_day SET tz_offset_h = ?, tz_source = ? WHERE id = ?", (offset, source, row["id"]))
        updated += offset is not None
    return updated


def resolve_all(conn: sqlite3.Connection) -> None:
    """Fill official UTC times and the start time used for each valid flight."""
    infer_tz_offsets(conn)

    for row in conn.execute(
        "SELECT o.class_day_id, o.contest_code, o.start_local, o.finish_local, cd.day, cd.tz_offset_h "
        "FROM start_official o JOIN class_day cd ON cd.id = o.class_day_id"
    ).fetchall():
        conn.execute(
            "UPDATE start_official SET start_utc = ?, finish_utc = ? WHERE class_day_id = ? AND contest_code = ?",
            (
                _local_to_epoch(row["day"], row["start_local"], row["tz_offset_h"]),
                _local_to_epoch(row["day"], row["finish_local"], row["tz_offset_h"]),
                row["class_day_id"],
                row["contest_code"],
            ),
        )

    shared = Counter(
        (row["class_day_id"], row["start_utc"])
        for row in conn.execute("SELECT class_day_id, start_utc FROM start_official WHERE start_utc IS NOT NULL")
    )
    crossings: dict[int, list[float]] = defaultdict(list)
    for row in conn.execute("SELECT flight_id, timestamp_utc FROM start_crossing ORDER BY flight_id, seq"):
        crossings[row["flight_id"]].append(row["timestamp_utc"])

    for row in conn.execute(
        "SELECT f.id, f.class_day_id, o.start_utc AS official_utc, d.timestamp_utc AS detected_utc "
        "FROM flight f "
        "LEFT JOIN start_official o ON o.class_day_id = f.class_day_id AND o.contest_code = f.contest_code "
        "LEFT JOIN start_detected d ON d.flight_id = f.id "
        "WHERE f.valid = 1"
    ).fetchall():
        start, source, note = resolve_start(
            row["official_utc"],
            row["detected_utc"],
            crossings.get(row["id"], ()),
            shared.get((row["class_day_id"], row["official_utc"]), 1),
        )
        conn.execute(
            "INSERT OR REPLACE INTO start_resolved (flight_id, start_utc, source, note) VALUES (?, ?, ?, ?)",
            (row["id"], start, source, note),
        )
    conn.commit()


def compare_official_with_detected(conn: sqlite3.Connection, tolerance_s: float = 2.0) -> list[dict[str, Any]]:
    """Return one row per flight that has both an official and a detected start."""
    return [
        dict(row)
        for row in conn.execute(
            "SELECT c.name AS contest, cd.class_name, cd.day, f.file_path, "
            "o.start_utc - d.timestamp_utc AS residual_s, r.source, r.note "
            "FROM flight f "
            "JOIN class_day cd ON cd.id = f.class_day_id "
            "JOIN contest c ON c.id = cd.contest_id "
            "JOIN start_official o ON o.class_day_id = f.class_day_id AND o.contest_code = f.contest_code "
            "JOIN start_detected d ON d.flight_id = f.id "
            "LEFT JOIN start_resolved r ON r.flight_id = f.id "
            "WHERE o.start_utc IS NOT NULL AND d.timestamp_utc IS NOT NULL "
            "ORDER BY c.name, cd.class_name, cd.day, f.file_path"
        )
    ]


def analyse_file(path: str) -> dict[str, Any]:
    """Worker for the process pool: hash a file and run start detection on it."""
    from flight_model import load_flight_record  # deferred: pulls in libigc

    try:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        record = load_flight_record(path)
        return {
            "path": path,
            "sha256": digest,
            "valid": bool(record.valid),
            "start_detail": record.start_detail if record.valid else None,
        }
    except Exception as exc:
        return {"path": path, "error": str(exc)}


def discover_igc_files(downloads_dir: str | Path) -> list[tuple[str, str, str, Path]]:
    """Return (contest, class, day, path) for files laid out as <contest>/<class>/<day>/*.igc."""
    return [
        (igc.parent.parent.parent.name, igc.parent.parent.name, igc.parent.name, igc)
        for igc in sorted(Path(downloads_dir).glob("*/*/*/*.igc"))
    ]


def _queue_urls(downloads_dir: str | Path) -> dict[str, str]:
    path = Path(downloads_dir) / ".contest_acquisition_queue.json"
    if not path.exists():
        return {}
    entries = json.loads(path.read_text(encoding="utf-8")).get("contests", [])
    return {sanitize(entry["name"]): entry["url"] for entry in entries if entry.get("name") and entry.get("url")}


def build_database(downloads_dir: str | Path, db_path: str | Path = DEFAULT_DB_PATH, workers: int | None = None) -> dict:
    files = discover_igc_files(downloads_dir)
    urls = _queue_urls(downloads_dir)
    conn = connect(db_path)
    errors: list[str] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for (contest, class_name, day, path), result in zip(
            files, pool.map(analyse_file, [str(item[3]) for item in files], chunksize=4)
        ):
            if "error" in result:
                errors.append(f"{path}: {result['error']}")
                continue
            class_day_id = upsert_class_day(conn, upsert_contest(conn, contest, urls.get(contest)), class_name, day)
            flight_id = upsert_flight(
                conn, class_day_id, contest_id_from_igc_path(path), str(path), result["sha256"], result["valid"]
            )
            if result["start_detail"]:
                save_detected_start(conn, flight_id, result["start_detail"])
    conn.commit()
    resolve_all(conn)
    flights = conn.execute("SELECT COUNT(*) FROM flight").fetchone()[0]
    conn.close()
    return {"files": len(files), "flights": flights, "errors": errors}


def _print_check(conn: sqlite3.Connection) -> None:
    rows = compare_official_with_detected(conn)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["contest"], row["class_name"], row["day"])].append(row)
    for (contest, class_name, day), items in groups.items():
        matched = sum(1 for item in items if abs(item["residual_s"]) <= 2.0)
        print(f"{contest} / {class_name} / {day}: matched {matched}/{len(items)}")
        for item in items:
            if abs(item["residual_s"]) > 2.0:
                print(
                    f"   {Path(item['file_path']).name}: residual {item['residual_s']:+.0f}s "
                    f"-> {item['source']} ({item['note'] or 'official matches a crossing'})"
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analysis_db")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="scan downloaded IGC files and detect starts")
    build.add_argument("--downloads", default=DOWNLOAD_DIR)
    fetch = commands.add_parser("fetch-official", help="scrape official times for a contest")
    fetch.add_argument("contest_url")
    fetch.add_argument("contest_name", help="the contest's folder name under the downloads directory")
    commands.add_parser("resolve", help="recompute UTC offsets and the start time used for each flight")
    commands.add_parser("check", help="compare official and detected starts")
    args = parser.parse_args(argv)

    if args.command == "build":
        summary = build_database(args.downloads, args.db)
        print(f"{summary['flights']} flights stored from {summary['files']} files")
        for message in summary["errors"]:
            print(f"error: {message}", file=sys.stderr)
        return 1 if summary["errors"] else 0

    conn = connect(args.db)
    if args.command == "fetch-official":
        contest = sanitize(args.contest_name)
        upsert_contest(conn, contest, args.contest_url)
        for item in fetch_contest_results(args.contest_url):
            import_official(conn, contest, item["class_name"], item["day"], item["pilots"], item["url"])
        conn.commit()
        resolve_all(conn)
    elif args.command == "resolve":
        resolve_all(conn)
    else:
        _print_check(conn)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
