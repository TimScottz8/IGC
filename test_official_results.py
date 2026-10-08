import unittest

from official_results import (
    contest_id_from_igc_path,
    parse_daily_results,
)

HTML = """
<table>
<thead><tr><th>#</th><th>CN</th><th>Contestant</th><th>Start</th><th>Finish</th><th>Points</th></tr></thead>
<tbody>
<tr><td>1.</td><td>HG</td><td>A Pilot</td><td data-value="x">13:50:56</td><td>16:45:04</td><td>932</td></tr>
<tr><td>2.</td><td>ADX</td><td>B Pilot</td><td>14:03:57</td><td></td><td>301</td></tr>
<tr><td>3.</td><td>XX</td><td>C Pilot</td><td></td><td></td><td>0</td></tr>
</tbody>
</table>
"""


class OfficialResultsTests(unittest.TestCase):
    def test_parse_daily_results_reads_start_and_finish_by_header(self):
        self.assertEqual(
            parse_daily_results(HTML),
            {
                "HG": {"start": "13:50:56", "finish": "16:45:04"},
                "ADX": {"start": "14:03:57", "finish": None},
                "XX": {"start": None, "finish": None},
            },
        )

    def test_page_without_results_table_gives_nothing(self):
        self.assertEqual(parse_daily_results("<p>no table</p>"), {})

    def test_contest_id_is_the_part_after_the_class_day_prefix(self):
        self.assertEqual(contest_id_from_igc_path("/x/659_HG.igc"), "HG")
        self.assertEqual(contest_id_from_igc_path("/x/HG.igc"), "HG")


if __name__ == "__main__":
    unittest.main()
