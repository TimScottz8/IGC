from __future__ import annotations

import os
import sys
import time

import pyqtgraph as pg
from pyproj import CRS, Transformer
from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flight_loader import FlightCache
from gaggle_analysis import compute_thermal_gaggles
from qt_controllers import DownloadController
from qt_status import StatusController
from qt_viewer import FlightLoadController, FlightRenderController
from scene_state import SceneState
from geo_task import (
    build_sector_split_points,
)
from qt_helpers import (
    build_contest_download_plan,
    build_start_time_entries as format_start_time_entries,
    group_start_time_entries,
    normalize_file_selection,
    selected_files_label,
)
from sector_geometry import _distance_between_points_m
from timeline_state import TimelineState


# The free functions below are intentionally kept thin so the UI shell stays
# focused on presentation while the network and discovery logic lives in
# qt_helpers.py.


class GaggleDetectionWorker(QObject):
    progress = Signal(str, int, int)
    finished = Signal(int, object, bool)
    failed = Signal(int, str)

    def __init__(
        self,
        *,
        job_id: int,
        flights: list,
        max_distance_m: float,
        max_time_delta_s: float,
        max_altitude_delta_m: float,
        min_cluster_size: int,
    ) -> None:
        super().__init__()
        self.job_id = int(job_id)
        self.flights = list(flights)
        self.max_distance_m = float(max_distance_m)
        self.max_time_delta_s = float(max_time_delta_s)
        self.max_altitude_delta_m = float(max_altitude_delta_m)
        self.min_cluster_size = int(min_cluster_size)
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            clusters = compute_thermal_gaggles(
                self.flights,
                max_distance_m=self.max_distance_m,
                max_time_delta_s=self.max_time_delta_s,
                max_altitude_delta_m=self.max_altitude_delta_m,
                progress_callback=self._emit_progress,
                cancel_check=lambda: self._cancel_requested,
                use_multiprocessing=True,
                max_workers=os.cpu_count() or 1,
            )
            if self._cancel_requested:
                self.finished.emit(self.job_id, [], True)
                return
            filtered = [
                cluster
                for cluster in clusters
                if int(cluster.get("size", 0)) >= self.min_cluster_size
            ]
            self.finished.emit(self.job_id, filtered, False)
        except Exception as exc:
            self.failed.emit(self.job_id, str(exc))

    def _emit_progress(self, stage: str, current: int, total: int) -> None:
        self.progress.emit(str(stage), int(current), int(total))


