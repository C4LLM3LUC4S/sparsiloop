"""Explicit local models in planned comparisons; legacy built-in records stay unchanged."""

from dataclasses import asdict, replace
import hashlib
from pathlib import Path

from . import engine, models, planned_study
from .engine import make_trace, simulate
from .models import PlantAdapter
from .planned_study import (PlannedSpec, RULE, candidates, choose, configured, digest,
                            selection_summaries, summarize)


FORMAT = "sparsiloop-planned-model-selection-v1"
TEST_FORMAT = "planned-model-budget-test-v1"


def sources():
    return {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for name, module in (("engine.py", engine), ("models.py", models),
                                 ("planned_study.py", planned_study))} | {
        "planned_models.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def model_metadata(plant, config):
    if not isinstance(plant, PlantAdapter):
        raise ValueError("请在本地重新构建原模型，并传入 plant=模型；JSON 不包含可执行的模型代码。")
    plant.validate(config)
    value = plant.metadata()
    if value["source_sha256"] is None:
        raise ValueError("先为模型声明 source_sha256，再保存选择记录；来源摘要仍由使用者负责核对。")
    return value


def run_candidate(spec, candidate, seed, trace, plant):
    config = configured(spec, candidate, seed)
    run = simulate(config, candidate["policy"], trace=trace, plant=plant)
    return {"candidate_id": candidate["id"], "seed": seed, "config": asdict(config), "run": run}


def select_model_schedule(spec, *, plant):
    """Use only selection seeds; initialize the supplied model afresh for every run."""
    if not isinstance(spec, PlannedSpec):
        raise ValueError("请用 PlannedSpec 声明方案，再开始选择。")
    metadata = model_metadata(plant, spec.config)
    rows, traces = [], {}
    for seed in spec.selection_seeds:
        trace, _ = make_trace(replace(spec.config, seed=seed))
        traces[str(seed)] = trace
        rows.extend(run_candidate(spec, candidate, seed, trace, plant) for candidate in candidates(spec))
    summaries = selection_summaries(spec, rows)
    record = {"format": FORMAT, "spec": asdict(spec), "model": metadata,
              "source_sha256": sources(), "rule": RULE, "selection_runs": rows,
              "selection_summaries": summaries, "selected_id": choose(summaries),
              "selection_traces": traces,
              "scope": "Local declared model and fixed LinearFeedback; zero target for first-state RMSE. No controller training or provenance certification"}
    record["record_sha256"] = digest(record)
    return record


def load_model_selection(record, *, plant):
    """Check the declared model and fixed choice before any test simulation."""
    try:
        expected = {"format", "spec", "model", "source_sha256", "rule", "selection_runs",
                    "selection_summaries", "selected_id", "selection_traces", "scope", "record_sha256"}
        if not isinstance(record, dict) or set(record) != expected or record["format"] != FORMAT:
            raise ValueError("请选择本地模型流程保存的完整选择记录，不能用内置模型的记录替代。")
        if digest({k: v for k, v in record.items() if k != "record_sha256"}) != record["record_sha256"]:
            raise ValueError("选择记录与保存时的摘要不一致，请使用原文件，不要补写摘要。")
        if record["source_sha256"] != sources():
            raise ValueError("计算代码与选择时不同，请保留原版本复核，不要修改来源摘要。")
        spec = PlannedSpec.from_dict(record["spec"])
        if digest(model_metadata(plant, spec.config)) != digest(record["model"]):
            raise ValueError("模型参数、单位或来源与选择时不同；请重新构建原模型，不会退回内置模型。")
        expected_rows = [(candidate, seed) for seed in spec.selection_seeds for candidate in candidates(spec)]
        if (not isinstance(record["selection_runs"], list)
                or len(record["selection_runs"]) != len(expected_rows) or record["rule"] != RULE
                or not isinstance(record["selection_traces"], dict)
                or set(record["selection_traces"]) != set(map(str, spec.selection_seeds))):
            raise ValueError("选择记录的候选、编号或规则不完整。")
        for row, (candidate, seed) in zip(record["selection_runs"], expected_rows):
            run, config = row["run"], asdict(configured(spec, candidate, seed))
            if (set(row) != {"candidate_id", "seed", "config", "run"}
                    or row["candidate_id"] != candidate["id"] or type(row["seed"]) is not int or row["seed"] != seed
                    or digest(row["config"]) != digest(config) or run["policy"] != candidate["policy"]
                    or run["plant"] != record["model"] or digest(run["plant_initialization_config"]) != digest(config)
                    or run["plant_adapter_source_sha256"] != record["source_sha256"]["models.py"]
                    or type(run["packets"]["attempted"]) is not int
                    or not 0 <= run["packets"]["attempted"] <= spec.config.budget):
                raise ValueError("选择记录中的模型、初始化、候选、编号或发送次数不匹配。")
        summaries = selection_summaries(spec, record["selection_runs"])
        if summaries != record["selection_summaries"] or choose(summaries) != record["selected_id"]:
            raise ValueError("保存的选择结果不符合原先声明的规则。")
        return spec
    except (KeyError, TypeError, IndexError, AttributeError, OverflowError) as exc:
        raise ValueError("本地模型选择记录不完整，请使用原样保存的完整文件。") from exc


def test_model_schedule(record, *, plant):
    """Require an explicit matching model; never reselect or infer executable code."""
    spec = load_model_selection(record, plant=plant)
    result = {"analysis": TEST_FORMAT, "selection": record, "selected_id": record["selected_id"],
              "status": "not_run_no_eligible_choice", "test_runs": [], "test_traces": {},
              "selected_summary": None, "reference_summary": None, "paired_results": [],
              "scope": "Explicit matching local model; no reselection or training. Same predeclared cap, not matched actual traffic"}
    if record["selected_id"] is None:
        return result
    selected = next(row for row in candidates(spec) if row["id"] == record["selected_id"])
    periodic = candidates(spec)[0]
    for seed in spec.test_seeds:
        trace, _ = make_trace(replace(spec.config, seed=seed))
        result["test_traces"][str(seed)] = trace
        chosen = run_candidate(spec, selected, seed, trace, plant)
        chosen["roles"] = ["selected"]
        result["test_runs"].append(chosen)
        if selected["id"] == "periodic":
            reference = chosen
            chosen["roles"].append("periodic_reference")
        else:
            reference = run_candidate(spec, periodic, seed, trace, plant)
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
