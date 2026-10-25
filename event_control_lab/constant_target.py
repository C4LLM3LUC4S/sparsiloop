"""A declared constant position target in double-integrator error coordinates."""

from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
import math
from pathlib import Path

from . import engine
from .engine import Config, POLICIES, compare
from .planned_context import runtime_info, validate_runtime


FORMAT = "sparsiloop-constant-target-double-integrator-v1"
COORDINATES = "e=p-target; state and transmitted measurements are (e,velocity); physical input is unchanged"
SCOPE = ("Fixed known constant target and fixed feedback on delivered error/velocity only. "
         "Relative triggering uses the error/velocity norm. State limit bounds that error state, "
         "not physical-position safety. Full-horizon RMSE uses the existing trapezoidal convention; "
         "the cost is a normalized index, not energy. No training, target trajectory or stability claim.")


def finite(value, name):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except (OverflowError, TypeError):
        valid = False
    if not valid:
        raise ValueError(f"{name} 必须是有限数值，不能是布尔值。")
    return value


def digest(value):
    def normalize(item):
        if type(item) is float and item.is_integer():
            return int(item)
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        if isinstance(item, list):
            return [normalize(child) for child in item]
        return item
    data = json.dumps(normalize(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


@dataclass(frozen=True)
class TargetSpec:
    target: float = 1.0
    config: Config = field(default_factory=lambda: Config(plant="double_integrator", initial_position=0.0))

    def __post_init__(self):
        finite(self.target, "target")
        if abs(self.target) > 5:
            raise ValueError("target 的教学范围是 -5 到 5。")
        if not isinstance(self.config, Config) or self.config.plant != "double_integrator":
            raise ValueError("常值目标任务只支持内置位置—速度对象 double_integrator 和固定反馈。")
        try:
            self.error_config()
        except ValueError as exc:
            raise ValueError("初始位置减目标后的误差也必须满足原 Config 的范围和状态界限：" + str(exc)) from exc

    def error_config(self):
        return replace(self.config, initial_position=self.config.initial_position - self.target)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"target", "config"}:
            raise ValueError("方案需要 target 和完整 config 两个字段；不能把旧结果当方案。")
        return cls(value["target"], Config.from_dict(value["config"]))


def sources():
    return {"engine.py": hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),
            "constant_target.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def run_task(spec, *, input_sha256=None):
    if not isinstance(spec, TargetSpec):
        raise ValueError("请用 TargetSpec 声明目标和实际初态。")
    if input_sha256 is not None and (not isinstance(input_sha256, str) or len(input_sha256) != 64
                                   or any(c not in "0123456789abcdef" for c in input_sha256)):
        raise ValueError("输入摘要需要是 SHA-256，或在未记录时保留为空。")
    result = {"format": FORMAT, "spec": asdict(spec), "coordinates": COORDINATES,
              "error_config": asdict(spec.error_config()), "source_sha256": sources(),
              "execution": {"state": "recorded", "runtime": runtime_info()},
              "input_sha256": input_sha256, "scope": SCOPE,
              "comparison": compare(spec.error_config())}
    result["record_sha256"] = digest(result)
    return result


def _vector(value, size, name):
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f"{name} 维数不符，请使用完整原记录。")
    for item in value:
        finite(item, name)


