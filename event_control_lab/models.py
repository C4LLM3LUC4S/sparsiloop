"""Explicit, local-only plant adapters; metadata is a declaration, not certification."""

from dataclasses import dataclass, field
import json
import math
from numbers import Real
from itertools import islice


@dataclass(frozen=True)
class PlantAdapter:
    name: str
    state_layout: str
    factory: object = field(repr=False)
    parameters: dict = field(default_factory=dict)
    state_units: tuple = ("normalized_output",)
    input_unit: str = "normalized_command"
    source: str = "user supplied local Python"
    source_sha256: str | None = None
    _metadata_json: str = field(init=False, repr=False)

    def __post_init__(self):
        if not isinstance(self.state_layout, str) or self.state_layout not in {"scalar", "double_integrator"}:
            raise ValueError("adapter layout must be scalar or double_integrator (position, velocity)")
        dimensions = 1 if self.state_layout == "scalar" else 2
        if (not isinstance(self.state_units, (tuple, list)) or len(self.state_units) != dimensions
                or any(not isinstance(unit, str) or not unit.strip() for unit in self.state_units)):
            raise ValueError("state_units must name the unit of each declared state")
        for name in ("name", "input_unit", "source"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty string")
        if not callable(self.factory) or not isinstance(self.parameters, dict):
            raise ValueError("adapter needs a callable factory and a parameter object")
        if self.source_sha256 is not None and (
                not isinstance(self.source_sha256, str) or len(self.source_sha256) != 64
                or any(x not in "0123456789abcdef" for x in self.source_sha256)):
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest or None")
        metadata = {
            "kind": "local_python_adapter", "name": self.name, "state_layout": self.state_layout,
            "state_units": list(self.state_units), "input_unit": self.input_unit,
            "parameters": self.parameters, "source": self.source, "source_sha256": self.source_sha256,
            "verification": "User-declared model and provenance; not independently certified",
            "metric_scope": "Zero-target first-state RMSE; quadratic_cost is the fixed weighted index in the protocol, not physical energy",
        }
        def string_keys(value):
            if isinstance(value, dict):
                if any(not isinstance(key, str) for key in value):
                    raise ValueError("adapter metadata object keys must be strings")
                for item in value.values():
                    string_keys(item)
            elif isinstance(value, (tuple, list)):
                for item in value:
                    string_keys(item)

        try:
            string_keys(metadata)
            encoded = json.dumps(metadata, allow_nan=False, sort_keys=True)
        except (ValueError, TypeError, RecursionError) as exc:
            raise ValueError("adapter metadata must be finite JSON data with string keys") from exc
        object.__setattr__(self, "_metadata_json", encoded)

    def metadata(self):
        # A snapshot prevents later edits to a caller's parameter dictionary changing a saved declaration.
        return json.loads(self._metadata_json)

    def validate(self, config):
        if config.plant != self.state_layout:
            raise ValueError("Config.plant must select the adapter's state layout")

    def initialize(self, config):
        self.validate(config)
        step = self.factory(config)
        if not callable(step):
            raise ValueError("plant factory must return a callable step(state, held_input, dt)")
        return step


def checked_state(value, dimensions):
    if isinstance(value, (str, bytes, dict)):
        raise ValueError("plant step must return a state vector")
    try:
        items = tuple(islice(iter(value), dimensions + 1))
    except TypeError as exc:
        raise ValueError("plant step must return a state vector") from exc
    if len(items) != dimensions:
        raise ValueError(f"plant returned {len(items)} states; expected {dimensions}")
    result = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, Real):
            raise ValueError("plant states must be real numbers, excluding booleans")
        try:
            number = float(item)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("plant state cannot be represented as a finite float") from exc
        if not math.isfinite(number) or abs(number) > 1e100:
            raise ValueError("plant states must be finite and within the numerical bound +/-1e100")
        result.append(number)
    return tuple(result)
