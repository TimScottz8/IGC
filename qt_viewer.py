from __future__ import annotations

import json
import os
import subprocess
import sys

import pyqtgraph as pg
from PySide6.QtCore import QObject, QThread, QTimer, Signal

from flight_model import FlightRecord, flight_record_from_payload
from qt_helpers import normalize_file_selection, selected_start_time_paths
from timeline_state import TimelineState


def recent_track_window_for_record(
    record: FlightRecord,
    current_index: int,
    recent_track_seconds: float,
    *,
    total_seconds: float | None = None,
) -> tuple[int, int]:
    offsets = TimelineState.from_flight(record).time_offsets
    if not offsets:
        return 0, 0

    clamped_index = max(0, min(int(current_index), len(offsets) - 1))
    local_total = max(float(total_seconds) if total_seconds is not None else offsets[-1], 1.0)
    window_points = max(2, int((float(recent_track_seconds) / local_total) * max(len(offsets) - 1, 1)))
    start_index = max(0, clamped_index - window_points)
    return start_index, clamped_index


class PersistentFlightParserService:
    def __init__(self, working_directory: str) -> None:
        self.working_directory = working_directory
        self._process: subprocess.Popen[str] | None = None

    def shutdown(self) -> None:
        if self._process is None:
            return
        process = self._process
        self._process = None
        try:
            if process.stdin is not None:
                process.stdin.close()
        except Exception:
            pass
        try:
            if process.stdout is not None:
                process.stdout.close()
        except Exception:
            pass
        try:
            if process.stderr is not None:
                process.stderr.close()
        except Exception:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    def load_record_payload(self, file_path: str) -> dict:
        response = self._request({"paths": [file_path]})
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error") or "parser service failed"))
        records = response.get("records") or []
        if not records:
            raise RuntimeError(f"parser service returned no data for {file_path}")
        return dict(records[0])

    def _request(self, payload: dict, *, retry: bool = True) -> dict:
        process = self._ensure_process()
        try:
            assert process.stdin is not None
            assert process.stdout is not None
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()
            response_line = process.stdout.readline()
        except Exception as exc:
            self.shutdown()
            if retry:
                return self._request(payload, retry=False)
            raise RuntimeError(f"parser service communication failed: {exc}") from exc

        if response_line:
            return json.loads(response_line)

        error_output = ""
        if process.stderr is not None:
            try:
                error_output = process.stderr.read().strip()
            except Exception:
                error_output = ""
        exit_code = process.poll()
        self.shutdown()
        if retry:
            return self._request(payload, retry=False)
        raise RuntimeError(error_output or f"parser service exited with code {exit_code}")

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process

        self.shutdown()
        self._process = subprocess.Popen(
            [sys.executable, "-m", "flight_model", "--serve"],
            cwd=self.working_directory,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        return self._process


class FlightLoadWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object, bool, int, int)
    failed = Signal(str)

    def __init__(self, parser_service: PersistentFlightParserService, file_paths: list[str]) -> None:
        super().__init__()
        self.parser_service = parser_service
        self.file_paths = list(file_paths)
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            records: list[FlightRecord] = []
            total = len(self.file_paths)
            for index, file_path in enumerate(self.file_paths, start=1):
                if self._cancel_requested:
                    self.finished.emit(records, True, len(records), total)
                    return
                payload = self.parser_service.load_record_payload(file_path)
                records.append(flight_record_from_payload(payload))
                self.progress.emit(index, total, file_path)
            self.finished.emit(records, False, len(records), total)
        except Exception as exc:
            self.failed.emit(f"Failed to load flight records: {exc}")