def _run(run, policy, config, trace_hash):
    fields = {"policy", "status", "error", "duration_completed", "trace_sha256", "packets",
              "timing", "metrics", "trajectory"}
    if not isinstance(run, dict) or set(run) != fields or run["policy"] != policy:
        raise ValueError("记录缺少完整且有序的三种发送结果。")
    if run["status"] not in {"complete", "state_limit", "controller_error", "plant_error"}:
        raise ValueError("运行状态不受支持。")
    complete = run["status"] == "complete"
    if (run["error"] is not None if complete else not isinstance(run["error"], str)):
        raise ValueError("完成情况与原错误信息不符。")
    if run["trace_sha256"] != trace_hash:
        raise ValueError("三种发送结果没有引用同一份原随机输入。")
    duration = finite(run["duration_completed"], "duration_completed")
    intervals = round(duration / config.dt)
    if (not 0 <= duration <= config.duration or not math.isclose(duration, intervals * config.dt, abs_tol=1e-9)
            or complete and intervals != config.steps):
        raise ValueError("运行时段与声明的网格不符。")
    packets = run["packets"]
    if (not isinstance(packets, dict) or set(packets) != {"attempted", "dropped", "delivered", "in_flight"}
            or any(type(x) is not int or x < 0 for x in packets.values())
            or packets["attempted"] > config.budget
            or packets["attempted"] != packets["dropped"] + packets["delivered"] + packets["in_flight"]):
        raise ValueError("消息账本不完整或不闭合。")
    timing = {"dt_seconds": config.dt, "delay_seconds": config.delay_steps * config.dt,
              "heartbeat_applies": policy != "periodic", "requested_heartbeat_seconds": config.heartbeat,
              "effective_heartbeat_steps": config.heartbeat_steps,
              "effective_heartbeat_seconds": config.heartbeat_steps * config.dt,
              "heartbeat_rounding": "ceil_after_four_ulp_integer_snap"}
    if run["timing"] != timing:
        raise ValueError("运行的实际时序与声明不符。")
    metrics = run["metrics"]
    names = {"position_rmse", "quadratic_cost", "partial_position_integral", "mean_observation_age",
             "unobserved_steps", "sensor_samples", "norm_checks", "controller_evaluations",
             "saturated_updates", "requests_blocked_by_budget"}
    if not isinstance(metrics, dict) or set(metrics) != names:
        raise ValueError("原指标不完整。")
    for key in ("position_rmse", "quadratic_cost"):
        if complete:
            if finite(metrics[key], key) < 0:
                raise ValueError("完整时域指标不能为负数。")
        elif metrics[key] is not None:
            raise ValueError("失败运行的完整时域指标必须保持 null，不能填成零。")
    if finite(metrics["partial_position_integral"], "partial_position_integral") < 0:
        raise ValueError("部分积分不能为负数。")
    age = metrics["mean_observation_age"]
    if age is not None and finite(age, "mean_observation_age") < 0:
        raise ValueError("观测年龄不能为负数。")
    for key in names - {"position_rmse", "quadratic_cost", "partial_position_integral", "mean_observation_age"}:
        if type(metrics[key]) is not int or metrics[key] < 0:
            raise ValueError("原计数必须是非负整数。")
    rows = run["trajectory"]
    row_fields = {"t", "state", "input", "controller_values", "observation_age", "sent", "dropped", "delivered"}
    if not isinstance(rows, list) or len(rows) != intervals + 1:
        raise ValueError("请保留完整轨迹，不能用局部 CSV 替代。")
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != row_fields:
            raise ValueError("轨迹字段不完整。")
        if not math.isclose(finite(row["t"], "t"), index * config.dt, abs_tol=1e-9):
            raise ValueError("轨迹时钟与网格不符。")
        _vector(row["state"], 2, "error/velocity state")
        if row["controller_values"] is not None:
            _vector(row["controller_values"], 2, "received error/velocity")
        if abs(finite(row["input"], "command")) > config.input_limit:
            raise ValueError("保存的指令超过限幅。")
        if row["observation_age"] is not None and finite(row["observation_age"], "observation_age") < 0:
            raise ValueError("观测年龄不能为负数。")
        if (type(row["sent"]) is not bool or type(row["dropped"]) is not bool
                or type(row["delivered"]) is not int or row["delivered"] not in {0, 1}
                or row["dropped"] and not row["sent"]):
            raise ValueError("轨迹中的通信事件不完整。")
    if rows[0]["state"] != list(config.initial_state):
        raise ValueError("轨迹初态与目标换算后的误差初态不符。")
    if run["status"] in {"complete", "state_limit"} and (
            rows[-1]["sent"] or rows[-1]["dropped"] or rows[-1]["delivered"]):
        raise ValueError("末行只记录末状态，不能增加发送或到达事件。")
    if any(packets[key] != sum(row[field] for row in rows)
           for key, field in (("attempted", "sent"), ("dropped", "dropped"), ("delivered", "delivered"))):
        raise ValueError("消息账本与原轨迹不符。")


