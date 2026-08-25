import unittest

from geo_task import (
    _bearing_between_points,
    _infer_sector_orientation,
    _internal_bisector_from_legs,
    _outward_bisector_from_legs,
    build_sector_points,
    build_sector_split_points,
    extract_glider_start_time,
    extract_task_sectors_from_igc,
    format_human_readable_datetime,
    is_point_in_sector,
    project_geometry_table,
    project_point_from_bearing,
)


class SectorGeometryTests(unittest.TestCase):
    def test_sector_arc_is_symmetric_about_outward_bisector(self):
        center_lat = 0.0
        center_lon = 0.0
        radius_m = 1000.0
        center_bearing_deg = 270.0

        expected_start_lat, expected_start_lon = project_point_from_bearing(
            center_lat,
            center_lon,
            center_bearing_deg - 45.0,
            radius_m,
        )
        expected_end_lat, expected_end_lon = project_point_from_bearing(
            center_lat,
            center_lon,
            center_bearing_deg + 45.0,
            radius_m,
        )

        actual = build_sector_points(
            center_lat,
            center_lon,
            radius_m,
            45.0,
            180.0,
            center_bearing_deg=center_bearing_deg,
        )

        # The sector is symmetric around the outward bisector. The arc should
        # begin at the 45° left-hand side and end at the 45° right-hand side.
        self.assertAlmostEqual(actual[1][0], expected_start_lat, places=12)
        self.assertAlmostEqual(actual[1][1], expected_start_lon, places=12)
        self.assertAlmostEqual(actual[-2][0], expected_end_lat, places=12)
        self.assertAlmostEqual(actual[-2][1], expected_end_lon, places=12)

    def test_sector_is_drawn_as_two_halves_from_bisector(self):
        center_lat = 0.0
        center_lon = 0.0
        radius_m = 1000.0
        center_bearing_deg = 270.0

        cw_points, ccw_points = build_sector_split_points(
            center_lat,
            center_lon,
            radius_m,
            center_bearing_deg,
            45.0,
        )

        expected_cw_end = project_point_from_bearing(
            center_lat,
            center_lon,
            center_bearing_deg + 45.0,
            radius_m,
        )
        expected_ccw_end = project_point_from_bearing(
            center_lat,
            center_lon,
            center_bearing_deg - 45.0,
            radius_m,
        )

        self.assertAlmostEqual(cw_points[0][0], project_point_from_bearing(center_lat, center_lon, center_bearing_deg, radius_m)[0], places=12)
        self.assertAlmostEqual(cw_points[0][1], project_point_from_bearing(center_lat, center_lon, center_bearing_deg, radius_m)[1], places=12)
        self.assertAlmostEqual(cw_points[-1][0], expected_cw_end[0], places=12)
        self.assertAlmostEqual(cw_points[-1][1], expected_cw_end[1], places=12)

        self.assertAlmostEqual(ccw_points[0][0], project_point_from_bearing(center_lat, center_lon, center_bearing_deg, radius_m)[0], places=12)
        self.assertAlmostEqual(ccw_points[0][1], project_point_from_bearing(center_lat, center_lon, center_bearing_deg, radius_m)[1], places=12)
        self.assertAlmostEqual(ccw_points[-1][0], expected_ccw_end[0], places=12)
        self.assertAlmostEqual(ccw_points[-1][1], expected_ccw_end[1], places=12)

    def test_inner_arc_uses_a2_span(self):
        center_lat = 0.0
        center_lon = 0.0
        outer_radius = 1000.0
        inner_radius = 200.0
        center_bearing_deg = 90.0

        result = build_sector_split_points(
            center_lat,
            center_lon,
            outer_radius,
            center_bearing_deg,
            45.0,
            inner_radius_m=inner_radius,
            inner_half_angle_deg=30.0,
        )

        self.assertTrue(len(result) == 4)
        inner_clockwise, inner_anticlockwise = result[2], result[3]
        expected_inner_cw = project_point_from_bearing(
            center_lat,
            center_lon,
            center_bearing_deg + 30.0,
            inner_radius,
        )
        expected_inner_ccw = project_point_from_bearing(
            center_lat,
            center_lon,
            center_bearing_deg - 30.0,
            inner_radius,
        )

        self.assertAlmostEqual(inner_clockwise[-1][0], expected_inner_cw[0], places=12)
        self.assertAlmostEqual(inner_clockwise[-1][1], expected_inner_cw[1], places=12)
        self.assertAlmostEqual(inner_anticlockwise[-1][0], expected_inner_ccw[0], places=12)
        self.assertAlmostEqual(inner_anticlockwise[-1][1], expected_inner_ccw[1], places=12)

    def test_start_sector_axis_is_reciprocal_of_first_leg(self):
        path = (
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/"
            "15 Metre/2026-08-08/688_Z3.igc"
        )
        start_sector = next(sector for sector in extract_task_sectors_from_igc(path) if sector["idx"] == -1)
        next_pt = next(item for item in extract_task_sectors_from_igc(path) if item["idx"] == 0)

        outbound = _bearing_between_points(start_sector["lat"], start_sector["lon"], next_pt["lat"], next_pt["lon"])
        expected = (outbound + 180.0) % 360.0
        self.assertAlmostEqual(start_sector["orientation_deg"], expected, places=9)

    def test_finish_sector_axis_is_reciprocal_of_inbound_leg(self):
        path = (
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/"
            "15 Metre/2026-08-08/688_Z3.igc"
        )
        finish_sector = next(sector for sector in extract_task_sectors_from_igc(path) if sector["idx"] == 4)
        prev_pt = next(item for item in extract_task_sectors_from_igc(path) if item["idx"] == 3)

        inbound = _bearing_between_points(prev_pt["lat"], prev_pt["lon"], finish_sector["lat"], finish_sector["lon"])
        expected = (inbound + 180.0) % 360.0
        self.assertAlmostEqual(finish_sector["orientation_deg"], expected, places=9)

    def test_internal_bisector_handles_wrapped_bearings(self):
        self.assertAlmostEqual(
            _internal_bisector_from_legs(350.0, 20.0),
            95.0,
            places=12,
        )
        self.assertAlmostEqual(
            _outward_bisector_from_legs(350.0, 20.0),
            275.0,
            places=12,
        )

    def test_outward_bisector_uses_opposite_ray(self):
        self.assertAlmostEqual(
            _outward_bisector_from_legs(240.0, 300.0),
            180.0,
            places=12,
        )

    def test_real_task_sector_uses_outward_bisector(self):
        path = (
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/"
            "15 Metre/2026-08-16/68G_Z3.igc"
        )
        sectors = extract_task_sectors_from_igc(path)
        turnpoint = next(sector for sector in sectors if sector["idx"] == 0)

        expected = _infer_sector_orientation(path, 0, turnpoint["lat"], turnpoint["lon"])
        self.assertIsNotNone(expected)
        self.assertAlmostEqual(turnpoint["orientation_deg"], expected, places=9)

    def test_start_sector_uses_a1_as_half_angle(self):
        path = (
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/"
            "15 Metre/2026-08-09/689_Z3.igc"
        )
        start_sector = next(sector for sector in extract_task_sectors_from_igc(path) if sector["idx"] == -1)
        center_bearing_deg = start_sector["orientation_deg"]
        actual = build_sector_points(
            start_sector["lat"],
            start_sector["lon"],
            start_sector["radius_m"],
            start_sector["a1_deg"],
            start_sector["a2_deg"],
            center_bearing_deg=center_bearing_deg,
        )
        self.assertEqual(len(actual), 51)
        self.assertAlmostEqual(
            actual[1][0],
            project_point_from_bearing(start_sector["lat"], start_sector["lon"], (center_bearing_deg - start_sector["a1_deg"]) % 360.0, start_sector["radius_m"])[0],
            places=9,
        )
        self.assertAlmostEqual(
            actual[-2][0],
            project_point_from_bearing(start_sector["lat"], start_sector["lon"], (center_bearing_deg + start_sector["a1_deg"]) % 360.0, start_sector["radius_m"])[0],
            places=9,
        )

    def test_project_geometry_table_includes_start_tp_and_finish_rows(self):
        path = (
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/"
            "15 Metre/2026-08-08/688_Z3.igc"
        )
        rows = project_geometry_table(path)
        self.assertTrue(any(row["point"] == "Start" for row in rows))
        self.assertTrue(any(row["point"] == "TP0" for row in rows))
        self.assertTrue(any(row["point"] == "Finish" for row in rows))
        self.assertIn("first_leg_deg", rows[0])
        self.assertIn("a12_deg", rows[0])

    def test_point_in_sector_detects_included_fixes(self):
        sector = {
            "lat": 0.0,
            "lon": 0.0,
            "radius_m": 1000.0,
            "inner_radius_m": 0.0,
            "a1_deg": 45.0,
            "orientation_deg": 90.0,
        }

        inside_lat, inside_lon = project_point_from_bearing(0.0, 0.0, 90.0, 500.0)
        outside_lat, outside_lon = project_point_from_bearing(0.0, 0.0, 0.0, 500.0)
        far_lat, far_lon = project_point_from_bearing(0.0, 0.0, 90.0, 1500.0)

        self.assertTrue(is_point_in_sector(inside_lat, inside_lon, sector))
        self.assertFalse(is_point_in_sector(outside_lat, outside_lon, sector))
        self.assertFalse(is_point_in_sector(far_lat, far_lon, sector))

    def test_extract_glider_start_time_ignores_post_tp1_start_sector_fixes(self):
        start_sector = {
            "lat": 0.0,
            "lon": 0.0,
            "radius_m": 1000.0,
            "inner_radius_m": 0.0,
            "a1_deg": 45.0,
            "orientation_deg": 90.0,
        }
        tp1_sector = {
            "lat": 0.0,
            "lon": 0.02,
            "radius_m": 1000.0,
            "inner_radius_m": 0.0,
            "a1_deg": 45.0,
            "orientation_deg": 90.0,
        }

        start_fix_1 = {"lat": 0.0, "lon": 0.0, "timestamp": "2024-01-01T10:00:00Z"}
        tp1_fix = {"lat": 0.0, "lon": 0.025, "timestamp": "2024-01-01T10:01:00Z"}
        start_fix_2 = {"lat": 0.0, "lon": 0.0, "timestamp": "2024-01-01T10:02:00Z"}

        fixes = [start_fix_1, tp1_fix, start_fix_2]
        self.assertEqual(
            extract_glider_start_time(fixes, start_sector, tp1_sector),
            "2024-01-01T10:00:00Z",
        )

    def test_format_human_readable_datetime_uses_utc(self):
        self.assertEqual(
            format_human_readable_datetime("2024-01-01T10:00:00Z"),
            "2024-01-01 10:00:00 UTC",
        )
        self.assertEqual(
            format_human_readable_datetime(1786189525.0),
            "2026-08-08 11:45:25 UTC",
        )


if __name__ == "__main__":
    unittest.main()
