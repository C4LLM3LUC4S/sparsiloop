"""Descriptive, post-hoc periodic references at equal attempted packet counts."""

import csv
from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
import math
from pathlib import Path
import platform

from .engine import Config, LinearFeedback, PROTOCOL, make_trace, simulate


@dataclass(frozen=True)
class StudySpec:
    config: Config = field(default_factory=Config)
    thresholds: tuple = (0.02, 0.06, 0.12, 0.24)
    seeds: tuple | None = None

    def __post_init__(self):
        if not isinstance(self.config, Config):
            raise ValueError("config must be a Config")
        if self.seeds is None:
            object.__setattr__(self, "seeds", (self.config.seed,))
        for name, maximum in (("thresholds", 8), ("seeds", 5)):
            values = getattr(self, name)
            if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= maximum:
                raise ValueError(f"{name} must contain 1..{maximum} values")
            object.__setattr__(self, name, tuple(values))
        for value in self.thresholds:
            if (type(value) not in (int, float) or not 0 <= value <= 2
                    or not math.isfinite(value)):
                raise ValueError("thresholds must be finite numbers between 0 and 2")
        if any(type(value) is not int or not 0 <= value < 2**32 for value in self.seeds):
            raise ValueError("seeds must be 32-bit nonnegative integers")
        if len(set(self.thresholds)) != len(self.thresholds) or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("duplicate thresholds or seeds are not independent repetitions")
        # Two event policies, each with its own periodic reference. Bound even failed cases.
        if 4 * len(self.thresholds) * len(self.seeds) * self.config.steps > 120000:
            raise ValueError("study exceeds 120000 simulation steps; reduce seeds, thresholds or horizon")

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - {"config", "thresholds", "seeds"}:
            raise ValueError("study accepts only config, thresholds and seeds")
        arguments = {key: item for key, item in value.items() if key != "config"}
        return cls(config=Config.from_dict(value.get("config", {})), **arguments)


