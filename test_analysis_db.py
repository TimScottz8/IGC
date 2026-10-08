import tempfile
import unittest
from pathlib import Path

from analysis_db import (
    compare_official_with_detected,
    connect,
    import_official,
    resolve_all,
    save_detected_start,
    upsert_class_day,
    upsert_contest,
    upsert_flight,
)
from datetime import datetime, timezone

from start_detection import resolve_start

DAY = "2026-05-09"
MIDNIGHT = datetime.fromisoformat(DAY).replace(tzinfo=timezone.utc).timestamp()


def utc(hh, mm, ss=0):
    return MIDNIGHT + hh * 3600 + mm * 60 + ss


class ResolveStartTests(unittest.TestCase):
    def test_official_is_used_when_it_matches_a_crossing(self):
        self.assertEqual(resolve_start(100.0, 130.0, [100.0, 130.0]), (100.0, "official", None))

    def test_detected_is_used_when_official_matches_no_crossing(self):
        self.assertEqual(resolve_start(500.0, 130.0, [100.0, 130.0]), (130.0, "detected", "official_not_in_crossings"))

    def test_detected_is_used_when_many_pilots_share_the_official_time(self):
        self.assertEqual(resolve_start(100.0, 130.0, [130.0], shared_official_count=3), (130.0, "detected", "shared_official_time"))

    def test_single_source_is_used_when_the_other_is_missing(self):
        self.assertEqual(resolve_start(100.0, None), (100.0, "official", "no_detected_start"))
        self.assertEqual(resolve_start(None, 130.0), (130.0, "detected", "no_official_start"))
        self.assertEqual(resolve_start(None, None), (None, None, "no_start"))


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name) / "test.sqlite")
        self.contest_id = upsert_contest(self.conn, "Test Contest", "https://example.test/c")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add_flight(self, class_name, code, detected, candidates=None):
        class_day_id = upsert_class_day(self.conn, self.contest_id, class_name, DAY)
        flight_id = upsert_flight(self.conn, class_day_id, code, f"/x/{class_name}/{code}.igc", "hash", True)
        save_detected_start(
            self.conn,
            flight_id,
            {"method": "line", "source": "crossing", "timestamp": detected, "crossing_count": 1, "candidates": candidates or [detected]},
        )

    def resolved(self, code):
        return self.conn.execute(
            "SELECT r.start_utc, r.source, r.note FROM start_resolved r JOIN flight f ON f.id = r.flight_id WHERE f.contest_code = ?",
            (code,),
        ).fetchone()

    def test_schema_creation_is_repeatable(self):
        self.conn.executescript("SELECT 1;")
        connect(Path(self.tmp.name) / "test.sqlite").close()

    def test_offset_is_inferred_and_official_start_resolved(self):
        for code, hh, mm, ss in [("A", 11, 50, 56), ("B", 11, 47, 35), ("E", 11, 40, 51), ("F", 11, 44, 10)]:
            self.add_flight("15m", code, utc(hh, mm, ss))
        # Double start: the scored (earlier) start matches an earlier crossing.
        self.add_flight("15m", "C", utc(12, 10), candidates=[utc(11, 44), utc(12, 10)])
        # Official time that matches no crossing.
        self.add_flight("15m", "D", utc(12, 0))
        import_official(
            self.conn,
            "Test Contest",
            "15m",
            DAY,
            {
                "A": {"start": "13:50:56", "finish": None},
                "B": {"start": "13:47:35", "finish": "16:00:00"},
                "E": {"start": "13:40:51", "finish": None},
                "F": {"start": "13:44:10", "finish": None},
                "C": {"start": "13:44:00", "finish": None},
                "D": {"start": "13:31:00", "finish": None},
            },
        )
        resolve_all(self.conn)

        offset = self.conn.execute("SELECT tz_offset_h, tz_source FROM class_day").fetchone()
        self.assertEqual((offset[0], offset[1]), (2.0, "inferred"))
        self.assertEqual(tuple(self.resolved("A")), (utc(11, 50, 56), "official", None))
        self.assertEqual(tuple(self.resolved("C")), (utc(11, 44), "official", None))
        self.assertEqual(tuple(self.resolved("D")), (utc(12, 0), "detected", "official_not_in_crossings"))
        finish = self.conn.execute("SELECT finish_utc FROM start_official WHERE contest_code = 'B'").fetchone()[0]
        self.assertEqual(finish, utc(14, 0))

    def test_gate_time_class_uses_detected_crossings(self):
        for code, hh, mm, ss in [("A", 11, 50, 56), ("B", 11, 47, 35), ("E", 11, 40, 51)]:
            self.add_flight("15m", code, utc(hh, mm, ss))
        pilots = {}
        for code, (mm, ss) in {"G1": (31, 20), "G2": (32, 10), "G3": (33, 0)}.items():
            self.add_flight("Dosi", code, utc(11, mm, ss))
            pilots[code] = {"start": "13:31:00", "finish": None}
        import_official(
            self.conn,
            "Test Contest",
            "15m",
            DAY,
            {
                "A": {"start": "13:50:56", "finish": None},
                "B": {"start": "13:47:35", "finish": None},
                "E": {"start": "13:40:51", "finish": None},
            },
        )
        import_official(self.conn, "Test Contest", "Dosi", DAY, pilots)
        resolve_all(self.conn)

        self.assertEqual(tuple(self.resolved("G2")), (utc(11, 32, 10), "detected", "shared_official_time"))

    def test_compare_reports_residuals(self):
        for code, hh, mm, ss in [("A", 11, 50, 56), ("B", 11, 47, 35), ("E", 11, 40, 51)]:
            self.add_flight("15m", code, utc(hh, mm, ss))
        import_official(
            self.conn,
            "Test Contest",
            "15m",
            DAY,
            {
                "A": {"start": "13:50:56", "finish": None},
                "B": {"start": "13:47:40", "finish": None},
                "E": {"start": "13:40:51", "finish": None},
            },
        )
        resolve_all(self.conn)

        residuals = {Path(row["file_path"]).stem: row["residual_s"] for row in compare_official_with_detected(self.conn)}
        self.assertEqual(residuals, {"A": 0.0, "B": 5.0, "E": 0.0})


if __name__ == "__main__":
    unittest.main()
