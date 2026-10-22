"""Reproducible MFAC, trial ILC and train/freeze/evaluate Q-learning recipes."""

import csv
from dataclasses import asdict, dataclass, field, replace
import hashlib
import html
import json
from pathlib import Path
import platform
import random

from . import controllers, engine
from .controllers import CFDLMFAC, MFACParameters, QController, QParameters, QTable, TrialILC, ilc_next, number
from .engine import Config, compare, make_trace, simulate


def teaching_config():
    return Config(duration=1.2, dt=0.02, budget=60, delay_steps=0,
                  loss_probability=0, measurement_noise=0, process_noise=0, heartbeat=0.2)


@dataclass(frozen=True)
class ControllerLabSpec:
    config: Config = field(default_factory=teaching_config)
    mfac: MFACParameters = field(default_factory=MFACParameters)
    ilc_trials: int = 12
    ilc_gain: float = 2.0
    q: QParameters = field(default_factory=QParameters)
    training_seeds: tuple = tuple(range(100, 228))
    evaluation_seeds: tuple = (1001, 1002, 1003)
    evaluation_config: Config | None = None

    def __post_init__(self):
        if not isinstance(self.config, Config) or not isinstance(self.mfac, MFACParameters) or not isinstance(self.q, QParameters):
            raise ValueError("config, mfac and q must be their declared specification types")
        c = self.config
        if (c.plant != "scalar" or c.budget != c.steps or c.delay_steps
                or c.loss_probability or c.measurement_noise or c.process_noise):
            raise ValueError("learning recipes require scalar, full-rate, zero-delay/loss/noise training")
        if type(self.ilc_trials) is not int or not 2 <= self.ilc_trials <= 100:
            raise ValueError("ilc_trials must be an integer between 2 and 100")
        number(self.ilc_gain, "ilc_gain", 0, 20)
        for name in ("training_seeds", "evaluation_seeds"):
            seeds = getattr(self, name)
            if (not isinstance(seeds, tuple) or not 1 <= len(seeds) <= 512
                    or any(type(seed) is not int or not 0 <= seed < 2**32 for seed in seeds)
                    or len(set(seeds)) != len(seeds)):
                raise ValueError(f"{name} must contain 1..512 unique integer seeds in 0..2**32-1")
        if set(self.training_seeds) & set(self.evaluation_seeds):
            raise ValueError("training and evaluation seeds must be disjoint")
        if (len(self.training_seeds) + self.ilc_trials + 9 * len(self.evaluation_seeds) + 1) * c.steps > 100000:
            raise ValueError("declared learning/evaluation budget exceeds 100000 simulation intervals")
        if self.evaluation_config is not None:
            if not isinstance(self.evaluation_config, Config):
                raise ValueError("evaluation_config must be a Config")
            for name in ("plant", "dt", "duration", "input_limit"):
                if getattr(self.evaluation_config, name) != getattr(c, name):
                    raise ValueError(f"evaluation_config must retain the trained {name}")

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("controller-lab specification must be an object")
        value = dict(value)
        for key, kind in (("config", Config), ("evaluation_config", Config),
                          ("mfac", MFACParameters), ("q", QParameters)):
            if key in value and value[key] is not None:
                if not isinstance(value[key], dict):
                    raise ValueError(f"{key} must be an object")
                try:
                    value[key] = kind(**value[key])
                except TypeError as exc:
                    raise ValueError(f"unknown or invalid {key} fields") from exc
        for key in ("training_seeds", "evaluation_seeds"):
            if key in value:
                if not isinstance(value[key], list):
                    raise ValueError(f"{key} must be an array")
                value[key] = tuple(value[key])
        try:
            return cls(**value)
        except TypeError as exc:
            raise ValueError("unknown controller-lab fields") from exc


def single(config, controller):
    trace, digest = make_trace(config)
    return {"config": asdict(config), "exogenous_trace": trace,
            "exogenous_trace_sha256": digest, "run": simulate(config, "periodic", controller, trace)}


def initial_position(seed):
    return random.Random(seed ^ 0x494E4954).uniform(-1.5, 1.5)


def run_mfac(spec):
    controller = CFDLMFAC(spec.config, spec.mfac)
    record = single(spec.config, controller)
    record.update({"parameters": asdict(spec.mfac), "updates": controller.updates,
                   "initial_input_history": [0, 0],
                   "scope": "SISO CFDL teaching baseline; sign/gain prior is declared, not identified from plant truth"})
    return record


