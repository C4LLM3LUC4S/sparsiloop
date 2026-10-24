import copy
from html.parser import HTMLParser
import math
import unittest

from event_control_lab.planned_report import selection_run_details


class Rows(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.rows, self.current, self.cell = [], None, None
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.current = []
        elif tag == "td":
            self.cell = []

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag == "td":
            self.current.append("".join(self.cell))
            self.cell = None
        elif tag == "tr" and self.current:
            self.rows.append(self.current)


def record(values):
    return {"spec": {"rmse_limit": 0.4},
            "selection_summaries": [{"id": "absolute-1", "policy": "absolute", "threshold": 0.2}],
            "selection_runs": [{"candidate_id": "absolute-1", "seed": seed,
                                "run": {"status": status, "metrics": {"position_rmse": value},
                                        "packets": {"attempted": 2}, "error": error}}
                               for seed, status, value, error in values]}


class SelectionRunEvidenceTests(unittest.TestCase):
    def test_reader_can_locate_exceeding_failed_and_missing_runs_without_csv(self):
        saved = record([(3001, "complete", 0.2, None), (3003, "complete", 0.4449616255473971, None),
                        (3004, "plant_error", None, "<script>original cause</script>"),
                        (3005, "complete", None, None)])
        original = copy.deepcopy(saved)
        source = selection_run_details(saved)
        rows = {row[0]: row for row in Rows(source).rows}
        self.assertEqual(rows["3003"][2:4], ["0.4449616255473971", "误差超标"])
        self.assertEqual(rows["3004"][1:4], ["模型出错", "无法计算", "未完整结束"])
        self.assertEqual(rows["3005"][3], "无法判断")
        self.assertIn("不能当作零", rows["3005"][-1])
        self.assertEqual(rows["3001"][3], "达标")
        self.assertIn("3 次未满足要求", source)
        self.assertNotIn("<script>", source)
        self.assertIn("&lt;script&gt;original cause&lt;/script&gt;", source)
        self.assertEqual(saved, original)

    def test_close_values_use_full_precision_and_unknown_is_never_a_pass(self):
        just_over = math.nextafter(0.4, math.inf)
        source = selection_run_details(record([(1, "complete", 0.4, None),
                                              (2, "complete", just_over, None),
                                              (3, "state_limit", None, None)]))
        rows = {row[0]: row for row in Rows(source).rows}
        self.assertEqual(rows["1"][3], "达标")
        self.assertEqual(rows["2"][2:4], [str(just_over), "误差超标"])
        self.assertEqual(rows["3"][2:4], ["无法计算", "未完整结束"])
        self.assertIn("完整时段 RMSE，不是瞬时最大偏差", source)

    def test_large_preview_prioritizes_the_problem_and_explains_omitted_rows(self):
        values = [(seed, "complete", 0.1, None) for seed in range(25)]
        values.append((99, "complete", 0.5, None))
        saved = record(values)
        source = selection_run_details(saved)
        rows = Rows(source).rows
        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[0][0:4:3], ["99", "误差超标"])
        self.assertIn("20 / 26", source)
        self.assertIn('href="runs.csv"', source)
        self.assertIn('href="selection.json"', source)
        self.assertEqual(len(saved["selection_runs"]), 26)


if __name__ == "__main__":
    unittest.main()
