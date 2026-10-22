"""Bring a first-order actuator model to network, MFAC, ILC and frozen-RL recipes."""

import argparse
from dataclasses import replace
import hashlib
import html
import json
import math
from pathlib import Path

from event_control_lab import PlantAdapter, StudySpec, compare, study
from event_control_lab.__main__ import export
from event_control_lab.controller_lab import ControllerLabSpec, controller_lab, export_controller_lab
from event_control_lab.study import export_study


def actuator_model(decay=0.4, gain=1.2):
    """Illustrative normalized actuator deviation, not a calibrated hardware model."""
    if not math.isfinite(decay) or decay <= 0 or not math.isfinite(gain) or gain <= 0:
        raise ValueError("decay and gain must be finite positive numbers")

    def factory(config):
        # Construct a new step function here; reset any model memory/RNG in this factory.
        def step(state, held_input, dt):
            response = -math.expm1(-decay * dt)
            return (state[0] * math.exp(-decay * dt) + gain * held_input * response / decay,)
        return step

    return PlantAdapter(
        name="First-order actuator deviation / 一阶执行器偏差",
        state_layout="scalar", factory=factory,
        parameters={"decay_per_second": decay, "input_gain_per_second": gain,
                    "equation": "dx/dt = -decay*x + gain*u; exact constant-input interval"},
        state_units=("normalized_displacement",), input_unit="normalized_command",
        source="Independent illustrative ODE in examples/own_model_case.py; no measured hardware data",
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


def run_case(destination, decay=0.4, gain=1.2):
    plant = actuator_model(decay, gain)
    spec = ControllerLabSpec()
    network_config = replace(spec.config, budget=30, delay_steps=2, loss_probability=0.05,
                             measurement_noise=0.005, process_noise=0.01)
    network = compare(network_config, plant=plant)
    traffic = study(StudySpec(network_config, thresholds=(0.06, 0.12), seeds=(1001, 1002)), plant=plant)
    learned = controller_lab(spec, plant=plant)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    export(network, destination / "network")
    export_study(traffic, destination / "traffic")
    export_controller_lab(learned, destination / "controllers")
    (destination / "model.json").write_text(json.dumps(plant.metadata(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = []
    for run in network["runs"]:
        score = run["metrics"]["position_rmse"]
        policy = {"periodic": "周期", "absolute": "绝对变化", "relative": "相对变化"}[run["policy"]]
        status = {"complete": "完整结束", "state_limit": "状态超限", "plant_error": "模型错误",
                  "controller_error": "控制器错误"}[run["status"]]
        values = [policy, status, "不可用" if score is None else f"{score:.6g}",
                  run["packets"]["attempted"], run["packets"]["delivered"],
                  run["metrics"]["requests_blocked_by_budget"]]
        rows.append("<tr>" + "".join("<td>" + html.escape(str(x)) + "</td>" for x in values) + "</tr>")
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SparsiLoop · 接入自己的模型</title>
<style>body{font:17px/1.65 system-ui,sans-serif;max-width:1000px;margin:auto;padding:24px;color:#183546;background:#f5f8fa}
section{background:white;padding:20px;border:1px solid #ccdce4;border-radius:12px;margin:18px 0}a{color:#006c77}
.scroll{overflow:auto}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:10px;border-bottom:1px solid #dbe5ea;white-space:nowrap}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>
<h1>接入自己的模型 / Bring your own model</h1>
<p>同一个一阶执行器模型接入网络比较、事后实际发送量参考，以及 MFAC、ILC、强化学习流程。无需改核心代码。参数为教学设定，未作实物校准。</p>
<section><h2>1 · 先核模型和单位</h2><p>零目标的归一化执行器偏差；采样间隔内输入保持不变。工厂在每个策略、试次、训练轮次重新创建模型。<a href="model.json">参数、来源与实现摘要</a></p><pre>'''
    page += html.escape(json.dumps(plant.metadata()["parameters"], ensure_ascii=False, indent=2)) + "</pre></section>"
    page += '''<section><h2>2 · 查看网络约束是否影响运行</h2><p>共同发送上限并不等于实际发送数相同；下面不能直接选“最佳策略”。失败的完整时域分数为空。</p>
<div class="scroll" tabindex="0" role="region" aria-label="网络比较结果"><table><tr><th>策略</th><th>状态</th><th>第一状态 RMSE ↓</th><th>发送尝试</th><th>到达</th><th>预算阻止请求</th></tr>'''
    page += "".join(rows) + '''</table></div><p><a href="network/result.json">完整网络轨迹、参数与随机输入</a> · <a href="traffic/study.json">事后实际发送量参考（所有阈值和种子）</a></p>
<p>若出现失败，先读错误并核对模型单位、步长和初始条件；若预算阻止请求，查看发生时刻，再明确调整预算或阈值重跑，保留原结果。事后参考不等于提前调参或独立测试。</p></section>
<section><h2>3 · 查看在线估计、重复学习和冻结评测</h2><p><a href="controllers/report.html">打开带阶段说明的 MFAC / ILC / RL 报告</a></p>
<p>MFAC、ILC 仍要求规则完整采样；RL 单独列出训练和未训练种子评测。更换模型不会使这些方法自动兼容延迟或获得收敛保证。</p></section>
<section><h2>4 · 替换为自己的模型</h2><p>从 examples/own_model_case.py 的 factory 和 step 开始，声明参数、来源与单位，再核对一个已知输入下的解析解或可信参考轨迹。Python 接口只在本机运行；浏览器不接收模型代码。</p>
<p>当前仅支持单输入、一维输出或位置—速度布局；各指标仍按协议的零目标和固定权重计算，不能当成物理能耗。网格核查只覆盖内置模型，不验证这个自定义模型。</p></section></html>'''
    (destination / "report.html").write_text(page, encoding="utf-8")
    return {"status": "exported", "plant": plant.metadata(), "out": str(destination.resolve()),
            "network_statuses": [run["status"] for run in network["runs"]],
            "traffic_pairs": len(traffic["pairs"]),
            "scope": "Independent engineering example, not external adoption or calibrated plant evidence"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--decay", type=float, default=0.4)
    parser.add_argument("--gain", type=float, default=1.2)
    arguments = parser.parse_args()
    if arguments.out.exists():
        parser.error("output already exists; choose a new directory to preserve the previous run")
    try:
        result = run_case(arguments.out, arguments.decay, arguments.gain)
    except (ValueError, OSError) as exc:
        parser.exit(1, "SparsiLoop model case: " + str(exc) + "\n")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
