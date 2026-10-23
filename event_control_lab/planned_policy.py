"""Choose a communication schedule for a frozen policy, retaining declared history."""

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
from pathlib import Path
import re

from . import controllers, engine, models, planned_study, policy
from .controllers import QController
from .engine import make_trace, simulate
from .planned_study import (PlannedSpec, RULE, candidates, choose, configured, digest,
                            seed_values, selection_summaries, summarize)


FORMAT = "sparsiloop-planned-policy-selection-v1"
TEST_FORMAT = "planned-policy-budget-test-v1"
HISTORY_FORMAT = "sparsiloop-planned-policy-history-v1"
INITIAL_STATE_RULE = "fixed_configured_initial_state_all_seeds"


def sources():
    return {name + ".py": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for name, module in (("engine", engine), ("models", models), ("controllers", controllers),
                                 ("policy", policy), ("planned_study", planned_study))} | {
        "planned_policy.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def history_for(value):
    """Accept a legacy full checkpoint or the phase-specific continuation, without repair."""
    if isinstance(value, dict) and value.get("format") == policy.FORMAT:
        policy.load_checkpoint(value)
        result = {"format": HISTORY_FORMAT, "checkpoint": deepcopy(value),
                  "earlier_evaluation_seeds": list(value["previous_evaluation_seeds"]),
                  "declared_development_seeds": [], "planned_history": []}
        result["history_sha256"] = digest(result)
        return result
    fields = {"format", "checkpoint", "earlier_evaluation_seeds", "declared_development_seeds",
              "planned_history", "history_sha256"}
    if not isinstance(value, dict) or set(value) != fields or value["format"] != HISTORY_FORMAT:
        raise ValueError("请载入完整 policy-checkpoint.json 或 policy-history.json，只有 Q 表不能复用。")
    if digest({k: v for k, v in value.items() if k != "history_sha256"}) != value["history_sha256"]:
        raise ValueError("策略历史与摘要不一致，请找回原文件，不要补写摘要。")
    saved = value["checkpoint"]
    policy.load_checkpoint(saved)
    previous = list(policy.seed_list(value["earlier_evaluation_seeds"], "earlier evaluation seeds"))
    development = list(seed_values(value["declared_development_seeds"], "declared development seeds", 0, 512))
    if set(development) & set(previous + saved["training_seeds"]):
        raise ValueError("开发编号与已保存的训练或评测编号重复，请使用原历史文件。")
    previous.extend(development)
    history = value["planned_history"]
    if not isinstance(history, list) or len(history) > 512:
        raise ValueError("策略历史不完整或超过限制，请使用原记录。")
    pending = None
    for item in history:
        if (not isinstance(item, dict) or set(item) != {"phase", "seeds", "plan_sha256"}
                or item["phase"] not in ("selection", "test")
                or not isinstance(item["plan_sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", item["plan_sha256"])):
            raise ValueError("选择和测试历史的字段不正确。")
        seeds = policy.seed_list(item["seeds"], "planned history seeds")
        if len(seeds) > 5 or set(seeds) & set(previous + saved["training_seeds"]):
            raise ValueError("历史编号有重复或与训练重叠，请使用完整原记录。")
        if item["phase"] == "selection":
            pending = item["plan_sha256"]
        elif pending != item["plan_sha256"]:
            raise ValueError("测试历史缺少对应的选择阶段。")
        else:
            pending = None
        previous.extend(seeds)
    if previous != saved["previous_evaluation_seeds"]:
        raise ValueError("分阶段历史与策略中的已用编号不一致。")
    return deepcopy(value)


def add_history(value, spec, phase):
    result = deepcopy(value)
    seeds = list(spec.selection_seeds if phase == "selection" else spec.test_seeds)
    saved = result["checkpoint"]
    used = set(saved["training_seeds"] + saved["previous_evaluation_seeds"])
    result["declared_development_seeds"] += [seed for seed in spec.previously_used_seeds if seed not in used]
    result["planned_history"].append({"phase": phase, "seeds": seeds, "plan_sha256": digest(asdict(spec))})
    saved["previous_evaluation_seeds"] = (result["earlier_evaluation_seeds"] + result["declared_development_seeds"]
        + [seed for item in result["planned_history"] for seed in item["seeds"]])
    saved["checkpoint_sha256"] = policy.checkpoint_digest(saved)
    result["history_sha256"] = digest({k: v for k, v in result.items() if k != "history_sha256"})
    return result


def compatible(spec, saved):
    table, training, _ = policy.load_checkpoint(saved["checkpoint"])
    if not isinstance(spec, PlannedSpec):
        raise ValueError("请先用 PlannedSpec 声明方案。")
    for name in ("plant", "dt", "duration", "input_limit"):
        if getattr(spec.config, name) != getattr(training, name):
            raise ValueError(f"这份策略需要保留训练时的 {name}；相同步数不代表相同物理时间。")
    checkpoint = saved["checkpoint"]
    used = set(checkpoint["training_seeds"] + checkpoint["previous_evaluation_seeds"])
    if used & set(spec.selection_seeds + spec.test_seeds):
        raise ValueError("选择或测试编号已经用于训练、评测或此前计划，请换新编号并保留历史。")
    added_development = set(spec.previously_used_seeds) - used
    if (len(checkpoint["previous_evaluation_seeds"]) + len(added_development)
            + len(spec.selection_seeds + spec.test_seeds) > 512):
        raise ValueError("继续记录后会超过 512 个已用编号，请缩小本次方案并保留全部旧记录。")
    return table


def run_candidate(spec, candidate, seed, trace, table):
    config = configured(spec, candidate, seed)
    controller = QController(config, table)
    before = table.fingerprint()
    run = simulate(config, candidate["policy"], controller=controller, trace=trace)
    after = table.fingerprint()
    if before != after or controller.updates:
        raise ValueError("这次运行改变了冻结策略，没有生成新的完整记录。")
    return {"candidate_id": candidate["id"], "seed": seed, "config": asdict(config), "run": run,
            "controller": {"recipe": "frozen-tabular-q", "initialization_config": asdict(config),
                           "before_sha256": before, "after_sha256": after, "learning_updates": 0}}


def select_policy_schedule(spec, *, policy_checkpoint):
    saved = history_for(policy_checkpoint)
    table = compatible(spec, saved)
    before = table.fingerprint()
    rows, traces = [], {}
    for seed in spec.selection_seeds:
        trace, _ = make_trace(replace(spec.config, seed=seed))
        traces[str(seed)] = trace
        rows.extend(run_candidate(spec, candidate, seed, trace, table) for candidate in candidates(spec))
    summaries = selection_summaries(spec, rows)
    record = {"format": FORMAT, "spec": asdict(spec), "policy_before": saved,
              "policy_after": add_history(saved, spec, "selection"), "initial_state_rule": INITIAL_STATE_RULE,
              "frozen_before_sha256": before, "frozen_after_sha256": table.fingerprint(),
              "source_sha256": sources(), "rule": RULE, "selection_runs": rows,
              "selection_summaries": summaries, "selected_id": choose(summaries), "selection_traces": traces,
              "scope": "Frozen built-in scalar Q policy, fixed configured initial state, no training. Declared history only, not authenticated provenance or independence"}
    record["record_sha256"] = digest(record)
    return record


def load_policy_selection(record):
    try:
        fields = {"format", "spec", "policy_before", "policy_after", "initial_state_rule", "frozen_before_sha256",
                  "frozen_after_sha256", "source_sha256", "rule", "selection_runs", "selection_summaries",
                  "selected_id", "selection_traces", "scope", "record_sha256"}
        if not isinstance(record, dict) or set(record) != fields or record["format"] != FORMAT:
            raise ValueError("请选择冻结策略流程保存的完整选择记录。")
        if digest({k: v for k, v in record.items() if k != "record_sha256"}) != record["record_sha256"]:
            raise ValueError("选择记录与原摘要不一致，请使用原文件。")
        if record["source_sha256"] != sources():
            raise ValueError("计算代码与选择时不同，请保留原版本复核，不要改写摘要。")
        saved = history_for(record["policy_before"])
        spec = PlannedSpec.from_dict(record["spec"])
        table = compatible(spec, saved)
        fingerprint = table.fingerprint()
        if (record["initial_state_rule"] != INITIAL_STATE_RULE or record["rule"] != RULE
                or record["frozen_before_sha256"] != fingerprint or record["frozen_after_sha256"] != fingerprint
                or digest(history_for(record["policy_after"])) != digest(add_history(saved, spec, "selection"))):
            raise ValueError("策略、初态规则或分阶段历史与选择时不同。")
        expected = [(candidate, seed) for seed in spec.selection_seeds for candidate in candidates(spec)]
        if (not isinstance(record["selection_runs"], list) or len(record["selection_runs"]) != len(expected)
                or not isinstance(record["selection_traces"], dict)
                or set(record["selection_traces"]) != set(map(str, spec.selection_seeds))):
            raise ValueError("选择记录的候选、编号或随机输入不完整。")
        for row, (candidate, seed) in zip(record["selection_runs"], expected):
            config = asdict(configured(spec, candidate, seed))
            expected_controller = {"recipe": "frozen-tabular-q", "initialization_config": config,
                                   "before_sha256": fingerprint, "after_sha256": fingerprint, "learning_updates": 0}
            if (set(row) != {"candidate_id", "seed", "config", "run", "controller"}
                    or row["candidate_id"] != candidate["id"] or type(row["seed"]) is not int or row["seed"] != seed
                    or digest(row["config"]) != digest(config) or digest(row["controller"]) != digest(expected_controller)
                    or row["run"]["policy"] != candidate["policy"]
                    or type(row["run"]["packets"]["attempted"]) is not int
                    or not 0 <= row["run"]["packets"]["attempted"] <= spec.config.budget):
                raise ValueError("选择记录中的控制器、初始化、候选或发送次数不匹配。")
        summaries = selection_summaries(spec, record["selection_runs"])
        if summaries != record["selection_summaries"] or choose(summaries) != record["selected_id"]:
            raise ValueError("保存的结果不符合事先声明的选择规则。")
        return spec, table
    except (KeyError, TypeError, IndexError, AttributeError, OverflowError) as exc:
        raise ValueError("冻结策略选择记录不完整，请使用原样保存的完整文件。") from exc


def test_policy_schedule(record):
    spec, table = load_policy_selection(record)
    result = {"analysis": TEST_FORMAT, "selection": record, "selected_id": record["selected_id"],
              "status": "not_run_no_eligible_choice", "test_runs": [], "test_traces": {},
              "selected_summary": None, "reference_summary": None, "paired_results": [],
              "policy_after": deepcopy(record["policy_after"]),
              "scope": "Same frozen policy and predeclared cap for selected and periodic schedules. No training or reselection; repeating the original choice is replication, not new tests"}
    if record["selected_id"] is None:
        return result
    selected = next(row for row in candidates(spec) if row["id"] == record["selected_id"])
    periodic = candidates(spec)[0]
    for seed in spec.test_seeds:
        trace, _ = make_trace(replace(spec.config, seed=seed))
        result["test_traces"][str(seed)] = trace
        chosen = run_candidate(spec, selected, seed, trace, table)
        chosen["roles"] = ["selected"]
        result["test_runs"].append(chosen)
        if selected["id"] == "periodic":
            reference = chosen
            chosen["roles"].append("periodic_reference")
        else:
            reference = run_candidate(spec, periodic, seed, trace, table)
            reference["roles"] = ["periodic_reference"]
            result["test_runs"].append(reference)
        both = all(row["run"]["status"] == "complete" for row in (chosen, reference))
        result["paired_results"].append({"seed": seed, "both_complete": both,
            "rmse_selected_minus_periodic": (chosen["run"]["metrics"]["position_rmse"]
                - reference["run"]["metrics"]["position_rmse"] if both else None),
            "attempts_selected_minus_periodic": (chosen["run"]["packets"]["attempted"]
                - reference["run"]["packets"]["attempted"] if both else None)})
    result["policy_after"] = add_history(record["policy_after"], spec, "test")
    result["selected_summary"] = summarize([row for row in result["test_runs"] if "selected" in row["roles"]], spec.rmse_limit)
    result["reference_summary"] = summarize([row for row in result["test_runs"] if "periodic_reference" in row["roles"]], spec.rmse_limit)
    result["status"] = "met_declared_tests" if result["selected_summary"]["eligible"] else "did_not_meet_declared_tests"
    return result
