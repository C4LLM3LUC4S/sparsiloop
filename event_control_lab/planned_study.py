"""Choose a communication schedule before running the declared test conditions."""

import argparse
from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
import math
from pathlib import Path
import sys

from . import engine
from .engine import Config, make_trace, simulate


FORMAT = "sparsiloop-planned-selection-v1"
RULE = "All selection runs complete and RMSE <= limit; minimize mean attempted packets, then mean RMSE, then declared order"
MAX_INTERVALS = 40000


def digest(value):
    def numbers(item):
        if isinstance(item, float) and item.is_integer():
            return int(item)
        if isinstance(item, dict):
            return {key: numbers(value) for key, value in item.items()}
        if isinstance(item, (list, tuple)):
            return [numbers(value) for value in item]
        return item
    body = json.dumps(numbers(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode()).hexdigest()


def seed_values(values, name, minimum=1, maximum=5):
    if (not isinstance(values, (list, tuple)) or not minimum <= len(values) <= maximum
            or any(type(x) is not int or not 0 <= x < 2**32 for x in values)
            or len(set(values)) != len(values)):
        raise ValueError(f"{name} 请填 {minimum}–{maximum} 个不重复的整数种子，范围为 0 到 4294967295")
    return tuple(values)


@dataclass(frozen=True)
class PlannedSpec:
    config: Config = field(default_factory=Config)
    absolute_thresholds: tuple = (0.02, 0.06, 0.12, 0.24)
    relative_thresholds: tuple = (0.05, 0.15, 0.3)
    selection_seeds: tuple = (3001, 3002, 3003)
    test_seeds: tuple = (4001, 4002, 4003)
    previously_used_seeds: tuple = ()
    rmse_limit: float = 0.3

    def __post_init__(self):
        if not isinstance(self.config, Config):
            raise ValueError("config 必须是 Config")
        for name in ("absolute_thresholds", "relative_thresholds"):
            values = getattr(self, name)
            if (not isinstance(values, (list, tuple)) or not 0 <= len(values) <= 8
                    or any(type(x) not in (int, float) or not 0 <= x <= 2 for x in values)
                    or len(set(values)) != len(values)):
                raise ValueError(f"{name} 请填至多 8 个不重复的门槛，范围为 0 到 2")
            object.__setattr__(self, name, tuple(values))
        if type(self.rmse_limit) not in (int, float) or not 0 < self.rmse_limit <= 100:
            raise ValueError("rmse_limit 请填 0 到 100 之间的正数")
        for name in ("selection_seeds", "test_seeds", "previously_used_seeds"):
            previous = name == "previously_used_seeds"
            object.__setattr__(self, name, seed_values(getattr(self, name), name,
                                                     0 if previous else 1, 512 if previous else 5))
        groups = [set(self.selection_seeds), set(self.test_seeds), set(self.previously_used_seeds)]
        if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]:
            raise ValueError("选择、测试和此前用过的种子有重叠，请在运行前分别声明")
        count = 1 + len(self.absolute_thresholds) + len(self.relative_thresholds)
        if (count * len(self.selection_seeds) + 2 * len(self.test_seeds)) * self.config.steps > MAX_INTERVALS:
            raise ValueError("这份方案超过 40000 个潜在仿真区间，请减少门槛、种子或时长")

    @classmethod
    def from_dict(cls, value):
        names = {"config", "absolute_thresholds", "relative_thresholds", "selection_seeds",
                 "test_seeds", "previously_used_seeds", "rmse_limit"}
        if not isinstance(value, dict) or set(value) - names:
            raise ValueError("方案里有不支持的字段，请按示例填写")
        return cls(config=Config.from_dict(value.get("config", {})),
                   **{key: item for key, item in value.items() if key != "config"})


def sources():
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in
            (("engine.py", Path(engine.__file__)), ("planned_study.py", Path(__file__)))}


def candidates(spec):
    values = [{"id": "periodic", "policy": "periodic", "threshold": None}]
    for policy, thresholds in (("absolute", spec.absolute_thresholds), ("relative", spec.relative_thresholds)):
        values += [{"id": f"{policy}-{index + 1}", "policy": policy, "threshold": value}
                   for index, value in enumerate(thresholds)]
    return values


def configured(spec, candidate, seed):
    changes = {"seed": seed}
    if candidate["policy"] != "periodic":
        changes["threshold" if candidate["policy"] == "absolute" else "relative_threshold"] = candidate["threshold"]
    return replace(spec.config, **changes)


def summarize(rows, rmse_limit):
    values = [row["run"]["metrics"]["position_rmse"] for row in rows]
    complete = sum(row["run"]["status"] == "complete" and type(value) in (int, float)
                   and math.isfinite(value) and value >= 0 for row, value in zip(rows, values))
    available = bool(rows) and complete == len(rows)
    maximum = max(values) if available else None
    return {"requested": len(rows), "complete": complete,
            "all_runs_mean_rmse": math.fsum(values) / len(values) if available else None,
            "all_runs_max_rmse": maximum,
            "all_requested_mean_attempts": math.fsum(row["run"]["packets"]["attempted"] for row in rows) / len(rows),
            "eligible": available and maximum <= rmse_limit}


def selection_summaries(spec, rows):
    return [{**candidate, **summarize([row for row in rows if row["candidate_id"] == candidate["id"]], spec.rmse_limit)}
            for candidate in candidates(spec)]


def choose(summaries):
    eligible = [(row["all_requested_mean_attempts"], row["all_runs_mean_rmse"], index, row["id"])
                for index, row in enumerate(summaries) if row["eligible"]]
    return min(eligible)[-1] if eligible else None


