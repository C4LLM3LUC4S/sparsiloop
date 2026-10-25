"""Presentation and local export for the separately declared constant-target task."""

import csv
import html
import json
from pathlib import Path

from .constant_target import load_record, physical_rows, read_record
from .export_recovery import recovery_record
from .output_paths import check_new_output
from .planned_context import runtime_info


def number(value):
    return "不可用" if value is None else f"{value:.6g}"


def render_html(value):
    load_record(value)
    spec, config = value["spec"], value["spec"]["config"]
    def esc(value):
        return html.escape(str(value))
    rows = []
    names = {"periodic": "周期发送", "absolute": "绝对变化发送", "relative": "相对变化发送"}
    states = {"complete": "完整结束", "state_limit": "误差状态超限", "controller_error": "反馈失败", "plant_error": "对象失败"}
    for run in value["comparison"]["runs"]:
        packet = run["packets"]
        fields = [names[run["policy"]], states[run["status"]], number(run["metrics"]["position_rmse"]),
                  packet["attempted"], packet["delivered"], packet["dropped"], packet["in_flight"],
                  run["error"] or "—"]
        rows.append("<tr>" + "".join("<td>" + esc(x) + "</td>" for x in fields) + "</tr>")
    environment = "原执行环境已记录" if value["execution"]["state"] == "recorded" else "原执行环境未知；这次重绘没有补填"
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SparsiLoop · 常值目标位置</title><style>body{{font:17px/1.7 system-ui,sans-serif;max-width:1040px;margin:auto;padding:22px;background:#f4f8fa;color:#183546}}section{{padding:20px;background:white;border:1px solid #cbdde4;border-radius:12px;margin:18px 0}}a{{color:#006b76}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%}}td,th{{padding:10px;text-align:left;border-bottom:1px solid #d5e0e5;white-space:nowrap}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}</style>
<h1>让位置靠近你设定的目标</h1><p>目标位置是 <strong>{esc(spec['target'])}</strong>，实际初始位置是 <strong>{esc(config['initial_position'])}</strong>，初始速度为 {esc(config['initial_velocity'])}。先看误差，再看实际发送了多少消息。</p>
<section><h2>这次比较什么？</h2><p>同一个归一化位置—速度数学模型，使用固定反馈，比较三种传感器发送方式。目标从开始到结束保持不变，发送端和控制器都预先知道它。控制器只会用已经到达的误差和速度测量，没收到消息时继续保持原指令；首次收到消息前指令为零。</p>
<p>下面的误差 RMSE 把完整时段的位置偏差合成一个数，越小表示越靠近目标。它来自原协议的梯形积分，失败运行显示“不可用”，不能把较短的失败运行当作低成本完成。三种方式的发送上限相同，实际消息数仍可能不同。</p>
<div class="scroll" tabindex="0" role="region" aria-label="常值目标比较"><table><tr><th>发送方式</th><th>结果</th><th>目标误差 RMSE ↓</th><th>尝试发送</th><th>到达</th><th>丢失</th><th>在途</th><th>失败原因</th></tr>{''.join(rows)}</table></div>
<p><a href="physical-trajectories.csv" download>查看实际位置、目标和误差轨迹 CSV</a> · <a href="target-task.json" download>保存完整任务和原结果</a></p></section>
<section><h2>怎么采取下一步？</h2><p>先确认目标、初态、输入限幅和通信条件符合你的问题。没有完整结束时，先看失败原因与轨迹；不要删掉失败或缩短时域来美化平均分。完整运行后，结合误差和实际消息账本决定是否另设门槛或预算，并另存新方案和结果；不能只凭一次例子声称某种策略更好。</p>
<p>只想下次看结果，保留整个输出目录后打开 report.html。只重绘用完整 target-task.json：</p><pre>python -m event_control_lab.constant_target render "old results/target-task.json" --out "reports/redrawn-target"</pre>
<p>换电脑时也保存本次对应的发行包和源码。重绘不训练、不重新仿真、不重新计算原指标。只留 CSV、截图、策略文件或旧的零目标比较，不能还原这份完整任务。{esc(environment)}。</p></section>
<section><h2>范围和条件</h2><p>这里支持理想双积分对象的常值目标。e=p−目标，底层状态为(e,速度)，实际位置是e+目标。相对触发使用这个误差—速度向量的范数，并不是相对绝对位置触发。state_limit 限制误差—速度状态，不能当作实际位置的安全界限。</p>
<p>clipped_command 是限幅后的控制指令；扰动在限幅之后加入。CSV 的 effective_interval_input 表示完整推进区间内实际使用的指令加扰动，末行没有推进区间，留空。二次代价是固定的归一化指标，不是物理能耗。</p>
<p>这条新任务没有训练控制器，不复用原零目标的 MFAC、ILC 或 Q 策略，不支持标量对象、时变目标或任意私人模型；也不认证稳定性、硬件效果或真实采用。</p>
<details><summary>查看完整方案、坐标和来源说明</summary><pre>{esc(json.dumps({'spec':spec,'error_config':value['error_config'],'coordinates':value['coordinates'],'source_sha256':value['source_sha256'],'scope':value['scope']},ensure_ascii=False,indent=2))}</pre><p>摘要用于核对一致性，不能认证原始来源；不要修改摘要来强行载入。</p></details>
<details><summary>English task and boundary</summary><p>A fixed known target r for p'=v, v'=u+w is represented by e=p-r. The unchanged engine sees error and velocity; the report adds physical position e+r. Relative events use the error/velocity norm. Existing full-horizon trapezoidal RMSE measures tracking error; failures remain unavailable. The state limit is an error-state simulation bound, not physical safety. Commands are clipped before input disturbance. Save the complete typed record and matching source; render only redraws. No learning, time-varying reference, hardware or stability claim.</p></details></section></html>'''


def export_task(value, destination):
    check_new_output(destination)
    value = load_record(value)
    target = Path(destination).resolve()
    with recovery_record(value, target, "constant_target", verify=read_record):
        target.mkdir(parents=True, exist_ok=False)
        (target / "target-task.json").write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        rows = list(physical_rows(value))
        with (target / "physical-trajectories.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        environment = {"execution": value["execution"], "report_rendering": runtime_info()}
        (target / "environment.json").write_text(json.dumps(environment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (target / "report.html").write_text(render_html(value), encoding="utf-8")