def run_ilc(spec):
    signal = (0.0,) * spec.config.steps
    trials = []
    for index in range(spec.ilc_trials):
        controller = TrialILC(spec.config, signal)
        record = single(spec.config, controller)
        complete = record["run"]["status"] == "complete" and len(controller.observations) == spec.config.steps
        learned = index + 1 < spec.ilc_trials and complete
        after = ilc_next(signal, controller.observations, spec.ilc_gain, spec.config.input_limit) if learned else signal
        record.update({"trial": index + 1, "feedforward_used": list(signal),
                       "received_observations": controller.observations,
                       "controller_updates": controller.updates,
                       "learning_applied": learned,
                       "learning_skip_reason": None if learned else "final_declared_trial" if complete else "incomplete_trial",
                       "next_feedforward": list(after) if learned else None})
        trials.append(record)
        signal = after
    return {"gain": spec.ilc_gain, "trials": trials,
            "update": "v[j+1,k]=clip(v[j,k]-gain*y[j,k+1]); zero target, Q=identity, plus -kp*y feedback",
            "learned_output_indices": [1, spec.config.steps - 1],
            "unlearned_final_input_reason": "No terminal T observation is delivered; final feedforward remains zero",
            "reset": "Same initial state, grid and deterministic inputs; new controller each trial",
            "scope": "Repeated-task shifted P-type ILC; not an event-triggered ILC implementation or a convergence certificate"}


def run_q_learning(spec):
    table = QTable(spec.config.steps, spec.config.input_limit, spec.q)
    initial = table.snapshot()
    training = []
    for seed in spec.training_seeds:
        config = replace(spec.config, seed=seed, initial_position=initial_position(seed))
        learner = QController(config, table, rng=random.Random(seed ^ 0x4143544E))
        record = single(config, learner)
        record.update({"seed": seed, "q_updates": learner.updates,
                       "completed_updates": len(learner.updates),
                       "unobserved_final_transition": "No y(T) reward/update; learning terminates at last received grid sample"})
        training.append(record)
    trained = table.snapshot()
    frozen_hash = table.fingerprint()
    empty = QTable(spec.config.steps, spec.config.input_limit, spec.q)
    evaluation = []
    base = spec.evaluation_config or replace(spec.config, budget=max(1, spec.config.steps // 2),
                                            delay_steps=2, loss_probability=0.05,
                                            measurement_noise=0.005, process_noise=0.01)
    for seed in spec.evaluation_seeds:
        config = replace(base, seed=seed, initial_position=initial_position(seed))
        evaluation.append({"seed": seed, "trained": compare(config, lambda c: QController(c, table)),
                           "untrained": compare(config, lambda c: QController(c, empty)),
                           "linear_feedback": compare(config)})
    if table.fingerprint() != frozen_hash:
        raise ValueError("evaluation changed the supposedly frozen Q policy")
    return {"algorithm": "tabular Q-learning on (arrival tick, clipped position bin)",
            "parameters": asdict(spec.q), "training_seeds": list(spec.training_seeds),
            "evaluation_seeds": list(spec.evaluation_seeds),
            "initial_table": initial, "frozen_table": trained, "frozen_sha256": frozen_hash,
            "frozen_after_evaluation_sha256": table.fingerprint(), "training": training,
            "evaluation": evaluation,
            "training_reward": "-dt*(next_received_position**2+0.01*previous_action**2)",
            "training_budget_intervals": len(spec.training_seeds) * spec.config.steps,
            "state_scope": "Discretized observation and time omit true continuous state; no Markov/optimality/convergence guarantee",
            "evaluation_scope": "Held-out seeds with fixed initial-state draw; network/noise shift is reported, not training data",
            "initial_state_rule": "Random(seed XOR 0x494E4954).uniform(-1.5,1.5)",
            "selection": "Final declared training episode; no best-seed or evaluation-based selection"}


def controller_lab(spec=None, method="all"):
    spec = spec or ControllerLabSpec()
    if method not in {"all", "mfac", "ilc", "rl"}:
        raise ValueError("method must be all, mfac, ilc or rl")
    paths = {"engine": Path(engine.__file__), "controllers": Path(controllers.__file__),
             "controller_lab": Path(__file__)}
    result = {"analysis": "classic-controller-recipes-v1", "python_version": platform.python_version(),
              "specification": asdict(spec), "method": method,
              "source_sha256": {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items()},
              "scope": "Teaching/engineering recipes, not paper reproduction, general superiority or stability certification",
              "cases": {}}
    for name, function in (("mfac", run_mfac), ("ilc", run_ilc), ("rl", run_q_learning)):
        if method in {"all", name}:
            result["cases"][name] = function(spec)
    return result


def records(result):
    for method, case in result["cases"].items():
        if method == "mfac":
            yield method, "online", "1", case["config"], case["run"]
        elif method == "ilc":
            for trial in case["trials"]:
                yield method, "trial", str(trial["trial"]), trial["config"], trial["run"]
        else:
            for episode in case["training"]:
                yield method, "training", str(episode["seed"]), episode["config"], episode["run"]
            for evaluation in case["evaluation"]:
                for label in ("trained", "untrained", "linear_feedback"):
                    comparison = evaluation[label]
                    for run in comparison["runs"]:
                        yield method, "evaluation_" + label, str(evaluation["seed"]), comparison["config"], run


def export_controller_lab(result, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "controllers.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if "rl" in result["cases"]:
        (destination / "policy.json").write_text(
            json.dumps(result["cases"]["rl"]["frozen_table"], indent=2, allow_nan=False) + "\n", encoding="utf-8")
    table, training_table = [], []
    with (destination / "summary.csv").open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["method", "stage", "trial_or_seed", "policy", "status", "position_rmse",
                         "attempted", "dropped", "delivered", "in_flight"])
        for method, stage, label, config, run in records(result):
            value = run["metrics"]["position_rmse"]
            values = [method, stage, label, run["policy"], run["status"], "" if value is None else value,
                      *[run["packets"][key] for key in ("attempted", "dropped", "delivered", "in_flight")]]
            writer.writerow(values)
            stage_label = {"online": "在线估计", "trial": "重复试次", "training": "训练",
                           "evaluation_trained": "冻结评测：已训练", "evaluation_untrained": "评测：未训练参考",
                           "evaluation_linear_feedback": "评测：固定反馈参考"}[stage]
            status_label = {"complete": "完整结束", "state_limit": "提前停止：状态超限",
                            "controller_error": "控制器错误"}.get(run["status"], run["status"])
            policy_label = {"periodic": "周期", "absolute": "绝对变化", "relative": "相对变化"}[run["policy"]]
            shown = [method.upper(), stage_label, label, policy_label, status_label,
                     "不可用 / N/A" if value is None else f"{value:.6g}"] + values[6:]
            row = "<tr>" + "".join(f"<td>{html.escape(str(x))}</td>" for x in shown) + "</tr>"
            (training_table if stage == "training" else table).append(row)
    with (destination / "trajectories.csv").open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["method", "stage", "trial_or_seed", "policy", "t_s", "position",
                         "input", "received_position", "observation_age", "sent", "dropped", "delivered"])
        for method, stage, label, config, run in records(result):
            for row in run["trajectory"]:
                values = row["controller_values"]
                writer.writerow([method, stage, label, run["policy"], row["t"], row["state"][0], row["input"],
                                 "" if values is None else values[0], row["observation_age"],
                                 row["sent"], row["dropped"], row["delivered"]])
    headings = ["方法", "阶段", "轮次/种子", "发送策略", "状态", "位置 RMSE ↓", "发送尝试", "丢失", "到达", "在途"]
    header = "<tr>" + "".join(f"<th>{x}</th>" for x in headings) + "</tr>"
    page = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SparsiLoop · 经典控制案例</title>
