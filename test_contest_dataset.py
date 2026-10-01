from __future__ import annotations

from pathlib import Path

from contest_dataset import ContestDataset
from contest_queue import ContestAcquisitionQueue
from qt_helpers import build_contest_download_plan, download_single_candidate
from qt_controllers import ContestAcquisitionWorker


class FakeResponse:
    def __init__(self, status_code, headers=None, payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.payload = payload or b"fake igc data"
        self.url = "https://example.com/test.igc"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def iter_content(self, chunk_size):
        yield self.payload


class FakeSession:
    def __init__(self):
        self.calls = 0
        self.headers = {}

    def get(self, url, timeout=None, stream=None, headers=None):
        self.calls += 1
        if self.calls == 1:
            return FakeResponse(429, {"content-type": "text/html"}, b"retry")
        return FakeResponse(200, {"content-type": "application/vnd.flight+igc", "content-disposition": 'attachment; filename="test.igc"'}, b"igc")


def test_dataset_loads_multiple_contests(tmp_path):
    first = tmp_path / "Open Standard 15M Nationals 2026 Husbands Bosworth 2026"
    second = tmp_path / "Open Standard 15M Nationals 2027 Husbands Bosworth 2027"

    (first / "15 Metre" / "2026-08-08").mkdir(parents=True)
    (second / "15 Metre" / "2027-08-09").mkdir(parents=True)

    (first / "15 Metre" / "2026-08-08" / "688_10.igc").write_text("fake igc")
    (first / "15 Metre" / "2026-08-08" / "688_9.igc").write_text("fake igc")
    (second / "15 Metre" / "2027-08-09" / "777_10.igc").write_text("fake igc")

    dataset = ContestDataset.from_contest_paths([str(first), str(second)])

    assert len(dataset.records) == 3
    assert {record.year for record in dataset.records} == {2026, 2027}
    assert {record.contest_name for record in dataset.records} == {
        "Open Standard 15M Nationals 2026 Husbands Bosworth 2026",
        "Open Standard 15M Nationals 2027 Husbands Bosworth 2027",
    }


def test_dataset_filters_by_year_and_class(tmp_path):
    contest = tmp_path / "Open Standard 15M Nationals 2026 Husbands Bosworth 2026"
    (contest / "15 Metre" / "2026-08-08").mkdir(parents=True)
    (contest / "20 Metre" / "2026-08-09").mkdir(parents=True)

    (contest / "15 Metre" / "2026-08-08" / "A.igc").write_text("fake igc")
    (contest / "15 Metre" / "2026-08-08" / "B.igc").write_text("fake igc")
    (contest / "20 Metre" / "2026-08-09" / "C.igc").write_text("fake igc")

    dataset = ContestDataset.from_contest_paths([str(contest)])

    filtered = dataset.filter_by_year(2026).filter_by_class("15 Metre")
    assert len(filtered.records) == 2
    assert all(record.class_name == "15 Metre" for record in filtered.records)

    filtered_2 = dataset.filter_by_class("20 Metre")
    assert len(filtered_2.records) == 1
    assert filtered_2.records[0].day == "2026-08-09"


def test_contest_acquisition_queue_deduplicates_and_recovers_interrupted_run(tmp_path):
    queue_path = tmp_path / "contest_queue.json"
    queue = ContestAcquisitionQueue(queue_path)

    first_url = "https://www.soaringspot.com/en_gb/contest-one/"
    second_url = "https://www.soaringspot.com/en_gb/contest-two/"
    assert queue.add(first_url, "Contest One") is True
    assert queue.add(first_url.rstrip("/"), "Duplicate") is False
    assert queue.add(second_url, "Contest Two") is True
    queue.set_status(first_url, "running")
    queue.set_status(second_url, "completed")

    restored = ContestAcquisitionQueue(queue_path)

    assert [entry["status"] for entry in restored.entries] == ["pending", "completed"]
    assert [entry["name"] for entry in restored.entries_to_run()] == ["Contest One"]


def test_contest_acquisition_worker_processes_contests_serially(monkeypatch, tmp_path):
    class ContestPageResponse:
        text = "contest page"

        @staticmethod
        def raise_for_status():
            return None

    class Session:
        @staticmethod
        def get(url, timeout=None):
            return ContestPageResponse()

    contest_urls = [
        "https://www.soaringspot.com/en_gb/contest-one/",
        "https://www.soaringspot.com/en_gb/contest-two/",
    ]
    download_order = []
    statuses = []
    finished = []
    selection = [{"class_name": "15 Metre", "day": "2026-08-08", "link": "https://example.com/flight.igc"}]

    monkeypatch.setattr("qt_controllers.create_session", Session)
    monkeypatch.setattr("qt_controllers.build_contest_download_plan", lambda *args: selection)
    monkeypatch.setattr("qt_controllers.contest_download_dir", lambda name: str(tmp_path / name))

    def process_download_selection(
        session,
        contest_url,
        selected,
        *,
        base_dir,
        cancel_callback,
        progress_callback=None,
    ):
        download_order.append(contest_url)
        result = {"index": 1, "link": selected[0]["link"], "status": "ok", "retries": 0, "elapsed_seconds": 0.1}
        if progress_callback is not None:
            progress_callback(result)
        return [result]

    monkeypatch.setattr("qt_controllers.process_download_selection", process_download_selection)

    worker = ContestAcquisitionWorker([
        {"url": url, "name": name}
        for url, name in zip(contest_urls, ["Contest One", "Contest Two"], strict=True)
    ])
    worker.contest_status.connect(lambda url, status, message: statuses.append((url, status)))
    worker.finished.connect(lambda *args: finished.append(args))
    worker.run()

    assert download_order == contest_urls
    assert [status for _, status in statuses if status == "completed"] == ["completed", "completed"]
    assert finished == [(False, False, 2, 0)]


def test_contest_acquisition_worker_pauses_between_contests(monkeypatch, tmp_path):
    class ContestPageResponse:
        text = "contest page"

        @staticmethod
        def raise_for_status():
            return None

    class Session:
        @staticmethod
        def get(url, timeout=None):
            return ContestPageResponse()

    contest_urls = [
        "https://www.soaringspot.com/en_gb/contest-one/",
        "https://www.soaringspot.com/en_gb/contest-two/",
    ]
    download_order = []
    finished = []
    selection = [{"class_name": "15 Metre", "day": "2026-08-08", "link": "https://example.com/flight.igc"}]

    monkeypatch.setattr("qt_controllers.create_session", Session)
    monkeypatch.setattr("qt_controllers.build_contest_download_plan", lambda *args: selection)
    monkeypatch.setattr("qt_controllers.contest_download_dir", lambda name: str(tmp_path / name))

    def process_download_selection(
        session,
        contest_url,
        selected,
        *,
        base_dir,
        cancel_callback,
        progress_callback=None,
    ):
        download_order.append(contest_url)
        result = {"index": 1, "link": selected[0]["link"], "status": "ok", "retries": 0, "elapsed_seconds": 0.1}
        if progress_callback is not None:
            progress_callback(result)
        return [result]

    monkeypatch.setattr("qt_controllers.process_download_selection", process_download_selection)

    worker = ContestAcquisitionWorker([
        {"url": url, "name": name}
        for url, name in zip(contest_urls, ["Contest One", "Contest Two"], strict=True)
    ])
    worker.request_pause()
    worker.finished.connect(lambda *args: finished.append(args))
    worker.run()

    assert download_order == contest_urls[:1]
    assert finished == [(False, True, 1, 0)]


def test_download_single_candidate_retries_after_429(tmp_path):
    session = FakeSession()
    result = download_single_candidate(
        session,
        "https://example.com/contest",
        "https://example.com/file.igc",
        str(tmp_path),
        max_retries=2,
    )

    assert result["status"] == "ok"
    assert session.calls == 2
    assert (tmp_path / "test.igc").exists()


def test_discovery_plan_handles_real_soaringspot_page():
    url = "https://www.soaringspot.com/en_gb/wgc2021-club-std-15m-montlucon-gueret-2021/"
    response = __import__("requests").get(url, timeout=20)
    assert response.status_code == 200
    plan = build_contest_download_plan(url, response.text, "https://www.soaringspot.com")
    assert isinstance(plan, list)
    assert len(plan) >= 1


def test_downloads_listing_page_is_not_treated_as_igc_candidate():
    html = '''<html><body><a href="/en_gb/wgc2021-club-std-15m-montlucon-gueret-2021/downloads">Downloads</a><a href="https://example.com/flight.igc">IGC</a></body></html>'''
    from download_helpers import direct_candidate_links, find_candidates

    direct = direct_candidate_links(html, "https://www.soaringspot.com")
    candidates = find_candidates(html, "https://www.soaringspot.com")

    assert all("/downloads" not in link.lower() for link in direct)
    assert all("/downloads" not in link.lower() for link in candidates)
    assert any(link.lower().endswith(".igc") for link in candidates)


def test_numeric_fragment_ids_are_rejected_as_non_flight_candidates():
    html = '''<html><body><a href="https://www.soaringspot.com/en_gb/download-contest-flight/3377-6981419117">Bogus</a><a href="https://archive.soaringspot.com/contest/033/3377/flights/6658/6981419117.igc">Flight</a></body></html>'''
    from download_helpers import direct_candidate_links, find_candidates

    direct = direct_candidate_links(html, "https://www.soaringspot.com")
    candidates = find_candidates(html, "https://www.soaringspot.com")

    assert all("download-contest-flight/3377-6981419117" not in link.lower() for link in direct)
    assert all("download-contest-flight/3377-6981419117" not in link.lower() for link in candidates)
    assert any(link.lower().endswith(".igc") for link in candidates)


def test_encoded_result_download_igc_links_are_discovered_contextually():
    from download_helpers import find_candidates

    embedded_anchor = (
        "&#x20;&lt;a&#x20;target&#x3D;&quot;_blank&quot;&#x20;"
        "href&#x3D;&quot;&#x2F;en_gb&#x2F;download-contest-flight&#x2F;4814-9754902540?dl=1&quot;&gt;"
        "Download&#x20;IGC&lt;&#x2F;a&gt;"
    )
    html = (
        f'<div data-content="{embedded_anchor}"></div>'
        '<a href="/en_gb/download-contest-flight/3377-6981419117">Bogus</a>'
    )

    candidates = find_candidates(html, "https://www.soaringspot.com")

    assert "https://www.soaringspot.com/en_gb/download-contest-flight/4814-9754902540" in candidates
    assert all("3377-6981419117" not in link for link in candidates)


def test_contest_plan_follows_class_and_daily_result_links():
    class_url = "https://www.soaringspot.com/en_gb/57-hww/results/15m"
    day_url = f"{class_url}/task-5-on-2025-05-31/daily"
    embedded_anchor = (
        "&#x20;&lt;a&#x20;target&#x3D;&quot;_blank&quot;&#x20;"
        "href&#x3D;&quot;&#x2F;en_gb&#x2F;download-contest-flight&#x2F;4814-9754902540&quot;&gt;"
        "&lt;i&gt;&lt;&#x2F;i&gt;&amp;nbsp&#x3B;Download&#x20;IGC&lt;&#x2F;a&gt;"
    )
    pages = {
        "https://www.soaringspot.com/en_gb/57-hww/": (
            '<a href="/en_gb/57-hww/results/15m">15m</a>'
        ),
        class_url: f'<a href="{day_url}">5.</a>',
        day_url: f'<div data-content="{embedded_anchor}"></div>',
    }

    class Response:
        def __init__(self, text):
            self.text = text

        @staticmethod
        def raise_for_status():
            return None

    class Session:
        def get(self, url, timeout=None):
            return Response(pages[url])

    plan = build_contest_download_plan(
        "https://www.soaringspot.com/en_gb/57-hww/",
        pages["https://www.soaringspot.com/en_gb/57-hww/"],
        "https://www.soaringspot.com",
        Session(),
    )

    assert plan == [{
        "class_name": "15m",
        "day": "2025-05-31",
        "link": "https://www.soaringspot.com/en_gb/download-contest-flight/4814-9754902540",
    }]


def test_host_cooldown_blocks_throttled_requests():
    from download_helpers import get_host_cooldown_remaining, register_host_cooldown

    register_host_cooldown("https://www.soaringspot.com/test.igc", cooldown_seconds=30.0)
    remaining = get_host_cooldown_remaining("https://www.soaringspot.com/test.igc")

    assert remaining > 0.0
    assert remaining <= 30.0


def test_download_service_turns_selection_into_queue_results(tmp_path):
    from contest_service import process_download_selection

    selection = [
        {"class_name": "15 Metre", "day": "2026-08-08", "link": "https://example.com/file.igc"},
        {"class_name": "15 Metre", "day": "2026-08-09", "link": "https://example.com/file2.igc"},
    ]

    session = FakeSession()
    results = process_download_selection(
        session,
        "https://example.com/contest",
        selection,
        base_dir=str(tmp_path),
        cancel_callback=lambda: False,
    )

    assert len(results) == 2
    assert {item["status"] for item in results} == {"ok"}
    assert all(item["path"] is not None for item in results)


def test_download_service_reports_each_completed_file_before_returning(tmp_path):
    from contest_service import process_download_selection

    class SuccessfulSession:
        headers = {}

        @staticmethod
        def get(url, timeout=None, stream=None, headers=None):
            response = FakeResponse(
                200,
                {
                    "content-type": "application/vnd.flight+igc",
                    "content-disposition": 'attachment; filename="test.igc"',
                },
                b"igc",
            )
            response.url = url
            return response

    selection = [
        {"class_name": "15 Metre", "day": "2026-08-08", "link": "https://example.com/one.igc"},
        {"class_name": "15 Metre", "day": "2026-08-09", "link": "https://example.com/two.igc"},
    ]
    progress = []

    results = process_download_selection(
        SuccessfulSession(),
        "https://example.com/contest",
        selection,
        base_dir=str(tmp_path),
        progress_callback=progress.append,
    )

    assert [result["index"] for result in progress] == [1, 2]
    assert [result["status"] for result in progress] == ["ok", "ok"]
    assert len(results) == 2
