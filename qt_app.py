from __future__ import annotations

import sys
import time

import libigc
import pyqtgraph as pg
from pyproj import CRS, Transformer
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from geo_task import (
    build_sector_split_points,
    extract_finish_sector_from_igc,
    extract_start_sector_from_igc,
    extract_task_points_from_igc,
    extract_task_sectors_from_igc,
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("IGC Desktop Viewer")
        self.resize(1000, 700)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addWidget(QLabel("PySide6 shell is running."))
        self.selected_file_label = QLabel("Selected file: none")
        layout.addWidget(self.selected_file_label)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("w")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)
        self.plot_widget.setLabel("bottom", "Easting (km)")
        self.plot_widget.setLabel("left", "Northing (km)")
        self.plot_widget.setAspectLocked(lock=True, ratio=1)
        self.track_item = self.plot_widget.plot([], [], pen=pg.mkPen(color="#bbbbbb", width=2))
        self.flown_track_item = self.plot_widget.plot([], [], pen=pg.mkPen(color="#111111", width=2))
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
        layout.addWidget(self.plot_widget, stretch=1)

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
        layout.addLayout(controls_layout)

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
        layout.addLayout(timeline_layout)

        self.status_label = QLabel("Status: waiting for file")
        layout.addWidget(self.status_label)
        self.setCentralWidget(central)

        self.track_lons: list[float] = []
        self.track_lats: list[float] = []
        self.track_xs: list[float] = []
        self.track_ys: list[float] = []
        self.track_time_offsets: list[float] = []
        self.geo_to_local: Transformer | None = None
        self.current_index = 0
        self.sim_elapsed_seconds = 0.0
        self.last_tick_monotonic: float | None = None
        self.timeline_internal_update = False
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.on_tick)
        self.plot_widget.scene().sigMouseClicked.connect(self.on_plot_mouse_clicked)

        file_menu = self.menuBar().addMenu("File")
        open_action = QAction("Open IGC...", self)
        open_action.triggered.connect(self.open_igc_file)
        file_menu.addAction(open_action)

    def open_igc_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open IGC file",
            "",
            "IGC files (*.igc);;All files (*)",
        )
        if file_path:
            self.selected_file_label.setText(f"Selected file: {file_path}")
            self.render_static_track(file_path)

    def render_static_track(self, file_path: str) -> None:
        self.timer.stop()
        self.last_tick_monotonic = None
        self.status_label.setText("Status: loading file...")
        self._clear_static_overlays()
        try:
            flight = libigc.Flight.create_from_file(file_path)
        except Exception as exc:
            self.status_label.setText(f"Status: failed to parse file ({exc})")
            self.track_item.setData([], [])
            self.flown_track_item.setData([], [])
            self.marker_item.setData([], [])
            self.track_time_offsets = []
            self.play_button.setEnabled(False)
            self.pause_button.setEnabled(False)
            self.reset_button.setEnabled(False)
            self.speed_combo.setEnabled(False)
            self.timeline_slider.setEnabled(False)
            self._set_timeline_slider_value(0)
            self.timeline_slider.setMaximum(0)
            self.timeline_label.setText("Time: 00:00:00 / 00:00:00")
            return

        if not flight.valid:
            self.status_label.setText("Status: parsed file is marked invalid")
            self.track_item.setData([], [])
            self.flown_track_item.setData([], [])
            self.marker_item.setData([], [])
            self.track_time_offsets = []
            self.play_button.setEnabled(False)
            self.pause_button.setEnabled(False)
            self.reset_button.setEnabled(False)
            self.speed_combo.setEnabled(False)
            self.timeline_slider.setEnabled(False)
            self._set_timeline_slider_value(0)
            self.timeline_slider.setMaximum(0)
            self.timeline_label.setText("Time: 00:00:00 / 00:00:00")
            return

        try:
            self.track_lons = [fix.lon for fix in flight.fixes]
            self.track_lats = [fix.lat for fix in flight.fixes]
            if not self.track_lons or not self.track_lats:
                self.status_label.setText("Status: no valid fixes found")
                self.track_item.setData([], [])
                self.flown_track_item.setData([], [])
                self.marker_item.setData([], [])
                self.track_time_offsets = []
                self.play_button.setEnabled(False)
                self.pause_button.setEnabled(False)
                self.reset_button.setEnabled(False)
                self.speed_combo.setEnabled(False)
                self.timeline_slider.setEnabled(False)
                self._set_timeline_slider_value(0)
                self.timeline_slider.setMaximum(0)
                self.timeline_label.setText("Time: 00:00:00 / 00:00:00")
                return

            self._configure_projection(self.track_lons, self.track_lats)
            self.track_xs, self.track_ys = self._project_lon_lat_lists(self.track_lons, self.track_lats)

            self.track_time_offsets = self._build_time_offsets(flight.fixes)

            self.track_item.setData(self.track_xs, self.track_ys)
            self.current_index = 0
            self.sim_elapsed_seconds = 0.0
            self.flown_track_item.setData([self.track_xs[0]], [self.track_ys[0]])
            self.marker_item.setData([self.track_xs[0]], [self.track_ys[0]])
            self.plot_widget.enableAutoRange()
            self.play_button.setEnabled(True)
            self.pause_button.setEnabled(True)
            self.reset_button.setEnabled(True)
            self.speed_combo.setEnabled(True)
            self.timeline_slider.setEnabled(True)
            self.timeline_slider.setMaximum(max(0, len(self.track_xs) - 1))
            self._set_timeline_slider_value(0)
            self.timeline_label.setText(
                f"Time: 00:00:00 / {self._format_seconds(self.track_time_offsets[-1] if self.track_time_offsets else 0.0)}"
            )
            self.status_label.setText(f"Status: rendered static track ({len(self.track_lons)} fixes)")

            self._render_static_overlays(file_path)
        except Exception as exc:
            self.track_item.setData([], [])
            self.flown_track_item.setData([], [])
            self.marker_item.setData([], [])
            self.track_time_offsets = []
            self.play_button.setEnabled(False)
            self.pause_button.setEnabled(False)
            self.reset_button.setEnabled(False)
            self.speed_combo.setEnabled(False)
            self.timeline_slider.setEnabled(False)
            self._set_timeline_slider_value(0)
            self.timeline_slider.setMaximum(0)
            self.timeline_label.setText("Time: 00:00:00 / 00:00:00")
            self.status_label.setText(f"Status: failed to render track ({exc})")

    def _clear_static_overlays(self) -> None:
        for item in self.static_overlay_items:
            self.plot_widget.removeItem(item)
        self.static_overlay_items = []

    def _add_overlay_line(self, lons: list[float], lats: list[float], color: str, width: int = 2) -> None:
        if not lons or not lats:
            return
        xs, ys = self._project_lon_lat_lists(lons, lats)
        item = self.plot_widget.plot(xs, ys, pen=pg.mkPen(color=color, width=width))
        self.static_overlay_items.append(item)

    def _render_static_overlays(self, file_path: str) -> None:
        try:
            task_points = extract_task_points_from_igc(file_path)
            task_sectors = extract_task_sectors_from_igc(file_path)
            start_sector = extract_start_sector_from_igc(file_path)
            finish_sector = extract_finish_sector_from_igc(file_path)
        except Exception:
            return

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
            self.last_tick_monotonic = time.monotonic()
            self.timer.start()

    def pause_animation(self) -> None:
        self.timer.stop()
        self.last_tick_monotonic = None

    def reset_animation(self) -> None:
        self.timer.stop()
        self.last_tick_monotonic = None
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
            self.status_label.setText(f"Status: complete ({len(self.track_xs)} / {len(self.track_xs)})")
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
        end = self.current_index + 1
        self.flown_track_item.setData(self.track_xs[:end], self.track_ys[:end])
        self.marker_item.setData([self.track_xs[self.current_index]], [self.track_ys[self.current_index]])
        self.status_label.setText(f"Status: frame {end} / {len(self.track_xs)}")

    def current_speed_multiplier(self) -> int:
        label = self.speed_combo.currentText().strip().lower()
        if label.endswith("x"):
            label = label[:-1]
        try:
            value = int(label)
        except ValueError:
            return 1
        return max(1, value)

    def jump_to_index(self, index: int) -> None:
        if not self.track_xs:
            return

        clamped_index = max(0, min(index, len(self.track_xs) - 1))
        self.current_index = clamped_index
        if self.track_time_offsets and clamped_index < len(self.track_time_offsets):
            self.sim_elapsed_seconds = self.track_time_offsets[clamped_index]
        else:
            self.sim_elapsed_seconds = float(clamped_index)

        end = clamped_index + 1
        self.flown_track_item.setData(self.track_xs[:end], self.track_ys[:end])
        self.marker_item.setData([self.track_xs[clamped_index]], [self.track_ys[clamped_index]])
        self._set_timeline_slider_value(clamped_index)
        total_seconds = self.track_time_offsets[-1] if self.track_time_offsets else float(len(self.track_xs) - 1)
        self.timeline_label.setText(
            f"Time: {self._format_seconds(self.sim_elapsed_seconds)} / {self._format_seconds(total_seconds)}"
        )
        self.status_label.setText(f"Status: frame {end} / {len(self.track_xs)}")

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

    def _build_time_offsets(self, fixes: list) -> list[float]:
        if not fixes:
            return []

        first_timestamp = getattr(fixes[0], "timestamp", None)
        if first_timestamp is None:
            return [float(i) for i in range(len(fixes))]

        offsets: list[float] = []
        previous = 0.0
        for idx, fix in enumerate(fixes):
            timestamp = getattr(fix, "timestamp", None)
            if timestamp is None:
                offsets.append(float(idx))
                previous = offsets[-1]
                continue

            if isinstance(timestamp, (int, float)) and isinstance(first_timestamp, (int, float)):
                delta = float(timestamp - first_timestamp)
            else:
                delta_obj = timestamp - first_timestamp
                if hasattr(delta_obj, "total_seconds"):
                    delta = float(delta_obj.total_seconds())
                else:
                    delta = float(delta_obj)

            if delta < previous:
                delta = previous
            offsets.append(float(delta))
            previous = float(delta)

        if offsets[-1] <= 0.0:
            return [float(i) for i in range(len(fixes))]
        return offsets

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


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