def load_record(value):
    """Validate declarations and original record structure; never recompute metrics/runs."""
    fields = {"format", "spec", "coordinates", "error_config", "source_sha256", "execution",
              "input_sha256", "scope", "comparison", "record_sha256"}
    try:
        if not isinstance(value, dict) or set(value) != fields or value["format"] != FORMAT:
            raise ValueError("请载入本任务完整的 target-task.json；方案、旧比较或策略不能代替结果。")
        if value["record_sha256"] != digest({k: v for k, v in value.items() if k != "record_sha256"}):
            raise ValueError("目标任务与保存时的摘要不同，请使用原文件。")
        if value["source_sha256"] != sources():
            raise ValueError("目标任务或核心代码与保存时不同，请使用匹配的原版本；不要改摘要。")
        spec = TargetSpec.from_dict(value["spec"])
        config = spec.error_config()
        if (digest(value["spec"]) != digest(asdict(spec))
                or value["coordinates"] != COORDINATES or value["scope"] != SCOPE
                or digest(value["error_config"]) != digest(asdict(config))):
            raise ValueError("目标、物理初态与误差坐标设置不一致。")
        input_hash = value["input_sha256"]
        if input_hash is not None and (not isinstance(input_hash, str) or len(input_hash) != 64
                                      or any(c not in "0123456789abcdef" for c in input_hash)):
            raise ValueError("原输入摘要不完整。")
        execution = value["execution"]
        if not isinstance(execution, dict) or set(execution) != {"state", "runtime"}:
            raise ValueError("原执行环境记录不完整。")
        if execution["state"] == "recorded":
            validate_runtime(execution["runtime"])
        elif execution["state"] != "not_recorded" or execution["runtime"] is not None:
            raise ValueError("缺失环境必须保持未知，不能补当前环境。")
        comparison = value["comparison"]
        expected = {"schema_version", "engine_version", "protocol", "engine_source_sha256", "python_version",
                    "config", "controller", "scope", "exogenous_trace_sha256", "exogenous_trace", "runs"}
        if (not isinstance(comparison, dict) or set(comparison) != expected
                or type(comparison["schema_version"]) is not int or comparison["schema_version"] != 1
                or comparison["engine_version"] != "0.0.1" or comparison["protocol"] != engine.PROTOCOL
                or comparison["controller"] != "LinearFeedback"
                or comparison["engine_source_sha256"] != value["source_sha256"]["engine.py"]
                or digest(comparison["config"]) != digest(asdict(config))
                or not isinstance(comparison["python_version"], str) or not isinstance(comparison["scope"], str)):
            raise ValueError("原比较的核心、反馈或配置与此目标任务不符。")
        if (execution["state"] == "recorded"
                and execution["runtime"]["python_version"] != comparison["python_version"]):
            raise ValueError("原执行环境与比较记录的 Python 版本不一致。")
        trace = comparison["exogenous_trace"]
        if not isinstance(trace, dict) or set(trace) != {"measurement_standard_normal", "input_disturbance_standard_normal", "loss_uniform"}:
            raise ValueError("原随机输入不完整。")
        if any(not isinstance(rows, list) or len(rows) != config.steps for rows in trace.values()):
            raise ValueError("原随机输入与完整时域不符。")
        for row in trace["measurement_standard_normal"]:
            _vector(row, 2, "measurement noise")
        for row in trace["input_disturbance_standard_normal"]:
            finite(row, "input disturbance")
        for row in trace["loss_uniform"]:
            if not 0 <= finite(row, "loss realization") <= 1:
                raise ValueError("丢包随机输入需要在 0 到 1 之间。")
        encoded = json.dumps(trace, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if hashlib.sha256(encoded).hexdigest() != comparison["exogenous_trace_sha256"]:
            raise ValueError("原随机输入与其摘要不符。")
        if not isinstance(comparison["runs"], list) or len(comparison["runs"]) != len(POLICIES):
            raise ValueError("请保留三种发送方式的全部结果和失败。")
        for run, policy in zip(comparison["runs"], POLICIES):
            _run(run, policy, config, comparison["exogenous_trace_sha256"])
        return value
    except (KeyError, TypeError, IndexError, AttributeError, OverflowError) as exc:
        raise ValueError("目标任务记录不完整，请使用原样保存的完整 target-task.json。") from exc


def read_record(path):
    with Path(path).open(encoding="utf-8-sig") as handle:
        return load_record(json.load(handle))


def physical_rows(value):
    """Derived display coordinates; original trajectories/metrics stay in the record."""
    load_record(value)
    target = value["spec"]["target"]
    config = Config.from_dict(value["error_config"])
    trace = value["comparison"]["exogenous_trace"]
    for run in value["comparison"]["runs"]:
        intervals = round(run["duration_completed"] / config.dt)
        for index, row in enumerate(run["trajectory"]):
            effective = (row["input"] + config.process_noise * trace["input_disturbance_standard_normal"][index]
                         if index < intervals else None)
            yield {"policy": run["policy"], "t_s": row["t"], "position": row["state"][0] + target,
                   "target": target, "position_error": row["state"][0], "velocity": row["state"][1],
                   "clipped_command": row["input"], "effective_interval_input": effective,
                   "received_position_error": None if row["controller_values"] is None else row["controller_values"][0],
                   "received_velocity": None if row["controller_values"] is None else row["controller_values"][1],
                   "observation_age_s": row["observation_age"], "sent": row["sent"],
                   "dropped": row["dropped"], "delivered": row["delivered"]}


if __name__ == "__main__":
    from .constant_target_cli import main
    raise SystemExit(main())
