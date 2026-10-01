from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from download_helpers import DOWNLOAD_DIR, canonical_url


QUEUE_SCHEMA_VERSION = 1
QUEUE_STATUSES = {"pending", "running", "completed", "failed"}


class ContestAcquisitionQueue:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or Path(DOWNLOAD_DIR) / ".contest_acquisition_queue.json")
        self.entries: list[dict[str, str]] = []
        self._load()

    @staticmethod
    def normalize_url(url: str) -> str:
        parsed = urlparse(str(url).strip())
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme.lower() not in {"http", "https"} or not (
            hostname == "soaringspot.com" or hostname.endswith(".soaringspot.com")
        ):
            raise ValueError("Enter a valid SoaringSpot contest URL.")

        path = parsed.path.rstrip("/")
        normalized = urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))
        return canonical_url(normalized)

    def _load(self) -> None:
        if not self.path.exists():
            return

        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != QUEUE_SCHEMA_VERSION:
            raise ValueError("Unsupported contest queue schema version.")

        recovered_running = False
        for raw_entry in payload.get("contests", []):
            url = self.normalize_url(raw_entry["url"])
            status = str(raw_entry.get("status", "pending"))
            if status not in QUEUE_STATUSES:
                status = "pending"
            if status == "running":
                status = "pending"
                recovered_running = True
            self.entries.append({
                "url": url,
                "name": str(raw_entry.get("name") or url),
                "status": status,
                "message": str(raw_entry.get("message") or ""),
            })

        if recovered_running:
            self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {"schema_version": QUEUE_SCHEMA_VERSION, "contests": self.entries}
        temporary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary_path, self.path)

    def add(self, url: str, name: str) -> bool:
        normalized_url = self.normalize_url(url)
        if any(entry["url"] == normalized_url for entry in self.entries):
            return False
        self.entries.append({
            "url": normalized_url,
            "name": str(name).strip() or normalized_url,
            "status": "pending",
            "message": "",
        })
        self.save()
        return True

    def set_status(self, url: str, status: str, message: str = "") -> None:
        if status not in QUEUE_STATUSES:
            raise ValueError(f"Unknown contest queue status: {status}")
        normalized_url = self.normalize_url(url)
        for entry in self.entries:
            if entry["url"] == normalized_url:
                entry["status"] = status
                entry["message"] = str(message)
                self.save()
                return
        raise KeyError(normalized_url)

    def entries_to_run(self) -> list[dict[str, str]]:
        return [dict(entry) for entry in self.entries if entry["status"] in {"pending", "failed"}]

    def remove(self, urls: set[str]) -> None:
        normalized_urls = {self.normalize_url(url) for url in urls}
        self.entries = [entry for entry in self.entries if entry["url"] not in normalized_urls]
        self.save()