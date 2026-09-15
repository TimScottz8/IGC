from __future__ import annotations

import os
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QTreeWidgetItem

from download_helpers import DOWNLOAD_DIR, sanitize
from qt_helpers import (
    build_contest_download_plan,
    build_contest_tree_items,
    build_local_contest_tree_items,
    contest_name_from_url,
    create_session,
    download_single_candidate,
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
    progress = Signal(int, int, str)
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
            base_dir = os.path.join(DOWNLOAD_DIR, sanitize(self.contest_name or "contest"))
            os.makedirs(base_dir, exist_ok=True)

            lines: list[str] = []
            total = len(self.selection)
            for index, item in enumerate(self.selection, start=1):
                if self._cancel_requested:
                    self.finished.emit(lines, base_dir, total, True, len(lines))
                    return
                out_dir = os.path.join(base_dir, sanitize(str(item["class_name"])), sanitize(str(item["day"])))
                os.makedirs(out_dir, exist_ok=True)
                result = download_single_candidate(session, self.contest_url, item["link"], out_dir)
                if result["status"] == "ok":
                    line = f"{index}/{total} OK {result['path']}"
                else:
                    line = f"{index}/{total} {result['status']}"
                lines.append(line)
                link_path = str(item["link"]).split("?", 1)[0].rstrip("/")
                label = os.path.basename(link_path) or link_path
                self.progress.emit(index, total, label)

            self.finished.emit(lines, base_dir, total, False, len(lines))
        except Exception as exc:
            self.failed.emit(f"Download failed: {exc}")


class DownloadController(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self._discovery_thread: QThread | None = None
        self._discovery_worker: ContestDiscoveryWorker | None = None
        self._download_thread: QThread | None = None
        self._download_worker: ContestDownloadWorker | None = None
        self._shutting_down = False
        self._cancel_requested = False

    def shutdown(self) -> None:
        self._shutting_down = True
        self._wait_for_thread(self._discovery_thread)
        self._wait_for_thread(self._download_thread)

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
        if self._download_worker is None:
            return
        self._cancel_requested = True
        self._download_worker.request_cancel()
        self.window.set_download_busy(True, allow_cancel=False)
        self.window.status_controller.download_cancelling()

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

    def _on_download_progress(self, index: int, total: int, line: str) -> None:
        if self._shutting_down:
            return
        self.window.status_controller.update_download_progress(index, total, line)

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