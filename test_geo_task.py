import os
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QTreeWidget

from qt_app import MainWindow, build_contest_download_plan
from qt_helpers import build_contest_result_lines, infer_contest_class_day_from_path
from map_helpers import GliderTrace
from flight_model import FlightRecord, load_flight_record, serialize_flight_record
from qt_viewer import recent_track_window_for_record
from flight_set import FlightSet
from scene_state import SceneState
from timeline_state import TimelineState
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
    segment_crosses_sector,
)


def process_events_until(predicate, timeout_seconds: float = 10.0) -> None:
    app = QApplication.instance() or QApplication([])
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
    raise AssertionError("Timed out waiting for Qt work to finish")


def sample_payload(file_path: str) -> dict:
    return {
        "file_path": file_path,
        "valid": True,
        "fixes": [
            {"lat": 52.0, "lon": -1.0, "timestamp": 0.0},
            {"lat": 52.01, "lon": -0.99, "timestamp": 60.0},
        ],
        "task_points": [],
        "task_sectors": [],
        "start_sector": None,
        "finish_sector": None,
        "start_time": "2024-01-01T10:00:00Z",
    }


class SectorGeometryTests(unittest.TestCase):
    def test_recent_track_window_uses_each_flight_timeline(self):
        primary = FlightRecord(file_path="primary.igc", valid=True, fixes=[
            type("Fix", (), {"lat": 51.0, "lon": -1.0, "timestamp": 0.0})(),
            type("Fix", (), {"lat": 51.1, "lon": -0.9, "timestamp": 60.0})(),
            type("Fix", (), {"lat": 51.2, "lon": -0.8, "timestamp": 120.0})(),
        ])
        secondary = FlightRecord(file_path="secondary.igc", valid=True, fixes=[
            type("Fix", (), {"lat": 52.0, "lon": -1.0, "timestamp": 0.0})(),
            type("Fix", (), {"lat": 52.1, "lon": -0.9, "timestamp": 20.0})(),
            type("Fix", (), {"lat": 52.2, "lon": -0.8, "timestamp": 40.0})(),
            type("Fix", (), {"lat": 52.3, "lon": -0.7, "timestamp": 60.0})(),
        ])

        primary_start, primary_end = recent_track_window_for_record(primary, 1, 30.0, total_seconds=120.0)
        secondary_start, secondary_end = recent_track_window_for_record(secondary, 3, 30.0, total_seconds=60.0)

        self.assertEqual(primary_start, 0)
        self.assertEqual(primary_end, 1)
        self.assertEqual(secondary_start, 1)
        self.assertEqual(secondary_end, 3)

    def test_build_contest_download_plan_discovers_classes_and_day_links(self):
        contest_html = """
        <html><body>
            <a href="/en_gb/contest/results/15-meter">15 Metre</a>
            <a href="/en_gb/contest/results/15-meter/day/2026-08-08">2026-08-08</a>
            <a href="/download-contest-flight/abc123?dl=1">download</a>
        </body></html>
        """
        plan = build_contest_download_plan(
            "https://www.soaringspot.com/en_gb/contest/results",
            contest_html,
            "https://www.soaringspot.com",
        )

        self.assertTrue(plan)
        self.assertIn("15 Metre", [item["class_name"] for item in plan])
        self.assertTrue(any(item["day"] == "2026-08-08" for item in plan))
        self.assertTrue(any("download-contest-flight" in item["link"] for item in plan))

    def test_glider_trace_exposes_task_zone_metadata(self):
        path = (
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/"
            "15 Metre/2026-08-08/688_10.igc"
        )
        trace = GliderTrace(path)

        self.assertEqual(trace.file_path, path)
        self.assertIsNotNone(trace.flight)
        self.assertGreater(len(trace.task_points), 0)
        self.assertGreater(len(trace.sectors), 0)
        self.assertIsNotNone(trace.get_start_time())
        self.assertIsNotNone(trace.get_task_points())
        self.assertIsNotNone(trace.get_sectors())
        self.assertIsNotNone(trace.get_zone_fix_mask())
        self.assertIsNotNone(trace.get_task_route())

    def test_build_contest_download_plan_deduplicates_equivalent_download_links(self):
        contest_html = """
        <html><body>
            <a href="/en_gb/contest/results/15-meter/day/2026-08-08">15 Metre</a>
            <a href="/download-contest-flight/abc123?dl=1">download</a>
            <a href="/download-contest-flight/abc123">download</a>
        </body></html>
        """
        plan = build_contest_download_plan(
            "https://www.soaringspot.com/en_gb/contest/results",
            contest_html,
            "https://www.soaringspot.com",
        )

        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["day"], "2026-08-08")
        self.assertIn("download-contest-flight/abc123", plan[0]["link"])

    def test_contest_result_lines_group_by_class_then_day(self):
        plan = [
            {"class_name": "15 Metre", "day": "2026-08-08", "link": "/a"},
            {"class_name": "15 Metre", "day": "2026-08-08", "link": "/b"},
            {"class_name": "15 Metre", "day": "2026-08-09", "link": "/c"},
            {"class_name": "Open", "day": "2026-08-09", "link": "/d"},
        ]

        lines = build_contest_result_lines(plan, limit=50)

        self.assertIn("15 Metre", "\n".join(lines))
        self.assertIn("2026-08-08", "\n".join(lines))
        self.assertIn("Open", "\n".join(lines))
        self.assertLess(lines.index("[15 Metre]"), lines.index("[Open]"))

    def test_main_window_builds_start_time_entries_for_single_flight(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        entries = window.build_start_time_entries([
            {"file_path": "sample.igc", "start_time": "2024-01-01T10:00:00Z"},
        ])

        self.assertEqual(entries, ["sample.igc — 2024-01-01 10:00:00 UTC"])
        app.quit()

    def test_main_window_uses_collapsible_start_time_tree(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()

        self.assertTrue(hasattr(window, "start_times_tree"))
        self.assertIs(window.start_times_list, window.start_times_tree)
        self.assertTrue(window.start_times_tree.isHeaderHidden())
        app.quit()

    def test_main_window_uses_tree_widget_for_contest_results(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()

        self.assertIsInstance(window.contest_results, QTreeWidget)
        self.assertTrue(window.contest_results.isHeaderHidden())
        self.assertTrue(hasattr(window, "download_progress"))
        app.quit()

    def test_main_window_uses_dedicated_download_and_viewer_controllers(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()

        self.assertIs(window.download_controller.window, window)
        self.assertIs(window.flight_load_controller.window, window)
        self.assertIs(window.flight_render_controller.window, window)
        app.quit()

    def test_main_window_download_selection_tracks_class_day_and_flight_scope(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        plan = [
            {"class_name": "15 Metre", "day": "2026-08-08", "link": "/a"},
            {"class_name": "15 Metre", "day": "2026-08-08", "link": "/b"},
            {"class_name": "15 Metre", "day": "2026-08-09", "link": "/c"},
            {"class_name": "Open", "day": "2026-08-09", "link": "/d"},
        ]
        window.contest_download_plan = plan
        window._render_contest_tree(plan)

        contest_root = window.contest_results.topLevelItem(0)
        class_item = contest_root.child(0)
        day_item = class_item.child(0)
        flight_item = day_item.child(0)

        window.contest_results.setCurrentItem(contest_root)
        self.assertEqual(len(window._selected_download_plan()), 4)

        window.contest_results.setCurrentItem(class_item)
        self.assertEqual(len(window._selected_download_plan()), 3)

        window.contest_results.setCurrentItem(day_item)
        self.assertEqual(len(window._selected_download_plan()), 2)

        window.contest_results.setCurrentItem(flight_item)
        self.assertEqual(len(window._selected_download_plan()), 1)
        app.quit()

    def test_main_window_disables_conflicting_actions_while_downloading(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.contest_download_plan = [{"class_name": "15 Metre", "day": "2026-08-08", "link": "/download/a"}]
        window.contest_root_name = "Contest"
        window.contest_url_input.setText("https://www.soaringspot.com/en_gb/contest/results")

        started = threading.Event()
        release = threading.Event()

        def controlled_download(*args, **kwargs):
            started.set()
            release.wait(timeout=5.0)
            return {"link": "/download/a", "status": "ok", "path": "igc_downloads/test.igc"}

        with (
            patch("qt_controllers.download_single_candidate", side_effect=controlled_download),
            patch("qt_controllers.QMessageBox.information", return_value=None),
        ):
            window.download_contest()
            process_events_until(lambda: started.is_set())
            self.assertFalse(window.open_igc_action.isEnabled())
            self.assertFalse(window.local_contests.isEnabled())
            self.assertFalse(window.cancel_download_button.isHidden())
            self.assertTrue(window.cancel_download_button.isEnabled())
            release.set()

        process_events_until(lambda: window.download_controller._download_thread is None)
        self.assertTrue(window.open_igc_action.isEnabled())
        self.assertTrue(window.local_contests.isEnabled())
        window.close()
        app.quit()

    def test_main_window_can_open_multiple_igc_files(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        paths = [
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/15 Metre/2026-08-08/688_10.igc",
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/15 Metre/2026-08-09/689_10.igc",
        ]

        window.render_static_tracks(paths)
        process_events_until(lambda: len(window.scene_state.active_flights) == 2 and window.timeline is not None)

        self.assertEqual(len(window.scene_state.active_flights), 2)
        self.assertEqual(window.scene_state.selected_flight.file_path, paths[0])
        self.assertIsNotNone(window.timeline)
        window.close()
        app.quit()

    def test_main_window_open_multiple_igc_files_uses_async_loader_when_uncached(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        paths = [
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/15 Metre/2026-08-08/688_10.igc",
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/15 Metre/2026-08-09/689_10.igc",
        ]

        started = threading.Event()
        release = threading.Event()

        payloads_by_path = {
            path: sample_payload(path)
            for path in paths
        }

        def controlled_request(file_path: str):
            started.set()
            release.wait(timeout=5.0)
            return payloads_by_path[file_path]

        with patch.object(window.flight_load_controller.parser_service, "load_record_payload", side_effect=controlled_request):
            window.render_static_tracks(paths)
            process_events_until(lambda: started.is_set())
            self.assertIsNotNone(window.flight_load_controller._load_thread)
            release.set()

        process_events_until(lambda: window.flight_load_controller._load_thread is None)
        window.close()
        app.quit()

    def test_main_window_disables_conflicting_actions_while_flight_loading(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        path = "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/15 Metre/2026-08-08/688_10.igc"

        started = threading.Event()
        release = threading.Event()
        payload = sample_payload(path)

        def controlled_request(file_path: str):
            started.set()
            release.wait(timeout=5.0)
            return payload

        with patch.object(window.flight_load_controller.parser_service, "load_record_payload", side_effect=controlled_request):
            window.render_static_tracks([path])
            process_events_until(lambda: started.is_set())
            self.assertFalse(window.open_igc_action.isEnabled())
            self.assertFalse(window.local_contests.isEnabled())
            self.assertFalse(window.cancel_flight_loading_button.isHidden())
            self.assertTrue(window.cancel_flight_loading_button.isEnabled())
            release.set()

        process_events_until(lambda: window.flight_load_controller._load_thread is None)
        self.assertTrue(window.open_igc_action.isEnabled())
        self.assertTrue(window.local_contests.isEnabled())
        window.close()
        app.quit()

    def test_main_window_can_cancel_flight_loading_after_current_file(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        path = "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/15 Metre/2026-08-08/688_10.igc"

        started = threading.Event()
        release = threading.Event()
        payload = sample_payload(path)

        def controlled_request(file_path: str):
            started.set()
            release.wait(timeout=5.0)
            return payload

        with patch.object(window.flight_load_controller.parser_service, "load_record_payload", side_effect=controlled_request):
            window.render_static_tracks([path, path])
            process_events_until(lambda: started.is_set())
            window.cancel_flight_loading()
            self.assertFalse(window.cancel_flight_loading_button.isEnabled())
            self.assertIn("cancelling flight loading", window.status_label.text().lower())
            release.set()

        process_events_until(lambda: window.flight_load_controller._load_thread is None)
        self.assertIn("cancelled flight loading", window.status_label.text().lower())
        window.close()
        app.quit()

    def test_main_window_shows_current_file_name_while_loading(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        path = "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/15 Metre/2026-08-08/688_10.igc"

        started = threading.Event()
        release = threading.Event()
        payload = sample_payload(path)

        def controlled_request(file_path: str):
            started.set()
            release.wait(timeout=5.0)
            return payload

        with patch.object(window.flight_load_controller.parser_service, "load_record_payload", side_effect=controlled_request):
            window.render_static_tracks([path])
            process_events_until(lambda: started.is_set())
            release.set()
            process_events_until(lambda: "688_10.igc" in window.status_label.text())

        process_events_until(lambda: window.flight_load_controller._load_thread is None)
        window.close()
        app.quit()

    def test_main_window_renders_overlays_from_cached_flight_record(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        path = (
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/"
            "15 Metre/2026-08-08/688_10.igc"
        )

        record = window._cache_or_load_flight_record(path)
        window.render_static_track(path)

        self.assertGreater(len(record.task_points), 0)
        self.assertGreater(len(window.static_overlay_items), 0)
        self.assertIs(window.scene_state.selected_flight, record)
        app.quit()

    def test_main_window_lists_downloaded_contests_from_local_dir(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()

        self.assertIsNotNone(window.local_contests)
        self.assertTrue(window.local_contests.topLevelItemCount() > 0)
        self.assertIn("open-standard-15m-nationals-2026-husbands-bosworth-2026", [
            window.local_contests.topLevelItem(index).text(0)
            for index in range(window.local_contests.topLevelItemCount())
        ])
        app.quit()

    def test_main_window_start_time_list_allows_multi_select_for_multiple_flights(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()

        window.start_times_tree.setSelectionMode(QTreeWidget.SelectionMode.MultiSelection)
        actual_paths = [
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/15 Metre/2026-08-08/688_10.igc",
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/15 Metre/2026-08-09/689_10.igc",
        ]
        window.refresh_start_time_list([
            {"file_path": actual_paths[0], "start_time": "2024-01-01T10:00:00Z"},
            {"file_path": actual_paths[1], "start_time": "2024-01-02T10:00:00Z"},
        ])
        self.assertEqual(len(window._selected_start_time_flight_paths()), 0)
        day_item = window.start_times_tree.topLevelItem(0)
        class_item = day_item.child(0)
        first_file = class_item.child(0)
        second_file = class_item.child(1)
        first_file.setSelected(True)
        second_file.setSelected(True)
        self.assertEqual(len(window._selected_start_time_flight_paths()), 2)
        process_events_until(lambda: len(window.scene_state.active_flights) == 2)
        self.assertEqual(len(window.scene_state.active_flights), 2)
        self.assertGreaterEqual(len(window.visible_flight_markers), 2)
        window.close()
        app.quit()

    def test_infer_contest_class_day_from_path(self):
        info = infer_contest_class_day_from_path(
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/15 Metre/2026-08-08/688_10.igc"
        )

        self.assertEqual(info["contest_name"], "open-standard-15m-nationals-2026-husbands-bosworth-2026")
        self.assertEqual(info["class_name"], "15 Metre")
        self.assertEqual(info["day"], "2026-08-08")

    def test_main_window_start_time_filters_by_day_and_class(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()

        flights = [
            {
                "file_path": "igc_downloads/contest-a/15 Metre/2026-08-08/a1.igc",
                "start_time": "2024-01-01T10:00:00Z",
                "class_name": "15 Metre",
                "day": "2026-08-08",
            },
            {
                "file_path": "igc_downloads/contest-a/Club/2026-08-08/c1.igc",
                "start_time": "2024-01-01T10:05:00Z",
                "class_name": "Club",
                "day": "2026-08-08",
            },
            {
                "file_path": "igc_downloads/contest-a/15 Metre/2026-08-09/a2.igc",
                "start_time": "2024-01-02T10:00:00Z",
                "class_name": "15 Metre",
                "day": "2026-08-09",
            },
        ]
        window.refresh_start_time_list(flights)

        self.assertGreater(window.start_times_day_filter.count(), 2)
        self.assertGreater(window.start_times_class_filter.count(), 2)

        window.start_times_day_filter.setCurrentText("2026-08-09")
        process_events_until(lambda: window.start_times_tree.topLevelItemCount() == 1)
        day_item = window.start_times_tree.topLevelItem(0)
        self.assertEqual(day_item.text(0), "2026-08-09")

        window.start_times_day_filter.setCurrentText("All days")
        window.start_times_class_filter.setCurrentText("Club")
        process_events_until(lambda: window.start_times_tree.topLevelItemCount() == 1)
        class_day_item = window.start_times_tree.topLevelItem(0)
        self.assertEqual(class_day_item.text(0), "2026-08-08")
        self.assertEqual(class_day_item.child(0).text(0), "Club")

        window.close()
        app.quit()

    def test_main_window_preserves_playback_time_when_reselecting_flights(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        path = (
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/"
            "15 Metre/2026-08-08/688_10.igc"
        )

        record = window._cache_or_load_flight_record(path)
        window.track_lons = record.lons
        window.track_lats = record.lats
        window.track_xs, window.track_ys = window._project_lon_lat_lists(window.track_lons, window.track_lats)
        window.track_time_offsets = TimelineState.from_flight(record).time_offsets
        window.current_index = max(1, min(10, len(window.track_time_offsets) - 1))
        window.sim_elapsed_seconds = window.track_time_offsets[window.current_index]

        window._render_loaded_record(record, active_records=[record])

        self.assertEqual(window.current_index, max(1, min(10, len(window.track_time_offsets) - 1)))
        self.assertAlmostEqual(window.sim_elapsed_seconds, window.track_time_offsets[window.current_index], places=6)
        window.close()
        app.quit()

    def test_main_window_caches_loaded_flight_records_for_fast_selection(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        path = (
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/"
            "15 Metre/2026-08-08/688_10.igc"
        )

        first = window._cache_or_load_flight_record(path)
        second = window._cache_or_load_flight_record(path)

        self.assertIs(first, second)
        self.assertIn(os.path.abspath(path), window.flight_cache)
        app.quit()

    def test_main_window_uses_single_2d_map_view(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()

        self.assertIsNotNone(window.plot_widget)
        self.assertIs(window.secondary_plot_widget, window.plot_widget)
        self.assertFalse(hasattr(window, "secondary_3d_widget"))
        app.quit()

    def test_main_window_no_longer_requires_3d_support(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()

        self.assertFalse(hasattr(window, "secondary_3d_widget"))
        self.assertFalse(hasattr(window, "secondary_3d_axis"))
        self.assertFalse(hasattr(window, "_build_secondary_3d_points"))
        app.quit()

    def test_load_flight_record_exposes_core_flight_metadata(self):
        path = (
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/"
            "15 Metre/2026-08-08/688_10.igc"
        )
        record = load_flight_record(path)

        self.assertIsInstance(record, FlightRecord)
        self.assertEqual(record.file_path, path)
        self.assertGreater(len(record.fixes), 0)
        self.assertIsNotNone(record.start_time)
        self.assertGreater(len(record.task_points), 0)

    def test_flight_set_collects_multiple_flights_and_summarises_them(self):
        paths = [
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/15 Metre/2026-08-08/688_10.igc",
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/15 Metre/2026-08-09/689_10.igc",
        ]
        dataset = FlightSet.from_paths(paths)

        self.assertEqual(dataset.count(), 2)
        self.assertEqual(len(dataset.by_start_time()), 2)
        self.assertGreater(dataset.summary()["with_start_time"], 0)

    def test_timeline_state_tracks_time_offsets_and_index(self):
        path = (
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/"
            "15 Metre/2026-08-08/688_10.igc"
        )
        state = TimelineState.from_flight(load_flight_record(path))

        self.assertGreater(state.total_seconds, 0)
        self.assertEqual(state.index, 0)
        self.assertEqual(len(state.time_offsets), len(load_flight_record(path).fixes))
        state.set_index(1)
        self.assertEqual(state.index, 1)

    def test_scene_state_tracks_selected_flight_and_active_set(self):
        path = (
            "igc_downloads/open-standard-15m-nationals-2026-husbands-bosworth-2026/"
            "15 Metre/2026-08-08/688_10.igc"
        )
        flight = load_flight_record(path)
        state = SceneState()

        state.set_active_flights([flight])
        state.set_selected_flight(flight)
        state.set_selected_index(7)

        self.assertIs(state.selected_flight, flight)
        self.assertEqual(state.selected_index, 7)
        self.assertEqual(len(state.active_flights), 1)

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

    def test_point_in_sector_counts_inner_radius_as_valid_for_inclusive_envelope(self):
        sector = {
            "lat": 0.0,
            "lon": 0.0,
            "radius_m": 1000.0,
            "inner_radius_m": 500.0,
            "a1_deg": 45.0,
            "orientation_deg": 90.0,
        }

        inside_inner_lat, inside_inner_lon = project_point_from_bearing(0.0, 0.0, 90.0, 250.0)
        self.assertTrue(is_point_in_sector(inside_inner_lat, inside_inner_lon, sector))

    def test_track_segment_crosses_sector_when_line_passes_through_inner_radius(self):
        sector = {
            "lat": 0.0,
            "lon": 0.0,
            "radius_m": 1000.0,
            "inner_radius_m": 500.0,
            "a1_deg": 45.0,
            "orientation_deg": 90.0,
        }

        start_lat, start_lon = project_point_from_bearing(0.0, 0.0, 90.0, 1500.0)
        end_lat, end_lon = project_point_from_bearing(0.0, 0.0, 270.0, 1500.0)

        self.assertTrue(segment_crosses_sector(start_lat, start_lon, end_lat, end_lon, sector))

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
