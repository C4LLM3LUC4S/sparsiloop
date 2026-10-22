import copy
from dataclasses import replace
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from event_control_lab import Config
from event_control_lab import engine
from event_control_lab import planned_study as planned
from event_control_lab.planned_report import export_selection, export_test


class Context(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.active = False
        self.detail_depth = 0
        self.visible, self.text, self.rows = [], [], []
        self.row = self.cell = None
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "section" and attrs.get("id") == "experiment-conditions":
            self.active = True
        if not self.active:
            return
        if tag == "details":
            self.detail_depth += 1
        if tag == "tr":
            self.row = []
        if tag == "td":
            self.cell = []

    def handle_endtag(self, tag):
        if not self.active:
            return
        if tag == "details":
            self.detail_depth -= 1
        if tag == "td" and self.cell is not None:
            self.row.append("".join(self.cell))
            self.cell = None
        if tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = None
        if tag == "section":
            self.active = False

    def handle_data(self, value):
        if not self.active:
            return
        self.text.append(value)
        if self.detail_depth == 0:
            self.visible.append(value)
        if self.cell is not None:
            self.cell.append(value)

    @property
    def fields(self):
        return dict(self.rows)


class PlannedReportContextTests(unittest.TestCase):
    def record(self, **changes):
        config = Config(duration=0.8, dt=0.02, budget=40, heartbeat=0.051,
                        delay_steps=3, loss_probability=0.1, measurement_noise=0.02,
                        process_noise=0.03, initial_position=1.2, initial_velocity=-0.3,
                        kp=3.1, kd=1.7, seed=999)
        spec = planned.PlannedSpec(config=replace(config, **changes),
                                   absolute_thresholds=(0.2,), relative_thresholds=(),
                                   selection_seeds=(701,), test_seeds=(801,), rmse_limit=100)
        return planned.select_schedule(spec)

    def pages(self, record):
        result = planned.test_schedule(record)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            export_selection(record, root / "choice")
            export_test(result, root / "test")
            return [Context((root / name / "report.html").read_text(encoding="utf-8"))
                    for name in ("choice", "test")]

    def test_both_saved_phases_identify_actual_model_initial_state_and_zero_goal(self):
        for plant, name in [("scalar", "一阶标量对象"),
                            ("double_integrator", "位置—速度对象")]:
            for page in self.pages(self.record(plant=plant)):
                with self.subTest(plant=plant):
                    intro = "".join(page.visible)
                    self.assertIn(name, intro)
                    self.assertIn("1.2", intro)
                    self.assertIn("回到 0", intro)
                    self.assertIn("数学示例", intro)
                    if plant == "double_integrator":
                        self.assertIn("-0.3", intro)
                        self.assertIn("p' = v, v' = u", page.fields["对象方程"])
                        self.assertIn("kd=1.7", page.fields["固定反馈与指令限幅"])
                    else:
                        self.assertNotIn("-0.3", intro)
                        self.assertIn("x' = x + u", page.fields["对象方程"])
                        self.assertIn("kd 不参与", page.fields["固定反馈与指令限幅"])

    def test_clock_noise_and_information_describe_the_engine_instead_of_continuous_noise(self):
        for page in self.pages(self.record()):
            self.assertIn("3 步", page.fields["传感器到控制器的链路"])
            self.assertIn("0.06 秒", page.fields["传感器到控制器的链路"])
            self.assertIn("10%", page.fields["传感器到控制器的链路"])
            heartbeat = page.fields["事件发送的最长尝试间隔"]
            self.assertIn("0.051 秒", heartbeat)
            self.assertIn("3 步", heartbeat)
            self.assertIn("0.06 秒", heartbeat)
            self.assertIn("剩余预算", heartbeat)
            self.assertIn("0.02", page.fields["噪声怎样加入"])
            self.assertIn("0.03", page.fields["噪声怎样加入"])
            self.assertIn("指令限幅之后", page.fields["噪声怎样加入"])
            self.assertIn("不是连续时间", page.fields["噪声怎样加入"])
            self.assertIn("到达的观测", page.fields["控制器看到了什么"])
            self.assertIn("不是瞬时最大", page.fields["误差与提前停止"])

    def test_relative_floor_and_executed_seed_lists_do_not_hide_config_overrides(self):
        record = self.record()
        spec = replace(planned.PlannedSpec.from_dict(record["spec"]),
                       config=replace(planned.Config.from_dict(record["spec"]["config"]), threshold=0.37),
                       absolute_thresholds=(), relative_thresholds=(0.62,))
        choice, testing = self.pages(planned.select_schedule(spec))
        for page in (choice, testing):
            self.assertIn("0.37", page.fields["事件发送规则"])
            self.assertIn("0.62", page.fields["事件发送规则"])
            self.assertIn("最后一次尝试发送", page.fields["事件发送规则"])
            self.assertIn("999", page.fields["配置里哪些值会被替换"])
            self.assertIn("不作为本轮运行编号", page.fields["配置里哪些值会被替换"])
        self.assertIn("701", "".join(choice.visible))
        self.assertIn("801", "".join(choice.visible))
        self.assertIn("本阶段未运行", "".join(choice.visible))
        self.assertIn("801", "".join(testing.visible))

    def test_rendering_only_preserves_saved_records_and_does_not_run_any_seed(self):
        record = self.record()
        result = planned.test_schedule(record)
        original = copy.deepcopy([record, result])
        expected_sources = planned.sources()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(planned, "simulate", side_effect=AssertionError("renderer ran a seed")), \
                 patch.object(engine, "simulate", side_effect=AssertionError("renderer ran a seed")):
                export_selection(record, root / "choice")
                export_test(result, root / "test")
            self.assertEqual(json.loads((root / "choice/selection.json").read_text()), json.loads(json.dumps(record)))
            self.assertEqual(json.loads((root / "test/test.json").read_text()), json.loads(json.dumps(result)))
        self.assertEqual([record, result], original)
        self.assertEqual(planned.sources(), expected_sources)
        self.assertEqual(planned.load_selection(record), planned.PlannedSpec.from_dict(record["spec"]))

    def test_unrun_test_and_periodic_only_do_not_invent_event_activity(self):
        record = self.record(kp=0, state_limit=1.3)
        self.assertIsNone(record["selected_id"])
        for page in self.pages(record):
            self.assertIn("801", "".join(page.visible))
        self.assertIn("本阶段未运行测试", "".join(self.pages(record)[1].visible))
        spec = replace(planned.PlannedSpec.from_dict(record["spec"]),
                       config=replace(planned.Config.from_dict(record["spec"]["config"]), state_limit=20),
                       absolute_thresholds=(), relative_thresholds=())
        for page in self.pages(planned.select_schedule(spec)):
            self.assertIn("没有事件候选", page.fields["事件发送规则"])
            self.assertIn("周期发送不使用", page.fields["事件发送的最长尝试间隔"])

    def test_incomplete_saved_conditions_do_not_invent_default_values(self):
        record = self.record()
        for name in ("loss_probability", "initial_position", "seed"):
            del record["spec"]["config"][name]
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "incomplete"
            export_selection(record, destination)
            page = Context((destination / "report.html").read_text(encoding="utf-8"))
            self.assertIn("不能用默认值代替原记录", "".join(page.visible))
            self.assertIn("loss_probability", "".join(page.visible))
            self.assertNotIn("5%", "".join(page.visible))
            self.assertFalse(page.fields)


if __name__ == "__main__":
    unittest.main()
