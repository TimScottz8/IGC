from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from download_helpers import DOWNLOAD_DIR, sanitize
from qt_helpers import download_single_candidate


def contest_download_dir(contest_name: str | None) -> str:
    """Return the download root directory for a contest."""
    base_dir = os.path.join(DOWNLOAD_DIR, sanitize(contest_name or "contest"))
    os.makedirs(base_dir, exist_ok=True)
    return base_dir


def process_download_selection(
    session,
    contest_url: str,
    selection: list[dict[str, str]],
    *,
    base_dir: str | None = None,
    cancel_callback=None,
) -> list[dict[str, str | int | float | None]]:
    """Process a selection and return per-item download results in index order."""
    if cancel_callback is None:
        cancel_callback = lambda: False

    total = len(selection)
    if total == 0:
        return []

    root_dir = base_dir or contest_download_dir("contest")
    result_by_index: dict[int, dict[str, str | int | float | None]] = {}

    def worker_task(index: int, item: dict[str, str]) -> dict[str, str | int | float | None]:
        if cancel_callback():
            return {
                "index": index,
                "class_name": str(item.get("class_name") or "contest"),
                "day": str(item.get("day") or "all"),
                "link": str(item.get("link") or ""),
                "status": "cancelled",
                "path": None,
                "retries": 0,
                "elapsed_seconds": 0.0,
            }

        out_dir = os.path.join(root_dir, sanitize(str(item.get("class_name") or "contest")), sanitize(str(item.get("day") or "all")))
        os.makedirs(out_dir, exist_ok=True)
        result = download_single_candidate(session, contest_url, str(item.get("link") or ""), out_dir)
        result["index"] = index
        result["class_name"] = str(item.get("class_name") or "contest")
        result["day"] = str(item.get("day") or "all")
        return result

    with ThreadPoolExecutor(max_workers=1) as pool:
        future_map = {
            pool.submit(worker_task, index, item): item
            for index, item in enumerate(selection, start=1)
        }
        for future in as_completed(future_map):
            if cancel_callback():
                break
            result = future.result()
            result_by_index[int(result["index"])] = result

    ordered = []
    for index in range(1, total + 1):
        if index in result_by_index:
            ordered.append(result_by_index[index])
    return ordered
