from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from qt_helpers import selected_local_flight_paths, selected_start_time_paths


def _flight_item(file_path: str) -> QTreeWidgetItem:
    item = QTreeWidgetItem([file_path.split("/")[-1]])
    item.setData(0, Qt.ItemDataRole.UserRole, "local_flight")
    item.setData(0, Qt.ItemDataRole.UserRole + 4, file_path)
    return item


def _start_time_flight_item(file_path: str) -> QTreeWidgetItem:
    item = QTreeWidgetItem([file_path.split("/")[-1]])
    item.setData(0, Qt.ItemDataRole.UserRole, file_path)
    return item


def _build_local_tree() -> tuple[QTreeWidgetItem, QTreeWidgetItem]:
    contest_a = QTreeWidgetItem(["Contest A"])
    contest_a.setData(0, Qt.ItemDataRole.UserRole, "local_contest")
    class_a = QTreeWidgetItem(["15 Metre"])
    day_a = QTreeWidgetItem(["2026-08-08"])
    day_a.addChild(_flight_item("/tmp/contest_a/15m/2026-08-08/a1.igc"))
    day_a.addChild(_flight_item("/tmp/contest_a/15m/2026-08-08/a2.igc"))
    class_a.addChild(day_a)
    contest_a.addChild(class_a)

    contest_b = QTreeWidgetItem(["Contest B"])
    contest_b.setData(0, Qt.ItemDataRole.UserRole, "local_contest")
    class_b = QTreeWidgetItem(["Open"])
    day_b = QTreeWidgetItem(["2026-08-09"])
    day_b.addChild(_flight_item("/tmp/contest_b/open/2026-08-09/b1.igc"))
    class_b.addChild(day_b)
    contest_b.addChild(class_b)

    return contest_a, contest_b


def test_selected_local_flight_paths_collects_all_descendants_for_contest_selection():
    contest_a, _ = _build_local_tree()

    paths = selected_local_flight_paths([contest_a])

    assert len(paths) == 2
    assert "/tmp/contest_a/15m/2026-08-08/a1.igc" in paths
    assert "/tmp/contest_a/15m/2026-08-08/a2.igc" in paths


def test_selected_local_flight_paths_supports_multi_contest_selection():
    contest_a, contest_b = _build_local_tree()

    paths = selected_local_flight_paths([contest_a, contest_b])

    assert len(paths) == 3
    assert "/tmp/contest_a/15m/2026-08-08/a1.igc" in paths
    assert "/tmp/contest_a/15m/2026-08-08/a2.igc" in paths
    assert "/tmp/contest_b/open/2026-08-09/b1.igc" in paths


def test_selected_local_flight_paths_prefers_specific_day_over_selected_contest():
    contest_a, _ = _build_local_tree()
    class_a = contest_a.child(0)
    day_a = class_a.child(0)

    paths = selected_local_flight_paths([contest_a, day_a])

    assert len(paths) == 2
    assert "/tmp/contest_a/15m/2026-08-08/a1.igc" in paths
    assert "/tmp/contest_a/15m/2026-08-08/a2.igc" in paths


def _build_start_time_tree() -> tuple[QTreeWidgetItem, QTreeWidgetItem]:
    day_1 = QTreeWidgetItem(["2026-08-08"])
    class_1 = QTreeWidgetItem(["15 Metre"])
    class_1.addChild(_start_time_flight_item("/tmp/contest_a/15m/2026-08-08/a1.igc"))
    class_1.addChild(_start_time_flight_item("/tmp/contest_a/15m/2026-08-08/a2.igc"))
    day_1.addChild(class_1)

    day_2 = QTreeWidgetItem(["2026-08-09"])
    class_2 = QTreeWidgetItem(["15 Metre"])
    class_2.addChild(_start_time_flight_item("/tmp/contest_a/15m/2026-08-09/a3.igc"))
    day_2.addChild(class_2)
    return day_1, day_2


def test_selected_start_time_paths_prefers_specific_day_over_class_selection():
    day_1, day_2 = _build_start_time_tree()
    class_node = day_1.child(0)

    paths = selected_start_time_paths([class_node, day_1])

    assert len(paths) == 2
    assert "/tmp/contest_a/15m/2026-08-08/a1.igc" in paths
    assert "/tmp/contest_a/15m/2026-08-08/a2.igc" in paths
    assert "/tmp/contest_a/15m/2026-08-09/a3.igc" not in paths


def test_selected_start_time_paths_supports_multi_day_selection():
    day_1, day_2 = _build_start_time_tree()

    paths = selected_start_time_paths([day_1, day_2])

    assert len(paths) == 3
    assert "/tmp/contest_a/15m/2026-08-08/a1.igc" in paths
    assert "/tmp/contest_a/15m/2026-08-08/a2.igc" in paths
    assert "/tmp/contest_a/15m/2026-08-09/a3.igc" in paths