class FlightLoadController(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.parser_service = PersistentFlightParserService(os.path.dirname(__file__))
        self._load_thread: QThread | None = None
        self._load_worker: FlightLoadWorker | None = None
        self._load_completion: dict[str, object] | None = None
        self._shutting_down = False
        self._cancel_requested = False

    def shutdown(self) -> None:
        self._shutting_down = True
        if self._load_thread is not None:
            self._load_thread.quit()
            self._load_thread.wait()
        self.parser_service.shutdown()

    def is_loading(self) -> bool:
        return self._load_thread is not None

    def cancel_loading(self) -> None:
        if self._load_worker is None:
            return
        self._cancel_requested = True
        self._load_worker.request_cancel()
        self.window.set_flight_loading_busy(True, allow_cancel=False)
        self.window.status_controller.flight_cancelling()

    def cached_record(self, file_path: str):
        normalized = self.window.flight_cache.normalize_path(file_path)
        return self.window.flight_cache.get(normalized)

    def load_records_for_paths(self, file_paths: list[str], on_loaded=None) -> list[FlightRecord] | None:
        if self._shutting_down:
            return []

        unique_paths = normalize_file_selection(file_paths)
        if not unique_paths:
            return []

        cached_records = self._all_cached_records(unique_paths)
        if cached_records is not None:
            self.window.status_controller.ready_to_view(len(cached_records))
            return cached_records

        if self._load_thread is not None:
            self.window.status_controller.flight_loading_in_progress()
            return None

        self._cancel_requested = False
        self.window.status_controller.start_flight_progress(len(unique_paths), unique_paths[0])
        self.window.set_flight_loading_busy(True, allow_cancel=True)

        thread = QThread(self.window)
        worker = FlightLoadWorker(self.parser_service, unique_paths)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_load_progress)
        worker.finished.connect(self._on_load_finished)
        worker.failed.connect(self._on_load_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._cleanup_load_thread)

        self._load_thread = thread
        self._load_worker = worker
        self._load_completion = {"on_loaded": on_loaded}
        thread.start()
        return None

    def _all_cached_records(self, file_paths: list[str]) -> list[FlightRecord] | None:
        records: list[FlightRecord] = []
        for file_path in file_paths:
            record = self.cached_record(file_path)
            if record is None:
                return None
            records.append(record)
        return [record for record in records if record.valid and record.flight is not None]

    def _cache_loaded_records(self, records: list[FlightRecord]) -> list[FlightRecord]:
        valid_records: list[FlightRecord] = []
        for record in records:
            normalized = self.window.flight_cache.normalize_path(record.file_path)
            self.window.flight_cache[normalized] = record
            if record.valid and record.flight is not None:
                valid_records.append(record)
        return valid_records

    def _on_load_progress(self, index: int, total: int, file_path: str) -> None:
        if self._shutting_down:
            return
        self.window.status_controller.update_flight_progress(index, total, file_path)

    def _on_load_finished(self, records: list[FlightRecord], cancelled: bool, completed: int, total: int) -> None:
        if self._shutting_down:
            return
        completion = self._load_completion or {}
        valid_records = self._cache_loaded_records(records)
        self.window.status_controller.finish_flight_progress()
        self.window.set_flight_loading_busy(False)
        on_loaded = completion.get("on_loaded")
        if cancelled or self._cancel_requested:
            self.window.status_controller.flight_cancelled(completed, total)
            self._cancel_requested = False
            return
        self.window.status_controller.ready_to_view(len(valid_records))
        if callable(on_loaded):
            on_loaded(valid_records)

    def _on_load_failed(self, message: str) -> None:
        if self._shutting_down:
            return
        completion = self._load_completion or {}
        self.window.status_controller.finish_flight_progress()
        self.window.set_flight_loading_busy(False)
        self.window.status_controller.contest_message(message)
        on_loaded = completion.get("on_loaded")
        if callable(on_loaded):
            on_loaded([])

    def _cleanup_load_thread(self) -> None:
        if self._load_thread is not None:
            self._load_thread.deleteLater()
        self._load_thread = None
        self._load_worker = None
        self._load_completion = None
        self._cancel_requested = False


