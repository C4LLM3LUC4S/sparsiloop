"""Reuse the public actuator model for a declared selection and a separate test."""

import argparse
from pathlib import Path
import sys

from event_control_lab.planned_context import export_bundle, select_with_context, test_with_context
from event_control_lab.output_paths import check_new_output
from event_control_lab.planned_study import PlannedSpec, read_json
from examples.own_model_case import actuator_model


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="用同一个本地执行器模型选方案，再按原计划复核")
    commands = parser.add_subparsers(dest="command", required=True)
    selection = commands.add_parser("select")
    selection.add_argument("--spec", required=True)
    selection.add_argument("--decay", type=float, default=0.4)
    selection.add_argument("--gain", type=float, default=1.2)
    testing = commands.add_parser("test")
    testing.add_argument("record")
    testing.add_argument("--decay", type=float, required=True)
    testing.add_argument("--gain", type=float, required=True)
    for command in (selection, testing):
        command.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        check_new_output(args.out)
        output = Path(args.out).resolve()
        value, input_hash = read_json(args.spec if args.command == "select" else args.record)
        plant = actuator_model(args.decay, args.gain)
        if args.command == "select":
            saved = select_with_context(PlannedSpec.from_dict(value), plant=plant)
            print("选择阶段已结束，预留测试编号还没有运行。")
        else:
            saved = test_with_context(value, plant=plant)
            print({"met_declared_tests": "本次所选方案在声明的复核条件下均完整结束且达标。",
                   "did_not_meet_declared_tests": "没有满足本次所有要求，原选择未改变；请在报告中查看失败或超限项。",
                   "not_run_no_eligible_choice": "原选择没有合格候选，这次没有运行测试。"}[saved["result"]["status"]])
        export_bundle(saved, output, input_hash)
        print(f"报告：{output / 'report.html'}")
        print("请同时保留模型代码、参数和 selection-bundle.json；JSON 不会恢复可执行模型。")
        return 0
    except (ValueError, OSError, UnicodeError, RecursionError, KeyError, TypeError) as exc:
        print(f"这次没有生成完整新报告：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
