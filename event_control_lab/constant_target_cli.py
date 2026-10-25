"""Local constant-target command; no web, learned-policy or arbitrary-code loading."""

import argparse
import hashlib
from pathlib import Path
import sys

from .cli_input_errors import read_cli_input, read_cli_json, recursion_failure
from .constant_target import TargetSpec, read_record, run_task
from .constant_target_report import export_task
from .export_recovery import ExportRecoveryError
from .output_paths import check_new_output


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="比较固定目标位置下的三种发送方式，不训练控制器")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="按声明的固定目标、实际初态和通信条件运行")
    run.add_argument("--spec", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    render = commands.add_parser("render", help="只重绘完整 target-task.json，不重新仿真")
    render.add_argument("record", type=Path)
    render.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        check_new_output(args.out)
        if args.command == "run":
            original = args.spec.read_bytes()
            spec = TargetSpec.from_dict(read_cli_json(args.spec))
            if args.spec.read_bytes() != original:
                raise ValueError("方案在读取时发生变化，请保留原件后重新确认。")
            value = run_task(spec, input_sha256=hashlib.sha256(original).hexdigest())
        else:
            value = read_cli_input(args.record, read_record)
        export_task(value, args.out)
        print(f"报告已保存：{(args.out / 'report.html').resolve()}")
        print("只重绘已有结果，没有训练或重新仿真。" if args.command == "render" else
              "三种发送结果和失败均已保存；先看完整时段误差，再看实际消息数。")
        print("保留整个目录和对应源码。下次重绘使用 target-task.json；新实验另存方案和输出。")
        return 0
    except ExportRecoveryError as exc:
        print(str(exc), file=sys.stderr)
        return 130 if exc.interrupted else 2
    except KeyboardInterrupt:
        print("操作已中断，尚未确认新的完整恢复文件。", file=sys.stderr)
        return 130
    except RecursionError as exc:
        print(recursion_failure(exc), file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(f"没有生成完整的新报告：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
