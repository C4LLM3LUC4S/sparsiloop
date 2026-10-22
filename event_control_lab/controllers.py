"""Explicit teaching baselines; controller state is separate from communication policy."""

from dataclasses import asdict, dataclass
import hashlib
import json
import math


def number(value, name, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite and between {low} and {high}")
    return value


def clip(value, limit):
    return max(-limit, min(limit, value))


def received(observation, config, last=None, regular=False):
    values, sample, arrival = observation.values, observation.sample_time, observation.arrival_time
    if (len(values) != len(config.initial_state)
            or any(type(x) not in (int, float) or not math.isfinite(x)
                   for x in (*values, sample, arrival))
            or not 0 <= sample <= arrival):
        raise ValueError("a finite, causal observation of the configured dimension is required")
    if last is not None and arrival <= last:
        raise ValueError("observation arrivals must increase strictly")
    tick = round(arrival / config.dt)
    if not math.isclose(tick * config.dt, arrival, abs_tol=1e-9, rel_tol=0):
        raise ValueError("observation arrival must be on the simulation grid")
    if regular and (sample != arrival or
                    not math.isclose(arrival, 0 if last is None else last + config.dt,
                                     abs_tol=1e-9, rel_tol=0)):
        raise ValueError("this baseline requires every sample, starting at zero, without delay")
    return values[0], tick


@dataclass(frozen=True)
class MFACParameters:
    phi0: float = 0.02
    eta: float = 0.6
    mu: float = 0.01
    rho: float = 0.6
    penalty: float = 0.01
    epsilon: float = 1e-5
    phi_max: float = 10.0

    def __post_init__(self):
        number(self.phi0, "phi0", -10, 10)
        number(self.eta, "eta", 1e-9, 2)
        number(self.rho, "rho", 1e-9, 1)
        for name in ("mu", "penalty", "epsilon", "phi_max"):
            number(getattr(self, name), name, 1e-12, 100)
        if not self.epsilon <= abs(self.phi0) <= self.phi_max:
            raise ValueError("phi0 magnitude must lie between epsilon and phi_max")


class CFDLMFAC:
    """SISO CFDL update with declared sign prior and actual clipped input increments."""

    def __init__(self, config, parameters=None):
        if config.plant != "scalar":
            raise ValueError("the current CFDL-MFAC recipe supports the scalar teaching plant")
        self.config, self.parameters = config, parameters or MFACParameters()
        self.phi, self.u, self.prior_u = self.parameters.phi0, 0.0, 0.0
        self.last_y, self.last_arrival, self.updates = None, None, []

    def __call__(self, observation):
        y, tick = received(observation, self.config, self.last_arrival, regular=True)
        p = self.parameters
        du, dy, reset = None, None, None
        if self.last_y is not None:
            du, dy = self.u - self.prior_u, y - self.last_y
            estimate = self.phi + p.eta * du * (dy - self.phi * du) / (p.mu + du * du)
            if abs(du) < p.epsilon:
                reset = "input_increment_too_small"
            elif not p.epsilon <= abs(estimate) <= p.phi_max:
                reset = "estimate_outside_declared_bounds"
            elif estimate * p.phi0 <= 0:
                reset = "estimate_sign_changed"
            self.phi = p.phi0 if reset else estimate
        raw = self.u - p.rho * self.phi * y / (p.penalty + self.phi * self.phi)
        output = clip(raw, self.config.input_limit)
        self.updates.append({"tick": tick, "sample_time": observation.sample_time,
                             "observed_position": y, "delta_y": dy, "delta_u": du,
                             "phi": self.phi, "reset_reason": reset,
                             "requested_input": raw, "applied_input": output})
        self.prior_u, self.u = self.u, output
        self.last_y, self.last_arrival = y, observation.arrival_time
        return output


class TrialILC:
    """A fixed feedforward signal plus feedback; learning happens between trials."""

    def __init__(self, config, feedforward):
        if config.plant != "scalar":
            raise ValueError("the current shifted P-type ILC recipe supports the scalar plant")
        if len(feedforward) != config.steps:
            raise ValueError("ILC feedforward must have one value per input interval")
        self.config = config
        self.feedforward = tuple(number(x, "feedforward", -config.input_limit, config.input_limit)
                                 for x in feedforward)
        self.last_arrival, self.observations, self.updates = None, [], []

    def __call__(self, observation):
        y, tick = received(observation, self.config, self.last_arrival, regular=True)
        if tick >= len(self.feedforward):
            raise ValueError("ILC observation lies outside its declared trial")
        raw = self.feedforward[tick] - self.config.kp * y
        output = clip(raw, self.config.input_limit)
        self.observations.append(y)
        self.updates.append({"tick": tick, "observed_position": y,
                             "feedforward": self.feedforward[tick], "applied_input": output})
        self.last_arrival = observation.arrival_time
        return output


def ilc_next(feedforward, observations, gain, limit):
    number(gain, "ILC gain", 0, 20)
    if len(feedforward) != len(observations) or len(feedforward) < 2:
        raise ValueError("ILC learning requires all delivered samples of one complete trial")
    for x in (*feedforward, *observations):
        number(x, "ILC sample", -1e6, 1e6)
    # y[k+1] is known after the trial. y[T] is not delivered by the core channel.
    return tuple(clip(u - gain * observations[k + 1], limit) if k + 1 < len(observations) else u
                 for k, u in enumerate(feedforward))


@dataclass(frozen=True)
class QParameters:
    alpha: float = 0.2
    gamma: float = 0.98
    epsilon: float = 0.25
    bins: int = 81
    position_range: float = 4.0

    def __post_init__(self):
        number(self.alpha, "alpha", 1e-9, 1)
        number(self.gamma, "gamma", 0, 1)
        number(self.epsilon, "epsilon", 0, 1)
        number(self.position_range, "position_range", 0.1, 100)
        if type(self.bins) is not int or not 3 <= self.bins <= 201 or self.bins % 2 != 1:
            raise ValueError("bins must be an odd integer between 3 and 201")


class QTable:
    """Finite-horizon, discretized-position Q-learning, not a plant model."""

    def __init__(self, steps, input_limit, parameters=None):
        if type(steps) is not int or not 2 <= steps <= 5000:
            raise ValueError("Q horizon must contain 2..5000 intervals")
        number(input_limit, "input_limit", 1e-9, 20)
        self.steps, self.input_limit = steps, input_limit
        self.parameters = parameters or QParameters()
        self.actions = tuple(input_limit * value for value in (-1, -0.5, -0.25, 0, 0.25, 0.5, 1))
        self.values = {}

    def state(self, tick, position):
        number(position, "observed position", -1e100, 1e100)
        if type(tick) is not int or not 0 <= tick < self.steps:
            raise ValueError("Q state tick is outside the declared horizon")
        p = self.parameters
        bucket = round((clip(position, p.position_range) + p.position_range)
                       * (p.bins - 1) / (2 * p.position_range))
        return tick, bucket

    def row(self, state):
        return self.values.get(state, (0.0,) * len(self.actions))

    def greedy(self, state):
        row = self.row(state)
        return max(range(len(self.actions)), key=lambda i: (row[i], -abs(self.actions[i]), -i))

    def update(self, state, action, reward, next_state, terminal=False):
        if type(action) is not int or not 0 <= action < len(self.actions):
            raise ValueError("invalid Q action index")
        number(reward, "reward", -1e100, 1e100)
        row = list(self.row(state))
        target = reward + (0 if terminal else self.parameters.gamma * max(self.row(next_state)))
        old = row[action]
        row[action] += self.parameters.alpha * (target - old)
        self.values[state] = tuple(row)
        return {"state": list(state), "action_index": action, "reward": reward,
                "next_state": list(next_state), "terminal": terminal,
                "old_q": old, "target": target, "new_q": row[action]}

    def snapshot(self):
        return {"steps": self.steps, "input_limit": self.input_limit,
                "parameters": asdict(self.parameters), "actions": list(self.actions),
                "rows": [{"state": list(key), "q": list(self.values[key])} for key in sorted(self.values)]}

    def fingerprint(self):
        body = json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(body.encode()).hexdigest()

    @classmethod
    def from_snapshot(cls, value):
        if not isinstance(value, dict) or set(value) != {"steps", "input_limit", "parameters", "actions", "rows"}:
            raise ValueError("invalid Q checkpoint fields")
        try:
            result = cls(value["steps"], value["input_limit"], QParameters(**value["parameters"]))
        except (TypeError, KeyError) as exc:
            raise ValueError("invalid Q checkpoint parameters") from exc
        if value["actions"] != list(result.actions) or not isinstance(value["rows"], list):
            raise ValueError("Q checkpoint actions or rows do not match the declared recipe")
        if len(value["rows"]) > result.steps * result.parameters.bins:
            raise ValueError("too many Q checkpoint rows")
        for entry in value["rows"]:
            if not isinstance(entry, dict) or set(entry) != {"state", "q"}:
                raise ValueError("invalid Q checkpoint row")
            state, row = entry["state"], entry["q"]
            if (not isinstance(state, list) or len(state) != 2
                    or any(type(x) is not int for x in state)
                    or not 0 <= state[0] < result.steps or not 0 <= state[1] < result.parameters.bins
                    or tuple(state) in result.values or not isinstance(row, list)
                    or len(row) != len(result.actions)):
                raise ValueError("invalid or duplicate Q checkpoint state")
            result.values[tuple(state)] = tuple(number(x, "Q value", -1e100, 1e100) for x in row)
        return result


class QController:
    """Only received positions and the arrival clock enter the policy/update."""

    def __init__(self, config, table, rng=None):
        if (config.plant != "scalar" or table.steps != config.steps
                or table.input_limit != config.input_limit):
            raise ValueError("Q policy requires the scalar plant, trained horizon and input limit")
        self.config, self.table, self.rng = config, table, rng
        self.previous, self.last_arrival, self.updates = None, None, []

    def __call__(self, observation):
        y, tick = received(observation, self.config, self.last_arrival, regular=self.rng is not None)
        state = self.table.state(tick, y)
        if self.rng is not None and self.previous is not None:
            old_state, action = self.previous
            reward = -self.config.dt * (y * y + 0.01 * self.table.actions[action] ** 2)
            self.updates.append(self.table.update(old_state, action, reward, state,
                                                  terminal=tick == self.config.steps - 1))
        action = self.table.greedy(state)
        if self.rng is not None and self.rng.random() < self.table.parameters.epsilon:
            action = self.rng.randrange(len(self.table.actions))
        self.previous, self.last_arrival = (state, action), observation.arrival_time
        return self.table.actions[action]
