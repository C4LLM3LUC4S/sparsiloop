"""Continue frozen-policy tasks without flattening their chronological history."""

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
from pathlib import Path
import re

from . import planned_context as context, planned_policy as planned, policy
from .controllers import initial_position
from .engine import Config
from .planned_study import PlannedSpec, digest


HISTORY_FORMAT = "sparsiloop-policy-history-v2"
WORKFLOW_FORMAT = "sparsiloop-policy-workflow-v1"
PHASES = {"declared_development", "selection", "test", "evaluation"}


def source_identity():
    return {"policy_journal.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def signed(value, field):
    value[field] = digest({key: item for key, item in value.items() if key != field})
    return value


def checksum(value, field):
    if value.get(field) != digest({key: item for key, item in value.items() if key != field}):
        raise ValueError("记录与原摘要不一致，请找回原文件，不要手动补摘要。")


def origin_history(origin):
    if isinstance(origin, dict) and (origin.get("format") == context.BUNDLE_FORMAT
                                    or origin.get("analysis") == planned.TEST_FORMAT):
        bundle = context.as_bundle(origin)
        record = bundle["result"]
        if bundle["context"]["phase"] != "test" or record.get("analysis") != planned.TEST_FORMAT:
            raise ValueError("起点需要完整的冻结策略复核记录，不能用尚未复核的选择记录代替。")
        _validate_test(record)
        return planned.history_for(record["policy_after"])
    return planned.history_for(origin)


def _checkpoint(origin):
    return origin_history(origin)["checkpoint"]


def _compatible(config, saved):
    _, trained, _ = policy.load_checkpoint(saved)
    for key in ("plant", "dt", "duration", "input_limit"):
        if getattr(config, key) != getattr(trained, key):
            raise ValueError(f"请保留训练时的 {key}；相同步数不能代替相同物理时间。")


def _history_for(value):
    """Keep the supplied v1 origin intact and validate every subsequent used seed."""
    if isinstance(value, dict) and (value.get("format") in (policy.FORMAT, planned.HISTORY_FORMAT, context.BUNDLE_FORMAT)
                                    or value.get("analysis") == planned.TEST_FORMAT):
        saved = _checkpoint(value)
        return signed({"format": HISTORY_FORMAT, "origin": deepcopy(value),
                       "checkpoint": deepcopy(saved), "events": []}, "history_sha256")
    fields = {"format", "origin", "checkpoint", "events", "history_sha256"}
    if not isinstance(value, dict) or set(value) != fields or value["format"] != HISTORY_FORMAT:
        raise ValueError("请载入完整策略、原计划历史，或这条流程保存的 policy-history.json。")
    checksum(value, "history_sha256")
    original = _checkpoint(value["origin"])
    expected = deepcopy(original)
    used = list(original["previous_evaluation_seeds"])
    training = set(original["training_seeds"])
    pending = {}
    events = value["events"]
    if not isinstance(events, list) or len(events) > 512:
        raise ValueError("接续历史最多保留 512 个阶段，请保留完整原记录。")
    for event in events:
        if (not isinstance(event, dict) or set(event) !=
                {"phase", "seeds", "result_sha256", "config", "plan", "selected_id", "runtime"}
                or not isinstance(event["phase"], str) or event["phase"] not in PHASES
                or not isinstance(event["result_sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", event["result_sha256"])
                or event["selected_id"] is not None and not isinstance(event["selected_id"], str)):
            raise ValueError("阶段记录字段不完整，请使用原样保存的文件。")
        phase = event["phase"]
        seeds = policy.seed_list(event["seeds"], "阶段编号")
        if set(seeds) & (set(used) | training):
            raise ValueError("阶段编号与训练或已用编号重复，请保留完整历史并换新编号。")
        config = Config.from_dict(event["config"])
        _compatible(config, original)
        reserved = {seed for group, _ in pending.values() for seed in group}
        if phase == "evaluation":
            if event["plan"] is not None or event["selected_id"] is not None or set(seeds) & reserved:
                raise ValueError("单独评测不能使用已有计划预留的复核编号。")
        else:
            spec = PlannedSpec.from_dict(event["plan"])
            plan_id = digest(asdict(spec))
            if digest(asdict(spec.config)) != digest(event["config"]):
                raise ValueError("阶段条件与计划不一致。")
            if phase == "declared_development":
                if (event["selected_id"] is not None or event["runtime"] is not None
                        or event["result_sha256"] != plan_id
                        or not set(seeds) <= set(spec.previously_used_seeds) or set(seeds) & reserved):
                    raise ValueError("补充的开发编号只是声明，不能记作本次仿真。")
            elif phase == "selection":
                ids = {row["id"] for row in planned.candidates(spec)}
                if (seeds != list(spec.selection_seeds) or event["selected_id"] not in ids | {None}
                        or set(seeds + list(spec.test_seeds)) & (reserved | set(used) | training)):
                    raise ValueError("选择与预留测试编号不符合原声明。")
                if event["selected_id"] is not None:
                    pending[plan_id] = (list(spec.test_seeds), event["selected_id"])
            elif (seeds != list(spec.test_seeds)
                  or pending.get(plan_id) != (seeds, event["selected_id"]) or event["selected_id"] is None):
                raise ValueError("复核阶段缺少对应的选择与预留编号。")
            else:
                del pending[plan_id]
        if phase != "declared_development":
            context.validate_runtime(event["runtime"])
        used.extend(seeds)
    if len(used) > 512:
        raise ValueError("接续后会超过 512 个已用编号，请缩小本次任务并保留旧历史。")
    expected["previous_evaluation_seeds"] = used
    signed(expected, "checkpoint_sha256")
    policy.load_checkpoint(value["checkpoint"])
    if digest(expected) != digest(value["checkpoint"]):
        raise ValueError("阶段历史与完整策略的编号、Q表或训练条件对不上。")
    return deepcopy(value)


def history_for(value):
    try:
        return _history_for(value)
    except (KeyError, TypeError, IndexError, AttributeError, OverflowError) as exc:
        raise ValueError("策略历史字段不完整，请使用原样保存的完整文件。") from exc


def reserved_seeds(value):
    pending = {}
    for event in value["events"]:
        if event["phase"] == "selection" and event["selected_id"] is not None:
            pending[digest(event["plan"])] = event["plan"]["test_seeds"]
        elif event["phase"] == "test":
            pending.pop(digest(event["plan"]), None)
    return {seed for group in pending.values() for seed in group}


def _fresh(value, seeds):
    saved = value["checkpoint"]
    if set(seeds) & set(saved["training_seeds"] + saved["previous_evaluation_seeds"]):
        raise ValueError("这些编号已经用过，请保留历史并换新编号。")
    if set(seeds) & reserved_seeds(value):
        raise ValueError("这些编号留给了已有计划的复核，请使用其他新编号。")


def _ready(value):
    if reserved_seeds(value):
        raise ValueError("这份历史还有待复核计划。请先用选择阶段的 policy-workflow.json 按原条件复核，再继续新任务。")
    origin = value["origin"]
    if isinstance(origin, dict) and origin.get("format") == planned.HISTORY_FORMAT:
        phases = origin["planned_history"]
        if phases and phases[-1]["phase"] == "selection":
            raise ValueError("原历史只记到选择阶段，无法判断预留测试是否运行。请先完成原复核，再载入完整 test-bundle.json；没有合格项时也保存明确未运行的记录。")


def _event(phase, seeds, result, config, runtime, spec=None, selected_id=None):
    return {"phase": phase, "seeds": list(seeds), "result_sha256": digest(result),
            "config": asdict(config), "plan": asdict(spec) if spec else None,
            "selected_id": selected_id, "runtime": deepcopy(runtime)}


def _validate_test(record):
    selection = record["selection"]
    spec, table = planned.load_policy_selection(selection)
    chosen = selection["selected_id"]
    if record["selected_id"] != chosen or record.get("analysis") != planned.TEST_FORMAT:
        raise ValueError("复核没有沿用原选择。")
    if chosen is None:
        if (record["test_runs"] or record["test_traces"] or record["paired_results"]
                or record["status"] != "not_run_no_eligible_choice"
                or record["selected_summary"] is not None or record["reference_summary"] is not None):
            raise ValueError("未选到方案的记录不能包含已运行测试。")
        expected = selection["policy_after"]
    else:
        expected = planned.add_history(selection["policy_after"], spec, "test")
        if (record["status"] not in ("met_declared_tests", "did_not_meet_declared_tests")
                or set(record["test_traces"]) != set(map(str, spec.test_seeds))):
            raise ValueError("复核的运行状态或随机输入编号不完整。")
        candidates = {candidate["id"]: candidate for candidate in planned.candidates(spec)}
        ids = [chosen] if chosen == "periodic" else [chosen, "periodic"]
        pairs = [(seed, candidate) for seed in spec.test_seeds for candidate in ids]
        if len(record["test_runs"]) != len(pairs):
            raise ValueError("复核运行数量与原声明不一致。")
        for row, (seed, candidate) in zip(record["test_runs"], pairs):
            config = asdict(planned.configured(spec, candidates[candidate], seed))
            if (type(row["seed"]) is not int or row["seed"] != seed or row["candidate_id"] != candidate
                    or digest(row["config"]) != digest(config)
                    or row["controller"]["before_sha256"] != table.fingerprint()
                    or row["controller"]["after_sha256"] != table.fingerprint()
                    or row["controller"]["learning_updates"] != 0):
                raise ValueError("复核运行的编号、初态或冻结策略与原声明不一致。")
    if digest(record["policy_after"]) != digest(expected):
        raise ValueError("复核后的阶段历史没有对应实际运行的编号。")


def _after(before, phase, data, runtime):
    result = deepcopy(before)
    saved = result["checkpoint"]
    if phase == "evaluation":
        events = [_event(phase, data["evaluation_seeds"], data,
                         Config.from_dict(data["evaluation_config"]), runtime)]
    else:
        record = data["result"]
        selection = record if phase == "selection" else record["selection"]
        spec = PlannedSpec.from_dict(selection["spec"])
        events = []
        if phase == "selection":
            used = set(saved["training_seeds"] + saved["previous_evaluation_seeds"])
            declared = [seed for seed in spec.previously_used_seeds if seed not in used]
            if declared:
                events.append(_event("declared_development", declared, asdict(spec), spec.config, None, spec))
            events.append(_event(phase, spec.selection_seeds, record, spec.config, runtime,
                                 spec, record["selected_id"]))
        elif record["test_runs"]:
            events.append(_event(phase, spec.test_seeds, record, spec.config, runtime,
                                 spec, record["selected_id"]))
    result["events"].extend(events)
    saved["previous_evaluation_seeds"] += [seed for event in events for seed in event["seeds"]]
    signed(saved, "checkpoint_sha256")
    signed(result, "history_sha256")
    return history_for(result)


def _validate_data(phase, before, data):
    saved = before["checkpoint"]
    if phase == "evaluation":
        if (not isinstance(data, dict) or data.get("analysis") != "frozen-policy-evaluation-v1"
                or digest(data["checkpoint"]) != digest(saved)):
            raise ValueError("单独评测不属于这份策略历史。")
        seeds = policy.seed_list(data["evaluation_seeds"], "测试编号")
        _fresh(before, seeds)
        config = Config.from_dict(data["evaluation_config"])
        _compatible(config, saved)
        if (data["frozen_before_sha256"] != saved["table_sha256"]
                or data["frozen_after_sha256"] != saved["table_sha256"] or len(data["cases"]) != len(seeds)):
            raise ValueError("评测中的冻结策略或运行数量不一致。")
        for seed, case in zip(seeds, data["cases"]):
            expected = asdict(replace(config, seed=seed, initial_position=initial_position(seed)))
            if (type(case["seed"]) is not int or case["seed"] != seed
                    or any(digest(case[key]["config"]) != digest(expected)
                           or len(case[key]["runs"]) != 3 for key in ("policy", "linear_feedback"))):
                raise ValueError("单独评测的初态、条件或参考运行不符合原协议。")
        return
    bundle = context.as_bundle(data)
    if bundle["context"]["phase"] != phase:
        raise ValueError("运行记录与接续阶段不一致。")
    record = bundle["result"]
    selection = record if phase == "selection" else record["selection"]
    spec, _ = planned.load_policy_selection(selection)
    if phase == "selection":
        _fresh(before, list(spec.selection_seeds + spec.test_seeds))
        if digest(selection["policy_before"]["checkpoint"]) != digest(saved):
            raise ValueError("这份选择记录使用了另一条策略历史。")
    else:
        _validate_test(record)
        if digest(selection["policy_after"]["checkpoint"]) != digest(saved):
            raise ValueError("这份复核记录没有接在原选择阶段之后。")


def _workflow(phase, before, data, runtime):
    _validate_data(phase, before, data)
    return signed({"format": WORKFLOW_FORMAT, "phase": phase, "history_before": before,
                   "history_after": _after(before, phase, data, runtime), "data": data,
                   "execution_runtime": runtime, "source_sha256": source_identity()}, "record_sha256")


def load_workflow(value):
    try:
        fields = {"format", "phase", "history_before", "history_after", "data", "execution_runtime",
                  "source_sha256", "record_sha256"}
        if (not isinstance(value, dict) or set(value) != fields or value["format"] != WORKFLOW_FORMAT
                or value["phase"] not in {"selection", "test", "evaluation"}):
            raise ValueError("请载入完整 policy-workflow.json；单独的数值记录不能代替接续记录。")
        checksum(value, "record_sha256")
        if value["source_sha256"] != source_identity():
            raise ValueError("接续代码与保存时不同，请保留原版本重绘或复核，不要改写摘要。")
        before = history_for(value["history_before"])
        history_for(value["history_after"])
        _validate_data(value["phase"], before, value["data"])
        runtime = value["execution_runtime"]
        if value["phase"] != "evaluation":
            actual = value["data"]["context"][value["phase"]]["runtime"]
            if runtime != actual:
                raise ValueError("接续环境与实际阶段记录不一致。")
        if runtime is not None:
            context.validate_runtime(runtime)
        elif value["phase"] != "test" or value["data"]["result"]["test_runs"]:
            raise ValueError("已运行的阶段不能缺少环境记录。")
        if digest(_after(before, value["phase"], value["data"], runtime)) != digest(value["history_after"]):
            raise ValueError("接续后的阶段历史与本次结果不一致。")
        return deepcopy(value)
    except (KeyError, TypeError, IndexError, AttributeError, OverflowError) as exc:
        raise ValueError("接续记录不完整，请使用原样保存的完整文件。") from exc


def evaluate_saved(value, seeds, config=None):
    before = history_for(value)
    _ready(before)
    seeds = policy.seed_list(seeds, "新测试编号")
    _fresh(before, seeds)
    runtime = context.runtime_info()
    data = policy.evaluate_policy(before["checkpoint"], seeds, config)
    return _workflow("evaluation", before, data, runtime)


def select_plan(spec, value):
    if not isinstance(spec, PlannedSpec):
        raise ValueError("请先用 PlannedSpec 声明完整方案。")
    before = history_for(value)
    _ready(before)
    _fresh(before, list(spec.selection_seeds + spec.test_seeds))
    declared = set(spec.previously_used_seeds) - set(before["checkpoint"]["previous_evaluation_seeds"])
    if declared & reserved_seeds(before):
        raise ValueError("开发声明用了其他计划预留的复核编号，请先核对记录。")
    data = context.select_with_context(spec, policy_checkpoint=before["checkpoint"])
    return _workflow("selection", before, data, data["context"]["selection"]["runtime"])


def test_plan(value):
    selection = load_workflow(value)
    if selection["phase"] != "selection":
        raise ValueError("按原计划复核需要选择阶段的 policy-workflow.json。")
    data = context.test_with_context(selection["data"])
    return _workflow("test", selection["history_after"], data, data["context"]["test"]["runtime"])


if __name__ == "__main__":
    from .policy_journal_cli import main

    raise SystemExit(main())
