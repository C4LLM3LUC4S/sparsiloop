"""Terminal wording and file entry points, separate from numerical identity."""

import argparse
from pathlib import Path
import sys

from .planned_report import label
from .planned_study import PlannedSpec, read_json
from .planned_context import as_bundle, export_bundle, select_with_context, test_with_context
from .export_recovery import ExportRecoveryError
from .output_paths import check_new_output


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="先选发送方案，再用预留条件复核")
    commands = parser.add_subparsers(dest="command", required=True)
    selection = commands.add_parser("select", help="只用选择种子，保存方案和完整记录")
    selection.add_argument("--spec", required=True)
    selection.add_argument("--policy-checkpoint", help="可选：复用完整冻结策略或 policy-history.json；不再训练")
    selection.add_argument("--out", required=True)
    testing = commands.add_parser("test", help="载入既定方案，只运行预先声明的测试种子")
    testing.add_argument("record", help="选择阶段的 selection.json")
    testing.add_argument("--out", required=True)
    rendering = commands.add_parser("render", help="只重绘已保存的记录，不运行选择或测试")
    rendering.add_argument("record", help="原始结果或带环境的记录包")
    rendering.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        output = Path(args.out)
        check_new_output(output)
        output = output.resolve()
        value, input_hash = read_json(args.spec if args.command == "select" else args.record)
        if args.command == "select":
            policy_checkpoint = read_json(args.policy_checkpoint)[0] if args.policy_checkpoint else None
            if args.policy_checkpoint and not isinstance(policy_checkpoint, dict):
                raise ValueError("策略文件需要是完整 checkpoint 或历史对象，空值不能代替策略，也不会改用线性反馈。")
            bundle = select_with_context(PlannedSpec.from_dict(value), policy_checkpoint=policy_checkpoint)
            result = bundle["result"]
            choice = next((row for row in result["selection_summaries"] if row["id"] == result["selected_id"]), None)
            print("已选定：" + label(choice) + "。测试种子还没有运行。" if choice else
                  "没有候选满足要求；测试种子还没有运行。")
        elif args.command == "test":
            bundle = test_with_context(value)
            result = bundle["result"]
            messages = {"met_declared_tests": "这次声明的测试都完整结束，所选方案均满足误差要求。",
                        "did_not_meet_declared_tests": "所选方案没有通过这次所有要求。完整结果已保留，没有重新选门槛。",
                        "not_run_no_eligible_choice": "选择阶段没有合格候选，这次没有运行测试。"}
            print(messages[result["status"]])
        else:
            bundle = as_bundle(value)
            print("只重新生成报告，没有运行选择或测试；缺失的原运行环境仍是未知。")
        export_bundle(bundle, output, input_hash)
        if "policy_after" in bundle["result"]:
            print("这次没有训练策略。另做新计划时，请载入 policy-history.json，保留已经用过的编号。")
        if bundle["context"]["selection"]["state"] == "not_recorded":
            print("原选择记录未保存环境，不能用当前环境补过去。")
        print("下次复核可载入 selection-bundle.json，一并保留选择时的环境。")
        print(f"报告已保存：{output / 'report.html'}")
        return 0
    except ExportRecoveryError as exc:
        print(str(exc), file=sys.stderr)
        return 130 if exc.interrupted else 2
    except KeyboardInterrupt:
        print("任务已中断，尚未生成新的完整报告或确认可恢复的记录。 / Interrupted before a complete recovery record was confirmed.", file=sys.stderr)
        return 130
    except (ValueError, OSError, UnicodeError, RecursionError) as exc:
        print(f"没有生成完整的新报告：{exc}", file=sys.stderr)
        return 2
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        print(f"没有生成完整的新报告：记录不完整或字段格式不正确（{exc}）", file=sys.stderr)
        return 2