def study(spec=None, controller_factory=None, *, plant=None):
    spec = StudySpec() if spec is None else spec
    factory = LinearFeedback if controller_factory is None else controller_factory
    runs, pairs, traces = {}, [], {}
    for seed in spec.seeds:
        for threshold in spec.thresholds:
            config = replace(spec.config, seed=seed, threshold=threshold)
            trace, _ = make_trace(config)
            traces[str(seed)] = trace
            for policy in ("absolute", "relative"):
                identifier = f"pair-{len(pairs) + 1:03d}"
                event_id, reference_id = identifier + "-event", identifier + "-reference"
                event = simulate(config, policy, factory(config), trace, plant=plant)
                reference_config = replace(config, budget=event["packets"]["attempted"])
                # Transport budget changes; controller and model initialization stay identical.
                reference = simulate(reference_config, "periodic", factory(config), trace,
                                     plant=plant, plant_config=config)
                runs[event_id] = {"config": asdict(config), "controller_factory_config": asdict(config), "result": event}
                runs[reference_id] = {"config": asdict(reference_config), "controller_factory_config": asdict(config), "result": reference}
                matched = event["packets"]["attempted"] == reference["packets"]["attempted"]
                reasons = []
                if event["status"] != "complete":
                    reasons.append("event_failed")
                if reference["status"] != "complete":
                    reasons.append("reference_failed")
                if not matched:
                    reasons.append("attempted_count_mismatch")
                if event["trace_sha256"] != reference["trace_sha256"]:
                    reasons.append("exogenous_trace_mismatch")
                pairs.append({
                    "id": identifier, "policy": policy, "seed": seed, "threshold": threshold,
                    "event_run": event_id, "reference_run": reference_id,
                    "reference_budget": reference_config.budget, "traffic_matched": matched,
                    "eligible": not reasons, "unavailable_reasons": reasons,
                    "rmse_delta_event_minus_periodic": (
                        event["metrics"]["position_rmse"] - reference["metrics"]["position_rmse"]
                        if not reasons else None),
                })
    summaries = []
    for policy in ("absolute", "relative"):
        for threshold in spec.thresholds:
            group = [pair for pair in pairs if pair["policy"] == policy and pair["threshold"] == threshold]
            eligible = [pair for pair in group if pair["eligible"]]
            mean = (math.fsum(pair["rmse_delta_event_minus_periodic"] for pair in eligible) / len(eligible)
                    if eligible else None)
            summaries.append({
                "policy": policy, "threshold": threshold, "requested_pairs": len(group),
                "eligible_pairs": len(eligible),
                "failed_event_runs": sum("event_failed" in pair["unavailable_reasons"] for pair in group),
                "failed_reference_runs": sum("reference_failed" in pair["unavailable_reasons"] for pair in group),
                "unmatched_traffic_pairs": sum(not pair["traffic_matched"] for pair in group),
                "all_seed_mean_rmse_delta": mean if len(eligible) == len(group) else None,
                "eligible_subset_mean_rmse_delta": mean,
                "eligible_seeds": [pair["seed"] for pair in eligible],
            })
    source = Path(__file__).parent
    result = {
        "schema_version": 1, "engine_version": "0.0.1", "protocol": PROTOCOL,
        "analysis": "posthoc-attempted-packet-reference-v1",
        "python_version": platform.python_version(),
        "source_sha256": {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                          for name in ("engine.py", "study.py")},
        "controller": "LinearFeedback" if controller_factory is None else "custom_local_factory",
        "scope": {
            "reference_budget": "Selected after each event run, separately for each seed and threshold",
            "matched_resource": "Attempted sensor-to-controller packets, including losses and in-flight packets",
            "not_matched": "Delivered counts, observation times, age, detector work, bytes and energy",
            "interpretation": "Descriptive paired cases; not prospective tuning, independent test data or superiority evidence",
            "threshold_scan": "All supplied thresholds retained; no automatic best-threshold selection",
            "controller_initialization": "Two fresh instances from the same event configuration in each pair; reference budget changes transport only",
        },
        "spec": asdict(spec), "exogenous_traces": traces, "runs": runs,
        "pairs": pairs, "summaries": summaries,
    }
    if plant is not None:
        result["plant"] = plant.metadata()
        result["scope"]["plant_initialization"] = "Fresh model from the same event configuration for each side; only the transport budget changes"
    return result


def comparison_rows(result):
    for pair in result["pairs"]:
        event = result["runs"][pair["event_run"]]["result"]
        reference = result["runs"][pair["reference_run"]]["result"]
        row = {key: pair[key] for key in ("id", "policy", "seed", "threshold", "reference_budget", "traffic_matched", "eligible")}
        row["unavailable_reasons"] = ";".join(pair["unavailable_reasons"])
        for label, run in (("event", event), ("reference", reference)):
            row[label + "_status"] = run["status"]
            row[label + "_duration_completed"] = run["duration_completed"]
            row[label + "_rmse"] = run["metrics"]["position_rmse"]
            for key, value in run["packets"].items():
                row[label + "_" + key] = value
        row["rmse_delta_event_minus_periodic"] = pair["rmse_delta_event_minus_periodic"]
        yield row


def export_study(result, destination):
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "study.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    rows = list(comparison_rows(result))
    with (destination / "comparisons.csv").open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (destination / "trajectories.csv").open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["run_id", "policy", "seed", "threshold", "budget", "t_s", "position",
                         "velocity", "input", "seen_position", "seen_velocity", "age_s", "sent", "dropped", "delivered"])
        for identifier, item in result["runs"].items():
            run, config = item["result"], item["config"]
            for row in run["trajectory"]:
                state, seen = row["state"], row["controller_values"]
                writer.writerow([identifier, run["policy"], config["seed"], config["threshold"], config["budget"],
                                 row["t"], state[0], state[1] if len(state) > 1 else "", row["input"],
                                 seen[0] if seen is not None else "",
                                 seen[1] if seen is not None and len(seen) > 1 else "",
                                 row["observation_age"], int(row["sent"]), int(row["dropped"]), row["delivered"]])
