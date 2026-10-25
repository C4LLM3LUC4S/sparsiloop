"""Connect the pinned simple-pid controller to delivered simulation observations."""

import argparse
from dataclasses import asdict
import hashlib
from importlib import metadata
import json
import math
from pathlib import Path
import sys

from event_control_lab import Config, compare
from event_control_lab.__main__ import export
from event_control_lab.engine import POLICIES
from event_control_lab.output_paths import check_new_output


PINNED_VERSION = "2.0.1"


def load_pid():
    try:
        version = metadata.version("simple-pid")
        if version != PINNED_VERSION:
            raise ValueError(f"This recipe checks simple-pid=={PINNED_VERSION}; found {version}")
        from simple_pid import PID
        return PID
    except (metadata.PackageNotFoundError, ImportError) as exc:
        raise ValueError("Optional example requires: python -m pip install -r examples/requirements-simple-pid.txt") from exc


class PIDAdapter:
    def __init__(self, config, ki=0.1, kd=0.05):
        if any(type(value) not in (int, float) or not math.isfinite(value)
               or not 0 <= value <= 20 for value in (ki, kd)):
            raise ValueError("PID Ki and Kd must be finite gains between 0 and 20")
        self.config, self.ki = config, ki
        self.clock, self.last_arrival, self.updates = 0.0, None, []
        # The first received measurement initializes P; no unobserved past error is integrated.
        self.pid = load_pid()(config.kp, 0, kd, setpoint=0, sample_time=None,
                              output_limits=(-config.input_limit, config.input_limit),
                              time_fn=lambda: self.clock)

    def __call__(self, observation):
        values = observation.values
        times = (observation.sample_time, observation.arrival_time)
        if (len(values) != len(self.config.initial_state)
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for value in (*values, *times))
                or not 0 <= observation.sample_time <= observation.arrival_time):
            raise ValueError("PID requires finite, causal delivered observations of the configured dimension")
        elapsed = None if self.last_arrival is None else observation.arrival_time - self.last_arrival
        if elapsed is not None and elapsed <= 0:
            raise ValueError("PID observation arrivals must increase strictly")
        self.clock = observation.arrival_time
        output = self.pid(values[0], dt=self.config.dt if elapsed is None else elapsed)
        if elapsed is None:
            self.pid.Ki = self.ki
        self.last_arrival = observation.arrival_time
        self.updates.append({
            "sample_time": observation.sample_time, "arrival_time": observation.arrival_time,
            "observed_position": values[0], "elapsed_since_prior_arrival": elapsed,
            "bootstrap_proportional_only": elapsed is None,
            "components_p_i_d": list(self.pid.components), "output": output,
        })
        return output


def clock_negative_control():
    pid = load_pid()(2, 0, 0, time_fn=lambda: 0.0)
    naive = [pid(1.0), pid(0.5)]
    return {"kind": "synthetic_frozen_clock_control", "input_positions": [1.0, 0.5],
            "default_sample_time_seconds": pid.sample_time, "outputs": naive,
            "scope": "Frozen clock models a loop faster than the sampling gate; not a wall-time benchmark"}


def run_case(config, destination, ki=0.1, kd=0.05):
    instances = []

    def factory(current):
        controller = PIDAdapter(current, ki=ki, kd=kd)
        instances.append(controller)
        return controller

    result = compare(config, factory)
    pid_class = load_pid()
    source = Path(sys.modules[pid_class.__module__].__file__)
    controller_record = {
        "library": "simple-pid", "version": metadata.version("simple-pid"), "license": "MIT",
        "upstream": "https://github.com/m-lundberg/simple-pid/tree/v2.0.1",
        "installed_pid_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "adapter_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "config": asdict(config), "actual_gains": {"kp": config.kp, "ki": ki, "kd": kd},
        "gain_scope": "Config.kd belongs to the built-in controller; this adapter uses the explicitly recorded kd",
        "time": "Simulation arrival clock; explicit elapsed arrival gaps; library sample_time=None",
        "initialization": "Fresh PID per policy; first update P only, subsequent I/D use received-observation gaps",
        "information": "Position from delivered measurement plus sample/arrival timestamps; no current truth or velocity used",
        "internal_limits": [-config.input_limit, config.input_limit],
        "saturation_scope": "Core saturated_updates counts the downstream actuator limiter, not PID internal clamping",
        "clock_negative_control": clock_negative_control(),
        "updates_by_policy": {policy: instance.updates for policy, instance in zip(POLICIES, instances)},
        "scope": "Pinned library integration on teaching plants; not tuning, paper reproduction, stability or user adoption evidence",
    }
    export(result, destination)
    (destination / "controller.json").write_text(
        json.dumps(controller_record, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result, controller_record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ki", type=float, default=0.1)
    parser.add_argument("--kd", type=float, default=0.05)
    arguments = parser.parse_args()
    try:
        check_new_output(arguments.out)
        config = Config.from_dict(json.loads(arguments.config.read_text(encoding="utf-8-sig"))) if arguments.config else Config()
        result, record = run_case(config, arguments.out, arguments.ki, arguments.kd)
        print(json.dumps({"output": str(arguments.out.resolve()), "library_version": record["version"],
                          "runs": [{"policy": run["policy"], "status": run["status"],
                                    "packets": run["packets"]} for run in result["runs"]]}, indent=2))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"simple-pid example: {exc}\n")


if __name__ == "__main__":
    main()