def run_candidate(spec, candidate, seed, trace):
    config = configured(spec, candidate, seed)
    run = simulate(config, candidate["policy"], trace=trace)
    return {"candidate_id": candidate["id"], "seed": seed, "config": asdict(config), "run": run}


def select_schedule(spec):
    """Run selection seeds only. Test seeds remain unused by this function."""
    rows, traces = [], {}
    for seed in spec.selection_seeds:
        trace, _ = make_trace(replace(spec.config, seed=seed))
        traces[str(seed)] = trace
        rows.extend(run_candidate(spec, candidate, seed, trace) for candidate in candidates(spec))
    summaries = selection_summaries(spec, rows)
    record = {"format": FORMAT, "spec": asdict(spec), "source_sha256": sources(), "rule": RULE,
              "selection_runs": rows, "selection_summaries": summaries, "selected_id": choose(summaries),
              "selection_traces": traces,
              "scope": "Fixed LinearFeedback; no controller training. Declared seed split, not a preregistration or independence certificate"}
    record["record_sha256"] = digest(record)
    return record


def load_selection(record):
    try:
        expected = {"format", "spec", "source_sha256", "rule", "selection_runs", "selection_summaries",
                    "selected_id", "selection_traces", "scope", "record_sha256"}
        if not isinstance(record, dict) or set(record) != expected or record["format"] != FORMAT:
            raise ValueError("请选择 select 命令生成的完整 selection.json")
        if digest({key: value for key, value in record.items() if key != "record_sha256"}) != record["record_sha256"]:
            raise ValueError("选择记录与保存时的摘要不一致，请使用原文件")
        if record["source_sha256"] != sources():
            raise ValueError("计算代码与保存记录时不同，请保留原版本复核；不要修改摘要绕过检查")
        spec = PlannedSpec.from_dict(record["spec"])
        expected_rows = [(candidate, seed) for seed in spec.selection_seeds for candidate in candidates(spec)]
        if len(record["selection_runs"]) != len(expected_rows) or record["rule"] != RULE:
            raise ValueError("选择记录的运行数量或选择规则不匹配")
        for row, (candidate, seed) in zip(record["selection_runs"], expected_rows):
            run = row["run"]
            if (row["candidate_id"] != candidate["id"] or row["seed"] != seed
                    or row["config"] != asdict(configured(spec, candidate, seed))
                    or run["policy"] != candidate["policy"]
                    or type(run["packets"]["attempted"]) is not int
                    or not 0 <= run["packets"]["attempted"] <= spec.config.budget):
                raise ValueError("选择记录中的候选、种子、设置或发送次数不匹配")
        summaries = selection_summaries(spec, record["selection_runs"])
        if summaries != record["selection_summaries"] or choose(summaries) != record["selected_id"]:
            raise ValueError("保存的选择结果不符合声明规则")
        return spec
    except (KeyError, TypeError, IndexError, AttributeError, OverflowError) as exc:
        raise ValueError("选择记录不完整或格式不正确，请使用完整 selection.json") from exc


def test_schedule(record):
    """Load the fixed choice; run only the declared test seeds and periodic reference."""
    spec = load_selection(record)
    result = {"analysis": "planned-budget-test-v1", "selection": record, "selected_id": record["selected_id"],
              "status": "not_run_no_eligible_choice", "test_runs": [], "test_traces": {},
              "selected_summary": None, "reference_summary": None, "paired_results": [],
              "scope": "No reselection; same predeclared cap, not matched actual traffic. Repeating this file is replication, not new tests"}
    if record["selected_id"] is None:
        return result
    selected = next(row for row in candidates(spec) if row["id"] == record["selected_id"])
    periodic = candidates(spec)[0]
    for seed in spec.test_seeds:
        trace, _ = make_trace(replace(spec.config, seed=seed))
        result["test_traces"][str(seed)] = trace
        chosen = run_candidate(spec, selected, seed, trace)
        chosen["roles"] = ["selected"]
        result["test_runs"].append(chosen)
        if selected["id"] == "periodic":
            reference = chosen
            chosen["roles"].append("periodic_reference")
        else:
            reference = run_candidate(spec, periodic, seed, trace)
            reference["roles"] = ["periodic_reference"]
            result["test_runs"].append(reference)
        both = all(row["run"]["status"] == "complete" for row in (chosen, reference))
        result["paired_results"].append({"seed": seed, "both_complete": both,
            "rmse_selected_minus_periodic": (chosen["run"]["metrics"]["position_rmse"]
                - reference["run"]["metrics"]["position_rmse"] if both else None),
            "attempts_selected_minus_periodic": (chosen["run"]["packets"]["attempted"]
                - reference["run"]["packets"]["attempted"] if both else None)})
    result["selected_summary"] = summarize([row for row in result["test_runs"] if "selected" in row["roles"]], spec.rmse_limit)
    result["reference_summary"] = summarize([row for row in result["test_runs"] if "periodic_reference" in row["roles"]], spec.rmse_limit)
    result["status"] = "met_declared_tests" if result["selected_summary"]["eligible"] else "did_not_meet_declared_tests"
    return result


def read_json(path):
    with Path(path).open("rb") as handle:
        data = handle.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024:
        raise ValueError("记录超过 64 MiB 限制，请核对文件")
    return json.loads(data.decode("utf-8-sig")), hashlib.sha256(data).hexdigest()


def main(argv=None):
    from .planned_report import export_selection, export_test

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
        else:
            result = test_schedule(value)
            export_test(result, output, input_hash)
        print(f"报告已保存：{output / 'report.html'}")
        return 0
    except (ValueError, OSError, UnicodeError) as exc:
        print(f"没有生成完整的新报告：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