class MainWindow(QMainWindow):
    GAGGLE_MAX_DISTANCE_M = 500.0
    GAGGLE_MAX_TIME_DELTA_S = 30.0
    GAGGLE_MAX_ALTITUDE_DELTA_M = 800.0
    GAGGLE_MIN_CLUSTER_SIZE = 2
    GAGGLE_MAX_REFERENCE_ZONES = 350
    GAGGLE_MAX_ACTIVE_CLUSTERS = 80
    GAGGLE_MAX_ACTIVE_MEMBER_POINTS = 2000
    GAGGLE_ACTIVE_PERSISTENCE_S = 300.0
    GAGGLE_ZONE_LINK_BASE_DISTANCE_M = 300.0
    GAGGLE_ZONE_DRIFT_SPEED_MPS = 8.0
    GAGGLE_ZONE_MAX_GAP_S = 240.0
    GAGGLE_ZONE_MIN_MEMBER_OVERLAP = 1
    STATIC_FULL_ROUTE_PEN = (187, 187, 187, 140)
    STATIC_FLOWN_ROUTE_PEN = (17, 17, 17, 230)
    ANIMATING_TRAIL_PEN = (31, 119, 180, 230)
    ANIMATING_TRAIL_GHOST_PEN = (31, 119, 180, 120)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("IGC Desktop Viewer")
        self.resize(1000, 700)
        self.gaggle_distance_m = float(self.GAGGLE_MAX_DISTANCE_M)
        self.gaggle_time_delta_s = float(self.GAGGLE_MAX_TIME_DELTA_S)
        self.gaggle_altitude_delta_m = float(self.GAGGLE_MAX_ALTITUDE_DELTA_M)
        self.gaggle_min_cluster_size = int(self.GAGGLE_MIN_CLUSTER_SIZE)
        self._gaggle_thread: QThread | None = None
        self._gaggle_worker: GaggleDetectionWorker | None = None
        self._gaggle_job_id = 0
        self._gaggle_pending_refresh = False
        self._gaggle_clusters_ready = False
        self._gaggle_reference_drawn_count = 0

        self.tabs = QTabWidget(self)

        self.download_tab = QWidget(self)
        self.viewer_tab = QWidget(self)
        self.tabs.addTab(self.download_tab, "Download")
        self.tabs.addTab(self.viewer_tab, "Flight viewer")
        self.setCentralWidget(self.tabs)

        download_layout = QVBoxLayout(self.download_tab)
        download_layout.addWidget(QLabel("SoaringSpot contest download"))
        self.contest_url_input = QLineEdit()
        self.contest_url_input.setPlaceholderText("https://www.soaringspot.com/en_gb/contest/...")
        download_layout.addWidget(self.contest_url_input)
        contest_buttons = QHBoxLayout()
        self.discover_contest_button = QPushButton("Discover contest")
        self.download_contest_button = QPushButton("Download contest files")
        self.cancel_download_button = QPushButton("Cancel download")
        self.cancel_download_button.setEnabled(False)
        self.cancel_download_button.setVisible(False)
        self.download_contest_button.setEnabled(False)
        self.discover_contest_button.clicked.connect(self.discover_contest)
        self.download_contest_button.clicked.connect(self.download_contest)
        self.cancel_download_button.clicked.connect(self.cancel_download)
        contest_buttons.addWidget(self.discover_contest_button)
        contest_buttons.addWidget(self.download_contest_button)
        contest_buttons.addWidget(self.cancel_download_button)
        download_layout.addLayout(contest_buttons)
        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        self.download_progress.setVisible(False)
        download_layout.addWidget(self.download_progress)

        self.contest_results = QTreeWidget()
        self.contest_results.setHeaderHidden(True)
        self.contest_results.setColumnCount(1)
        self.contest_results.setUniformRowHeights(True)
        self.contest_results.setAlternatingRowColors(True)
        self.contest_results.setRootIsDecorated(True)
        self.contest_results.setIndentation(16)
        self.contest_results.setMaximumHeight(220)
        self.contest_results.addTopLevelItem(QTreeWidgetItem(["Contest discovery output appears here."]))
        self.contest_results.itemClicked.connect(self._update_download_button_label)
        download_layout.addWidget(self.contest_results)

        self.local_contests_label = QLabel("Downloaded contests")
        download_layout.addWidget(self.local_contests_label)
        self.local_selection_label = QLabel("Selected: 0 flights")
        download_layout.addWidget(self.local_selection_label)
        self.local_contests = QTreeWidget()
        self.local_contests.setHeaderHidden(True)
        self.local_contests.setColumnCount(1)
        self.local_contests.setUniformRowHeights(True)
        self.local_contests.setAlternatingRowColors(True)
        self.local_contests.setRootIsDecorated(True)
        self.local_contests.setIndentation(16)
        self.local_contests.setMaximumHeight(220)
        self.local_contests.itemSelectionChanged.connect(self._update_local_selection_label)
        download_layout.addWidget(self.local_contests)

        local_buttons = QHBoxLayout()
        self.open_local_contest_button = QPushButton("Open selected local flights")
        self.open_local_contest_button.clicked.connect(self.open_selected_local_flights)
        local_buttons.addWidget(self.open_local_contest_button)
        download_layout.addLayout(local_buttons)

        viewer_layout = QVBoxLayout(self.viewer_tab)
        self.selected_file_label = QLabel("Selected file: none")
        viewer_layout.addWidget(self.selected_file_label)

        self.start_times_label = QLabel("Start times")
        viewer_layout.addWidget(self.start_times_label)
        self.start_times_tree = QTreeWidget()
        self.start_times_tree.setHeaderHidden(True)
        self.start_times_tree.setColumnCount(1)
        self.start_times_tree.setMaximumHeight(150)
        self.start_times_tree.setRootIsDecorated(True)
        self.start_times_tree.setIndentation(16)
        self.start_times_tree.setUniformRowHeights(True)
        self.start_times_tree.setAlternatingRowColors(True)
        self.start_times_tree.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.start_times_list = self.start_times_tree
        self.start_times_tree.itemSelectionChanged.connect(self._render_selected_start_times)
        self.start_times_tree.addTopLevelItem(QTreeWidgetItem(["No start time available"]))
        viewer_layout.addWidget(self.start_times_tree)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("w")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)
        self.plot_widget.setLabel("bottom", "Easting (km)")
        self.plot_widget.setLabel("left", "Northing (km)")
        self.plot_widget.setAspectLocked(lock=True, ratio=1)
        self.track_item = self.plot_widget.plot([], [], pen=pg.mkPen(color=self.STATIC_FULL_ROUTE_PEN, width=1.5))
        self.flown_track_item = self.plot_widget.plot([], [], pen=pg.mkPen(color=self.STATIC_FLOWN_ROUTE_PEN, width=2.6))
        self.marker_item = self.plot_widget.plot(
            [],
            [],
            pen=None,
            symbol="o",
            symbolBrush="#d62728",
            symbolPen="#d62728",
            symbolSize=10,
        )
        self.static_overlay_items: list = []
        self.extra_track_items: list = []
        self.gaggle_overlay_items: list = []
        self.gaggle_reference_items: list = []
        self.gaggle_clusters_raw: list[dict] = []
        self.gaggle_clusters: list[dict] = []
        self.visible_flight_markers: list = []

        self.secondary_plot_widget = self.plot_widget

        viewer_layout.addWidget(self.plot_widget)

        controls_layout = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")
        self.reset_button = QPushButton("Reset")
        self.play_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.reset_button.setEnabled(False)
        self.play_button.clicked.connect(self.start_animation)
        self.pause_button.clicked.connect(self.pause_animation)
        self.reset_button.clicked.connect(self.reset_animation)
        self.speed_label = QLabel("Speed")
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["1x", "5x", "10x", "30x", "60x", "120x"])
        self.speed_combo.setCurrentText("1x")
        self.speed_combo.setEnabled(False)
        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.pause_button)
        controls_layout.addWidget(self.reset_button)
        controls_layout.addWidget(self.speed_label)
        controls_layout.addWidget(self.speed_combo)
        controls_layout.addStretch(1)
        viewer_layout.addLayout(controls_layout)

        gaggle_settings_layout = QHBoxLayout()
        gaggle_settings_label = QLabel("Gaggle settings")
        gaggle_settings_layout.addWidget(gaggle_settings_label)

        form_layout = QFormLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)

        self.gaggle_distance_spin = QSpinBox()
        self.gaggle_distance_spin.setRange(100, 2000)
        self.gaggle_distance_spin.setSingleStep(50)
        self.gaggle_distance_spin.setValue(int(self.GAGGLE_MAX_DISTANCE_M))
        self.gaggle_distance_spin.setSuffix(" m")
        self.gaggle_distance_spin.valueChanged.connect(self._on_gaggle_settings_changed)
        form_layout.addRow("Distance", self.gaggle_distance_spin)

        self.gaggle_time_spin = QSpinBox()
        self.gaggle_time_spin.setRange(5, 180)
        self.gaggle_time_spin.setSingleStep(5)
        self.gaggle_time_spin.setValue(int(self.GAGGLE_MAX_TIME_DELTA_S))
        self.gaggle_time_spin.setSuffix(" s")
        self.gaggle_time_spin.valueChanged.connect(self._on_gaggle_settings_changed)
        form_layout.addRow("Time window", self.gaggle_time_spin)

        self.gaggle_min_size_spin = QSpinBox()
        self.gaggle_min_size_spin.setRange(2, 12)
        self.gaggle_min_size_spin.setSingleStep(1)
        self.gaggle_min_size_spin.setValue(self.GAGGLE_MIN_CLUSTER_SIZE)
        self.gaggle_min_size_spin.valueChanged.connect(self._on_gaggle_settings_changed)
        form_layout.addRow("Min size", self.gaggle_min_size_spin)

        self.gaggle_altitude_spin = QSpinBox()
        self.gaggle_altitude_spin.setRange(100, 3000)
        self.gaggle_altitude_spin.setSingleStep(50)
        self.gaggle_altitude_spin.setValue(int(self.GAGGLE_MAX_ALTITUDE_DELTA_M))
        self.gaggle_altitude_spin.setSuffix(" m")
        self.gaggle_altitude_spin.valueChanged.connect(self._on_gaggle_settings_changed)
        form_layout.addRow("Vertical sep", self.gaggle_altitude_spin)

        gaggle_settings_layout.addLayout(form_layout)

        self.gaggle_reset_button = QPushButton("Reset")
        self.gaggle_reset_button.clicked.connect(self._reset_gaggle_settings)
        gaggle_settings_layout.addWidget(self.gaggle_reset_button)
        gaggle_settings_layout.addStretch(1)
        viewer_layout.addLayout(gaggle_settings_layout)

        self.gaggle_settings_summary_label = QLabel("")
        viewer_layout.addWidget(self.gaggle_settings_summary_label)

        gaggle_progress_layout = QHBoxLayout()
        self.gaggle_progress_label = QLabel("")
        self.gaggle_progress_label.setVisible(False)
        self.gaggle_progress_bar = QProgressBar()
        self.gaggle_progress_bar.setRange(0, 100)
        self.gaggle_progress_bar.setValue(0)
        self.gaggle_progress_bar.setVisible(False)
        self.cancel_gaggle_button = QPushButton("Cancel gaggle detection")
        self.cancel_gaggle_button.setVisible(False)
        self.cancel_gaggle_button.clicked.connect(self._cancel_gaggle_detection)
        gaggle_progress_layout.addWidget(self.gaggle_progress_label)
        gaggle_progress_layout.addWidget(self.gaggle_progress_bar, stretch=1)
        gaggle_progress_layout.addWidget(self.cancel_gaggle_button)
        viewer_layout.addLayout(gaggle_progress_layout)

        self._update_gaggle_settings_summary()

        timeline_layout = QHBoxLayout()
        self.timeline_slider = QSlider(Qt.Orientation.Horizontal)
        self.timeline_slider.setMinimum(0)
        self.timeline_slider.setMaximum(0)
        self.timeline_slider.setValue(0)
        self.timeline_slider.setEnabled(False)
        self.timeline_slider.valueChanged.connect(self.on_timeline_slider_changed)
        self.timeline_label = QLabel("Time: 00:00:00 / 00:00:00")
        timeline_layout.addWidget(self.timeline_slider, stretch=1)
        timeline_layout.addWidget(self.timeline_label)
        viewer_layout.addLayout(timeline_layout)

        self.status_label = QLabel("")
        viewer_layout.addWidget(self.status_label)

        flight_progress_buttons = QHBoxLayout()
        self.cancel_flight_loading_button = QPushButton("Cancel loading")
        self.cancel_flight_loading_button.setEnabled(False)
        self.cancel_flight_loading_button.setVisible(False)
        self.cancel_flight_loading_button.clicked.connect(self.cancel_flight_loading)
        flight_progress_buttons.addStretch(1)
        flight_progress_buttons.addWidget(self.cancel_flight_loading_button)
        viewer_layout.addLayout(flight_progress_buttons)

        self.flight_loading_progress = QProgressBar()
        self.flight_loading_progress.setRange(0, 100)
        self.flight_loading_progress.setValue(0)
        self.flight_loading_progress.setVisible(False)
        download_layout.addWidget(self.flight_loading_progress)

        self.flight_cache = FlightCache()
        self.contest_download_plan: list[dict[str, str]] = []
        self.contest_root_name = "Contest"
        self.track_lons: list[float] = []
        self.track_lats: list[float] = []
        self.track_xs: list[float] = []
        self.track_ys: list[float] = []
        self.track_time_offsets: list[float] = []
        self.recent_track_seconds = 30.0
        self.timeline = None
        self.scene_state = SceneState()
        self.geo_to_local: Transformer | None = None
        self.current_index = 0
        self.sim_elapsed_seconds = 0.0
        self.last_tick_monotonic: float | None = None
        self.timeline_internal_update = False
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.on_tick)
        self.plot_widget.scene().sigMouseClicked.connect(self.on_plot_mouse_clicked)

        self.status_controller = StatusController(
            self.status_label,
            self.flight_loading_progress,
            self.download_progress,
        )
        self.download_controller = DownloadController(self)
        self.flight_load_controller = FlightLoadController(self)
        self.flight_render_controller = FlightRenderController(self, self.flight_load_controller)
        self.viewer_controller = self.flight_render_controller
        self.status_controller.waiting_for_file()
        self.refresh_local_contest_tree()

        file_menu = self.menuBar().addMenu("File")
        open_action = QAction("Open IGC...", self)
        open_action.triggered.connect(self.open_igc_file)
        file_menu.addAction(open_action)
        self.open_igc_action = open_action

    @staticmethod
    def build_start_time_entries(flights: list[dict[str, str]]) -> list[str]:
        """Format flight metadata into the rows shown beside the map viewer."""
        return format_start_time_entries(flights)

    def refresh_start_time_list(self, flights: list[dict[str, str]]) -> None:
        """Refresh the start-time tree with the latest flight metadata grouped by day and class."""
        self.start_times_tree.clear()
        entries = self.build_start_time_entries(flights)
        if not entries:
            self.start_times_tree.addTopLevelItem(QTreeWidgetItem(["No start time available"]))
            return

        grouped = group_start_time_entries(flights)

        if not grouped:
            self.start_times_tree.addTopLevelItem(QTreeWidgetItem(["No start time available"]))
            return

        sorted_days = sorted(grouped, key=lambda name: str(name))
        for day in sorted_days:
            day_item = QTreeWidgetItem([day])
            for class_name in sorted(grouped[day], key=lambda name: str(name)):
                class_item = QTreeWidgetItem([class_name])
                for entry in grouped[day][class_name]:
                    item = QTreeWidgetItem([entry["label"]])
                    item.setData(0, Qt.ItemDataRole.UserRole, entry["file_path"])
                    class_item.addChild(item)
                day_item.addChild(class_item)
            self.start_times_tree.addTopLevelItem(day_item)

        self.start_times_tree.expandToDepth(0)

    def _cache_or_load_flight_record(self, file_path: str):
        """Delegate parsing and caching to the flight loader service."""
        return self.flight_cache.get_record(file_path)

    def _load_records_for_paths(self, file_paths: list[str], *, switch_to_viewer: bool = True) -> list:
        """Load each selected flight once, showing progress while the cache is populated."""
        return self.flight_load_controller.load_records_for_paths(file_paths)

    def _set_empty_track_state(self, status_text: str | None = None) -> None:
        """Reset the plot and playback controls to a clean, empty state."""
        self.flight_render_controller.set_empty_track_state()
        if status_text:
            self.status_controller.set_text(status_text)

    def _selected_start_time_flight_paths(self) -> list[str]:
        return self.flight_render_controller.selected_start_time_flight_paths()

    def _render_selected_start_times(self) -> None:
        self.flight_render_controller.render_selected_start_times()

    def open_igc_file(self) -> None:
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open IGC files",
            "",
            "IGC files (*.igc);;All files (*)",
        )
        if file_paths:
            self.open_igc_files(file_paths)

    def open_igc_files(self, file_paths: list[str]) -> None:
        unique_paths = normalize_file_selection(file_paths)
        if not unique_paths:
            return

        self.selected_file_label.setText(selected_files_label(unique_paths))
        self.render_static_tracks(unique_paths)

    def discover_contest(self) -> None:
        """Fetch a contest page and populate the download queue for the selected classes."""
        self.download_controller.start_discover_contest()

    def _update_download_button_label(self, item: QTreeWidgetItem | None = None) -> None:
        self.download_controller.update_download_button_label(item)

    def _selected_download_plan(self) -> list[dict[str, str]]:
        return self.download_controller.selected_download_plan()

    def _render_contest_tree(self, plan: list[dict[str, str]]) -> None:
        """Render discovered contest links as a collapsible tree grouped by class and then day."""
        self.download_controller.render_contest_tree(plan)

    def _iter_downloaded_contest_paths(self) -> list[str]:
        return self.download_controller.iter_downloaded_contest_paths()

    def _selected_local_flight_paths(self) -> list[str]:
        return self.download_controller.selected_local_flight_paths()

    def _update_local_selection_label(self) -> None:
        self.download_controller.update_local_selection_label()

    def refresh_local_contest_tree(self) -> None:
        self.download_controller.refresh_local_contest_tree()

    def open_selected_local_flights(self) -> None:
        self.download_controller.open_selected_local_flights()

    def cancel_download(self) -> None:
        self.download_controller.cancel_download()

    def download_contest(self) -> None:
        """Download the currently selected contest/class/day/flight subtree."""
        self.download_controller.start_download_contest()

    def render_static_tracks(self, file_paths: list[str]) -> None:
        """Load each IGC file once, cache it, and keep the first as the active primary track."""
        self.flight_render_controller.render_static_tracks(file_paths)

    def render_static_track(self, file_path: str, active_records: list | None = None) -> None:
        """Load one IGC file, extract metadata, and draw the corresponding map view."""
        self.flight_render_controller.render_static_track(file_path, active_records=active_records)

    def cancel_flight_loading(self) -> None:
        self.flight_load_controller.cancel_loading()

    def set_download_busy(self, is_busy: bool, *, allow_cancel: bool = False) -> None:
        self.discover_contest_button.setEnabled(not is_busy)
        self.download_contest_button.setEnabled(not is_busy and bool(self.contest_download_plan))
        self.cancel_download_button.setVisible(is_busy)
        self.cancel_download_button.setEnabled(is_busy and allow_cancel)
        self.contest_url_input.setEnabled(not is_busy)
        self.contest_results.setEnabled(not is_busy)
        self.local_contests.setEnabled(not is_busy)
        self.open_local_contest_button.setEnabled(not is_busy)
        self.start_times_tree.setEnabled(not is_busy)
        self.open_igc_action.setEnabled(not is_busy)

    def set_flight_loading_busy(self, is_busy: bool, *, allow_cancel: bool = False) -> None:
        self.cancel_flight_loading_button.setVisible(is_busy)
        self.cancel_flight_loading_button.setEnabled(is_busy and allow_cancel)
        self.discover_contest_button.setEnabled(not is_busy)
        self.download_contest_button.setEnabled(not is_busy and bool(self.contest_download_plan))
        self.contest_url_input.setEnabled(not is_busy)
        self.contest_results.setEnabled(not is_busy)
        self.local_contests.setEnabled(not is_busy)
        self.open_local_contest_button.setEnabled(not is_busy)
        self.start_times_tree.setEnabled(not is_busy)
        self.open_igc_action.setEnabled(not is_busy)

    def _clear_static_overlays(self) -> None:
        for item in self.static_overlay_items:
            self.plot_widget.removeItem(item)
        self.static_overlay_items = []

    def _clear_visible_flight_markers(self) -> None:
        for item in self.visible_flight_markers:
            try:
                self.plot_widget.removeItem(item)
            except Exception:
                pass
        self.visible_flight_markers = []

    def _clear_gaggle_overlays(self) -> None:
        for item in self.gaggle_overlay_items:
            try:
                self.plot_widget.removeItem(item)
            except Exception:
                pass
        self.gaggle_overlay_items = []

    def _clear_gaggle_reference_overlays(self) -> None:
        for item in self.gaggle_reference_items:
            try:
                self.plot_widget.removeItem(item)
            except Exception:
                pass
        self.gaggle_reference_items = []
        self._gaggle_reference_drawn_count = 0

    def _update_gaggle_settings_summary(self) -> None:
        raw_count = len(self.gaggle_clusters_raw)
        zone_count = len(self.gaggle_clusters)
        detecting_text = " | detecting..." if self._gaggle_thread is not None else ""
        self.gaggle_settings_summary_label.setText(
            "Legend: center marker encodes strength (low/medium/high), blue circles are members | "
            f"distance <= {int(self.gaggle_distance_m)} m, time <= {int(self.gaggle_time_delta_s)} s, "
            f"vertical <= {int(self.gaggle_altitude_delta_m)} m, min size >= {int(self.gaggle_min_cluster_size)} | "
            f"events: {raw_count}, zones: {zone_count}, active persist: {int(self.GAGGLE_ACTIVE_PERSISTENCE_S)} s "
            f"(drawn {self._gaggle_reference_drawn_count}){detecting_text}"
        )

    def _on_gaggle_settings_changed(self) -> None:
        self.gaggle_distance_m = float(self.gaggle_distance_spin.value())
        self.gaggle_time_delta_s = float(self.gaggle_time_spin.value())
        self.gaggle_altitude_delta_m = float(self.gaggle_altitude_spin.value())
        self.gaggle_min_cluster_size = int(self.gaggle_min_size_spin.value())
        self._gaggle_clusters_ready = False
        self._update_gaggle_settings_summary()
        if self.track_xs and len(self.scene_state.active_flights) >= 2:
            self._render_gaggle_reference_zones(restart_if_running=True)
            self._render_active_gaggles()

    def _reset_gaggle_settings(self) -> None:
        self.gaggle_distance_spin.setValue(int(self.GAGGLE_MAX_DISTANCE_M))
        self.gaggle_time_spin.setValue(int(self.GAGGLE_MAX_TIME_DELTA_S))
        self.gaggle_altitude_spin.setValue(int(self.GAGGLE_MAX_ALTITUDE_DELTA_M))
        self.gaggle_min_size_spin.setValue(int(self.GAGGLE_MIN_CLUSTER_SIZE))

    def _set_gaggle_detection_busy(self, is_busy: bool, label: str = "") -> None:
        self.gaggle_progress_label.setVisible(is_busy)
        self.gaggle_progress_bar.setVisible(is_busy)
        self.cancel_gaggle_button.setVisible(is_busy)
        self.cancel_gaggle_button.setEnabled(is_busy)
        if is_busy:
            self.gaggle_progress_label.setText(label or "Detecting gaggle zones...")
            self.gaggle_progress_bar.setRange(0, 0)
            self.gaggle_progress_bar.setValue(0)
        else:
            self.gaggle_progress_label.setText("")
            self.gaggle_progress_bar.setValue(0)

    def _cancel_gaggle_detection(self) -> None:
        if self._gaggle_worker is None:
            return
        self._gaggle_pending_refresh = True
        self._gaggle_worker.request_cancel()
        self.cancel_gaggle_button.setEnabled(False)
        self.gaggle_progress_label.setText("Cancelling gaggle detection...")

    @staticmethod
    def _gaggle_strength_style(strength: float) -> dict[str, str]:
        if strength >= 0.75:
            return {"label": "high", "color": "#d62728", "symbol": "star"}
        if strength >= 0.45:
            return {"label": "medium", "color": "#ff7f0e", "symbol": "d"}
        return {"label": "low", "color": "#f4b400", "symbol": "o"}

    def _compute_cluster_strength(self, cluster: dict, current_time: float) -> float:
        size_factor = min(max(cluster.get("size", 0) / 6.0, 0.0), 1.0)
        radius = float(cluster.get("radius_m", self.gaggle_distance_m))
        compactness = min(max(1.0 - (radius / max(self.gaggle_distance_m, 1.0)), 0.0), 1.0)
        age = abs(float(cluster.get("timestamp", current_time)) - current_time)
        recency = min(max(1.0 - (age / max(self.gaggle_time_delta_s, 1.0)), 0.0), 1.0)
        return min(max((0.5 * size_factor) + (0.3 * compactness) + (0.2 * recency), 0.0), 1.0)

    @staticmethod
    def _cluster_flight_ids(cluster: dict) -> set[str]:
        return {
            str(member.get("flight_id"))
            for member in list(cluster.get("members") or [])
            if member.get("flight_id") is not None
        }

    def _merge_drifting_clusters(
        self,
        clusters: list[dict],
        *,
        max_gap_s: float,
        reference_time: float | None = None,
    ) -> list[dict]:
        if not clusters:
            return []

        sorted_clusters = sorted(clusters, key=lambda item: float(item.get("timestamp", 0.0)))
        zones: list[dict] = []

        for cluster in sorted_clusters:
            centroid = cluster.get("centroid") or {}
            lat = centroid.get("lat")
            lon = centroid.get("lon")
            if lat is None or lon is None:
                continue
            ts = float(cluster.get("timestamp", 0.0))
            flight_ids = self._cluster_flight_ids(cluster)
            if not flight_ids:
                continue

            best_zone: dict | None = None
            best_score: float | None = None
            for zone in zones:
                dt = ts - float(zone["last_ts"])
                if dt < 0.0 or dt > max_gap_s:
                    continue
                overlap = len(flight_ids & zone["flight_ids"])
                if overlap < self.GAGGLE_ZONE_MIN_MEMBER_OVERLAP:
                    continue
                dist_m = _distance_between_points_m(
                    float(lat),
                    float(lon),
                    float(zone["centroid_lat"]),
                    float(zone["centroid_lon"]),
                )
                allowed_m = self.GAGGLE_ZONE_LINK_BASE_DISTANCE_M + self.GAGGLE_ZONE_DRIFT_SPEED_MPS * dt
                if dist_m > allowed_m:
                    continue
                score = (dist_m / max(allowed_m, 1.0)) - (0.12 * min(overlap, 3))
                if best_score is None or score < best_score:
                    best_score = score
                    best_zone = zone

            if best_zone is None:
                zones.append({
                    "first_ts": ts,
                    "last_ts": ts,
                    "centroid_lat": float(lat),
                    "centroid_lon": float(lon),
                    "sample_count": 1,
                    "flight_ids": set(flight_ids),
                    "peak_size": int(cluster.get("size", 0)),
                    "max_radius_m": float(cluster.get("radius_m", 0.0)),
                    "representative": cluster,
                })
                continue

            count = int(best_zone["sample_count"])
            weight = max(1, int(cluster.get("size", 1)))
            total_weight = count + weight
            best_zone["centroid_lat"] = ((float(best_zone["centroid_lat"]) * count) + (float(lat) * weight)) / total_weight
            best_zone["centroid_lon"] = ((float(best_zone["centroid_lon"]) * count) + (float(lon) * weight)) / total_weight
            best_zone["sample_count"] = count + 1
            best_zone["last_ts"] = ts
            best_zone["flight_ids"].update(flight_ids)
            best_zone["peak_size"] = max(int(best_zone["peak_size"]), int(cluster.get("size", 0)))
            best_zone["max_radius_m"] = max(float(best_zone["max_radius_m"]), float(cluster.get("radius_m", 0.0)))

            representative = best_zone.get("representative")
            if representative is None:
                best_zone["representative"] = cluster
            elif reference_time is None:
                if int(cluster.get("size", 0)) > int(representative.get("size", 0)):
                    best_zone["representative"] = cluster
            else:
                rep_ts = float(representative.get("timestamp", 0.0))
                rep_delta = abs(rep_ts - reference_time)
                new_delta = abs(ts - reference_time)
                if (new_delta < rep_delta) or (new_delta == rep_delta and int(cluster.get("size", 0)) > int(representative.get("size", 0))):
                    best_zone["representative"] = cluster

        merged: list[dict] = []
        for zone in zones:
            representative = zone.get("representative")
            if representative is None:
                continue
            merged_cluster = dict(representative)
            merged_cluster["centroid"] = {
                "lat": float(zone["centroid_lat"]),
                "lon": float(zone["centroid_lon"]),
            }
            merged_cluster["size"] = int(zone["peak_size"])
            merged_cluster["radius_m"] = float(zone["max_radius_m"])
            merged_cluster["first_timestamp"] = float(zone["first_ts"])
            merged_cluster["last_timestamp"] = float(zone["last_ts"])
            merged_cluster["zone_samples"] = int(zone["sample_count"])
            merged_cluster["zone_flight_ids"] = sorted(zone["flight_ids"])
            merged.append(merged_cluster)

        return sorted(
            merged,
            key=lambda item: (
                int(item.get("size", 0)),
                int(item.get("zone_samples", 1)),
                float(item.get("timestamp", 0.0)),
            ),
            reverse=True,
        )

    def _render_gaggle_reference_zones(self, *, restart_if_running: bool = False) -> None:
        flights = self.scene_state.active_flights
        if len(flights) < 2:
            self._reset_gaggle_display_state()
            return
        if not self.track_xs:
            self._reset_gaggle_display_state()
            return

        if self._gaggle_thread is not None:
            self._gaggle_pending_refresh = True
            if restart_if_running and self._gaggle_worker is not None:
                self._gaggle_worker.request_cancel()
            self._update_gaggle_settings_summary()
            return

        self._gaggle_clusters_ready = False
        self._gaggle_pending_refresh = False
        self._gaggle_job_id += 1
        job_id = self._gaggle_job_id
        self._set_gaggle_detection_busy(True)
        self._update_gaggle_settings_summary()

        thread = QThread(self)
        worker = GaggleDetectionWorker(
            job_id=job_id,
            flights=flights,
            max_distance_m=self.gaggle_distance_m,
            max_time_delta_s=self.gaggle_time_delta_s,
            max_altitude_delta_m=self.gaggle_altitude_delta_m,
            min_cluster_size=self.gaggle_min_cluster_size,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_gaggle_detection_progress)
        worker.finished.connect(self._on_gaggle_detection_finished)
        worker.failed.connect(self._on_gaggle_detection_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._cleanup_gaggle_detection_thread)

        self._gaggle_thread = thread
        self._gaggle_worker = worker
        thread.start()

    def _reset_gaggle_display_state(self) -> None:
        self.gaggle_clusters_raw = []
        self.gaggle_clusters = []
        self._gaggle_clusters_ready = True
        self._clear_gaggle_reference_overlays()
        self._clear_gaggle_overlays()
        self._update_gaggle_settings_summary()

    def _draw_gaggle_reference_zones(self, clusters: list[dict]) -> None:
        self._clear_gaggle_reference_overlays()
        merged = self._merge_drifting_clusters(
            clusters,
            max_gap_s=self.GAGGLE_ZONE_MAX_GAP_S,
        )
        self.gaggle_clusters = merged
        reduced = self._reduce_reference_clusters(merged)
        zone_xs: list[float] = []
        zone_ys: list[float] = []
        zone_sizes: list[float] = []

        for cluster in reduced:
            centroid = cluster.get("centroid") or {}
            lat = centroid.get("lat")
            lon = centroid.get("lon")
            if lat is None or lon is None:
                continue
            xs, ys = self._project_lon_lat_lists([float(lon)], [float(lat)])
            if not xs or not ys:
                continue
            zone_xs.append(xs[0])
            zone_ys.append(ys[0])
            zone_sizes.append(min(26.0, 8.0 + max(0.0, float(cluster.get("size", 0))) * 0.35))

        self._gaggle_reference_drawn_count = len(zone_xs)
        if not zone_xs:
            self._update_gaggle_settings_summary()
            return

        zone_item = pg.ScatterPlotItem(
            zone_xs,
            zone_ys,
            pen=pg.mkPen(color=(214, 39, 40, 150), width=1.4),
            brush=pg.mkBrush(0, 0, 0, 0),
            size=zone_sizes,
            symbol="o",
            pxMode=True,
        )
        zone_item.setZValue(2)
        self.plot_widget.addItem(zone_item)
        self.gaggle_reference_items.append(zone_item)
        self._update_gaggle_settings_summary()

    def _show_reference_zones_when_static(self) -> None:
        if self.timer.isActive():
            return
        if not self._gaggle_clusters_ready:
            return
        if not self.gaggle_clusters_raw:
            self._clear_gaggle_reference_overlays()
            self._update_gaggle_settings_summary()
            return
        self._draw_gaggle_reference_zones(self.gaggle_clusters_raw)

    def _hide_reference_zones_for_animation(self) -> None:
        if self.gaggle_reference_items:
            self._clear_gaggle_reference_overlays()
            self._update_gaggle_settings_summary()

    def _reduce_reference_clusters(self, clusters: list[dict]) -> list[dict]:
        if len(clusters) <= self.GAGGLE_MAX_REFERENCE_ZONES:
            return list(clusters)

        selected_by_bin: dict[tuple[int, int, int], dict] = {}
        for cluster in clusters:
            centroid = cluster.get("centroid") or {}
            lat = centroid.get("lat")
            lon = centroid.get("lon")
            ts = float(cluster.get("timestamp", 0.0))
            if lat is None or lon is None:
                continue
            key = (
                int(round(float(lat) * 100.0)),
                int(round(float(lon) * 100.0)),
                int(ts // 300.0),
            )
            existing = selected_by_bin.get(key)
            if existing is None or int(cluster.get("size", 0)) > int(existing.get("size", 0)):
                selected_by_bin[key] = cluster

        reduced = sorted(
            selected_by_bin.values(),
            key=lambda item: (int(item.get("size", 0)), float(item.get("timestamp", 0.0))),
            reverse=True,
        )
        return reduced[: self.GAGGLE_MAX_REFERENCE_ZONES]

    def _on_gaggle_detection_progress(self, stage: str, current: int, total: int) -> None:
        if self._gaggle_thread is None:
            return
        total_value = max(int(total), 1)
        current_value = max(0, min(int(current), total_value))
        self.gaggle_progress_bar.setRange(0, total_value)
        self.gaggle_progress_bar.setValue(current_value)
        if stage == "flight":
            self.gaggle_progress_label.setText(f"Detecting thermals: {current_value}/{total_value} flights")
        else:
            self.gaggle_progress_label.setText(f"Clustering events: {current_value}/{total_value}")

    def _on_gaggle_detection_finished(self, job_id: int, clusters: object, cancelled: bool) -> None:
        if int(job_id) != self._gaggle_job_id:
            return
        self._set_gaggle_detection_busy(False)
        if not cancelled:
            self.gaggle_clusters_raw = list(clusters or [])
            self.gaggle_clusters = []
            self._gaggle_clusters_ready = True
            if self.timer.isActive():
                self._hide_reference_zones_for_animation()
            else:
                self._draw_gaggle_reference_zones(self.gaggle_clusters_raw)
            self._render_active_gaggles()
        self._update_gaggle_settings_summary()

    def _on_gaggle_detection_failed(self, job_id: int, message: str) -> None:
        if int(job_id) != self._gaggle_job_id:
            return
        self._set_gaggle_detection_busy(False)
        self._gaggle_clusters_ready = False
        self.gaggle_settings_summary_label.setText(
            f"Gaggle detection failed: {message}"
        )

    def _cleanup_gaggle_detection_thread(self) -> None:
        if self._gaggle_thread is not None:
            self._gaggle_thread.deleteLater()
        self._gaggle_thread = None
        self._gaggle_worker = None
        self._update_gaggle_settings_summary()
        if self._gaggle_pending_refresh:
            self._gaggle_pending_refresh = False
            self._render_gaggle_reference_zones()

    def _render_active_gaggles(self) -> None:
        self._clear_gaggle_overlays()
        flights = self.scene_state.active_flights
        if len(flights) < 2:
            return
        if not self.track_xs:
            return

        current_time = self.track_time_offsets[self.current_index] if self.track_time_offsets else float(self.current_index)
        if not self._gaggle_clusters_ready:
            if self._gaggle_thread is not None:
                return
            self._render_gaggle_reference_zones()
            return
        active_persistence_s = max(float(self.GAGGLE_ACTIVE_PERSISTENCE_S), float(self.gaggle_time_delta_s))
        clusters = [
            cluster
            for cluster in self.gaggle_clusters_raw
            if 0.0 <= (current_time - float(cluster.get("timestamp", current_time))) <= active_persistence_s
        ]
        clusters = self._merge_drifting_clusters(
            clusters,
            max_gap_s=max(self.gaggle_time_delta_s * 2.0, 60.0),
            reference_time=current_time,
        )
        clusters = sorted(clusters, key=lambda item: int(item.get("size", 0)), reverse=True)
        clusters = clusters[: self.GAGGLE_MAX_ACTIVE_CLUSTERS]

        member_xs: list[float] = []
        member_ys: list[float] = []
        member_seen: set[tuple[int, int]] = set()
        for cluster in clusters:
            cluster_ts = float(cluster.get("timestamp", current_time))
            cluster_age_s = max(0.0, current_time - cluster_ts)
            fade_ratio = max(0.3, min(1.0, 1.0 - (cluster_age_s / max(active_persistence_s, 1.0))))
            strength = self._compute_cluster_strength(cluster, current_time)
            style = self._gaggle_strength_style(strength)
            centroid = cluster["centroid"]
            xs, ys = self._project_lon_lat_lists([centroid["lon"]], [centroid["lat"]])
            if not xs or not ys:
                continue

            flight_count = len(cluster.get("zone_flight_ids") or self._cluster_flight_ids(cluster))
            visual_size = min(36.0, 10.0 + max(2, flight_count) * 3.0)

            base_color = pg.mkColor(style["color"]).getRgb()
            pen_alpha = int(255 * fade_ratio)
            centroid_item = pg.ScatterPlotItem(
                [xs[0]],
                [ys[0]],
                pen=pg.mkPen(color=(base_color[0], base_color[1], base_color[2], pen_alpha), width=2.2),
                brush=pg.mkBrush(0, 0, 0, 0),
                size=visual_size,
                symbol="o",
            )
            centroid_item.setToolTip(
                f"Thermal center | strength: {style['label']} ({strength:.2f}) | "
                f"flights: {flight_count} | radius: {cluster.get('radius_m', 0.0):.0f} m | age: {cluster_age_s:.0f}s"
            )
            centroid_item.setZValue(5)
            self.plot_widget.addItem(centroid_item)
            self.gaggle_overlay_items.append(centroid_item)

            if cluster_age_s > self.gaggle_time_delta_s:
                continue

            for member in cluster["members"]:
                m_xs, m_ys = self._project_lon_lat_lists([member["lon"]], [member["lat"]])
                if not m_xs or not m_ys:
                    continue
                key = (int(round(m_xs[0] * 1000.0)), int(round(m_ys[0] * 1000.0)))
                if key in member_seen:
                    continue
                member_seen.add(key)
                member_xs.append(m_xs[0])
                member_ys.append(m_ys[0])
                if len(member_xs) >= self.GAGGLE_MAX_ACTIVE_MEMBER_POINTS:
                    break
            if len(member_xs) >= self.GAGGLE_MAX_ACTIVE_MEMBER_POINTS:
                break

        if not member_xs:
            return

        member_item = pg.ScatterPlotItem(
            member_xs,
            member_ys,
            pen=pg.mkPen(color="#1f77b4", width=1.6),
            brush=pg.mkBrush(31, 119, 180, 80),
            size=8,
            symbol="o",
        )
        member_item.setToolTip(
            f"Thermal members | shown points: {len(member_xs)}"
        )
        member_item.setZValue(4)
        self.plot_widget.addItem(member_item)
        self.gaggle_overlay_items.append(member_item)

    def _add_overlay_line(self, lons: list[float], lats: list[float], color: str, width: int = 2) -> None:
        if not lons or not lats:
            return
        xs, ys = self._project_lon_lat_lists(lons, lats)
        item = self.plot_widget.plot(xs, ys, pen=pg.mkPen(color=color, width=width))
        self.static_overlay_items.append(item)

    def _render_static_overlays(self, record) -> None:
        task_points = record.task_points
        task_sectors = record.task_sectors
        start_sector = record.start_sector
        finish_sector = record.finish_sector

        if task_points:
            route_lons = [float(point["lon"]) for point in task_points if "lon" in point and "lat" in point]
            route_lats = [float(point["lat"]) for point in task_points if "lon" in point and "lat" in point]
            self._add_overlay_line(route_lons, route_lats, color="#d62728", width=2)

            route_xs, route_ys = self._project_lon_lat_lists(route_lons, route_lats)

            waypoint_item = self.plot_widget.plot(
                route_xs,
                route_ys,
                pen=None,
                symbol="t",
                symbolBrush="#d62728",
                symbolPen="#d62728",
                symbolSize=8,
            )
            self.static_overlay_items.append(waypoint_item)

        start_idx = start_sector.get("idx") if start_sector else None
        finish_idx = finish_sector.get("idx") if finish_sector else None
        turnpoint_sectors = [
            sector
            for sector in task_sectors
            if sector.get("idx") not in {start_idx, finish_idx} and sector.get("idx") is not None
        ]

        if start_sector:
            self._draw_sector_overlay(start_sector, color="#2ca02c")
        if finish_sector and finish_idx != start_idx:
            self._draw_sector_overlay(finish_sector, color="#ff7f0e")
        for sector in turnpoint_sectors:
            self._draw_sector_overlay(sector, color="#1f77b4")

    def _draw_sector_overlay(self, sector: dict, color: str) -> None:
        try:
            orientation = sector.get("orientation_deg") or 0.0
            result = build_sector_split_points(
                sector["lat"],
                sector["lon"],
                sector["radius_m"],
                orientation,
                sector.get("a1_deg", 0.0),
                inner_radius_m=sector.get("inner_radius_m", 0.0),
                inner_half_angle_deg=sector.get("a2_deg", 0.0),
            )
        except Exception:
            return

        if len(result) == 2:
            clockwise_points, anticlockwise_points = result
            inner_clockwise_points = inner_anticlockwise_points = None
        else:
            clockwise_points, anticlockwise_points, inner_clockwise_points, inner_anticlockwise_points = result

        if clockwise_points:
            radial = [(sector["lat"], sector["lon"]), clockwise_points[-1]]
            self._add_overlay_line([point[1] for point in radial], [point[0] for point in radial], color=color)
            self._add_overlay_line(
                [point[1] for point in clockwise_points],
                [point[0] for point in clockwise_points],
                color=color,
            )

        if anticlockwise_points:
            radial = [(sector["lat"], sector["lon"]), anticlockwise_points[-1]]
            self._add_overlay_line([point[1] for point in radial], [point[0] for point in radial], color=color)
            self._add_overlay_line(
                [point[1] for point in anticlockwise_points],
                [point[0] for point in anticlockwise_points],
                color=color,
            )

        if inner_clockwise_points is not None:
            self._add_overlay_line(
                [point[1] for point in inner_clockwise_points],
                [point[0] for point in inner_clockwise_points],
                color=color,
            )
        if inner_anticlockwise_points is not None:
            self._add_overlay_line(
                [point[1] for point in inner_anticlockwise_points],
                [point[0] for point in inner_anticlockwise_points],
                color=color,
            )

        if inner_clockwise_points is not None and inner_anticlockwise_points is not None:
            join_points = [
                (sector["lat"], sector["lon"]),
                inner_clockwise_points[0],
                inner_anticlockwise_points[0],
            ]
            self._add_overlay_line([point[1] for point in join_points], [point[0] for point in join_points], color=color)

    def start_animation(self) -> None:
        if len(self.track_xs) > 1:
            self._hide_reference_zones_for_animation()
            self._render_track_view(use_recent_trail=True)
            self.last_tick_monotonic = time.monotonic()
            self.timer.start()

    def pause_animation(self) -> None:
        self.timer.stop()
        self.last_tick_monotonic = None
        self._render_track_view(use_recent_trail=False)
        self._show_reference_zones_when_static()

    def reset_animation(self) -> None:
        self.timer.stop()
        self.last_tick_monotonic = None
        self._show_reference_zones_when_static()
        if not self.track_lons:
            return
        self.jump_to_index(0)

    def on_tick(self) -> None:
        if not self.track_xs:
            self.timer.stop()
            self.last_tick_monotonic = None
            return

        if self.current_index >= len(self.track_xs) - 1:
            self.timer.stop()
            self.last_tick_monotonic = None
            self._render_track_view(use_recent_trail=False)
            self._show_reference_zones_when_static()
            self.status_controller.playback_complete(len(self.track_xs), len(self.track_xs))
            return

        now = time.monotonic()
        if self.last_tick_monotonic is None:
            self.last_tick_monotonic = now
            return

        real_delta_seconds = max(0.0, now - self.last_tick_monotonic)
        self.last_tick_monotonic = now
        self.sim_elapsed_seconds += real_delta_seconds * self.current_speed_multiplier()

        target_index = self.current_index
        last_index = len(self.track_time_offsets) - 1
        while target_index < last_index and self.track_time_offsets[target_index + 1] <= self.sim_elapsed_seconds:
            target_index += 1

        self.current_index = target_index
        self._render_track_view(use_recent_trail=True)
        self._render_active_gaggles()
        self.status_controller.playback_frame(self.current_index + 1, len(self.track_xs))

    def current_speed_multiplier(self) -> int:
        label = self.speed_combo.currentText().strip().lower()
        if label.endswith("x"):
            label = label[:-1]
        try:
            value = int(label)
        except ValueError:
            return 1
        return max(1, value)

    def _recent_track_indices(self, current_index: int) -> tuple[int, int]:
        if not self.track_time_offsets:
            return max(0, current_index - 10), current_index

        duration = max(self.track_time_offsets[-1], 1.0)
        lookback_seconds = min(float(self.recent_track_seconds), duration)
        window_points = max(2, int((lookback_seconds / duration) * max(len(self.track_time_offsets) - 1, 1)))
        start_index = max(0, current_index - window_points)
        return start_index, current_index

    def _render_track_view(self, *, use_recent_trail: bool) -> None:
        if not self.track_xs:
            return

        if use_recent_trail:
            self.track_item.setPen(pg.mkPen(color=self.ANIMATING_TRAIL_GHOST_PEN, width=2.0))
            self.flown_track_item.setPen(pg.mkPen(color=self.ANIMATING_TRAIL_PEN, width=2.8))
            start_index, end_index = self._recent_track_indices(self.current_index)
            trail_xs = self.track_xs[start_index:end_index + 1]
            trail_ys = self.track_ys[start_index:end_index + 1]
            self.track_item.setData(trail_xs, trail_ys)
            self.flown_track_item.setData(trail_xs, trail_ys)
        else:
            self.track_item.setPen(pg.mkPen(color=self.STATIC_FULL_ROUTE_PEN, width=1.5))
            self.flown_track_item.setPen(pg.mkPen(color=self.STATIC_FLOWN_ROUTE_PEN, width=2.6))
            self.track_item.setData(self.track_xs, self.track_ys)
            self.flown_track_item.setData(
                self.track_xs[: self.current_index + 1],
                self.track_ys[: self.current_index + 1],
            )

        self._render_extra_tracks(use_recent_trail=use_recent_trail)
        self.marker_item.setData([self.track_xs[self.current_index]], [self.track_ys[self.current_index]])

        if not self.scene_state.active_flights:
            self._clear_visible_flight_markers()
            return

        colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
        self._clear_visible_flight_markers()
        for index, flight in enumerate(self.scene_state.active_flights):
            if not getattr(flight, "lons", None) or not getattr(flight, "lats", None):
                continue
            fix_count = len(flight.lons)
            if fix_count == 0:
                continue
            flight_timeline = TimelineState.from_flight(flight)
            flight_offsets = flight_timeline.time_offsets
            local_total = max(float(flight_timeline.total_seconds), 1.0)
            active_index = 0
            if len(flight_offsets) > 1 and self.sim_elapsed_seconds > 0:
                active_index = min(
                    len(flight_offsets) - 1,
                    max(0, int((self.sim_elapsed_seconds / local_total) * (len(flight_offsets) - 1))),
                )
            lon = float(flight.lons[active_index]) if active_index < len(flight.lons) else float(flight.lons[-1])
            lat = float(flight.lats[active_index]) if active_index < len(flight.lats) else float(flight.lats[-1])
            px, py = self._project_lon_lat_lists([lon], [lat])
            if not px or not py:
                continue
            item = pg.ScatterPlotItem(
                [px[0]],
                [py[0]],
                pen=pg.mkPen(color=colors[index % len(colors)], width=2),
                brush=pg.mkBrush(colors[index % len(colors)]),
                size=8 if index > 0 else 10,
                symbol="o",
            )
            self.plot_widget.addItem(item)
            self.visible_flight_markers.append(item)

    def _render_extra_tracks(self, *, use_recent_trail: bool) -> None:
        for item in self.extra_track_items:
            self.plot_widget.removeItem(item)
        self.extra_track_items = []

        active_flights = self.scene_state.active_flights
        if len(active_flights) < 2:
            return

        colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
        for index, extra_record in enumerate(active_flights[1:], start=1):
            if not getattr(extra_record, "lons", None) or not getattr(extra_record, "lats", None):
                continue

            if use_recent_trail:
                extra_timeline = TimelineState.from_flight(extra_record)
                extra_offsets = extra_timeline.time_offsets
                if not extra_offsets:
                    continue
                local_total = max(float(extra_timeline.total_seconds), 1.0)
                local_index = 0
                if len(extra_offsets) > 1 and self.sim_elapsed_seconds > 0:
                    local_index = min(
                        len(extra_offsets) - 1,
                        max(0, int((self.sim_elapsed_seconds / local_total) * (len(extra_offsets) - 1))),
                    )
                window_points = max(
                    2,
                    int((float(self.recent_track_seconds) / local_total) * max(len(extra_offsets) - 1, 1)),
                )
                start_index = max(0, local_index - window_points)
                lons = extra_record.lons[start_index:local_index + 1]
                lats = extra_record.lats[start_index:local_index + 1]
            else:
                lons = extra_record.lons
                lats = extra_record.lats

            xs, ys = self._project_lon_lat_lists(lons, lats)
            if not xs or not ys:
                continue
            extra_pen = pg.mkPen(color=colors[(index - 1) % len(colors)], width=1.7)
            if not use_recent_trail:
                extra_pen = pg.mkPen(color=(*pg.mkColor(colors[(index - 1) % len(colors)]).getRgb()[:3], 90), width=1.1)
            extra_item = self.plot_widget.plot(
                xs,
                ys,
                pen=extra_pen,
            )
            self.extra_track_items.append(extra_item)

    def jump_to_index(self, index: int) -> None:
        if not self.track_xs:
            return

        clamped_index = max(0, min(index, len(self.track_xs) - 1))
        self.current_index = clamped_index
        if self.track_time_offsets and clamped_index < len(self.track_time_offsets):
            self.sim_elapsed_seconds = self.track_time_offsets[clamped_index]
        else:
            self.sim_elapsed_seconds = float(clamped_index)

        self._render_track_view(use_recent_trail=self.timer.isActive())
        self._render_active_gaggles()
        self._set_timeline_slider_value(clamped_index)
        total_seconds = self.track_time_offsets[-1] if self.track_time_offsets else float(len(self.track_xs) - 1)
        self.timeline_label.setText(
            f"Time: {self._format_seconds(self.sim_elapsed_seconds)} / {self._format_seconds(total_seconds)}"
        )
        self.status_controller.playback_frame(clamped_index + 1, len(self.track_xs))

    def on_timeline_slider_changed(self, value: int) -> None:
        if self.timeline_internal_update:
            return
        if not self.track_xs:
            return

        was_running = self.timer.isActive()
        self.jump_to_index(int(value))
        if was_running:
            self.last_tick_monotonic = time.monotonic()
        else:
            self.last_tick_monotonic = None

    def on_plot_mouse_clicked(self, event) -> None:
        if not event.double():
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self.track_xs:
            return

        self.timer.stop()
        self.last_tick_monotonic = None

        view_pos = self.plot_widget.plotItem.vb.mapSceneToView(event.scenePos())
        click_x = float(view_pos.x())
        click_y = float(view_pos.y())

        nearest_index = 0
        nearest_distance_sq = float("inf")
        for idx, (x_val, y_val) in enumerate(zip(self.track_xs, self.track_ys)):
            dx = x_val - click_x
            dy = y_val - click_y
            distance_sq = dx * dx + dy * dy
            if distance_sq < nearest_distance_sq:
                nearest_distance_sq = distance_sq
                nearest_index = idx

        self.jump_to_index(nearest_index)

    def _set_timeline_slider_value(self, value: int) -> None:
        self.timeline_internal_update = True
        self.timeline_slider.setValue(value)
        self.timeline_internal_update = False

    def _format_seconds(self, seconds_value: float) -> str:
        total_seconds = max(0, int(seconds_value))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _configure_projection(self, lons: list[float], lats: list[float]) -> None:
        center_lon = sum(lons) / len(lons)
        center_lat = sum(lats) / len(lats)
        local_crs = CRS.from_proj4(f"+proj=aeqd +lat_0={center_lat} +lon_0={center_lon} +datum=WGS84 +units=m +no_defs")
        self.geo_to_local = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)

    def _project_lon_lat_lists(self, lons: list[float], lats: list[float]) -> tuple[list[float], list[float]]:
        if not lons or not lats or len(lons) != len(lats):
            return [], []
        if self.geo_to_local is None:
            return lons, lats

        xs: list[float] = []
        ys: list[float] = []
        for lon, lat in zip(lons, lats):
            x_m, y_m = self.geo_to_local.transform(lon, lat)
            xs.append(float(x_m) / 1000.0)
            ys.append(float(y_m) / 1000.0)
        return xs, ys

    def closeEvent(self, event) -> None:
        if self._gaggle_worker is not None:
            self._gaggle_worker.request_cancel()
        if self._gaggle_thread is not None:
            self._gaggle_thread.quit()
            self._gaggle_thread.wait()
        self.flight_render_controller.shutdown()
        self.flight_load_controller.shutdown()
        self.download_controller.shutdown()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
