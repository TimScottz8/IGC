from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QTableWidgetItem, QTreeWidgetItem

from contest_queue import ContestAcquisitionQueue
from contest_service import contest_download_dir, process_download_selection
from download_helpers import DOWNLOAD_DIR, sanitize
from qt_helpers import (
    build_contest_download_plan,
    build_contest_tree_items,
    build_local_contest_tree_items,
    contest_name_from_url,
    create_session,
    iter_downloaded_igc_paths,
    selected_download_plan_items,
    selected_local_flight_paths,
)


class ContestDiscoveryWorker(QObject):
    finished = Signal(object, str)
    failed = Signal(str)

    def __init__(self, contest_url: str) -> None:
        super().__init__()
        self.contest_url = contest_url

    def run(self) -> None:
        try:
            session = create_session()
            response = session.get(self.contest_url, timeout=20)
            response.raise_for_status()
            parsed = urlparse(self.contest_url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            plan = build_contest_download_plan(self.contest_url, response.text, base, session)
            self.finished.emit(plan, contest_name_from_url(self.contest_url))
        except Exception as exc:
            self.failed.emit(f"Failed to discover contest: {exc}")


class ContestDownloadWorker(QObject):
    progress = Signal(int, int, str, str, int, float)
    finished = Signal(object, str, int, bool, int)
    failed = Signal(str)

    def __init__(self, contest_url: str, contest_name: str, selection: list[dict[str, str]]) -> None:
        super().__init__()
        self.contest_url = contest_url
        self.contest_name = contest_name
        self.selection = selection
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            session = create_session()
            base_dir = contest_download_dir(self.contest_name or "contest")

            lines: list[str] = []
            total = len(self.selection)
            if total == 0:
                self.finished.emit(lines, base_dir, total, False, len(lines))
                return

            def report_progress(result: dict) -> None:
                index = int(result["index"])
                item = next(item for item in self.selection if item.get("link") == result.get("link")) if result.get("link") else {"link": ""}
                if result["status"] == "ok":
                    line = f"{index}/{total} OK {result['path']}"
                    status_text = "OK"
                else:
                    line = f"{index}/{total} {result['status']}"
                    status_text = str(result["status"]).upper()
                lines.append(line)
                link_path = str(item.get("link") or result.get("link") or "").split("?", 1)[0].rstrip("/")
                label = os.path.basename(link_path) or link_path
                retry_count = int(result.get("retries", 0) or 0)
                elapsed = float(result.get("elapsed_seconds", 0.0) or 0.0)
                self.progress.emit(index, total, label, status_text, retry_count, elapsed)

            process_download_selection(
                session,
                self.contest_url,
                self.selection,
                base_dir=base_dir,
                cancel_callback=lambda: self._cancel_requested,
                progress_callback=report_progress,
            )

            if self._cancel_requested:
                self.finished.emit(lines, base_dir, total, True, len(lines))
                return

            self.finished.emit(lines, base_dir, total, False, len(lines))
        except Exception as exc:
            self.failed.emit(f"Download failed: {exc}")


class ContestAcquisitionWorker(QObject):
    contest_status = Signal(str, str, str)
    file_batch_started = Signal(str, int)
    progress = Signal(int, int, str, str, int, float)
    finished = Signal(bool, bool, int, int)

    def __init__(self, entries: list[dict[str, str]]) -> None:
        super().__init__()
        self.entries = [dict(entry) for entry in entries]
        self._cancel_requested = False
        self._pause_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def request_pause(self) -> None:
        self._pause_requested = True

    def run(self) -> None:
        completed = 0
        failed = 0
        paused = False

        for entry_index, entry in enumerate(self.entries):
            if self._cancel_requested:
                break

            contest_url = entry["url"]
            contest_name = entry["name"]
            self.contest_status.emit(contest_url, "running", "Discovering contest files")

            try:
                session = create_session()
                response = session.get(contest_url, timeout=20)
                response.raise_for_status()
                parsed = urlparse(contest_url)
                base = f"{parsed.scheme}://{parsed.netloc}"
                selection = build_contest_download_plan(contest_url, response.text, base, session)
                if not selection:
                    raise RuntimeError("No direct IGC download links were discovered.")

                self.file_batch_started.emit(contest_name, len(selection))
                def report_progress(result: dict) -> None:
                    link_path = str(result.get("link") or "").split("?", 1)[0].rstrip("/")
                    label = os.path.basename(link_path) or link_path
                    self.progress.emit(
                        int(result["index"]),
                        len(selection),
                        f"{contest_name}: {label}",
                        str(result.get("status") or "unknown").upper(),
                        int(result.get("retries", 0) or 0),
                        float(result.get("elapsed_seconds", 0.0) or 0.0),
                    )

                results = process_download_selection(
                    session,
                    contest_url,
                    selection,
                    base_dir=contest_download_dir(contest_name),
                    cancel_callback=lambda: self._cancel_requested,
                    progress_callback=report_progress,
                )

                if self._cancel_requested:
                    self.contest_status.emit(contest_url, "pending", "Cancelled; resume to continue")
                    break

                succeeded = sum(1 for result in results if result.get("status") == "ok")
                if succeeded == len(selection):
                    completed += 1
                    self.contest_status.emit(contest_url, "completed", f"Downloaded {succeeded} file(s)")
                else:
                    failed += 1
                    self.contest_status.emit(
                        contest_url,
                        "failed",
                        f"Downloaded {succeeded} of {len(selection)} file(s); retry via the queue",
                    )
            except Exception as exc:
                failed += 1
                self.contest_status.emit(contest_url, "failed", str(exc))

            if self._pause_requested:
                paused = entry_index < len(self.entries) - 1
                break

        self.finished.emit(self._cancel_requested, paused, completed, failed)


class DownloadController(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self._discovery_thread: QThread | None = None
        self._discovery_worker: ContestDiscoveryWorker | None = None
        self._download_thread: QThread | None = None
        self._download_worker: ContestDownloadWorker | None = None
        self._acquisition_thread: QThread | None = None
        self._acquisition_worker: ContestAcquisitionWorker | None = None
        self._acquisition_queue = ContestAcquisitionQueue()
        self._shutting_down = False
        self._cancel_requested = False
        self._render_acquisition_queue()

    def shutdown(self) -> None:
        self._shutting_down = True
        if self._acquisition_worker is not None:
            self._acquisition_worker.request_cancel()
        self._wait_for_thread(self._discovery_thread)
        self._wait_for_thread(self._download_thread)
        self._wait_for_thread(self._acquisition_thread)

    @staticmethod
    def _wait_for_thread(thread: QThread | None) -> None:
        if thread is None:
            return
        thread.quit()
        thread.wait()

    def update_download_button_label(self, item: QTreeWidgetItem | None = None) -> None:
        selected = item if item is not None else self.window.contest_results.currentItem()
        if selected is None:
            self.window.download_contest_button.setText("Download contest files")
            return

        kind = selected.data(0, Qt.ItemDataRole.UserRole)
        if kind == "class":
            self.window.download_contest_button.setText(f"Download {selected.text(0)}")
        elif kind == "day":
            self.window.download_contest_button.setText(f"Download {selected.text(0)}")
        elif kind == "link":
            self.window.download_contest_button.setText("Download flight")
        else:
            self.window.download_contest_button.setText("Download contest files")

    def selected_download_plan(self) -> list[dict[str, str]]:
        return selected_download_plan_items(self.window.contest_results.selectedItems(), self.window.contest_download_plan)

    def render_contest_tree(self, plan: list[dict[str, str]]) -> None:
        self.window.contest_results.clear()
        contest_root = build_contest_tree_items(self.window.contest_root_name, plan)[0]
        self.window.contest_results.addTopLevelItem(contest_root)
        self.window.contest_results.expandToDepth(0)
        self.window.contest_results.setCurrentItem(contest_root)

    def iter_downloaded_contest_paths(self) -> list[str]:
        return iter_downloaded_igc_paths(DOWNLOAD_DIR)

    def selected_local_flight_paths(self) -> list[str]:
        return selected_local_flight_paths(self.window.local_contests.selectedItems())

    def update_local_selection_label(self) -> None:
        selected_paths = self.selected_local_flight_paths()
        if not selected_paths:
            self.window.local_selection_label.setText("Selected: 0 flights")
            return
        count = len(selected_paths)
        label = "flight" if count == 1 else "flights"
        self.window.local_selection_label.setText(f"Selected: {count} {label}")

    def refresh_local_contest_tree(self) -> None:
        self.window.local_contests.clear()
        contest_paths = self.iter_downloaded_contest_paths()
        if not contest_paths:
            self.window.local_contests.addTopLevelItem(QTreeWidgetItem(["No downloaded contests available."]))
            return

        for contest_item in build_local_contest_tree_items(contest_paths):
            self.window.local_contests.addTopLevelItem(contest_item)

        self.window.local_contests.expandToDepth(0)
        self.update_local_selection_label()

    def open_selected_local_flights(self) -> None:
        file_paths = self.selected_local_flight_paths()
        if not file_paths:
            self.window.status_controller.no_downloaded_selection()
            return
        self.window.open_igc_files(file_paths)

    def cancel_download(self) -> None:
        if self._acquisition_worker is not None:
            self._acquisition_worker.request_cancel()
        elif self._download_worker is not None:
            self._cancel_requested = True
            self._download_worker.request_cancel()
        else:
            return
        self.window.set_download_busy(True, allow_cancel=False)
        self.window.status_controller.download_cancelling()

    def add_current_contest_to_queue(self) -> None:
        contest_url = self.window.contest_url_input.text().strip()
        try:
            added = self._acquisition_queue.add(contest_url, contest_name_from_url(contest_url))
        except (OSError, ValueError) as exc:
            self.window.status_controller.contest_message(str(exc))
            return
        self._render_acquisition_queue()
        message = "Contest added to acquisition queue." if added else "Contest is already in the acquisition queue."
        self.window.status_controller.contest_message(message)

    def remove_selected_queued_contests(self) -> None:
        selected_urls = {
            str(item.data(Qt.ItemDataRole.UserRole))
            for item in self.window.contest_acquisition_queue.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole)
        }
        if not selected_urls:
            return
        self._acquisition_queue.remove(selected_urls)
        self._render_acquisition_queue()

    def _render_acquisition_queue(self) -> None:
        table = self.window.contest_acquisition_queue
        table.setRowCount(0)
        for entry in self._acquisition_queue.entries:
            row = table.rowCount()
            table.insertRow(row)
            name_item = QTableWidgetItem(entry["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, entry["url"])
            name_item.setToolTip(entry["url"])
            status_item = QTableWidgetItem(entry["status"])
            status_item.setToolTip(entry["message"] or entry["url"])
            table.setItem(row, 0, name_item)
            table.setItem(row, 1, status_item)
        queue_busy = self._acquisition_thread is not None
        self.window.run_acquisition_queue_button.setEnabled(
            not queue_busy and bool(self._acquisition_queue.entries_to_run())
        )
        self.window.remove_queued_contests_button.setEnabled(not queue_busy and table.rowCount() > 0)

    def start_acquisition_queue(self) -> None:
        if self._acquisition_thread is not None:
            return
        entries = self._acquisition_queue.entries_to_run()
        if not entries:
            self.window.status_controller.contest_message("No pending or failed contests in the acquisition queue.")
            return

        self.window.download_log.clear()
        self.window.download_log.setVisible(True)
        self.window.download_log.appendPlainText(f"Starting serial acquisition of {len(entries)} contest(s)")
        self.window.download_queue.setVisible(True)
        self.window.download_queue.setRowCount(0)
        self.window.set_download_busy(True, allow_cancel=True)
        self.window.pause_acquisition_queue_button.setEnabled(True)
        self.window.status_controller.contest_message(f"Acquiring {len(entries)} queued contest(s)")

        thread = QThread(self.window)
        worker = ContestAcquisitionWorker(entries)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.contest_status.connect(self._on_acquisition_contest_status)
        worker.file_batch_started.connect(self._on_acquisition_file_batch_started)
        worker.progress.connect(self._on_download_progress)
        worker.finished.connect(self._on_acquisition_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._cleanup_acquisition_thread)

        self._acquisition_thread = thread
        self._acquisition_worker = worker
        thread.start()

    def pause_acquisition_queue(self) -> None:
        if self._acquisition_worker is None:
            return
        self._acquisition_worker.request_pause()
        self.window.pause_acquisition_queue_button.setEnabled(False)
        self.window.status_controller.contest_message("Queue will pause after the current contest finishes.")

    def _on_acquisition_contest_status(self, url: str, status: str, message: str) -> None:
        if self._shutting_down:
            return
        self._acquisition_queue.set_status(url, status, message)
        self._render_acquisition_queue()
        self.window.download_log.appendPlainText(f"{status.upper()}: {message or url}")

    def _on_acquisition_file_batch_started(self, contest_name: str, total: int) -> None:
        if self._shutting_down:
            return
        self.window.status_controller.start_download_progress(total)
        self.window.download_log.appendPlainText(f"{contest_name}: downloading {total} file(s) serially")

    def _on_acquisition_finished(self, cancelled: bool, paused: bool, completed: int, failed: int) -> None:
        if self._shutting_down:
            return
        self.window.set_download_busy(False)
        self.window.pause_acquisition_queue_button.setEnabled(False)
        self.refresh_local_contest_tree()
        if cancelled:
            message = f"Queue stopped. {completed} contest(s) completed; unfinished contests remain queued."
        elif paused:
            message = f"Queue paused. {completed} contest(s) completed; resume to continue."
        else:
            message = f"Queue finished: {completed} completed, {failed} failed."
        self.window.status_controller.contest_message(message)

    def _cleanup_acquisition_thread(self) -> None:
        if self._acquisition_thread is not None:
            self._acquisition_thread.deleteLater()
        self.window.status_controller.finish_download_progress()
        self._acquisition_thread = None
        self._acquisition_worker = None

    def start_discover_contest(self) -> None:
        contest_url = self.window.contest_url_input.text().strip()
        if not contest_url or "soaringspot.com" not in contest_url:
            self.window.contest_results.clear()
            self.window.contest_results.addTopLevelItem(QTreeWidgetItem(["Enter a valid SoaringSpot contest URL first."]))
            self.window.download_contest_button.setEnabled(False)
            return
        if self._discovery_thread is not None:
            return

        self.window.discover_contest_button.setEnabled(False)
        self.window.download_contest_button.setEnabled(False)
        self.window.status_controller.discovering_contest()

        thread = QThread(self.window)
        worker = ContestDiscoveryWorker(contest_url)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_discovery_finished)
        worker.failed.connect(self._on_discovery_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._cleanup_discovery_thread)

        self._discovery_thread = thread
        self._discovery_worker = worker
        thread.start()

    def _on_discovery_finished(self, plan: list[dict[str, str]], root_name: str) -> None:
        if self._shutting_down:
            return
        self.window.discover_contest_button.setEnabled(True)
        self.window.contest_download_plan = plan
        self.window.contest_root_name = root_name
        if not plan:
            self.window.contest_results.clear()
            self.window.contest_results.addTopLevelItem(QTreeWidgetItem(["No direct IGC download links were discovered for that contest page."]))
            self.window.download_contest_button.setEnabled(False)
            self.window.status_controller.no_contest_links()
            return

        self.render_contest_tree(plan)
        self.window.download_contest_button.setEnabled(True)
        self.window.status_controller.contest_discovered(len(plan))

    def _on_discovery_failed(self, message: str) -> None:
        if self._shutting_down:
            return
        self.window.discover_contest_button.setEnabled(True)
        self.window.contest_results.clear()
        self.window.contest_results.addTopLevelItem(QTreeWidgetItem([message]))
        self.window.contest_download_plan = []
        self.window.download_contest_button.setEnabled(False)
        self.window.status_controller.contest_message(message)

    def _cleanup_discovery_thread(self) -> None:
        if self._discovery_thread is not None:
            self._discovery_thread.deleteLater()
        self._discovery_thread = None
        self._discovery_worker = None

    def start_download_contest(self) -> None:
        if not self.window.contest_download_plan:
            self.window.contest_results.clear()
            self.window.contest_results.addTopLevelItem(QTreeWidgetItem(["Discover a contest first before downloading files."]))
            return

        contest_url = self.window.contest_url_input.text().strip()
        if not contest_url:
            self.window.contest_results.clear()
            self.window.contest_results.addTopLevelItem(QTreeWidgetItem(["No contest URL is available to download from."]))
            return

        if self._download_thread is not None:
            return

        selection = self.selected_download_plan()
        if not selection:
            selection = list(self.window.contest_download_plan)

        total = len(selection)
        self._cancel_requested = False
        self.window.download_log.clear()
        self.window.download_log.setVisible(True)
        self.window.download_log.appendPlainText(f"Starting download: {total} file(s)")
        self.window.download_queue.setVisible(True)
        self.window.download_queue.setRowCount(0)
        self.window.discover_contest_button.setEnabled(False)
        self.window.set_download_busy(True, allow_cancel=True)
        self.window.status_controller.start_download_progress(total)

        thread = QThread(self.window)
        worker = ContestDownloadWorker(contest_url, self.window.contest_root_name or "contest", selection)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_download_progress)
        worker.finished.connect(self._on_download_finished)
        worker.failed.connect(self._on_download_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._cleanup_download_thread)

        self._download_thread = thread
        self._download_worker = worker
        thread.start()

    def _on_download_progress(self, index: int, total: int, line: str, status: str, retries: int, elapsed_seconds: float) -> None:
        if self._shutting_down:
            return
        self.window.status_controller.update_download_progress(index, total, line)
        self.window.download_log.setVisible(True)
        self.window.download_log.appendPlainText(f"{index}/{total} {line} | status={status} | retries={retries} | time={elapsed_seconds:.1f}s")

        row = self.window.download_queue.rowCount()
        self.window.download_queue.insertRow(row)
        self.window.download_queue.setItem(row, 0, QTableWidgetItem(line))
        self.window.download_queue.setItem(row, 1, QTableWidgetItem(status))
        self.window.download_queue.setItem(row, 2, QTableWidgetItem(str(retries)))
        self.window.download_queue.setItem(row, 3, QTableWidgetItem(f"{elapsed_seconds:.1f}s"))
        self.window.download_queue.setVisible(True)
        self.window.download_queue.scrollToBottom()

    def _on_download_finished(self, lines: list[str], base_dir: str, total: int, cancelled: bool, completed: int) -> None:
        if self._shutting_down:
            return
        self.window.set_download_busy(False)
        self.window.discover_contest_button.setEnabled(True)
        self.window.contest_results.clear()
        for line in lines:
            self.window.contest_results.addTopLevelItem(QTreeWidgetItem([line]))
        self.refresh_local_contest_tree()
        if cancelled or self._cancel_requested:
            self.window.status_controller.download_cancelled(completed, total)
            self._cancel_requested = False
            return
        self.window.status_controller.download_completed(total)
        QMessageBox.information(self.window, "Download complete", f"Downloaded {total} flight(s) to {base_dir}")

    def _on_download_failed(self, message: str) -> None:
        if self._shutting_down:
            return
        self.window.set_download_busy(False)
        self.window.discover_contest_button.setEnabled(True)
        self.window.contest_results.clear()
        self.window.contest_results.addTopLevelItem(QTreeWidgetItem([message]))
        self.window.status_controller.contest_message(message)

    def _cleanup_download_thread(self) -> None:
        if self._download_thread is not None:
            self._download_thread.deleteLater()
        self.window.status_controller.finish_download_progress()
        self._download_thread = None
        self._download_worker = None
        self._cancel_requested = False