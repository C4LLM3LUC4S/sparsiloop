"""Deterministic grid checks with fixed physical schedules and held-input references."""

import csv
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, localcontext
import hashlib
import json
import math
from pathlib import Path
import platform

from .engine import Config, POLICIES, PROTOCOL, compare


def _integer_ratio(ratio, name):
    nearest = round(ratio)
    if abs(ratio - nearest) > 4 * math.ulp(ratio):
        raise ValueError(f"{name} must align to every sampling grid")
    return nearest


@dataclass(frozen=True)
class GridSpec:
    config: Config = field(default_factory=lambda: Config(
        loss_probability=0, measurement_noise=0, process_noise=0))
    time_steps: tuple = (0.02, 0.01, 0.005)

    def __post_init__(self):
        if not isinstance(self.config, Config):
            raise ValueError("config must be a Config")
        if any(getattr(self.config, key) != 0 for key in
               ("loss_probability", "measurement_noise", "process_noise")):
            raise ValueError("grid check requires zero loss, measurement noise and process noise")
        if not isinstance(self.time_steps, (tuple, list)) or not 2 <= len(self.time_steps) <= 4:
            raise ValueError("time_steps must contain 2..4 decreasing sample intervals")
        object.__setattr__(self, "time_steps", tuple(self.time_steps))
        if any(type(dt) not in (int, float) or not math.isfinite(dt)
               or not 0.002 <= dt <= 0.1 for dt in self.time_steps):
            raise ValueError("time_steps must be finite numbers between 0.002 and 0.1 seconds")
        if any(left <= right for left, right in zip(self.time_steps, self.time_steps[1:])):
            raise ValueError("time_steps must be distinct and decrease from coarse to fine")
        for dt in self.time_steps:
            _integer_ratio(dt / self.time_steps[-1], "nested time steps")
            _integer_ratio(self.config.duration / dt, "duration")
            _integer_ratio(self.config.heartbeat / dt, "heartbeat")
            current = self.at(dt)
            if current.budget and current.steps % current.budget:
                raise ValueError("budget must divide the step count on every grid to keep periodic times fixed")

    @property
    def physical_delay(self):
        return self.config.delay_steps * self.config.dt

    def at(self, dt):
        delay = _integer_ratio(self.physical_delay / dt, "physical delay")
        return replace(self.config, dt=dt, delay_steps=delay)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - {"config", "time_steps"}:
            raise ValueError("grid check accepts only config and time_steps")
        arguments = {key: item for key, item in value.items() if key != "config"}
        if "config" in value:
            arguments["config"] = Config.from_dict(value["config"])
        return cls(**arguments)


def _position_square_integral(plant, state, held_input, duration):
    """Integrate one exported held-input interval, independently of advance()."""
    with localcontext() as context:
        context.prec = 50
        h, u = Decimal(str(duration)), Decimal(str(held_input))
        p = Decimal(str(state[0]))
        if plant == "scalar":
            a = p + u
            return a * a * ((2 * h).exp() - 1) / 2 - 2 * a * u * (h.exp() - 1) + u * u * h
        v = Decimal(str(state[1]))
        return (p * p * h + p * v * h**2 + (v * v + p * u) * h**3 / 3
                + v * u * h**4 / 4 + u * u * h**5 / 20)


def _reference_rmse(config, run):
    if run["status"] != "complete":
        return None
    intervals = run["trajectory"][:-1]
    integral = math.fsum(float(_position_square_integral(
        config.plant, row["state"], row["input"], config.dt)) for row in intervals)
    return math.sqrt(integral / config.duration)


def grid_check(spec=None):
    spec = GridSpec() if spec is None else spec
    runs, summaries = [], []
    for dt in spec.time_steps:
        config = spec.at(dt)
        result = compare(config)
        runs.append({"dt_seconds": dt, "comparison": result})
        for run in result["runs"]:
            reference = _reference_rmse(config, run)
            reported = run["metrics"]["position_rmse"]
            summaries.append({
                "dt_seconds": dt, "policy": run["policy"], "status": run["status"],
                "duration_completed": run["duration_completed"],
                "attempted_packets": run["packets"]["attempted"],
                "reported_position_rmse": reported, "held_input_reference_rmse": reference,
                "rmse_quadrature_error": reported - reference if reference is not None else None,
            })
    finest = runs[-1]["comparison"]
    changes = []
    for item in runs[:-1]:
        stride = _integer_ratio(item["dt_seconds"] / spec.time_steps[-1], "nested time steps")
        for policy, coarse, fine in zip(POLICIES, item["comparison"]["runs"], finest["runs"]):
            complete = coarse["status"] == fine["status"] == "complete"
            max_difference = None
            if complete:
                max_difference = max(abs(a - b)
                    for i, row in enumerate(coarse["trajectory"])
                    for a, b in zip(row["state"], fine["trajectory"][i * stride]["state"]))
            changes.append({
                "policy": policy, "coarse_dt_seconds": item["dt_seconds"],
                "reference_dt_seconds": spec.time_steps[-1], "both_complete": complete,
                "unavailable_reasons": ([] if complete else ["at_least_one_run_incomplete"]),
                "max_state_difference_at_common_times": max_difference,
                "reported_rmse_minus_finest": (
                    coarse["metrics"]["position_rmse"] - fine["metrics"]["position_rmse"]
                    if complete else None),
                "attempted_packets_minus_finest": coarse["packets"]["attempted"] - fine["packets"]["attempted"],
            })
    source = Path(__file__).parent
    return {
        "schema_version": 1, "analysis": "deterministic-nested-grid-check-v1", "protocol": PROTOCOL,
        "python_version": platform.python_version(), "spec": asdict(spec),
        "source_sha256": {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                          for name in ("engine.py", "grid.py")},
        "physical_delay_seconds": spec.physical_delay,
        "scope": {
            "fixed": "Horizon, plant, initial state, gains, packet cap, physical delay, heartbeat and periodic opportunity times",
            "random_processes": "Zero loss and noise required; no cross-grid random-process equivalence is claimed",
            "event_timing": "Event checks occur on each grid and may change transmission times or counts",
            "reference": "50-digit Decimal held-input integrals over exported interval states; position RMSE only",
            "finest_grid": "Comparison reference, not ground truth or a convergence/stability certificate",
            "failure": "Incomplete runs retained; full-horizon references and differences unavailable",
        },
        "runs": runs, "summaries": summaries, "changes_from_finest": changes,
    }


def export_grid_check(result, destination):
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "grid.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    with (destination / "summary.csv").open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result["summaries"][0]))
        writer.writeheader()
        writer.writerows(result["summaries"])
    with (destination / "changes.csv").open("x", encoding="utf-8", newline="") as handle:
        rows = [{**item, "unavailable_reasons": ";".join(item["unavailable_reasons"])}
                for item in result["changes_from_finest"]]
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
