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
<h1>用自己的模型做控制实验</h1>
<p>这个例子让一个偏离目标位置的执行器回到原位。你可以先看减少传感器消息会带来什么变化，再试试 MFAC、ILC 和强化学习。以后换成自己的模型，也可以沿用这套流程。</p>
<section><h2>1 · 这次实验要做什么？</h2><p>位置偏差为 0 就是回到了目标位置。下面比较的是一个简化的数学模型，参数用于演示，没有用真实设备数据校准。</p>
<details><summary>查看模型公式、参数和计算方式</summary><p>每次运行都会重新初始化模型，避免上次运行留下的内部状态影响结果。一个采样间隔内，输入保持不变；这个例子使用相应的解析解更新状态。各阶段的初始位置和随机条件记录在详细结果中。</p><pre>'''
    page += html.escape(json.dumps(plant.metadata()["parameters"], ensure_ascii=False, indent=2)) + '</pre><p><a href="model.json">下载模型参数和来源记录</a></p></details></section>'
    page += '''<section><h2>2 · 少发一些消息，会发生什么？</h2><p>先看位置误差，再看用了多少条消息。RMSE 把整个仿真时段的偏差合成一个数，越小表示越接近目标。三种策略的发送上限相同，实际发送数可能不同。</p>
<div class="scroll" tabindex="0" role="region" aria-label="网络比较结果"><table><tr><th>发送策略</th><th>运行情况</th><th>位置误差 RMSE ↓</th><th>尝试发送（含丢包）</th><th>成功到达</th><th>预算用完后未发出的请求</th></tr>'''
    page += "".join(rows) + '''</table></div><p><a href="network/result.json">下载本次设置和完整轨迹（JSON）</a> · <a href="traffic/study.json">下载相同发送次数的对照结果（JSON）</a></p>
<p><b>接下来怎么看：</b>如果显示运行失败，先核对模型单位、初始位置和错误详情。如果预算用完后还有请求未能发出，可以调整发送上限或触发门槛，再另存一组结果比较。原来的失败和结果都应保留。</p>
<details><summary>相同发送次数的对照是什么意思？</summary><p>先记录事件策略实际尝试发送的次数，再让周期策略尝试发送同样多的消息。这能帮助你检查发送时机的影响，但发送次数是运行后才确定的，不能当作提前调好参数后的独立测试。运行未完成时，完整时段的分数显示为不可用，不是零。</p></details></section>
<section><h2>3 · 再看三种控制方法怎样完成任务</h2><p><a href="controllers/report.html">查看 MFAC、ILC 和强化学习的结果</a></p>
<p>MFAC 在运行中估计对象的响应；ILC 反复完成同一任务，用上一轮的误差调整下一轮；强化学习先训练，再固定策略进行测试。三种方法的实验条件不同，请按报告中的阶段分别阅读。</p>
<p>当前 MFAC 和 ILC 需要按固定间隔收到每一次测量，尚不能用于有延迟、丢包或噪声的训练。更换模型后，这些条件仍然适用。</p></section>
<section><h2>4 · 下一步，换成你的模型</h2><p>源码里的 <code>examples/own_model_case.py</code> 给出了接入示例，<code>docs/own-model.md</code> 解释了修改方法。先用一个已知输入核对模型轨迹，再运行控制实验。</p>
<details><summary>查看接口要求和指标范围</summary><p>在 factory 函数中初始化模型，在 step 函数中计算下一步状态，并记录参数、单位和来源。代码只在本机运行，网页不接收上传的 Python 代码。</p>
<p>当前支持一个控制输入，以及一维输出或“位置、速度”两个状态；控制目标是回到 0。RMSE 按第一个状态计算，固定权重的二次代价不是物理能耗。内置步长核查只适用于内置模型，不能验证你自己的积分器。</p></details>
<details><summary>English overview</summary><p>This example returns a simplified actuator to its target position. First compare position error and actual message counts, then read each controller's learning and test stages. Model parameters are illustrative, not fitted to hardware. Expand the technical notes for equations and limits; all settings and failures remain in the JSON exports.</p></details></section></html>'''
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