class FlightRenderController(QObject):
    def __init__(self, window, load_controller: FlightLoadController) -> None:
        super().__init__(window)
        self.window = window
        self.load_controller = load_controller
        self._pending_start_time_paths: list[str] | None = None
        self._rendering_selected_start_times = False
        self._shutting_down = False
        self._selection_replay_timer = QTimer(self)
        self._selection_replay_timer.setSingleShot(True)
        self._selection_replay_timer.timeout.connect(self._replay_pending_selection)

    def shutdown(self) -> None:
        self._shutting_down = True
        self._pending_start_time_paths = None
        self._selection_replay_timer.stop()

    def selected_start_time_flight_paths(self) -> list[str]:
        return selected_start_time_paths(self.window.start_times_tree.selectedItems())

    def set_empty_track_state(self) -> None:
        self.window.track_item.setData([], [])
        self.window.flown_track_item.setData([], [])
        self.window.marker_item.setData([], [])
        for item in self.window.extra_track_items:
            self.window.plot_widget.removeItem(item)
        self.window.extra_track_items = []
        self.window.track_time_offsets = []
        self.window.play_button.setEnabled(False)
        self.window.pause_button.setEnabled(False)
        self.window.reset_button.setEnabled(False)
        self.window.speed_combo.setEnabled(False)
        self.window.timeline_slider.setEnabled(False)
        self.window._set_timeline_slider_value(0)
        self.window.timeline_slider.setMaximum(0)
        self.window.timeline_label.setText("Time: 00:00:00 / 00:00:00")
        if not self._rendering_selected_start_times:
            self.window.refresh_start_time_list([])

    def render_selected_start_times(self) -> None:
        file_paths = self.selected_start_time_flight_paths()
        if not file_paths:
            return
        if self._rendering_selected_start_times:
            if self.load_controller.is_loading():
                self._pending_start_time_paths = file_paths
            return

        def on_loaded(records: list[FlightRecord]) -> None:
            self._rendering_selected_start_times = False
            if self._pending_start_time_paths is not None:
                self._selection_replay_timer.start(0)
                return
            if not records:
                self.window.status_controller.no_valid_flights()
                return
            self.window.scene_state.set_active_flights(records)
            self.window.scene_state.set_selected_flight(records[0])
            self.window.scene_state.set_selected_index(0)
            self._render_loaded_record(records[0], active_records=records)

        self._pending_start_time_paths = None
        self._rendering_selected_start_times = True
        records = self.load_controller.load_records_for_paths(file_paths, on_loaded=on_loaded)
        if records is not None:
            self._rendering_selected_start_times = False
            if not records:
                self.window.status_controller.no_valid_flights()
                return
            self.window.scene_state.set_active_flights(records)
            self.window.scene_state.set_selected_flight(records[0])
            self.window.scene_state.set_selected_index(0)
            self._render_loaded_record(records[0], active_records=records)

    def _replay_pending_selection(self) -> None:
        if self._shutting_down:
            return
        if self.load_controller.is_loading():
            self._selection_replay_timer.start(0)
            return
        self._pending_start_time_paths = None
        self.render_selected_start_times()

    def render_static_tracks(self, file_paths: list[str]) -> None:
        if not file_paths:
            return

        def on_loaded(records: list[FlightRecord]) -> None:
            if not records:
                self.set_empty_track_state()
                self.window.status_controller.no_valid_flights()
                return
            self.window.tabs.setCurrentWidget(self.window.viewer_tab)
            self.window.scene_state.set_active_flights(records)
            self.window.scene_state.set_selected_flight(records[0])
            self.window.scene_state.set_selected_index(0)
            if not self._rendering_selected_start_times:
                self.window.refresh_start_time_list([
                    {
                        "file_path": record.file_path,
                        "start_time": record.start_time or (record.fixes[0].timestamp if record.fixes else None),
                    }
                    for record in records
                ])
            self._render_loaded_record(records[0], active_records=records)

        records = self.load_controller.load_records_for_paths(file_paths, on_loaded=on_loaded)
        if records is not None:
            on_loaded(records)

    def render_static_track(self, file_path: str, active_records: list | None = None) -> None:
        cached_record = self.load_controller.cached_record(file_path)
        if cached_record is not None:
            self._render_loaded_record(cached_record, active_records=active_records)
            return

        def on_loaded(records: list[FlightRecord]) -> None:
            if not records:
                self.set_empty_track_state()
                self.window.status_controller.no_valid_flights()
                return
            self._render_loaded_record(records[0], active_records=active_records or records)

        records = self.load_controller.load_records_for_paths([file_path], on_loaded=on_loaded)
        if records is not None and records:
            self._render_loaded_record(records[0], active_records=active_records or records)

    def _render_loaded_record(self, record: FlightRecord, active_records: list | None = None) -> None:
        self.window.timer.stop()
        self.window.last_tick_monotonic = None
        self.window.status_controller.loading_file()
        self.window._clear_static_overlays()

        if not record.valid or record.flight is None:
            self.set_empty_track_state()
            self.window.status_controller.parsed_file_invalid(record.file_path if self._rendering_selected_start_times else None)
            return

        try:
            start_time = record.start_time or (record.fixes[0].timestamp if record.fixes else None)
            if active_records is None:
                active_records = [record]
                if not self._rendering_selected_start_times:
                    self.window.refresh_start_time_list([
                        {"file_path": record.file_path, "start_time": start_time}
                    ])
            self.window.scene_state.set_active_flights(active_records)
            self.window.scene_state.set_selected_flight(record)
            self.window.scene_state.set_selected_index(0)

            self.window.track_lons = record.lons
            self.window.track_lats = record.lats
            if not self.window.track_lons or not self.window.track_lats:
                self.set_empty_track_state()
                self.window.status_controller.no_valid_fixes()
                return

            self.window._clear_visible_flight_markers()
            self.window.timeline = TimelineState.from_flight(record)
            self.window._configure_projection(self.window.track_lons, self.window.track_lats)
            self.window.track_xs, self.window.track_ys = self.window._project_lon_lat_lists(self.window.track_lons, self.window.track_lats)
            self.window.track_time_offsets = self.window.timeline.time_offsets

            for item in self.window.extra_track_items:
                self.window.plot_widget.removeItem(item)
            self.window.extra_track_items = []
            if len(active_records) > 1:
                colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
                for index, extra_record in enumerate(active_records[1:], start=1):
                    reference_total = max(self.window.track_time_offsets[-1], 1.0) if self.window.track_time_offsets else max(len(self.window.track_xs) - 1, 1)
                    reference_fraction = 0.0 if reference_total <= 0 else self.window.sim_elapsed_seconds / reference_total
                    extra_timeline = TimelineState.from_flight(extra_record)
                    extra_offsets = extra_timeline.time_offsets
                    if extra_offsets and extra_offsets[-1] > 0:
                        local_total = extra_offsets[-1]
                        local_index = int(reference_fraction * max(len(extra_offsets) - 1, 0))
                        start_index, end_index = recent_track_window_for_record(
                            extra_record,
                            local_index,
                            self.window.recent_track_seconds,
                            total_seconds=local_total,
                        )
                        extra_lons = extra_record.lons[start_index:end_index + 1]
                        extra_lats = extra_record.lats[start_index:end_index + 1]
                    else:
                        extra_lons = extra_record.lons[-min(len(extra_record.lons), 10):]
                        extra_lats = extra_record.lats[-min(len(extra_record.lats), 10):]
                    extra_xs, extra_ys = self.window._project_lon_lat_lists(extra_lons, extra_lats)
                    extra_item = self.window.plot_widget.plot(
                        extra_xs,
                        extra_ys,
                        pen=pg.mkPen(color=colors[(index - 1) % len(colors)], width=1.5),
                    )
                    self.window.extra_track_items.append(extra_item)

            preserve_elapsed = self.window.track_xs and (self.window.sim_elapsed_seconds > 0 or self.window.current_index > 0)
            prior_elapsed = self.window.sim_elapsed_seconds
            prior_index = self.window.current_index
            if preserve_elapsed and self.window.track_time_offsets:
                target_elapsed = min(max(prior_elapsed, 0.0), self.window.track_time_offsets[-1])
                target_index = 0
                for idx, offset in enumerate(self.window.track_time_offsets):
                    if offset >= target_elapsed:
                        target_index = idx
                        break
                else:
                    target_index = len(self.window.track_time_offsets) - 1
                self.window.current_index = target_index
                self.window.sim_elapsed_seconds = target_elapsed
            else:
                self.window.current_index = 0
                self.window.sim_elapsed_seconds = 0.0
            self.window._render_recent_track_view()
            self.window._render_active_gaggles()
            self.window.plot_widget.enableAutoRange()
            self.window.play_button.setEnabled(True)
            self.window.pause_button.setEnabled(True)
            self.window.reset_button.setEnabled(True)
            self.window.speed_combo.setEnabled(True)
            self.window.timeline_slider.setEnabled(True)
            self.window.timeline_slider.setMaximum(max(0, len(self.window.track_xs) - 1))
            self.window._set_timeline_slider_value(self.window.current_index)
            self.window.timeline_label.setText(
                f"Time: {self.window._format_seconds(self.window.sim_elapsed_seconds)} / {self.window._format_seconds(self.window.track_time_offsets[-1] if self.window.track_time_offsets else 0.0)}"
            )
            if len(active_records) == 1:
                self.window.status_controller.rendered_static_track(len(self.window.track_lons))
            else:
                self.window.status_controller.rendered_active_flights(len(active_records), record.file_path)
            self.window._render_static_overlays(record)
        except Exception as exc:
            self.set_empty_track_state()
            self.window.status_controller.render_failed(exc)