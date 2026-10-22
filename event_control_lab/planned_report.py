"""Offline reports for a declared schedule choice; excluded from behavior identity."""

import csv
import html
import json
from pathlib import Path


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def label(candidate):
    if candidate["policy"] == "periodic":
        return "周期发送"
    return ("绝对变化" if candidate["policy"] == "absolute" else "相对变化") + f"，门槛 {candidate['threshold']}"


def shown(value):
    if value is None:
        return "无法计算"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def table(headings, rows):
    header = "<tr>" + "".join(f"<th>{html.escape(text)}</th>" for text in headings) + "</tr>"
    body = "".join("<tr>" + "".join(f"<td>{html.escape(shown(value))}</td>" for value in row) + "</tr>" for row in rows)
    return '<div class="scroll" tabindex="0" role="region" aria-label="可横向滚动的结果表"><table>' + header + body + "</table></div>"


def page(title, body):
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>''' + html.escape(title) + '''</title><style>body{font:16px/1.8 system-ui,sans-serif;max-width:1040px;margin:auto;padding:24px;color:#183546;background:#f5f8fa}section{background:white;border:1px solid #ccdce4;border-radius:12px;padding:20px;margin:18px 0}h1{font-size:28px}h2{font-size:21px}a{color:#006c77}pre{white-space:pre-wrap;overflow-wrap:anywhere}.scroll{overflow:auto}.scroll:focus-visible{outline:3px solid #55aa91}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:9px;border-bottom:1px solid #dbe5ea;text-align:left;white-space:nowrap}code{overflow-wrap:anywhere}</style>
<h1>''' + html.escape(title) + "</h1>" + body + "</html>"


def scope(record):
    spec = record["spec"]
    config = spec["config"]
    return (f"每次模拟 {config['duration']} 秒，每步 {config['dt']} 秒，最多尝试发送 {config['budget']} 条消息。"
            f"位置误差要求：每个声明种子的完整时段 RMSE 都不高于 {spec['rmse_limit']}。RMSE 概括整个时段的位置偏差，这个要求不是瞬时最大偏差的限制。"
            "周期与事件方案使用相同发送上限，实际消息数仍分别记录；不按事件结果改周期预算。")


def records_csv(folder, rows):
    with (folder / "runs.csv").open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["candidate_id", "seed", "roles", "status", "duration_completed", "position_rmse",
                         "attempted", "dropped", "delivered", "in_flight", "error"])
        for row in rows:
            run = row["run"]
            writer.writerow([row["candidate_id"], row["seed"], ";".join(row.get("roles", ["selection"])), run["status"],
                             run["duration_completed"], run["metrics"]["position_rmse"],
                             *[run["packets"][key] for key in ("attempted", "dropped", "delivered", "in_flight")], run["error"]])
    with (folder / "trajectories.csv").open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["candidate_id", "seed", "t_s", "state", "input", "received_values", "observation_age",
                         "sent", "dropped", "delivered"])
        for row in rows:
            for tick in row["run"]["trajectory"]:
                writer.writerow([row["candidate_id"], row["seed"], tick["t"], json.dumps(tick["state"]), tick["input"],
                                 "" if tick["controller_values"] is None else json.dumps(tick["controller_values"]),
                                 tick["observation_age"], tick["sent"], tick["dropped"], tick["delivered"]])


def footer():
    return '''<section><h2>这份记录能说明到哪里？</h2><p>这里只使用固定反馈控制器，没有训练控制器。所有候选、失败和无法计算的分数都保留。种子编号分开不证明统计独立；如果你已经根据测试结果调整过方案，就应把这些数据记作开发记录，再另定测试方案。</p>
<p>摘要用于核对文件和版本，不认证来源、预注册、稳定性、硬件效果或普遍最优。公开示例已被开发者观察，是流程演示。</p>
<details><summary>English overview</summary><p>A fixed controller selects a schedule using only declared selection seeds and a predeclared rule. A separate command loads the saved selection and evaluates only the declared test seeds with a fixed-cap periodic reference. All failures and raw trajectories remain. This is not a preregistration, independence or stability certificate.</p></details></section>'''


def export_selection(record, destination, input_hash=None):
    folder = Path(destination)
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / "selection.json", record)
    write_json(folder / "input-info.json", {"input_sha256": input_hash, "phase": "selection_only"})
    records_csv(folder, record["selection_runs"])
    summaries = record["selection_summaries"]
    chosen = next((row for row in summaries if row["id"] == record["selected_id"]), None)
    status = ("选定：" + label(chosen)) if chosen else "没有候选满足这次要求，测试阶段不会运行。"
    body = "<p>先用一组条件选发送规则，保存以后，再用另一组条件复核。这份报告只用了选择种子。</p>"
    body += "<section><h2>这次选到了什么？</h2><p>" + html.escape(status) + "</p><p>" + html.escape(scope(record)) + "</p>"
    body += "<p>规则已经写在方案里：每次都要完整结束且误差达标；满足后先选平均尝试发送最少的，再比平均误差。仍相同时按声明顺序选择。</p></section>"
    rows = [[label(row), f"{row['complete']} / {row['requested']}", row["all_runs_max_rmse"],
             row["all_runs_mean_rmse"], row["all_requested_mean_attempts"],
             "按规则选定" if row["id"] == record["selected_id"] else ("满足条件" if row["eligible"] else "未满足要求")] for row in summaries]
    body += "<section><h2>所有候选都在这里</h2>" + table(["候选", "完整运行", "各次 RMSE 的最大值", "平均 RMSE", "平均尝试发送", "选择情况"], rows) + "<p>提前失败的尝试数只统计停下之前发了多少条，不能当作完成整个任务的通信开销。</p></section>"
    body += '<section><h2>下一步怎么做？</h2>'
    if chosen:
        body += '<p>保留 selection.json，用 test 命令载入它；测试阶段不会重新选门槛，也不会改变事先声明的发送上限。</p><pre>python -m event_control_lab.planned_study test PATH/selection.json --out runs/planned-test</pre><p>把 PATH 换成这份报告所在的目录。</p>'
    else:
        body += '<p>先看哪些候选未跑完、哪些超过了误差要求。保持当前记录，不要从测试结果中临时挑一个门槛。若要改方案，请先记录已看过哪些数据，再用新目录保存。</p>'
    body += '<p><a href="selection.json" download>保存完整选择记录（JSON）</a> · <a href="runs.csv" download>每次运行（CSV）</a> · <a href="trajectories.csv" download>全部轨迹（CSV）</a></p></section>'
    body += '<details><summary>查看方案、种子和原始失败记录</summary><pre>' + html.escape(json.dumps({"spec": record["spec"], "failures": [{"candidate": row["candidate_id"], "seed": row["seed"], "status": row["run"]["status"], "error": row["run"]["error"]} for row in record["selection_runs"] if row["run"]["status"] != "complete"]}, ensure_ascii=False, indent=2)) + "</pre></details>"
    (folder / "report.html").write_text(page("先选一个发送方案", body + footer()), encoding="utf-8")


def export_test(result, destination, input_hash=None):
    folder = Path(destination)
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / "test.json", result)
    write_json(folder / "input-info.json", {"input_sha256": input_hash, "phase": "declared_test_only"})
    records_csv(folder, result["test_runs"])
    messages = {"met_declared_tests": "这次声明的测试都完整结束，所选方案也都满足误差要求。",
                "did_not_meet_declared_tests": "所选方案没有通过这次所有要求。它仍是原来选定的方案，没有改选。",
                "not_run_no_eligible_choice": "选择阶段没有合格候选，这次没有运行任何测试种子。"}
    names = {row["id"]: label(row) for row in result["selection"]["selection_summaries"]}
    selection = names.get(result["selected_id"], "未选定")
    body = "<section><h2>换一组条件后，表现怎样？</h2><p>沿用的方案：" + html.escape(selection) + "。</p><p>" + messages[result["status"]] + "</p><p>" + html.escape(scope(result["selection"])) + "</p></section>"
    rows = []
    for row in result["test_runs"]:
        run = row["run"]
        role = "所选方案 / 周期对照（同一方案）" if len(row["roles"]) == 2 else ("所选方案" if "selected" in row["roles"] else "周期对照")
        status = {"complete": "完整结束", "state_limit": "超过设置的状态上限", "controller_error": "控制器出错", "plant_error": "模型出错"}.get(run["status"], run["status"])
        rows.append([role, names[row["candidate_id"]], row["seed"], status, run["metrics"]["position_rmse"], run["packets"]["attempted"], run["packets"]["delivered"], run["error"] or "—"])
    body += "<section><h2>每次测试的误差和消息数</h2>" + table(["用途", "方案", "种子", "运行情况", "位置 RMSE", "尝试发送", "到达", "原因"], rows) + "</section>"
    body += '<section><h2>接下来怎么判断？</h2><p>先核对有没有提前停止，再看每个种子是否达标，以及实际发了多少条消息。周期对照用于描述相同上限下的取舍；测试里更好的另一个结果不会替换所选方案。若你据此继续调参，这组测试就成为开发数据，后续需要另定方案。</p><p><a href="test.json" download>完整方案、选择记录和测试结果（JSON）</a> · <a href="runs.csv" download>每次测试（CSV）</a> · <a href="trajectories.csv" download>全部测试轨迹（CSV）</a></p></section>'
    (folder / "report.html").write_text(page("复核已经选定的发送方案", body + footer()), encoding="utf-8")
