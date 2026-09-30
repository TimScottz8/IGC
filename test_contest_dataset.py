from __future__ import annotations

from pathlib import Path

from contest_dataset import ContestDataset
from qt_helpers import build_contest_download_plan, download_single_candidate


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


def test_host_cooldown_blocks_throttled_requests():
    from download_helpers import get_host_cooldown_remaining, register_host_cooldown

    register_host_cooldown("https://www.soaringspot.com/test.igc", cooldown_seconds=30.0)
    remaining = get_host_cooldown_remaining("https://www.soaringspot.com/test.igc")

    assert remaining > 0.0
    assert remaining <= 30.0
