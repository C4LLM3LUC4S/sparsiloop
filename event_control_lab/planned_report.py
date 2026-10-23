"""Offline reports for a declared schedule choice; excluded from behavior identity."""

import csv
from dataclasses import fields as dataclass_fields
import html
import json
import math
from pathlib import Path

from .engine import Config


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
<title>''' + html.escape(title) + '''</title><style>body{font:16px/1.8 system-ui,sans-serif;max-width:1040px;margin:auto;padding:24px;color:#183546;background:#f5f8fa}section{background:white;border:1px solid #ccdce4;border-radius:12px;padding:20px;margin:18px 0}h1{font-size:28px}h2{font-size:21px}a{color:#006c77}pre{white-space:pre-wrap;overflow-wrap:anywhere}.scroll{overflow:auto}.scroll:focus-visible{outline:3px solid #55aa91}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:9px;border-bottom:1px solid #dbe5ea;text-align:left;white-space:nowrap}.conditions table{table-layout:fixed}.conditions td,.conditions th{white-space:normal;overflow-wrap:anywhere}.conditions th:first-child,.conditions td:first-child{width:32%}code{overflow-wrap:anywhere}</style>
<h1>''' + html.escape(title) + "</h1>" + body + "</html>"


def scope(record):
    spec = record["spec"]
    config = spec["config"]
    error_name = "首个状态分量的误差" if record.get("model") else "位置误差"
    deviation = "第一个状态分量的偏差" if record.get("model") else "位置偏差"
    return (f"每次计划模拟 {config['duration']} 秒，每步 {config['dt']} 秒，最多尝试发送 {config['budget']} 条消息。"
            f"{error_name}要求：每个声明种子的完整时段 RMSE 都不高于 {spec['rmse_limit']}。RMSE 概括整个时段的{deviation}，这个要求不是瞬时最大偏差的限制。"
            "周期与事件方案使用相同发送上限，实际消息数仍分别记录；不按事件结果改周期预算。")


def experiment_conditions(record, *, testing=False):
    spec = record["spec"]
    missing = {field.name for field in dataclass_fields(Config)} - set(spec["config"])
    if missing:
        return ('<section id="experiment-conditions"><h2>保存的条件不完整</h2>'
                '<p>这份方案缺少以下配置，不能用默认值代替原记录：'
                + html.escape(", ".join(sorted(missing)))
                + '。请保留文件，回到生成记录的版本核对。下面只列出实际保存的字段。</p><pre>'
                + html.escape(json.dumps(spec, ensure_ascii=False, indent=2)) + '</pre></section>')
    config = Config.from_dict(spec["config"])
    scalar = config.plant == "scalar"
    model = "一阶标量对象（scalar）" if scalar else "位置—速度对象（double_integrator）"
    initial = (f"从 x={shown(config.initial_position)} 开始，让 x 回到 0。" if scalar else
               f"从位置 p={shown(config.initial_position)}、速度 v={shown(config.initial_velocity)} 开始，让两者回到 0；误差要求只考察位置。")
    custom = record.get("model")
    model_extra = ""
    provenance = "这是数学示例，没有实物标定；状态和控制量不默认对应米、牛顿等实际单位。"
    if custom:
        model = "本地模型：" + custom["name"]
        unit = custom["state_units"][0]
        unit_label = {"normalized_displacement": "归一化位移（没有换算成米）",
                      "normalized_output": "归一化输出（没有换算成实际量纲）"}.get(unit, unit)
        initial = (f"初始值是 {shown(config.initial_position)}，目标是 0。" if scalar else
                   f"初始位置是 {shown(config.initial_position)}，速度是 {shown(config.initial_velocity)}，目标都为 0。")
        initial += f"误差要求只看第一个状态分量；声明单位：{unit_label}。"
        provenance = "模型、参数、单位和来源由你提供，工具没有做独立核验。请保留原来的本地代码；JSON 不包含可执行模型。"
        model_extra = ('<details><summary>核对模型参数、单位和来源</summary><pre>'
                       + html.escape(json.dumps(custom, ensure_ascii=False, indent=2))
                       + '</pre></details><p><a href="model.json" download>保存模型声明（JSON）</a></p>')
    if testing:
        seeds = (f"这一步使用的测试编号：{', '.join(map(str, spec['test_seeds']))}。"
                 if record["selected_id"] is not None else
                 f"没有选定方案，本阶段未运行测试；原先预留的编号是 {', '.join(map(str, spec['test_seeds']))}。")
        seeds += f"选择阶段使用的编号：{', '.join(map(str, spec['selection_seeds']))}。"
        candidates = [row for row in record["selection_summaries"]
                      if row["id"] in {record["selected_id"], "periodic"}] if record["selected_id"] is not None else []
    else:
        seeds = (f"选择编号：{', '.join(map(str, spec['selection_seeds']))}；"
                 f"预留测试编号：{', '.join(map(str, spec['test_seeds']))}，本阶段未运行。")
        candidates = record["selection_summaries"]
    event_candidates = [row for row in candidates if row["policy"] != "periodic"]
    if testing and record["selected_id"] is None:
        event_rule = "本阶段未运行测试，不能把原候选当成已执行方案。完整选择记录仍保留所有候选。"
    elif not event_candidates:
        event_rule = "本阶段没有事件候选，只按共同上限安排周期发送；配置中保留的事件门槛没有参与周期发送。"
    else:
        event_rule = ("比较当前测量与最后一次尝试发送的测量之差（向量用欧氏距离）。"
                      "达到门槛，或等到最长尝试间隔时，在剩余预算内发送。丢包也会更新这份发送端记录。"
                      "本阶段事件方案：" + "；".join(label(row) for row in event_candidates) + "。")
        if any(row["policy"] == "relative" for row in event_candidates):
            event_rule += (f"相对方案的实际门槛是 sqrt({shown(config.threshold)}² + (r × 当前测量的长度)²)，"
                           "r 取该候选的门槛值；其中绝对底限不随候选 r 改变。")
    feedback = (f"指令=-kp × 到达的 x 观测，kp={shown(config.kp)}；kd 不参与一阶反馈。" if scalar else
                f"指令=-kp × 到达的位置观测-kd × 到达的速度观测，kp={shown(config.kp)}，kd={shown(config.kd)}。")
    feedback += f"指令截在 ±{shown(config.input_limit)} 以内；输入扰动随后另加。"
    frozen = "policy_before" in record
    if frozen:
        feedback = ("使用保存的 Q 表，按到达时刻与收到的位置观测选取指令；每次运行新建控制器，"
                    "没有探索随机数，也不更新 Q 表。kp、kd 都不参与这个策略。"
                    f"指令仍截在 ±{shown(config.input_limit)} 以内，输入扰动随后另加。")
    fields = [
        ["对象方程", ("x' = x + u" if scalar else "p' = v, v' = u") + "；u 是本区间含输入扰动的动力学输入。"],
        ["时间和共同发送上限", f"{shown(config.duration)} 秒，步长 {shown(config.dt)} 秒，共 {config.steps} 个区间；每次最多尝试发送 {config.budget} 条。丢包也消耗发送次数。"],
        ["冻结策略与指令限幅" if frozen else "固定反馈与指令限幅", feedback],
        ["控制器看到了什么", "只使用到达的观测，有新消息才更新指令。第一条消息到达前指令为 0，之后没有新消息时保持上次指令；不读未到达的状态。传感器仍每步采样以判断是否发送。"],
        ["传感器到控制器的链路", f"延迟 {config.delay_steps} 步，即 {shown(config.delay_steps * config.dt)} 秒；每次尝试的丢包概率 {shown(100 * config.loss_probability)}%。这里只模拟这一条上行链路。"],
        ["噪声怎样加入", f"每步用标准正态数 Z：各状态分量的测量加 {shown(config.measurement_noise)} × Z，区间输入加 {shown(config.process_noise)} × Z（在指令限幅之后）。两类数序列分别生成；这些是当前网格上的系数，不是连续时间噪声强度。"],
        ["事件发送规则", event_rule],
        ["事件发送的最长尝试间隔", f"请求 {shown(config.heartbeat)} 秒，按网格为 {config.heartbeat_steps} 步，即 {shown(config.heartbeat_steps * config.dt)} 秒；有剩余预算才会尝试。周期发送不使用这个间隔。"],
        ["误差与提前停止", f"每个完整运行的位置 RMSE 不高于 {shown(spec['rmse_limit'])}；它综合整个时段，不是瞬时最大偏差。状态向量长度超过 {shown(config.state_limit)} 或出现非有限数时提前停止；失败的完整时段指标不能当成 0。"],
        ["配置里哪些值会被替换", f"基准 seed={config.seed} 只保留在配置里，不作为本轮运行编号；实际使用上方声明的列表。绝对候选替换 threshold，相对候选替换 relative_threshold；周期不使用这两种门槛。" + ("一阶对象的 initial_velocity 和 kd 只保留在配置中，不参与运行。" if scalar else "")],
    ]
    if custom:
        fields = [[name, value.replace("一阶反馈", "标量反馈").replace("一阶对象", "标量对象")
                   .replace("位置 RMSE", "首个状态分量的 RMSE")] for name, value in fields]
        fields[0] = ["本地对象与单位", f"由原本地模型函数推进状态；参数与来源见模型声明。状态单位：{custom['state_units']}；输入单位：{custom['input_unit']}。"]
    if frozen:
        fields.append(["初态怎样设置", f"所有选择和测试运行都从声明的 x={shown(config.initial_position)} 开始；不会按种子另抽初态。种子只改变已声明的噪声和丢包输入。原 evaluate-policy 的初态规则不同，不能直接混在一起比较。"])
    return ('<section id="experiment-conditions"><h2>这次模拟的是什么？</h2>'
            f'<p>{html.escape(model + "。" + initial)}</p>'
            f'<p>{html.escape(provenance)}</p>' + model_extra
            + f'<p>{html.escape(seeds)}随机种子就是这组随机输入的编号。</p>'
            '<details><summary>核对控制、网络和发送规则</summary>'
            + '<div class="conditions">' + table(["条件", "当前记录"], fields) + '</div>'
            + '</details><details><summary>查看原样保存的完整方案</summary>'
            '<p>门槛和编号按每次运行的配置生效，不能把基准配置中的保留值当成实际使用值。下方字段不做小数缩短，原始结果另存于报告旁的 JSON。</p><pre>'
            + html.escape(json.dumps(spec, ensure_ascii=False, indent=2))
            + '</pre></details></section>')


def records_csv(folder, rows):
    with (folder / "runs.csv").open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["candidate_id", "policy", "threshold", "budget", "dt", "duration", "seed", "roles", "status", "duration_completed", "position_rmse",
                         "attempted", "dropped", "delivered", "in_flight", "error"])
        for row in rows:
            run = row["run"]
            config = row["config"]
            threshold = (config["threshold"] if run["policy"] == "absolute" else
                         config["relative_threshold"] if run["policy"] == "relative" else "")
            writer.writerow([row["candidate_id"], run["policy"], threshold, config["budget"], config["dt"],
                             config["duration"], row["seed"], ";".join(row.get("roles", ["selection"])), run["status"],
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


def footer(record=None):
    if record is not None and "policy_before" in record:
        return '''<section><h2>这份记录能说明到哪里？</h2><p>策略在选择发送方案之前已经固定；这两步都没有重新训练，也没有用测试结果换策略或门槛。周期对照使用同一份策略，不是另一种控制器。</p><p>所有候选、失败和无法计算的分数都保留。历史只能覆盖文件中已有和你声明的编号，不能自动发现漏报的试验；编号不同也不证明统计独立。若根据测试继续调参，请把它记为开发记录，另定新方案。</p><p>摘要帮助核对文件，不认证来源、稳定性、硬件效果或普遍最优。示例仅演示流程。</p><details><summary>English overview</summary><p>The saved scalar Q policy remains frozen during schedule selection and testing. Both schedules use the same policy, fixed declared initial state and message cap. Known training, evaluation and planned-phase seed history is retained. There is no retraining or reselection using tests; declared history is not an independence or provenance certificate.</p></details></section>'''
    return '''<section><h2>这份记录能说明到哪里？</h2><p>这里只使用固定反馈控制器，没有训练控制器。所有候选、失败和无法计算的分数都保留。种子编号分开不证明统计独立；如果你已经根据测试结果调整过方案，就应把这些数据记作开发记录，再另定测试方案。</p>
<p>摘要用于核对文件和版本，不认证来源、预注册、稳定性、硬件效果或普遍最优。公开示例已被开发者观察，是流程演示。</p>
<details><summary>English overview</summary><p>A fixed controller selects a schedule using only declared selection seeds and a predeclared rule. A separate command loads the saved selection and evaluates only the declared test seeds with a fixed-cap periodic reference. All failures and raw trajectories remain. This is not a preregistration, independence or stability certificate.</p></details></section>'''


def policy_section(record, continuation=None):
    if "policy_before" not in record:
        return ""
    original = record["policy_before"]["checkpoint"]
    current = continuation if continuation is not None else record["policy_after"]
    body = '<section id="frozen-policy"><h2>这次用了哪份策略？</h2><p>沿用已经训练好的 Q 表，这次只选择发送方式，不再训练控制器。周期对照也用同一个策略。</p>'
    body += '<p>每次运行都沿用同一份策略，学习更新次数为 0。核对用的文件摘要可以在下面展开。</p>'
    failures = [value for value in original["training_statuses"] if value != "complete"]
    training_status = f'有 {len(failures)} 次未完整结束' if failures else '均完整结束'
    body += f'<p>原训练共 {len(original["training_seeds"])} 次，{training_status}。各次状态保留在策略文件里；是否适合当前任务，仍要看预留条件下的测试。</p>'
    body += '<p>以后做新计划，用下面的 policy-history.json 接着走；它保留训练、过去评测以及每次选择和测试用过的编号。原选择记录可以重复复核，但重复运行不算一组新的测试。</p><p><a href="policy-history.json" download>保存策略和分阶段历史，供下次新计划使用</a> · <a href="policy-checkpoint.json" download>保存兼容旧评测入口的完整策略</a></p>'
    body += f'<details><summary>核对本次沿用的策略摘要</summary><p>Q 表：<code>{html.escape(original["table_sha256"])}</code>。每次运行前后摘要相同。</p></details>'
    body += '<details><summary>查看训练、过去评测和本轮使用过的编号</summary><pre>'
    body += html.escape(json.dumps({"training_seeds": original["training_seeds"],
        "earlier_evaluation_seeds": current["earlier_evaluation_seeds"],
        "declared_development_seeds": current["declared_development_seeds"],
        "planned_history": current["planned_history"]}, ensure_ascii=False, indent=2))
    return body + '</pre></details></section>'


def export_policy_files(value, folder):
    if "policy_after" in value:
        write_json(folder / "policy-history.json", value["policy_after"])
        write_json(folder / "policy-checkpoint.json", value["policy_after"]["checkpoint"])


def environment_section(manifest):
    if manifest is None:
        return '<section id="run-environment"><h2>换台电脑复核，先对照哪些信息？</h2><p>这份原始记录没有保存运行环境。仅凭当前电脑，无法反推出当时的 Python 和系统；重新生成报告也不会补成已知。</p></section>'
    def describe(value):
        messages = {"not_recorded": "未记录，不能从当前电脑反推。",
                    "not_requested": "这份记录只做了选择，复核尚未开始。", "not_run": "没有运行测试，也没有测试环境。"}
        if value["state"] != "recorded":
            return messages[value["state"]]
        runtime = value["runtime"]
        return (f"{runtime['python_implementation']} {runtime['python_version']}；"
                f"{runtime['os_family']} / {runtime['python_pointer_bits']} 位 Python；SparsiLoop {runtime['sparsiloop_version']}")
    context = manifest["execution"]
    body = '<section id="run-environment" class="conditions"><h2>换台电脑复核，先对照哪些信息？</h2><p>运行实验和生成报告是两件事，环境分开记。原记录没写的继续保留未知，不用这台电脑的信息补过去。</p>'
    body += table(["哪一步", "保存的环境"], [["选择方案时", describe(context["selection"])],
                 ["按原计划复核时", describe(context["test"])],
                 ["这次生成报告时", describe({"state": "recorded", "runtime": manifest["report_rendering"]})]])
    body += '<p>换电脑时可先核对 Python、系统和源码版本。环境相同也不保证浮点逐位一致；这些信息由程序自行记录，摘要只帮助核对文件，不能认证来源。</p><p><a href="selection-bundle.json" download>保存选择记录和运行环境，供下次复核</a> · <a href="environment.json" download>完整环境记录</a></p>'
    if context["phase"] == "test":
        body += '<p><a href="test-bundle.json" download>保存完整测试记录和环境，供以后重绘报告</a></p>'
    body += '<details><summary>查看完整环境字段与记录时间</summary><pre>' + html.escape(json.dumps(manifest, ensure_ascii=False, indent=2)) + '</pre></details></section>'
    return body


def export_selection(record, destination, input_hash=None, *, environment=None):
    folder = Path(destination)
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / "selection.json", record)
    export_policy_files(record, folder)
    if record.get("model"):
        write_json(folder / "model.json", record["model"])
    write_json(folder / "input-info.json", {"input_sha256": input_hash, "phase": "selection_only"})
    records_csv(folder, record["selection_runs"])
    summaries = record["selection_summaries"]
    chosen = next((row for row in summaries if row["id"] == record["selected_id"]), None)
    status = ("选定：" + label(chosen)) if chosen else "没有候选满足这次要求，测试阶段不会运行。"
    body = "<p>先用一组条件选发送规则，保存以后，再用另一组条件复核。这份报告只用了选择种子。</p>"
    body += "<section><h2>这次选到了什么？</h2><p>" + html.escape(status) + "</p><p>" + html.escape(scope(record)) + "</p>"
    body += "<p>规则已经写在方案里：每次都要完整结束且误差达标；满足后先选平均尝试发送最少的，再比平均误差。仍相同时按声明顺序选择。</p></section>"
    body += policy_section(record) + experiment_conditions(record)
    rows = [[label(row), f"{row['complete']} / {row['requested']}", row["all_runs_max_rmse"],
             row["all_runs_mean_rmse"], row["all_requested_mean_attempts"],
             "按规则选定" if row["id"] == record["selected_id"] else ("满足条件" if row["eligible"] else "未满足要求")] for row in summaries]
    body += "<section><h2>所有候选都在这里</h2>" + table(["候选", "完整运行", "各次 RMSE 的最大值", "平均 RMSE", "平均尝试发送", "选择情况"], rows) + "<p>提前失败的尝试数只统计停下之前发了多少条，不能当作完成整个任务的通信开销。</p></section>"
    body += '<section><h2>下一步怎么做？</h2>'
    if chosen:
        if "policy_before" in record:
            body += '<p>保留完整选择记录，用下面的 test 命令复核。策略已经保存在记录中，不能临时换 Q 表、门槛或测试编号。</p><pre>python -m event_control_lab.planned_study test PATH/selection-bundle.json --out runs/frozen-policy-test</pre><p>把 PATH 换成这份报告所在目录。以后另做新计划，再用 policy-history.json 接续已用编号。</p>'
        elif record.get("model"):
            saved_name = "selection-bundle.json" if environment is not None else "selection.json"
            body += f'<p>保存 {saved_name} 和原来的本地模型代码。下次先重新构建同一模型，再调用 test_with_context(选择记录, plant=模型)。参数、单位或来源不匹配时会拒绝，不会自动换回内置模型。测试只使用原先预留的编号；不重新选门槛或改预算。</p>'
        else:
            body += '<p>保留 selection.json，用 test 命令载入它；测试阶段不会重新选门槛，也不会改变事先声明的发送上限。</p><pre>python -m event_control_lab.planned_study test PATH/selection.json --out runs/planned-test</pre><p>把 PATH 换成这份报告所在的目录。</p>'
    else:
        body += '<p>先看哪些候选未跑完、哪些超过了误差要求。保持当前记录，不要从测试结果中临时挑一个门槛。若要改方案，请先记录已看过哪些数据，再用新目录保存。</p>'
    body += '<p><a href="selection.json" download>保存完整选择记录（JSON）</a> · <a href="runs.csv" download>每次运行（CSV）</a> · <a href="trajectories.csv" download>全部轨迹（CSV）</a></p></section>'
    body += '<details><summary>查看原始失败记录</summary><pre>' + html.escape(json.dumps({"failures": [{"candidate": row["candidate_id"], "seed": row["seed"], "status": row["run"]["status"], "error": row["run"]["error"]} for row in record["selection_runs"] if row["run"]["status"] != "complete"]}, ensure_ascii=False, indent=2)) + "</pre></details>"
    (folder / "report.html").write_text(page("先选一个发送方案", body + environment_section(environment) + footer(record)), encoding="utf-8")


def export_test(result, destination, input_hash=None, *, environment=None):
    folder = Path(destination)
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / "test.json", result)
    export_policy_files(result, folder)
    if result["selection"].get("model"):
        write_json(folder / "model.json", result["selection"]["model"])
    write_json(folder / "input-info.json", {"input_sha256": input_hash, "phase": "declared_test_only"})
    records_csv(folder, result["test_runs"])
    messages = {"met_declared_tests": "这次声明的测试都完整结束，所选方案也都满足误差要求。",
                "did_not_meet_declared_tests": "所选方案没有通过这次所有要求。它仍是原来选定的方案，没有改选。",
                "not_run_no_eligible_choice": "选择阶段没有合格候选，这次没有运行任何测试种子。"}
    names = {row["id"]: label(row) for row in result["selection"]["selection_summaries"]}
    selection = names.get(result["selected_id"], "未选定")
    body = "<section><h2>换一组条件后，表现怎样？</h2><p>沿用的方案：" + html.escape(selection) + "。</p><p>" + messages[result["status"]] + "</p><p>" + html.escape(scope(result["selection"])) + "</p></section>"
    body += policy_section(result["selection"], result.get("policy_after"))
    body += experiment_conditions(result["selection"], testing=True)
    rows = []
    for row in result["test_runs"]:
        run = row["run"]
        role = "所选方案 / 周期对照（同一方案）" if len(row["roles"]) == 2 else ("所选方案" if "selected" in row["roles"] else "周期对照")
        status = {"complete": "完整结束", "state_limit": "超过设置的状态上限", "controller_error": "控制器出错", "plant_error": "模型出错"}.get(run["status"], run["status"])
        value = run["metrics"]["position_rmse"]
        verdict = ("无法判断" if run["status"] != "complete" or type(value) not in (int, float)
                   or not math.isfinite(value) or value < 0 else
                   "达标" if value <= result["selection"]["spec"]["rmse_limit"] else "超出要求")
        rows.append([role, names[row["candidate_id"]], row["seed"], status, value, verdict, run["packets"]["attempted"], run["packets"]["delivered"], run["error"] or "—"])
    metric_name = "首个状态 RMSE" if result["selection"].get("model") else "位置 RMSE"
    body += "<section><h2>每次测试的误差和消息数</h2>" + table(["用途", "方案", "种子", "运行情况", metric_name, "误差是否达标", "尝试发送", "到达", "原因"], rows) + "<p>完整结束和误差达标是两件事。表格里的小数略有省略，是否达标按完整数值判断；需要复核时看 JSON。</p></section>"
    body += '<section><h2>接下来怎么判断？</h2><p>先核对有没有提前停止，再看每个种子是否达标，以及实际发了多少条消息。周期对照用于描述相同上限下的取舍；测试里更好的另一个结果不会替换所选方案。若你据此继续调参，这组测试就成为开发数据，后续需要另定方案。</p><p><a href="test.json" download>完整方案、选择记录和测试结果（JSON）</a> · <a href="runs.csv" download>每次测试（CSV）</a> · <a href="trajectories.csv" download>全部测试轨迹（CSV）</a></p></section>'
    (folder / "report.html").write_text(page("复核已经选定的发送方案", body + environment_section(environment) + footer(result["selection"])), encoding="utf-8")
