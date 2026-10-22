"""Exact held-input toy dynamics with a single delayed sensor-to-controller channel."""

from dataclasses import asdict, dataclass, fields
import hashlib
import json
import math
from pathlib import Path
import platform
import random


POLICIES = ("periodic", "absolute", "relative")
PROTOCOL = "sampled-uplink-v1"


@dataclass(frozen=True)
class Config:
    plant: str = "scalar"
    duration: float = 8.0
    dt: float = 0.02
    budget: int = 80
    delay_steps: int = 2
    loss_probability: float = 0.05
    measurement_noise: float = 0.005
    process_noise: float = 0.01
    threshold: float = 0.06
    relative_threshold: float = 0.15
    heartbeat: float = 0.5
    kp: float = 2.0
    kd: float = 2.0
    input_limit: float = 4.0
    state_limit: float = 20.0
    initial_position: float = 1.0
    initial_velocity: float = 0.0
    seed: int = 20261022

    def __post_init__(self):
        if not isinstance(self.plant, str) or self.plant not in {"scalar", "double_integrator"}:
            raise ValueError("plant must be scalar or double_integrator")
        for name in ("budget", "delay_steps", "seed"):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        for field in fields(self):
            if field.name in {"plant", "budget", "delay_steps", "seed"}:
                continue
            value = getattr(self, field.name)
            try:
                finite = math.isfinite(value)
            except (TypeError, OverflowError):
                finite = False
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not finite:
                raise ValueError(f"{field.name} must be a finite number")
        if not 0.002 <= self.dt <= 0.1 or not 0.2 <= self.duration <= 20:
            raise ValueError("dt must be 0.002..0.1 s and duration 0.2..20 s")
        if self.steps > 5000 or not math.isclose(self.duration / self.dt, self.steps, abs_tol=1e-8):
            raise ValueError("duration must be an integer number of steps, at most 5000")
        if not 0 <= self.budget <= self.steps or not 0 <= self.delay_steps <= self.steps:
            raise ValueError("budget and delay_steps must be between zero and the number of steps")
        if not 0 <= self.seed < 2**32 or not 0 <= self.loss_probability <= 1:
            raise ValueError("seed or loss_probability is outside its supported range")
        for name in ("measurement_noise", "process_noise", "threshold", "relative_threshold"):
            if not 0 <= getattr(self, name) <= 2:
                raise ValueError(f"{name} must be between 0 and 2")
        if not self.dt <= self.heartbeat <= self.duration:
            raise ValueError("heartbeat must be between dt and duration")
        if not 0 < self.input_limit <= 20 or not 1 <= self.state_limit <= 100:
            raise ValueError("input_limit or state_limit is outside its supported range")
        if not 0 <= self.kp <= 20 or not 0 <= self.kd <= 20:
            raise ValueError("controller gains must be between 0 and 20")
        if abs(self.initial_position) > 5 or abs(self.initial_velocity) > 5:
            raise ValueError("initial states must be between -5 and 5")
        if math.hypot(*self.initial_state) > self.state_limit:
            raise ValueError("initial state exceeds state_limit")

    @property
    def steps(self):
        return round(self.duration / self.dt)

    @property
    def heartbeat_steps(self):
        ratio = self.heartbeat / self.dt
        nearest = round(ratio)
        if abs(ratio - nearest) <= 4 * math.ulp(ratio):
            return nearest
        return math.ceil(ratio)

    @property
    def initial_state(self):
        return ((self.initial_position,) if self.plant == "scalar"
                else (self.initial_position, self.initial_velocity))

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("configuration must be an object")
        unknown = set(value) - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError("unknown configuration fields: " + ", ".join(sorted(map(str, unknown))))
        return cls(**value)


@dataclass(frozen=True)
class Observation:
    values: tuple
    sample_time: float
    arrival_time: float


class LinearFeedback:
    def __init__(self, config):
        self.kp, self.kd = config.kp, config.kd

    def __call__(self, observation):
        value = -self.kp * observation.values[0]
        return value - self.kd * observation.values[1] if len(observation.values) == 2 else value


def advance(plant, state, held_input, dt):
    if plant == "scalar":
        return (state[0] * math.exp(dt) + held_input * math.expm1(dt),)
    return (state[0] + state[1] * dt + 0.5 * held_input * dt * dt,
            state[1] + held_input * dt)


