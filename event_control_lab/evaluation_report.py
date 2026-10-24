"""Retain and redraw local standalone evaluations without running a policy."""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re
import sys

from .cli_input_errors import read_cli_input, recursion_failure
from .controller_lab import export_policy_evaluation
from .engine import Config, POLICIES, PROTOCOL
from .export_recovery import ExportRecoveryError, recovery_record
from .output_paths import check_new_output
from .policy import load_checkpoint, seed_list


FORMAT = "frozen-policy-evaluation-v1"


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _run(run, name, config):
    grid_end = config.steps * config.dt
    if (not isinstance(run, dict) or run["policy"] != name
            or run["status"] not in {"complete", "state_limit", "controller_error", "plant_error"}
            or run["error"] is not None and not isinstance(run["error"], str)
            or not number(run["duration_completed"]) or not 0 <= run["duration_completed"] <= grid_end):
        raise ValueError("运行状态或时段不完整，请使用原始完整评测记录。")
    if (run["status"] == "complete" and
            (run["duration_completed"] != grid_end or run["error"] is not None)):
        raise ValueError("完整运行的结束时刻或错误状态与原声明不一致。")
    score = run["metrics"]["position_rmse"]
    if (run["status"] == "complete" and (not number(score) or score < 0)
            or score is not None and (not number(score) or score < 0)
            or run["status"] != "complete" and score is not None):
        raise ValueError("运行状态与整段误差不一致：完整运行应有有限误差，未完成的误差应保持未知。")
    packets = run["packets"]
    counts = [packets[key] for key in ("attempted", "dropped", "delivered", "in_flight")]
    if (any(type(value) is not int or value < 0 for value in counts)
            or counts[0] != sum(counts[1:]) or counts[0] > config.budget):
        raise ValueError("通信账本与原声明不一致，请使用原始完整评测记录。")
    rows = run["trajectory"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("评测缺少完整轨迹，请使用原始文件，不要只留下汇总分数。")
    ticks = round(run["duration_completed"] / config.dt)
    if (run["duration_completed"] != ticks * config.dt or len(rows) != ticks + 1
            or rows[0]["state"] != list(config.initial_state)):
        raise ValueError("轨迹长度、起点或结束时刻与保存的完整运行不符。")
    last = -1
    for index, row in enumerate(rows):
        state, seen, age = row["state"], row["controller_values"], row["observation_age"]
        if (not number(row["t"]) or row["t"] != index * config.dt
                or not 0 <= row["t"] <= grid_end or row["t"] < last
                or not isinstance(state, list) or len(state) != 1 or not number(state[0])
                or not number(row["input"])
                or seen is not None and (not isinstance(seen, list) or len(seen) != 1 or not number(seen[0]))
                or age is not None and (not number(age) or age < 0)
                or type(row["sent"]) is not bool or type(row["dropped"]) is not bool
                or type(row["delivered"]) is not int or row["delivered"] < 0):
            raise ValueError("轨迹字段不完整或用途不符，请使用原始完整评测记录。")
        last = row["t"]


def _trace(comparison, config, expected_engine):
    required = {"schema_version", "engine_version", "protocol", "engine_source_sha256",
                "python_version", "config", "controller", "scope", "exogenous_trace_sha256",
                "exogenous_trace", "runs"}
    if not required <= set(comparison):
        raise ValueError("评测缺少完整的比较条件或随机输入，请使用原始 evaluation.json。")
    if (type(comparison["schema_version"]) is not int or comparison["schema_version"] != 1
            or comparison["engine_version"] != "0.0.1" or comparison["protocol"] != PROTOCOL
            or comparison["engine_source_sha256"] != expected_engine
            or not isinstance(comparison["python_version"], str) or not comparison["python_version"]
            or not isinstance(comparison["scope"], str)):
        raise ValueError("比较记录的计算来源或协议与原策略不符，请找回匹配的原记录和代码。")
    trace = comparison["exogenous_trace"]
    keys = {"measurement_standard_normal", "input_disturbance_standard_normal", "loss_uniform"}
    if not isinstance(trace, dict) or set(trace) != keys:
        raise ValueError("评测缺少完整的原随机输入，不能用新的随机数补齐。")
    sensor, disturbance, loss = (trace[key] for key in
        ("measurement_standard_normal", "input_disturbance_standard_normal", "loss_uniform"))
    if (any(not isinstance(values, list) or len(values) != config.steps for values in (sensor, disturbance, loss))
            or any(not isinstance(row, list) or len(row) != 1 or not number(row[0]) for row in sensor)
            or any(not number(value) for value in disturbance)
            or any(not number(value) or not 0 <= value < 1 for value in loss)):
        raise ValueError("原随机输入的长度或数值与声明不符，请保留完整原文件。")
    # The engine generated floats. Equivalent JSON 1 and 1.0 spellings do not
    # change the stored realization; no random input is regenerated here.
    normalized = {"measurement_standard_normal": [[float(row[0])] for row in sensor],
                  "input_disturbance_standard_normal": [float(value) for value in disturbance],
                  "loss_uniform": [float(value) for value in loss]}
    digest = hashlib.sha256()
    for part in json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False).iterencode(normalized):
        digest.update(part.encode("utf-8"))
    if comparison["exogenous_trace_sha256"] != digest.hexdigest():
        raise ValueError("保存的随机输入与摘要不一致，请使用未修改的完整原记录。")


