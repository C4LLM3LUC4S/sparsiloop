"""Terminal wording and file entry points, separate from numerical identity."""

import argparse
from pathlib import Path
import sys

from .planned_report import export_selection, export_test, label
from .planned_study import PlannedSpec, read_json, select_schedule, test_schedule


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="先选发送方案，再用预留条件复核")
    commands = parser.add_subparsers(dest="command", required=True)
    selection = commands.add_parser("select", help="只用选择种子，保存方案和完整记录")
    selection.add_argument("--spec", required=True)
    selection.add_argument("--out", required=True)
    testing = commands.add_parser("test", help="载入既定方案，只运行预先声明的测试种子")
    testing.add_argument("record", help="选择阶段的 selection.json")
    testing.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        output = Path(args.out).resolve()
        if output.exists():
            raise ValueError("输出目录已存在，请换一个新目录；旧结果不会覆盖")
        value, input_hash = read_json(args.spec if args.command == "select" else args.record)
        if args.command == "select":
            result = select_schedule(PlannedSpec.from_dict(value))
            export_selection(result, output, input_hash)
            choice = next((row for row in result["selection_summaries"] if row["id"] == result["selected_id"]), None)
            print("已选定：" + label(choice) + "。测试种子还没有运行。" if choice else
                  "没有候选满足要求；测试种子还没有运行。")
        else:
            result = test_schedule(value)
            export_test(result, output, input_hash)
            messages = {"met_declared_tests": "这次声明的测试都完整结束，所选方案均满足误差要求。",
                        "did_not_meet_declared_tests": "所选方案没有通过这次所有要求。完整结果已保留，没有重新选门槛。",
                        "not_run_no_eligible_choice": "选择阶段没有合格候选，这次没有运行测试。"}
            print(messages[result["status"]])
        print(f"报告已保存：{output / 'report.html'}")
        return 0
    except (ValueError, OSError, UnicodeError, RecursionError) as exc:
        print(f"没有生成完整的新报告：{exc}", file=sys.stderr)
        return 2
