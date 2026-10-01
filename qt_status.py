from __future__ import annotations

import os


class StatusController:
    def __init__(self, status_label, flight_progress, download_progress) -> None:
        self.status_label = status_label
        self.flight_progress = flight_progress
        self.download_progress = download_progress

    def set_text(self, text: str) -> None:
        self.status_label.setText(text)

    def waiting_for_file(self) -> None:
        self.set_text("Status: waiting for file")

    def no_downloaded_selection(self) -> None:
        self.set_text("Status: no downloaded contest flights selected")

    def discovering_contest(self) -> None:
        self.set_text("Status: discovering contest flight links...")

    def no_contest_links(self) -> None:
        self.set_text("Status: no contest flight links discovered")

    def contest_discovered(self, count: int) -> None:
        self.set_text(f"Status: discovered {count} contest flight links")

    def contest_message(self, message: str) -> None:
        self.set_text(f"Status: {message}")

    def start_download_progress(self, total: int) -> None:
        self.download_progress.setVisible(True)
        self.download_progress.setRange(0, total)
        self.download_progress.setValue(0)
        self.set_text(f"Status: downloading {total} contest entries")

    def update_download_progress(self, index: int, total: int, label: str | None = None) -> None:
        self.download_progress.setRange(0, total)
        self.download_progress.setValue(index)
        if label:
            self.set_text(f"Status: downloading {index} / {total} contest entries: {label}")
        else:
            self.set_text(f"Status: downloading {index} / {total} contest entries")

    def finish_download_progress(self) -> None:
        self.download_progress.setVisible(False)

    def download_completed(self, total: int) -> None:
        self.set_text(f"Status: downloaded {total} contest entries")

    def download_cancelling(self) -> None:
        self.set_text("Status: cancelling contest download after current file...")

    def download_cancelled(self, completed: int, total: int) -> None:
        self.set_text(f"Status: cancelled contest download after {completed} / {total} entries")

    def start_flight_progress(self, total: int, file_path: str | None = None) -> None:
        self.flight_progress.setRange(0, total)
        self.flight_progress.setValue(0)
        self.flight_progress.setVisible(True)
        if file_path:
            self.set_text(f"Status: loading 0 / {total} flight(s): {os.path.basename(file_path)}")
        else:
            self.set_text(f"Status: loading {total} flight(s)...")

    def update_flight_progress(self, index: int, total: int, file_path: str | None = None) -> None:
        self.flight_progress.setRange(0, total)
        self.flight_progress.setValue(index)
        if file_path:
            self.set_text(f"Status: loading {index} / {total} flight(s): {os.path.basename(file_path)}")
        else:
            self.set_text(f"Status: loading {index} / {total} flight(s)...")

    def finish_flight_progress(self) -> None:
        self.flight_progress.setVisible(False)
        self.flight_progress.setValue(0)

    def flight_cancelling(self) -> None:
        self.set_text("Status: cancelling flight loading after current file...")

    def flight_cancelled(self, completed: int, total: int) -> None:
        self.set_text(f"Status: cancelled flight loading after {completed} / {total} flight(s)")

    def ready_to_view(self, count: int) -> None:
        if count:
            self.set_text(f"Status: ready to view {count} flight(s)")
        else:
            self.no_valid_flights()

    def flight_loading_in_progress(self) -> None:
        self.set_text("Status: flight loading already in progress")

    def no_valid_flights(self) -> None:
        self.set_text("Status: no valid flights were loaded")

    def loading_file(self) -> None:
        self.set_text("Status: loading file...")

    def parsed_file_invalid(self, file_path: str | None = None) -> None:
        if file_path:
            self.set_text(f"Status: parsed file is marked invalid ({file_path})")
        else:
            self.set_text("Status: parsed file is marked invalid")

    def no_valid_fixes(self) -> None:
        self.set_text("Status: no valid fixes found")

    def rendered_static_track(self, fix_count: int) -> None:
        self.set_text(f"Status: rendered static track ({fix_count} fixes)")

    def rendered_active_flights(self, count: int, file_path: str) -> None:
        self.set_text(f"Status: rendered {count} active flights; selected {os.path.basename(file_path)}")

    def render_failed(self, exc: Exception) -> None:
        self.set_text(f"Status: failed to render track ({exc})")

    def playback_complete(self, current: int, total: int) -> None:
        self.set_text(f"Status: complete ({current} / {total})")

    def playback_frame(self, current: int, total: int) -> None:
        self.set_text(f"Status: frame {current} / {total}")
