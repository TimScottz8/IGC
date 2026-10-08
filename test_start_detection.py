import os
import tempfile
import unittest

from start_detection import (
    classify_start_sector,
    detect_start,
    extract_glider_start_time,
)
from task_parsing import extract_pev_times_from_igc

METRES_PER_DEGREE = 6371000.0 * 3.141592653589793 / 180.0


def fix(east_m, north_m, ts):
    return {"lat": north_m / METRES_PER_DEGREE, "lon": east_m / METRES_PER_DEGREE, "timestamp": float(ts)}


LINE_SECTOR = {
    "lat": 0.0,
    "lon": 0.0,
    "radius_m": 10000.0,
    "a1_deg": 0.0,
    "line_flag": 1,
    "orientation_deg": 270.0,
}
CYLINDER_SECTOR = {**LINE_SECTOR, "a1_deg": 180.0, "line_flag": 0, "radius_m": 5000.0}
TP1_SECTOR = {
    "lat": 0.0,
    "lon": 20000.0 / METRES_PER_DEGREE,
    "radius_m": 500.0,
    "a1_deg": 180.0,
    "inner_radius_m": 0.0,
}


class ClassifyStartSectorTests(unittest.TestCase):
    def test_line_flag_means_line(self):
        self.assertEqual(classify_start_sector({"line_flag": 1, "a1_deg": 180.0}), "line")

    def test_semicircle_is_treated_as_line(self):
        self.assertEqual(classify_start_sector({"line_flag": 0, "a1_deg": 90.0}), "line")

    def test_full_circle_is_cylinder(self):
        self.assertEqual(classify_start_sector({"line_flag": 0, "a1_deg": 180.0}), "cylinder")


class LineStartTests(unittest.TestCase):
    def test_crossing_time_is_interpolated_between_fixes(self):
        fixes = [fix(-1000, 0, 0), fix(-200, 0, 10), fix(800, 0, 20)]
        result = detect_start(fixes, LINE_SECTOR, TP1_SECTOR)
        self.assertEqual(result.method, "line")
        self.assertEqual(result.source, "crossing")
        self.assertEqual(result.timestamp, 12.0)
        self.assertAlmostEqual(result.lon, 0.0, places=6)

    def test_last_valid_crossing_wins_and_reverse_crossing_is_ignored(self):
        fixes = [
            fix(-500, 0, 0),
            fix(500, 0, 10),  # first start at t=5
            fix(-500, 0, 20),  # back across the line, wrong direction
            fix(500, 0, 30),  # restart at t=25
        ]
        result = detect_start(fixes, LINE_SECTOR, TP1_SECTOR)
        self.assertEqual(result.timestamp, 25.0)
        self.assertEqual(result.crossing_count, 2)
        self.assertEqual(result.candidates, (5.0, 25.0))

    def test_only_reverse_crossing_gives_no_start(self):
        fixes = [fix(500, 0, 0), fix(-500, 0, 10)]
        result = detect_start(fixes, LINE_SECTOR, TP1_SECTOR)
        self.assertIsNone(result.timestamp)
        self.assertEqual(result.reason, "no_crossing")

    def test_crossing_beyond_line_length_is_ignored(self):
        fixes = [fix(-500, 12000, 0), fix(500, 12000, 10)]
        result = detect_start(fixes, LINE_SECTOR, TP1_SECTOR)
        self.assertEqual(result.reason, "no_crossing")

    def test_crossings_after_first_turnpoint_are_ignored(self):
        fixes = [
            fix(-500, 0, 0),
            fix(500, 0, 10),  # valid start at t=5
            fix(20000, 0, 100),  # inside TP1
            fix(-500, 0, 200),
            fix(500, 0, 210),  # later pass of the line, after TP1
        ]
        self.assertEqual(extract_glider_start_time(fixes, LINE_SECTOR, TP1_SECTOR), 5.0)

    def test_semicircle_start_uses_its_straight_edge(self):
        semicircle = {**LINE_SECTOR, "a1_deg": 90.0, "line_flag": 0}
        fixes = [fix(-300, 0, 0), fix(300, 0, 6)]
        result = detect_start(fixes, semicircle, TP1_SECTOR)
        self.assertEqual(result.method, "line")
        self.assertEqual(result.timestamp, 3.0)

    def test_course_falls_back_to_sector_orientation_without_turnpoint(self):
        fixes = [fix(-500, 0, 0), fix(500, 0, 10)]
        self.assertEqual(extract_glider_start_time(fixes, LINE_SECTOR, None), 5.0)


class CylinderStartTests(unittest.TestCase):
    def setUp(self):
        self.fixes = [fix(-9000 + 1000 * i, 0, i * 10) for i in range(0, 20)]

    def test_last_pev_inside_cylinder_is_the_start(self):
        # Fixes at x = -9000 + 1000*i: inside the 5 km cylinder for i in 5..13.
        result = detect_start(self.fixes, CYLINDER_SECTOR, TP1_SECTOR, pev_timestamps=[60.0, 100.0, 195.0])
        self.assertEqual(result.method, "cylinder")
        self.assertEqual(result.source, "pev")
        self.assertEqual(result.timestamp, 100.0)

    def test_pevs_within_30_seconds_count_as_one_at_the_first_press(self):
        result = detect_start(self.fixes, CYLINDER_SECTOR, TP1_SECTOR, pev_timestamps=[100.0, 104.0, 110.0])
        self.assertEqual(result.timestamp, 100.0)

    def test_without_pev_the_last_cylinder_exit_is_the_start(self):
        result = detect_start(self.fixes, CYLINDER_SECTOR, TP1_SECTOR)
        self.assertEqual(result.source, "exit")
        # x crosses +5000 m between fixes at x=4000 (t=130) and x=5000 (t=140).
        self.assertEqual(result.timestamp, 140.0)

    def test_no_pev_and_no_exit_gives_no_start(self):
        result = detect_start([fix(-9000, 0, 0), fix(-8000, 0, 10)], CYLINDER_SECTOR, TP1_SECTOR)
        self.assertIsNone(result.timestamp)
        self.assertEqual(result.reason, "no_exit")


class MissingInputTests(unittest.TestCase):
    def test_no_start_zone(self):
        self.assertEqual(detect_start([fix(0, 0, 0), fix(1, 0, 1)], None).reason, "no_start_zone")

    def test_no_fixes(self):
        self.assertEqual(detect_start([], LINE_SECTOR).reason, "no_fixes")


class PevParsingTests(unittest.TestCase):
    def test_pev_times_are_read_from_e_records(self):
        with tempfile.NamedTemporaryFile("w", suffix=".igc", delete=False) as handle:
            handle.write("E105104ATS101701\nE114439PEV\nE114726PEV\nE113445BFION AH\n")
            path = handle.name
        try:
            self.assertEqual(extract_pev_times_from_igc(path), [11 * 3600 + 44 * 60 + 39, 11 * 3600 + 47 * 60 + 26])
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