def make_trace(config):
    dimensions = len(config.initial_state)
    sensor = random.Random(config.seed ^ 0x53454E53)
    disturbance = random.Random(config.seed ^ 0x44535442)
    network = random.Random(config.seed ^ 0x4E455457)
    trace = {
        "measurement_standard_normal": [[sensor.gauss(0, 1) for _ in range(dimensions)]
                                        for _ in range(config.steps)],
        "input_disturbance_standard_normal": [disturbance.gauss(0, 1) for _ in range(config.steps)],
        "loss_uniform": [network.random() for _ in range(config.steps)],
    }
    payload = json.dumps(trace, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return trace, hashlib.sha256(payload).hexdigest()


def simulate(config, policy="absolute", controller=None, trace=None):
    if policy not in POLICIES:
        raise ValueError("unknown communication policy")
    controller = LinearFeedback(config) if controller is None else controller
    generated, trace_hash = make_trace(config)
    if trace is not None and trace != generated:
        raise ValueError("trace differs from the configured exogenous realization")
    trace = generated
    scheduled = {i * config.steps // config.budget for i in range(config.budget)}
    state, held, command = config.initial_state, None, 0.0
    last_sent, last_attempt = None, -config.steps - 1
    queue, rows, ledger = {}, [], {"attempted": 0, "dropped": 0, "delivered": 0}
    norm_checks = evaluations = saturations = blocked = 0
    position_integral = cost = 0.0
    ages, unobserved, sensor_samples = [], 0, 0
    status, error = "complete", None
    completed = 0
    heartbeat = config.heartbeat_steps
    for tick in range(config.steps):
        sensor_samples += 1
        measured = tuple(x + config.measurement_noise * z for x, z in
                         zip(state, trace["measurement_standard_normal"][tick]))
        if policy == "periodic":
            wanted = tick in scheduled
        elif last_sent is None:
            wanted = True
        else:
            norm_checks += 1
            difference = math.dist(measured, last_sent)
            threshold = config.threshold
            if policy == "relative":
                threshold = math.hypot(threshold, config.relative_threshold * math.hypot(*measured))
            wanted = difference >= threshold or tick - last_attempt >= heartbeat
        sent, dropped, delivered = False, False, 0
        if wanted and ledger["attempted"] < config.budget:
            sent = True
            ledger["attempted"] += 1
            last_sent, last_attempt = measured, tick
            dropped = trace["loss_uniform"][tick] < config.loss_probability
            if dropped:
                ledger["dropped"] += 1
            else:
                queue.setdefault(tick + config.delay_steps, []).append((tick, measured))
        elif wanted:
            blocked += 1
        for sampled_at, values in queue.pop(tick, []):
            delivered += 1
            ledger["delivered"] += 1
            held = Observation(values, sampled_at * config.dt, tick * config.dt)
            evaluations += 1
            try:
                raw = controller(held)
                if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
                    raise ValueError("controller must return one finite number")
                command = max(-config.input_limit, min(config.input_limit, raw))
                saturations += int(raw != command)
            except Exception as exc:
                status, error = "controller_error", str(exc)
                break
        age = None if held is None else tick * config.dt - held.sample_time
        rows.append({"t": tick * config.dt, "state": list(state), "input": command,
                     "controller_values": None if held is None else list(held.values),
                     "observation_age": age, "sent": sent, "dropped": dropped,
                     "delivered": delivered})
        if status != "complete":
            break
        if age is None:
            unobserved += 1
        else:
            ages.append(age)
        next_state = advance(config.plant, state, command + config.process_noise *
                             trace["input_disturbance_standard_normal"][tick], config.dt)
        position_cost = 0.5 * config.dt * (state[0] ** 2 + next_state[0] ** 2)
        position_integral += position_cost
        velocity_cost = (0.05 * config.dt * (state[1] ** 2 + next_state[1] ** 2)
                         if len(state) == 2 else 0.0)
        cost += position_cost + velocity_cost + 0.01 * config.dt * command * command
        state, completed = next_state, tick + 1
        if not all(math.isfinite(value) for value in state) or math.hypot(*state) > config.state_limit:
            status = "state_limit"
            error = "state exceeded the declared simulation limit"
            break
    end_time = completed * config.dt
    if not rows or rows[-1]["t"] != end_time:
        rows.append({"t": end_time, "state": list(state), "input": command,
                     "controller_values": None if held is None else list(held.values),
                     "observation_age": None if held is None else end_time - held.sample_time,
                     "sent": False, "dropped": False, "delivered": 0})
    ledger["in_flight"] = sum(map(len, queue.values()))
    assert ledger["attempted"] == ledger["dropped"] + ledger["delivered"] + ledger["in_flight"]
    return {
        "policy": policy, "status": status, "error": error, "duration_completed": end_time,
        "trace_sha256": trace_hash, "packets": ledger,
        "timing": {
            "dt_seconds": config.dt, "delay_seconds": config.delay_steps * config.dt,
            "heartbeat_applies": policy != "periodic",
            "requested_heartbeat_seconds": config.heartbeat,
            "effective_heartbeat_steps": heartbeat,
            "effective_heartbeat_seconds": heartbeat * config.dt,
            "heartbeat_rounding": "ceil_after_four_ulp_integer_snap",
        },
        "metrics": {
            "position_rmse": math.sqrt(position_integral / config.duration) if status == "complete" else None,
            "quadratic_cost": cost if status == "complete" else None,
            "partial_position_integral": position_integral,
            "mean_observation_age": math.fsum(ages) / len(ages) if ages else None,
            "unobserved_steps": unobserved, "sensor_samples": sensor_samples,
            "norm_checks": norm_checks, "controller_evaluations": evaluations,
            "saturated_updates": saturations, "requests_blocked_by_budget": blocked,
        }, "trajectory": rows,
    }


def compare(config=None, controller_factory=None):
    config = Config() if config is None else config
    trace, trace_hash = make_trace(config)
    factory = LinearFeedback if controller_factory is None else controller_factory
    return {
        "schema_version": 1, "engine_version": "0.0.1", "protocol": PROTOCOL,
        "engine_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python_version": platform.python_version(), "config": asdict(config),
        "controller": "LinearFeedback" if controller_factory is None else "custom_local_factory",
        "scope": "Shared maximum attempted uplink packets, not equal actual traffic or a stability certificate",
        "exogenous_trace_sha256": trace_hash, "exogenous_trace": trace,
        "runs": [simulate(config, policy, factory(config), trace) for policy in POLICIES],
    }