def validate_evaluation(value):
    """Check saved declarations and renderer inputs; do not recompute any metric."""
    try:
        required = {"analysis", "checkpoint", "evaluation_config", "evaluation_seeds", "cases",
                    "frozen_before_sha256", "frozen_after_sha256", "scope"}
        if not isinstance(value, dict) or not required <= set(value) or value["analysis"] != FORMAT:
            raise ValueError("请载入完整 evaluation.json；controllers.json、策略或 Q 表不能代替评测结果。")
        for _ in json.JSONEncoder(allow_nan=False).iterencode(value):
            pass
        table, trained, _ = load_checkpoint(value["checkpoint"])
        base = Config.from_dict(value["evaluation_config"])
        if any(getattr(base, name) != getattr(trained, name) for name in ("plant", "dt", "duration", "input_limit")):
            raise ValueError("评测时钟、对象或输入上限与原策略不符，请使用匹配的完整记录。")
        seeds = seed_list(value["evaluation_seeds"], "evaluation_seeds")
        saved = value["checkpoint"]
        if (set(seeds) & set(saved["training_seeds"] + saved["previous_evaluation_seeds"])
                or len(seeds) + len(saved["previous_evaluation_seeds"]) > 512):
            raise ValueError("本次编号与原策略历史不符，请保留完整原文件。")
        if (value["frozen_before_sha256"] != table.fingerprint()
                or value["frozen_after_sha256"] != value["frozen_before_sha256"]
                or not isinstance(value["scope"], str)):
            raise ValueError("记录中的冻结策略摘要或说明不完整，请使用原文件。")
        if ("checkpoint_file_sha256" in value and
                (not isinstance(value["checkpoint_file_sha256"], str)
                 or not re.fullmatch(r"[a-f0-9]{64}", value["checkpoint_file_sha256"]))):
            raise ValueError("原策略文件摘要不完整，请使用原样保存的评测文件。")
        cases = value["cases"]
        if not isinstance(cases, list) or len(cases) != len(seeds):
            raise ValueError("评测次数与声明编号不符，请使用完整 evaluation.json。")
        for case, seed in zip(cases, seeds):
            if type(case["seed"]) is not int or case["seed"] != seed:
                raise ValueError("评测顺序或编号与声明不符。")
            first = None
            for key in ("policy", "linear_feedback"):
                comparison = case[key]
                config = Config.from_dict(comparison["config"])
                _trace(comparison, config, saved["source_sha256"]["engine"])
                expected_controller = "custom_local_factory" if key == "policy" else "LinearFeedback"
                if comparison["controller"] != expected_controller:
                    raise ValueError("策略与固定反馈对照的角色不符，请使用完整原评测记录。")
                if (config.seed != seed or any(getattr(config, field) != item for field, item in asdict(base).items()
                                               if field not in {"seed", "initial_position"})):
                    raise ValueError("运行条件与原评测声明不符。")
                actual = asdict(config)
                if first is not None and first != actual:
                    raise ValueError("策略与固定反馈对照没有使用相同条件。")
                first = actual
                runs = comparison["runs"]
                if not isinstance(runs, list) or len(runs) != len(POLICIES):
                    raise ValueError("评测缺少完整的三种发送结果。")
                for run, name in zip(runs, POLICIES):
                    _run(run, name, config)
                    if run["trace_sha256"] != comparison["exogenous_trace_sha256"]:
                        raise ValueError("运行与其比较记录没有引用同一份原随机输入。")
        return value
    except (KeyError, TypeError, IndexError, AttributeError, OverflowError) as exc:
        raise ValueError("评测字段不完整或类型不符，请使用原样保存的完整 evaluation.json。") from exc


def read_evaluation(path):
    """Read the complete local JSON; no checkpoint/planned byte cap is borrowed."""
    with Path(path).open(encoding="utf-8-sig") as handle:
        value = json.load(handle)
    return validate_evaluation(value)


def export_evaluation(value, destination):
    """Local safe export; legacy Python/web exporters retain their existing contract."""
    check_new_output(destination)
    target = Path(destination).resolve()
    validate_evaluation(value)
    with recovery_record(value, target, "evaluation", verify=read_evaluation):
        export_policy_evaluation(value, target)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="只重绘已保存的独立策略评测，不重新测试或训练")
    sub = parser.add_subparsers(dest="command", required=True)
    render = sub.add_parser("render", help="载入完整 evaluation.json，重新保存报告")
    render.add_argument("record", type=Path)
    render.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        check_new_output(args.out)
        value = read_cli_input(args.record, read_evaluation)
        export_evaluation(value, args.out)
        print(f"报告已重新保存：{(args.out / 'report.html').resolve()}\n"
              "没有训练、评测或生成新的随机输入；原记录没有执行环境的地方仍是未知。")
        return 0
    except ExportRecoveryError as exc:
        print(str(exc), file=sys.stderr)
        return 130 if exc.interrupted else 2
    except KeyboardInterrupt:
        print("操作已中断，尚未确认新的完整恢复文件。 / Interrupted before a complete recovery copy was confirmed.", file=sys.stderr)
        return 130
    except RecursionError as exc:
        print(recursion_failure(exc), file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(f"没有生成完整的新报告：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
