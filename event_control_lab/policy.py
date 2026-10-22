"""Save a built-in teaching policy with its clock and evaluate without training."""

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

from . import controllers, engine, models
from .controllers import QController, QTable
from .controller_lab import initial_position
from .engine import Config, compare


FORMAT = "sparsiloop-frozen-policy-v1"


def checkpoint_digest(value):
    body = {key: item for key, item in value.items() if key != "checkpoint_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def source_identity():
    paths = {name: Path(module.__file__) for name, module in
             (("engine", engine), ("models", models), ("controllers", controllers))}
    paths.update(controller_lab=Path(__file__).with_name("controller_lab.py"), policy=Path(__file__))
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


def checkpoint(result):
    if "plant" in result:
        raise ValueError("Standalone policy evaluation currently supports the built-in scalar model only")
    case = result["cases"]["rl"]
    sources = source_identity()
    if any(result["source_sha256"].get(key) != digest for key, digest in sources.items() if key != "policy"):
        raise ValueError("Training result came from different source code; preserve its original environment")
    value = {"format": FORMAT, "training_config": result["specification"]["config"],
            "evaluation_config": case["evaluation"][0]["trained"]["config"],
            "training_seeds": case["training_seeds"], "previous_evaluation_seeds": case["evaluation_seeds"],
            "source_sha256": sources,
            "table": case["frozen_table"], "table_sha256": case["frozen_sha256"],
            "training_statuses": [row["run"]["status"] for row in case["training"]],
            "selection": case["selection"]}
    value["checkpoint_sha256"] = checkpoint_digest(value)
    return value


def seed_list(value, name):
    if (not isinstance(value, list) or not 1 <= len(value) <= 512
            or any(type(x) is not int or not 0 <= x < 2**32 for x in value)
            or len(set(value)) != len(value)):
        raise ValueError(f"{name}: use 1..512 distinct integer seeds in 0..2**32-1")
    return value


def load_checkpoint(value):
    fields = {"format", "training_config", "evaluation_config", "training_seeds", "previous_evaluation_seeds",
              "source_sha256", "table", "table_sha256", "training_statuses", "selection", "checkpoint_sha256"}
    if not isinstance(value, dict) or set(value) != fields or value["format"] != FORMAT:
        raise ValueError("Use policy-checkpoint.json; the old policy.json table has no physical-time metadata")
    json.dumps(value, allow_nan=False)
    if checkpoint_digest(value) != value["checkpoint_sha256"]:
        raise ValueError("Checkpoint metadata checksum differs: use the original saved file")
    if not isinstance(value["selection"], str):
        raise ValueError("Policy selection record must be text")
    train = Config.from_dict(value["training_config"])
    base = Config.from_dict(value["evaluation_config"])
    table = QTable.from_snapshot(value["table"])
    if train.plant != "scalar" or table.steps != train.steps or table.input_limit != train.input_limit:
        raise ValueError("Policy table does not match the declared training model, horizon or input limit")
    for key in ("plant", "dt", "duration", "input_limit"):
        if getattr(base, key) != getattr(train, key):
            raise ValueError(f"Evaluation must retain the trained {key}")
    training = seed_list(value["training_seeds"], "training_seeds")
    previous = seed_list(value["previous_evaluation_seeds"], "previous_evaluation_seeds")
    if set(training) & set(previous):
        raise ValueError("Training and previous evaluation seeds overlap")
    if (not isinstance(value["training_statuses"], list)
            or len(value["training_statuses"]) != len(training)
            or any(not isinstance(x, str) or x not in {"complete", "state_limit", "controller_error", "plant_error"}
                   for x in value["training_statuses"])):
        raise ValueError("Training status records do not match the declared episodes")
    if table.fingerprint() != value["table_sha256"]:
        raise ValueError("Policy checksum differs: use the original saved checkpoint")
    if value["source_sha256"] != source_identity():
        raise ValueError("Simulation/controller source differs: use the original code version; this is not a quality judgment")
    return table, train, base


def evaluate_policy(value, seeds, config=None):
    """Evaluate declared fresh seeds; do not update or select a policy."""
    table, training_config, base = load_checkpoint(value)
    seeds = seed_list(seeds, "new evaluation seeds")
    if set(seeds) & set(value["training_seeds"] + value["previous_evaluation_seeds"]):
        raise ValueError("Use new seeds, separate from training and previous evaluation")
    base = base if config is None else config
    if not isinstance(base, Config):
        raise ValueError("Evaluation config must be a Config")
    for key in ("plant", "dt", "duration", "input_limit"):
        if getattr(base, key) != getattr(training_config, key):
            raise ValueError(f"Evaluation must retain the trained {key}; equal step counts alone are insufficient")
    if len(seeds) * 6 * base.steps > 100000:
        raise ValueError("Evaluation exceeds 100000 simulation intervals; use fewer seeds or the trained shorter horizon")
    before = table.fingerprint()
    cases = []
    configs = []
    for seed in seeds:
        try:
            configs.append(replace(base, seed=seed, initial_position=initial_position(seed)))
        except ValueError as exc:
            raise ValueError(f"Seed {seed} cannot start under this config: {exc}") from exc
    for seed, current in zip(seeds, configs):
        cases.append({"seed": seed, "policy": compare(current, lambda c: QController(c, table)),
                      "linear_feedback": compare(current)})
    after = table.fingerprint()
    if before != after:
        raise ValueError("Evaluation changed the saved policy")
    return {"analysis": "frozen-policy-evaluation-v1", "checkpoint": value,
            "evaluation_config": asdict(base), "evaluation_seeds": seeds, "cases": cases,
            "frozen_before_sha256": before, "frozen_after_sha256": after,
            "scope": "New declared seeds; no training or selection. Not evidence of stability or general superiority"}


def read_checkpoint(path):
    with Path(path).open("rb") as handle:
        data = handle.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("Checkpoint is too large (maximum 20 MiB)")
    value = json.loads(data.decode("utf-8-sig"))
    return value, hashlib.sha256(data).hexdigest()


def export_evaluation(result, destination):
    # Reuse the existing offline report writer without pretending that training ran again.
    from .controller_lab import export_controller_lab

    view = {"cases": {"rl": {"training": [], "frozen_table": result["checkpoint"]["table"],
                              "evaluation": [{"seed": case["seed"], "trained": case["policy"],
                                              "linear_feedback": case["linear_feedback"]}
                                             for case in result["cases"]]}},
            "evaluation_only": True, "source_checkpoint": result["checkpoint"],
            "evaluation_seeds": result["evaluation_seeds"],
            "frozen_before_sha256": result["frozen_before_sha256"],
            "frozen_after_sha256": result["frozen_after_sha256"]}
    export_controller_lab(view, destination)
    folder = Path(destination)
    (folder / "evaluation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                            encoding="utf-8")
