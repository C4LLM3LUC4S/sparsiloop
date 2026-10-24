"""Local commands for chronological policy continuation."""

import argparse
from pathlib import Path
import sys

from .engine import Config
from .planned_study import PlannedSpec, read_json
from .policy import read_checkpoint
from .policy_journal import evaluate_saved, load_workflow, select_plan, test_plan
from .policy_journal_report import export_workflow
from .export_recovery import ExportRecoveryError
from .output_paths import check_new_output


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="沿着完整历史继续测试同一份冻结策略")
    commands = parser.add_subparsers(dest="command", required=True)
    evaluate = commands.add_parser("evaluate", help="用新种子单独评测，并接上完整阶段历史")
    evaluate.add_argument("--policy", required=True)
    evaluate.add_argument("--seeds", required=True)
    evaluate.add_argument("--config")
    selection = commands.add_parser("select", help="只选择发送方案，不运行预留复核种子")
    selection.add_argument("--policy", required=True)
    selection.add_argument("--spec", required=True)
    for name, help_text in (("test", "按原选择复核，不换策略、门槛或种子"),
                            ("render", "只重绘完整流程记录，不再仿真")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("record", help="完整 policy-workflow.json")
    for command in (evaluate, selection, *[commands.choices[name] for name in ("test", "render")]):
        command.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        target = Path(args.out)
        check_new_output(target)
        target = target.resolve()
        if args.command in ("evaluate", "select"):
            value, input_hash = read_checkpoint(args.policy)
            if args.command == "evaluate":
                seeds = [int(part.strip()) for part in args.seeds.split(",")]
                config = Config.from_dict(read_json(args.config)[0]) if args.config else None
                result = evaluate_saved(value, seeds, config)
            else:
                result = select_plan(PlannedSpec.from_dict(read_json(args.spec)[0]), value)
        else:
            value, input_hash = read_json(args.record)
            result = test_plan(value) if args.command == "test" else load_workflow(value)
        export_workflow(result, target, input_hash)
        if args.command == "render":
            print("只重新生成报告，没有运行选择或测试；原阶段环境保持原样。")
        elif args.command == "select":
            chosen = result["data"]["result"]["selected_id"]
            print("选择已保存，预留复核种子还没有运行。" if chosen else "没有合格候选；预留复核种子没有运行。")
        elif args.command == "test":
            status = result["data"]["result"]["status"]
            print({"met_declared_tests": "原计划的复核均完整结束并达标。",
                   "did_not_meet_declared_tests": "复核未满足全部要求；结果保留，没有改选。",
                   "not_run_no_eligible_choice": "原选择没有合格候选，没有运行复核种子。"}[status])
        else:
            print("单独评测已保存，没有重新训练；阶段历史已接上。")
        print(f"报告：{target / 'report.html'}")
        print("继续新任务用 policy-history.json；复核或重绘本步用 policy-workflow.json。")
        return 0
    except ExportRecoveryError as exc:
        print(str(exc), file=sys.stderr)
        return 130 if exc.interrupted else 2
    except KeyboardInterrupt:
        print("任务已中断，尚未生成新的完整报告或确认可恢复的记录。 / Interrupted before a complete recovery record was confirmed.", file=sys.stderr)
        return 130
    except (ValueError, OSError, UnicodeError, RecursionError) as exc:
        print(f"没有生成新的完整报告：{exc}", file=sys.stderr)
        return 2
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        print(f"记录字段不完整，请保留原文件并核对：{exc}", file=sys.stderr)
        return 2