<style>body{font:17px/1.6 system-ui,sans-serif;max-width:1120px;margin:auto;padding:24px;color:#183546;background:#f5f8fa}
section{background:white;border:1px solid #ccdce4;border-radius:12px;padding:20px;margin:18px 0}a{color:#006c77}
.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:9px;border-bottom:1px solid #dbe5ea;text-align:left;white-space:nowrap}h1{font-size:28px}code{word-break:break-all}</style>
<h1>SparsiLoop · 经典控制案例 / Controller recipes</h1>
<p>先确认阶段和发送条件，再比较同一指标。此页是教学案例，没有选出通用“最佳控制器”。</p>
<section><h2>如何读这份结果</h2><ul>
<li><b>MFAC / 在线估计：</b>只用已收到的位置和自己施加的输入，在线估计响应；本例要求完整规则采样。</li>
<li><b>ILC / 重复试次：</b>每轮从相同状态重来，用上一轮收到的误差修正下一轮输入。看第 1 轮到最后一轮，所有轮次均保留。</li>
<li><b>RL / 冻结评测：</b>强化学习训练结束后冻结策略，在未参与训练的种子上评测；同时保留未训练对照与固定反馈参考。</li>
<li>训练分数在下方单列，不充当评测结果。RMSE 越小表示该时域内位置偏差越小；还需核对失败和实际消息数。</li>
<li>MFAC、ILC 的规则采样与 RL 的网络评测条件不同，不据此跨方法排榜。不可用不是零。</li></ul>
<p><a href="controllers.json">完整参数、学习/训练记录与策略</a> · <a href="summary.csv">汇总 CSV</a> · <a href="trajectories.csv">全部轨迹 CSV</a></p></section>
<section><h2>在线、重复试次与独立种子评测</h2><p>窄屏可横向滚动表格；键盘可聚焦表格区域后使用方向键。</p><div class="scroll" tabindex="0" role="region" aria-label="控制案例结果表"><table>"""
    page += header + "".join(table) + "</table></div></section>"
    if training_table:
        page += '<section><details><summary>展开全部训练轮次 / All training episodes</summary><div class="scroll" tabindex="0" role="region" aria-label="全部训练记录表"><table>'
        page += header + "".join(training_table) + "</table></div></details></section>"
    if "rl" in result["cases"]:
        page += '<p><a href="policy.json">单独下载冻结策略 / Frozen policy checkpoint</a></p>'
    page += '<p>Independent implementation of teaching recipes. Not a stability, optimality, hardware or paper-reproduction certificate.</p></html>'
    (destination / "report.html").write_text(page, encoding="utf-8")
